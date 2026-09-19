"""Auswertung der drei Quellen, ohne ins Netz zu gehen."""

from __future__ import annotations

import json

import httpx
import pytest

from app.services.engines import cloudflare, librespeed, ookla
from app.services.engines.base import Measurement, ThroughputMeter, jitter, percentile

OOKLA_RESULT = {
    "type": "result",
    "ping": {"jitter": 0.5, "latency": 11.2, "low": 10.1, "high": 13.4},
    "download": {"bandwidth": 117_000_000, "bytes": 1_200_000_000, "elapsed": 10000, "latency": {"iqm": 24.5}},
    "upload": {"bandwidth": 5_900_000, "bytes": 60_000_000, "elapsed": 10000, "latency": {"iqm": 61.0}},
    "packetLoss": 0.3,
    "isp": "Example ISP",
    "interface": {"externalIp": "203.0.113.7"},
    "server": {"id": 4711, "name": "Example Fiber", "location": "Duesseldorf", "country": "Germany", "host": "x"},
    "result": {"url": "https://www.speedtest.net/result/c/example"},
}


def test_ookla_bandwidth_is_bytes_per_second() -> None:
    result = Measurement()
    ookla.apply_result(OOKLA_RESULT, result)
    assert result.download_mbps == pytest.approx(936.0)
    assert result.upload_mbps == pytest.approx(47.2)
    assert result.ping_ms == 11.2
    assert result.loaded_down_ms == 24.5
    assert result.packet_loss == 0.3
    assert result.server is not None and result.server.id == "4711"
    assert result.server.location == "Duesseldorf, Germany"
    assert result.result_url.endswith("/example")


def test_ookla_server_list_in_both_shapes() -> None:
    servers = [{"id": 1, "name": "A", "location": "X", "country": "DE"}, {"name": "no id"}]
    assert [s.id for s in ookla.parse_servers(json.dumps({"type": "serverList", "servers": servers}))] == ["1"]
    assert [s.id for s in ookla.parse_servers(json.dumps(servers))] == ["1"]
    assert ookla.parse_servers("not json") == []


def test_librespeed_public_list() -> None:
    items = [
        {
            "id": 51,
            "name": "Amsterdam, Netherlands (Example)",
            "server": "//ams.example.net/backend",
            "dlURL": "garbage.php",
        },
        {"id": "x", "name": "broken"},
    ]
    [backend] = librespeed.parse_public(items)
    assert backend.id == "pub-51"
    assert backend.base == "https://ams.example.net/backend"
    assert backend.url(backend.dl) == "https://ams.example.net/backend/garbage.php"
    assert backend.info().location == "Amsterdam, Netherlands"


def test_librespeed_own_server_with_backend_folder() -> None:
    [backend] = librespeed.parse_own([{"name": "Homelab", "base": "http://10.0.0.5/", "prefix": "backend/"}])
    assert backend.url(backend.ul) == "http://10.0.0.5/backend/empty.php"
    assert backend.id == librespeed.own_id("http://10.0.0.5/")


def test_librespeed_ip_info() -> None:
    response = httpx.Response(200, json={"processedString": "203.0.113.9 - Example ISP, DE (12 km)", "rawIspInfo": ""})
    assert librespeed.parse_ip_info(response) == ("203.0.113.9", "Example ISP, DE")


def test_cloudflare_server_time_and_trace() -> None:
    response = httpx.Response(
        200,
        headers=[
            ("server-timing", "cfSpeedEdge;dur=4, cfSpeedWorker;dur=19"),
            ("server-timing", 'cfL4;desc="?proto=TCP&rtt=21423"'),
        ],
    )
    assert cloudflare.server_time(response) == pytest.approx(0.023)
    assert cloudflare.parse_trace("colo=FRA\nloc=DE\nip=203.0.113.1\n") == {
        "colo": "FRA",
        "loc": "DE",
        "ip": "203.0.113.1",
    }


def test_jitter_and_percentile() -> None:
    assert jitter([10, 12, 11, 15]) == pytest.approx((2 + 1 + 4) / 3)
    assert jitter([10]) is None
    assert percentile([1, 2, 3, 4], 0.5) == 2.5


def test_throughput_ignores_the_warmup(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    monkeypatch.setattr("app.services.engines.base.time.monotonic", lambda: clock[0])
    meter = ThroughputMeter(warmup_seconds=2)
    # Anlauf: langsam
    for _ in range(20):
        clock[0] += 0.1
        meter.add(10_000)
    # Danach 125 MB/s, also 1000 Mbit/s
    for _ in range(40):
        clock[0] += 0.1
        meter.add(12_500_000)
    assert meter.result_mbps() == pytest.approx(1000, rel=0.03)
    assert meter.current_mbps() == pytest.approx(1000, rel=0.03)


def test_cloudflare_download_stays_below_its_limit() -> None:
    # Ab 100 MB je Anfrage antwortet Cloudflare mit 403, der ganze Download scheitert.
    assert cloudflare.DOWNLOAD_BYTES < 100_000_000


async def test_librespeed_auto_prefers_the_faster_of_the_nearest(monkeypatch: pytest.MonkeyPatch) -> None:
    # Naechster nach Ping ist nicht immer der beste: Ein kleiner Server nah dran kann langsam sein.
    engine = librespeed.LibreSpeedEngine()
    backends = librespeed.parse_own(
        [{"name": n, "base": f"http://{n}.example.com/", "prefix": ""} for n in ("close_slow", "fast", "far")]
    )
    pings = {"close_slow": 12.0, "fast": 14.0, "far": 60.0}
    speeds = {"close_slow": 30e6, "fast": 110e6, "far": 125e6}

    async def probe(self: librespeed.LibreSpeedEngine, backend: librespeed.Backend) -> float:
        return pings[backend.name]

    async def quick(self: librespeed.LibreSpeedEngine, backend: librespeed.Backend) -> float:
        return speeds[backend.name]

    monkeypatch.setattr(librespeed.LibreSpeedEngine, "_probe", probe)
    monkeypatch.setattr(librespeed.LibreSpeedEngine, "_quick_download", quick)
    chosen = await engine.nearest(backends)
    # "far" ist schneller, liegt aber mehr als 10 ms hinter dem naechsten und kommt nicht in Frage.
    assert chosen.name == "fast"
