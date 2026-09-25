"""Ganze Messungen gegen einen nachgebauten Server im Prozess.

Die Zahlen sind hier bedeutungslos, es geht um den Ablauf: Phasen in der
richtigen Reihenfolge, Bytes gezaehlt, Ergebnis gefuellt, Abbruch greift.
"""

from __future__ import annotations

import asyncio
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
#: Nach so vielen Downloads antwortet der nachgebaute Server mit 429, wie Cloudflare nach 900 MB.
DOWN_CAP = {"after": 0, "count": 0}
#: Uploads, deren Koerper nicht so lang war wie angekuendigt. Ein echter Server (h11) bricht dann ab.
LENGTH = {"uploads": 0, "wrong": 0}
#: Groesste Upload-Anfrage, die /empty.php annimmt (0: alle), wie nginx mit client_max_body_size.
BODY_LIMIT = {"bytes": 0, "refused": 0, "largest_accepted": 0}


async def fake_server(scope: dict[str, Any], receive: Any, send: Any) -> None:
    assert scope["type"] == "http"
    path = scope["path"]
    query = parse_qs(scope["query_string"].decode())
    received = 0
    declared = dict(scope["headers"]).get(b"content-length")
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
        if size:
            DOWN_CAP["count"] += 1
            if DOWN_CAP["after"] and DOWN_CAP["count"] > DOWN_CAP["after"]:
                status = 429
        body = CHUNK[: min(size, len(CHUNK))]
        headers.append((b"server-timing", b"cfSpeedEdge;dur=1, cfSpeedWorker;dur=1"))
    elif path in ("/__up", "/empty.php"):
        body = b""
        if received:
            LENGTH["uploads"] += 1
            if declared is not None and int(declared) != received:
                LENGTH["wrong"] += 1
        if path == "/__up" and received:
            FLAKY["count"] += 1
            if FLAKY["mode"] == "crash_every_other" and FLAKY["count"] % 2 == 0:
                # Kein httpx-Fehler, wie h11s LocalProtocolError oder ein ssl.SSLError.
                raise OSError("connection broke off")
            if (
                FLAKY["mode"] == "all"
                or (FLAKY["mode"] == "every_other" and FLAKY["count"] % 2 == 0)
                or (FLAKY["mode"] == "first" and FLAKY["count"] == 1)
            ):
                status = 500
        if path == "/empty.php" and received:
            if BODY_LIMIT["bytes"] and received > BODY_LIMIT["bytes"]:
                BODY_LIMIT["refused"] += 1
                status = 413
            else:
                BODY_LIMIT["largest_accepted"] = max(BODY_LIMIT["largest_accepted"], received)
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
    DOWN_CAP.update(after=0, count=0)
    LENGTH.update(uploads=0, wrong=0)
    BODY_LIMIT.update(bytes=0, refused=0, largest_accepted=0)
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
    assert not transfer.unreliable(elapsed=10, needed=5, failed=1, accepted=0, streams=6)
    # Jede Verbindung ist gescheitert und keine Anfrage kam durch: keine Zahl.
    assert transfer.unreliable(elapsed=10, needed=5, failed=6, accepted=0, streams=6)
    # Viele Fehler, aber Anfragen kamen durch: die Messung zaehlt.
    assert not transfer.unreliable(elapsed=10, needed=5, failed=12, accepted=3, streams=6)
    # Alle haben frueh aufgegeben: aus dem Rest hochgerechnet, keine Zahl.
    assert transfer.unreliable(elapsed=3, needed=5, failed=0, accepted=5, streams=6)


async def test_download_ends_when_the_server_starts_throttling(monkeypatch: pytest.MonkeyPatch) -> None:
    # Cloudflare deckelt die Menge und antwortet dann mit 429. Die Phase endet, sobald nach
    # dem Anlauf genug gemessen ist, statt Wartezeit als Messzeit mitzuzaehlen.
    monkeypatch.setattr(transfer, "MIN_MEASURED", 0.3)
    DOWN_CAP["after"] = 400
    reporter, _ = recording_reporter()
    loop = asyncio.get_running_loop()
    started = loop.time()
    mbps, received, _loaded = await transfer.download(
        lambda: "http://fake/__down?bytes=25000000",
        lambda: "http://fake/__down?bytes=0",
        reporter,
        duration=20.0,
    )
    assert mbps and mbps > 0 and received > 0
    # Mit dem Ende bei 429 nach etwa einer halben Sekunde. Ohne es warteten die Verbindungen
    # fuenfmal je eine Sekunde, bevor sie aufgeben, und die Wartezeit zaehlte als Messzeit.
    assert loop.time() - started < 3


