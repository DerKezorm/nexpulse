"""Messung gegen speed.cloudflare.com.

Endpunkte wie Cloudflares eigene Bibliothek (github.com/cloudflare/speedtest):
``__down?bytes=N`` liefert N Bytes, ``__up`` nimmt beliebig viel entgegen.
Welches Rechenzentrum antwortet, entscheidet Cloudflare per Anycast; waehlen
kann man es nicht. ``/cdn-cgi/trace`` sagt hinterher, welches es war.

Die Serverzeit steht in ``Server-Timing`` (``cfSpeedEdge``, ``cfSpeedWorker``)
und wird von der Laufzeit abgezogen, wie in Cloudflares Bibliothek.

Paketverlust misst Cloudflare nur ueber WebRTC mit TURN. Von einem Server aus
geht das nicht sinnvoll, der Wert bleibt hier leer.
"""

from __future__ import annotations

import re
import secrets

import httpx

from . import transfer
from .base import Measurement, MeasurementError, Reporter, ServerInfo

BASE = "https://speed.cloudflare.com"
#: Bytes je Download-Anfrage. ⚠️ Ab 100 MB antwortet Cloudflare mit 403 (gemessen am
#: 19.09.2026: 99.000.000 geht, 100.000.000 nicht). 25 MB nimmt auch Cloudflares Bibliothek.
DOWNLOAD_BYTES = 25_000_000
#: Bytes je Upload-Anfrage. Grosse Uploads (25 MB und mehr) brach Cloudflare am 19.09.2026
#: haeufiger ab; mit 10 MB stimmte das Ergebnis mit Ookla ueberein.
UPLOAD_BYTES = 10_000_000
#: So viele Bytes laedt ein Test hoechstens herunter. ⚠️ Cloudflare deckelt die Menge: Am
#: 25.09.2026 kam nach 750 MB in einem Zug 429 (am 19.09.2026 nach 900 MB), und danach wies
#: es jede Download-Anfrage ab 10 MB fuer mehr als eine halbe Stunde ab. Bei 850 Mbit/s riss
#: ein einzelner Test den Deckel (Issue #3). Der Upload hat keinen: 1,2 GB am Stueck gingen durch.
DOWNLOAD_BUDGET = 500_000_000
_TIMING = re.compile(r"(cfSpeed\w*);dur=([\d.]+)")


def server_time(response: httpx.Response) -> float:
    total = 0.0
    for header in response.headers.get_list("server-timing"):
        for _name, value in _TIMING.findall(header):
            total += float(value)
    return total / 1000


def _nonce() -> str:
    # Gegen Zwischenspeicher unterwegs, jede Anfrage ist eine andere Adresse.
    return secrets.token_hex(4)


def parse_trace(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key:
            values[key.strip()] = value.strip()
    return values


class CloudflareEngine:
    name = "cloudflare"

    async def servers(self) -> list[ServerInfo]:
        return [ServerInfo(id="auto", name="Cloudflare", location="nearest data center")]

    async def measure(self, server_id: str | None, reporter: Reporter) -> Measurement:
        result = Measurement()
        async with transfer.client(1) as http:
            try:
                response = await http.get(f"{BASE}/cdn-cgi/trace")
            except httpx.HTTPError as exc:
                raise MeasurementError("unreachable", type(exc).__name__) from exc
            trace = parse_trace(response.text) if response.status_code == 200 else {}
            colo = trace.get("colo", "")
            country = trace.get("loc", "")
            result.external_ip = trace.get("ip", "")
            result.server = ServerInfo(
                id=colo or "auto", name="Cloudflare", location=" · ".join(part for part in (colo, country) if part)
            )
            reporter.server(result.server)

            reporter.phase("ping")
            samples = await transfer.measure_latency(
                http, lambda: f"{BASE}/__down?bytes=0&r={_nonce()}", reporter, server_time
            )
        latency = transfer.summarize_latency(samples)
        result.ping_ms = latency["ping_ms"]
        result.jitter_ms = latency["jitter_ms"]
        result.ping_low_ms = latency["ping_low_ms"]
        result.ping_high_ms = latency["ping_high_ms"]

        ping_url = lambda: f"{BASE}/__down?bytes=0&r={_nonce()}"

        reporter.phase("download")
        result.download_mbps, result.bytes_down, result.loaded_down_ms = await transfer.download(
            lambda: f"{BASE}/__down?bytes={DOWNLOAD_BYTES}&r={_nonce()}",
            ping_url,
            reporter,
            server_time,
            max_bytes=DOWNLOAD_BUDGET,
        )
        reporter.phase("upload")
        result.upload_mbps, result.bytes_up, result.loaded_up_ms = await transfer.upload(
            lambda: f"{BASE}/__up?r={_nonce()}", ping_url, reporter, server_time, request_bytes=UPLOAD_BYTES
        )
        return result
