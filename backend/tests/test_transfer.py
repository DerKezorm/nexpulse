"""Ganze Messungen gegen einen nachgebauten Server im Prozess.

Die Zahlen sind hier bedeutungslos, es geht um den Ablauf: Phasen in der
richtigen Reihenfolge, Bytes gezaehlt, Ergebnis gefuellt, Abbruch greift.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from app.services.engines import cloudflare, librespeed, transfer
from app.services.engines.base import Cancelled, MeasurementError, Reporter

CHUNK = b"x" * 262_144
#: Welche Upload-Anfragen der nachgebaute Server abweist: "none", "every_other" oder "all".
FLAKY = {"mode": "none", "count": 0}


async def fake_server(scope: dict[str, Any], receive: Any, send: Any) -> None:
    assert scope["type"] == "http"
    path = scope["path"]
    query = parse_qs(scope["query_string"].decode())
    received = 0
    while True:
        message = await receive()
        received += len(message.get("body", b""))
        if not message.get("more_body"):
            break
    status, headers, body = 200, [(b"content-type", b"application/octet-stream")], b""
    if path == "/cdn-cgi/trace":
        body = b"colo=FRA\nloc=DE\nip=203.0.113.5\n"
    elif path == "/__down":
        size = int(query.get("bytes", ["0"])[0])
        body = CHUNK[: min(size, len(CHUNK))]
        headers.append((b"server-timing", b"cfSpeedEdge;dur=1, cfSpeedWorker;dur=1"))
    elif path in ("/__up", "/empty.php"):
        body = b""
        if path == "/__up" and received:
            FLAKY["count"] += 1
            if (
                FLAKY["mode"] == "all"
                or (FLAKY["mode"] == "every_other" and FLAKY["count"] % 2 == 0)
                or (FLAKY["mode"] == "first" and FLAKY["count"] == 1)
            ):
                status = 500
    elif path == "/garbage.php":
        body = CHUNK
    elif path == "/getIP.php":
        body = b'{"processedString": "203.0.113.5 - Example ISP, DE", "rawIspInfo": ""}'
    else:
        status = 404
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


@pytest.fixture(autouse=True)
def local_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    def fake_client(streams: int | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=fake_server), base_url="http://fake")

    monkeypatch.setattr(transfer, "client", fake_client)
    monkeypatch.setattr(transfer, "DURATION", 0.8)
    monkeypatch.setattr(transfer, "WARMUP", 0.2)
    monkeypatch.setattr(transfer, "STREAMS", 2)
    monkeypatch.setattr(transfer, "UPLOAD_REQUEST_BYTES", 256 * 1024)
    monkeypatch.setattr(cloudflare, "BASE", "http://fake")
    monkeypatch.setattr(cloudflare, "UPLOAD_BYTES", 256 * 1024)
    FLAKY.update(mode="none", count=0)
    yield


def recording_reporter(cancel_after_phase: str = "") -> tuple[Reporter, list[dict[str, object]]]:
    events: list[dict[str, object]] = []

    def cancelled() -> bool:
        return bool(cancel_after_phase) and any(e.get("phase") == cancel_after_phase for e in events)

    return Reporter(emit=events.append, cancelled=cancelled), events


async def test_cloudflare_runs_all_phases() -> None:
    reporter, events = recording_reporter()
    result = await cloudflare.CloudflareEngine().measure(None, reporter)
    phases = [e["phase"] for e in events if e["type"] == "phase"]
    assert phases == ["ping", "download", "upload"]
    assert result.server is not None and result.server.id == "FRA"
    assert result.external_ip == "203.0.113.5"
    assert result.ping_ms is not None and result.jitter_ms is not None
    assert result.download_mbps and result.download_mbps > 0
    assert result.upload_mbps and result.upload_mbps > 0
    assert result.bytes_down and result.bytes_down >= len(CHUNK)
    assert result.bytes_up and result.bytes_up > 0
    assert result.loaded_down_ms is not None
    assert any(e["type"] == "value" and e["phase"] == "download" for e in events)


async def test_librespeed_with_a_fixed_own_server(monkeypatch: pytest.MonkeyPatch) -> None:
    async def own_only(self: librespeed.LibreSpeedEngine) -> list[librespeed.Backend]:
        return librespeed.parse_own([{"name": "Homelab", "base": "http://fake/", "prefix": ""}])

    monkeypatch.setattr(librespeed.LibreSpeedEngine, "backends", own_only)
    reporter, _ = recording_reporter()
    server_id = librespeed.own_id("http://fake/")
    result = await librespeed.LibreSpeedEngine().measure(server_id, reporter)
    assert result.isp == "Example ISP, DE"
    assert result.server is not None and result.server.name == "Homelab"
    assert result.download_mbps and result.upload_mbps


async def test_librespeed_unknown_server_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def own_only(self: librespeed.LibreSpeedEngine) -> list[librespeed.Backend]:
        return librespeed.parse_own([{"name": "Homelab", "base": "http://fake/", "prefix": ""}])

    monkeypatch.setattr(librespeed.LibreSpeedEngine, "backends", own_only)
    reporter, _ = recording_reporter()
    with pytest.raises(MeasurementError) as error:
        await librespeed.LibreSpeedEngine().measure("own-gone", reporter)
    assert error.value.code == "server_gone"


async def test_cancel_stops_during_download() -> None:
    reporter, events = recording_reporter(cancel_after_phase="download")
    with pytest.raises(Cancelled):
        await cloudflare.CloudflareEngine().measure(None, reporter)
    assert not any(e.get("phase") == "upload" for e in events)


async def test_failed_requests_are_repeated_not_fatal() -> None:
    # Cloudflare bricht Uploads sporadisch ab. Frueher endete damit die Verbindung und
    # der kurze Rest wurde hochgerechnet.
    FLAKY["mode"] = "every_other"
    reporter, _ = recording_reporter()
    result = await cloudflare.CloudflareEngine().measure(None, reporter)
    assert result.upload_mbps and result.upload_mbps > 0
    assert FLAKY["count"] > 4


async def test_upload_that_never_works_is_not_a_result() -> None:
    FLAKY["mode"] = "all"
    reporter, _ = recording_reporter()
    with pytest.raises(MeasurementError) as error:
        await cloudflare.CloudflareEngine().measure(None, reporter)
    assert error.value.code == "unstable"


async def test_librespeed_falls_back_when_the_best_server_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    backends = librespeed.parse_own(
        [
            {"name": "Refuses", "base": "http://fake/refuse/", "prefix": ""},
            {"name": "Works", "base": "http://fake/", "prefix": ""},
        ]
    )

    async def own(self: librespeed.LibreSpeedEngine) -> list[librespeed.Backend]:
        return backends

    async def ranked(
        self: librespeed.LibreSpeedEngine, candidates: list[librespeed.Backend]
    ) -> list[librespeed.Backend]:
        return candidates

    monkeypatch.setattr(librespeed.LibreSpeedEngine, "backends", own)
    monkeypatch.setattr(librespeed.LibreSpeedEngine, "ranked", ranked)
    reporter, _ = recording_reporter()
    result = await librespeed.LibreSpeedEngine().measure(None, reporter)
    assert result.server is not None and result.server.name == "Works"
    assert result.download_mbps


async def test_single_refused_ping_does_not_end_the_test(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}
    original = transfer.latency_sample

    async def sometimes_refused(http: httpx.AsyncClient, url: str, server_time: transfer.ServerTime) -> float:
        calls["count"] += 1
        if calls["count"] == 3:
            raise MeasurementError("server_error", f"HTTP 403 from {url}")
        return await original(http, url, server_time)

    monkeypatch.setattr(transfer, "latency_sample", sometimes_refused)
    reporter, _ = recording_reporter()
    result = await cloudflare.CloudflareEngine().measure(None, reporter)
    assert result.ping_ms is not None


def test_when_a_transfer_is_unreliable() -> None:
    # Ein Abbruch neben fuenf laufenden Verbindungen: die Messung zaehlt.
    assert not transfer.unreliable(elapsed=10, duration=10, failed=1, accepted=0, streams=6)
    # Jede Verbindung ist gescheitert und keine Anfrage kam durch: keine Zahl.
    assert transfer.unreliable(elapsed=10, duration=10, failed=6, accepted=0, streams=6)
    # Viele Fehler, aber Anfragen kamen durch: die Messung zaehlt.
    assert not transfer.unreliable(elapsed=10, duration=10, failed=12, accepted=3, streams=6)
    # Alle haben frueh aufgegeben: aus dem Rest hochgerechnet, keine Zahl.
    assert transfer.unreliable(elapsed=3, duration=10, failed=0, accepted=5, streams=6)