async def test_upload_body_is_exactly_as_long_as_announced(monkeypatch: pytest.MonkeyPatch) -> None:
    # Issue #3: Cloudflares 10.000.000 Bytes sind kein Vielfaches der Stueckgroesse. Das
    # letzte Stueck ging ueber die Laenge hinaus, und h11 brach jede Anfrage am Ende ab.
    monkeypatch.setattr(cloudflare, "UPLOAD_BYTES", 300_000)
    reporter, _ = recording_reporter()
    await cloudflare.CloudflareEngine().measure(None, reporter)
    assert LENGTH["uploads"] > 0
    assert LENGTH["wrong"] == 0


async def test_an_unexpected_error_does_not_quietly_end_a_connection() -> None:
    # Issue #3: Ein Fehler, der kein httpx-Fehler ist, beendete die Verbindung ohne
    # Eintrag. Bei schneller Leitung waren alle vor der halben Messzeit tot: "no answer".
    FLAKY["mode"] = "crash_every_other"
    reporter, _ = recording_reporter()
    result = await cloudflare.CloudflareEngine().measure(None, reporter)
    assert result.upload_mbps and result.upload_mbps > 0
    assert FLAKY["count"] > 4


async def test_upload_gets_smaller_when_the_server_refuses_the_size(monkeypatch: pytest.MonkeyPatch) -> None:
    # Issue #3: Manche LibreSpeed-Server nehmen nur 4 MiB oder 1 MiB je Anfrage (HTTP 413).
    monkeypatch.setattr(transfer, "UPLOAD_STEPS", (128 * 1024, 64 * 1024, 16 * 1024))
    BODY_LIMIT["bytes"] = 100_000
    reporter, _ = recording_reporter()
    mbps, sent, _loaded = await transfer.upload(
        lambda: "http://fake/empty.php", lambda: "http://fake/empty.php", reporter
    )
    assert mbps and mbps > 0 and sent > 0
    assert BODY_LIMIT["refused"] > 0
    assert BODY_LIMIT["largest_accepted"] == 64 * 1024


async def test_upload_that_is_too_large_even_at_the_smallest_step_is_not_a_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(transfer, "UPLOAD_STEPS", (128 * 1024, 16 * 1024))
    BODY_LIMIT["bytes"] = 1000
    reporter, _ = recording_reporter()
    with pytest.raises(MeasurementError) as error:
        await transfer.upload(lambda: "http://fake/empty.php", lambda: "http://fake/empty.php", reporter)
    assert error.value.code == "unstable"
    assert "HTTP 413" in error.value.detail


async def test_transfer_ends_at_its_byte_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    # Issue #3: Cloudflare deckelt die Menge je kurzem Zeitfenster. Bei schneller Leitung
    # erreichte ein einzelner Test den Deckel, und danach brach Cloudflare den Upload ab.
    monkeypatch.setattr(transfer, "MIN_MEASURED", 0.3)
    reporter, _ = recording_reporter()
    loop = asyncio.get_running_loop()
    started = loop.time()
    mbps, received, _loaded = await transfer.download(
        lambda: "http://fake/__down?bytes=25000000",
        lambda: "http://fake/__down?bytes=0",
        reporter,
        duration=20.0,
        max_bytes=len(CHUNK) * 4,
    )
    assert mbps and mbps > 0 and received >= len(CHUNK) * 4
    assert loop.time() - started < 3


async def test_cloudflare_download_stays_under_its_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transfer, "MIN_MEASURED", 0.3)
    monkeypatch.setattr(transfer, "DURATION", 20.0)
    monkeypatch.setattr(cloudflare, "DOWNLOAD_BUDGET", len(CHUNK) * 4)
    monkeypatch.setattr(transfer, "upload", _no_upload)
    reporter, _ = recording_reporter()
    loop = asyncio.get_running_loop()
    started = loop.time()
    result = await cloudflare.CloudflareEngine().measure(None, reporter)
    assert result.download_mbps and result.download_mbps > 0
    assert loop.time() - started < 5


async def _no_upload(*_args: Any, **_kwargs: Any) -> tuple[float | None, int, float | None]:
    return 1.0, 1, None
