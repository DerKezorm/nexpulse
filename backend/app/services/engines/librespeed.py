"""Messung gegen LibreSpeed-Server, oeffentliche oder eigene.

Das Protokoll ist schlicht: ``garbage.php?ckSize=N`` liefert N MiB Zufall,
``empty.php`` nimmt Uploads an und antwortet leer (auch fuer die Laufzeit),
``getIP.php?isp=true`` nennt Adresse und Anbieter. Der Client hier ist eigener
Code, nicht aus librespeed-cli (LGPL) uebernommen.

"Automatisch" nimmt wie librespeed-cli den Server mit der kuerzesten Laufzeit.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ...db import SessionLocal
from .. import settings_service
from . import transfer
from .base import Measurement, MeasurementError, Reporter, ServerInfo

logger = logging.getLogger("nexpulse.librespeed")

PUBLIC_LIST = "https://librespeed.org/backend-servers/servers.php"
LIST_TTL = 6 * 3600
PROBE_CONCURRENCY = 10
#: So viele der naechsten Server bekommen einen kurzen Download, bevor einer gewaehlt wird.
SHORTLIST = 3
#: Nur Server, die hoechstens so viel langsamer antworten als der schnellste.
SHORTLIST_SPREAD_MS = 10.0
QUICK_SECONDS = 1.5


@dataclass
class Backend:
    id: str
    name: str
    base: str
    dl: str = "garbage.php"
    ul: str = "empty.php"
    ping: str = "empty.php"
    ip: str = "getIP.php"
    sponsor: str = ""
    own: bool = False

    def url(self, path: str) -> str:
        return self.base.rstrip("/") + "/" + path.lstrip("/")

    def info(self) -> ServerInfo:
        location = self.name.split(" (")[0] if " (" in self.name else ("own server" if self.own else "")
        return ServerInfo(id=self.id, name=self.name, location=location, sponsor=self.sponsor, host=self.base)


def _absolute(base: str) -> str:
    return "https:" + base if base.startswith("//") else base


def own_id(base: str) -> str:
    return "own-" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]


def parse_public(items: list[dict[str, Any]]) -> list[Backend]:
    backends = []
    for item in items:
        try:
            backends.append(
                Backend(
                    id=f"pub-{int(item['id'])}",
                    name=str(item["name"]),
                    base=_absolute(str(item["server"])),
                    dl=str(item.get("dlURL") or "garbage.php"),
                    ul=str(item.get("ulURL") or "empty.php"),
                    ping=str(item.get("pingURL") or "empty.php"),
                    ip=str(item.get("getIpURL") or "getIP.php"),
                    sponsor=str(item.get("sponsorName") or ""),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return backends


def parse_own(items: list[dict[str, Any]]) -> list[Backend]:
    backends = []
    for item in items:
        base = str(item.get("base") or "")
        if not base:
            continue
        prefix = str(item.get("prefix") or "")
        backends.append(
            Backend(
                id=own_id(base),
                name=str(item.get("name") or base),
                base=base,
                dl=prefix + "garbage.php",
                ul=prefix + "empty.php",
                ping=prefix + "empty.php",
                ip=prefix + "getIP.php",
                own=True,
            )
        )
    return backends


class LibreSpeedEngine:
    name = "librespeed"

    def __init__(self) -> None:
        self._public: list[Backend] = []
        self._fetched = 0.0

    async def _public_list(self) -> list[Backend]:
        if self._public and time.monotonic() - self._fetched < LIST_TTL:
            return self._public
        try:
            async with transfer.client(1) as http:
                response = await http.get(PUBLIC_LIST)
                response.raise_for_status()
                self._public = parse_public(response.json())
                self._fetched = time.monotonic()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Could not load the public LibreSpeed server list: %s", type(exc).__name__)
        return self._public

    async def backends(self) -> list[Backend]:
        with SessionLocal() as db:
            settings = settings_service.load(db)
        own = parse_own(settings["librespeed_servers"])
        public = await self._public_list() if settings["librespeed_public"] else []
        return own + public

    async def servers(self) -> list[ServerInfo]:
        return [backend.info() for backend in await self.backends()]

    async def _probe(self, backend: Backend) -> float | None:
        try:
            async with transfer.client(1) as http:
                samples = []
                for _ in range(3):
                    samples.append(
                        await asyncio.wait_for(
                            transfer.latency_sample(
                                http, backend.url(backend.ping) + f"?r={secrets.token_hex(4)}", transfer.no_server_time
                            ),
                            timeout=2.5,
                        )
                    )
                # Die erste enthaelt den Verbindungsaufbau.
                return min(samples[1:])
        except (httpx.HTTPError, TimeoutError, MeasurementError):
            return None

    async def _quick_download(self, backend: Backend) -> float:
        """Bytes je Sekunde in einem kurzen Download ueber eine Verbindung."""
        received = 0
        loop = asyncio.get_running_loop()
        started = loop.time()
        try:
            async with transfer.client(1) as http:
                url = backend.url(backend.dl) + f"?r={secrets.token_hex(4)}&ckSize=20"
                async with http.stream("GET", url) as response:
                    if response.status_code >= 400:
                        return 0.0
                    async for chunk in response.aiter_raw(transfer.CHUNK):
                        received += len(chunk)
                        if loop.time() - started >= QUICK_SECONDS:
                            break
        except httpx.HTTPError:
            return 0.0
        return received / max(loop.time() - started, 0.01)

    async def nearest(self, candidates: list[Backend]) -> Backend:
        return (await self.ranked(candidates))[0]

    async def ranked(self, candidates: list[Backend]) -> list[Backend]:
        """Die Server fuer "automatisch", der beste zuerst, dahinter die Ausweichserver.

        Erst der Ping aller Server, dann ein kurzer Download bei den naechsten drei.
        Nur nach Ping zu waehlen (wie librespeed-cli) nahm am 19.09.2026 von docker-dev
        aus einen kleinen Server, der mit 16 ms antwortete und 270 Mbit/s lieferte,
        wo Frankfurt 13 ms und die volle Leitung hatte.
        """
        gate = asyncio.Semaphore(PROBE_CONCURRENCY)

        async def probe(backend: Backend) -> tuple[Backend, float | None]:
            async with gate:
                return backend, await self._probe(backend)

        results = await asyncio.gather(*(probe(backend) for backend in candidates))
        reachable = sorted(((b, ms) for b, ms in results if ms is not None), key=lambda pair: pair[1])
        if not reachable:
            raise MeasurementError("no_server", "No LibreSpeed server answered.")
        best_ping = reachable[0][1]
        shortlist = [backend for backend, ms in reachable[:SHORTLIST] if ms - best_ping <= SHORTLIST_SPREAD_MS]
        others = [backend for backend, _ms in reachable if backend not in shortlist][: SHORTLIST - 1]
        if len(shortlist) == 1:
            return shortlist + others
        speeds = await asyncio.gather(*(self._quick_download(backend) for backend in shortlist))
        by_speed = [backend for backend, _speed in sorted(zip(shortlist, speeds, strict=True), key=lambda p: -p[1])]
        return by_speed + others

    async def measure(self, server_id: str | None, reporter: Reporter) -> Measurement:
        backends = await self.backends()
        if not backends:
            raise MeasurementError("no_server", "No LibreSpeed server is configured.")
        reporter.phase("selecting")
        if server_id:
            fixed = next((backend for backend in backends if backend.id == server_id), None)
            if fixed is None:
                raise MeasurementError("server_gone", f"Server {server_id} is no longer in the list.")
            candidates = [fixed]
        else:
            candidates = await self.ranked(backends)

        # Streikt der gewaehlte Server gleich beim Ping, geht es mit dem naechsten weiter.
        # Bei einem fest gewaehlten Server nicht: Wer ihn waehlt, will ihn messen.
        samples: list[float] = []
        chosen = candidates[0]
        result = Measurement()
        for index, chosen in enumerate(candidates):
            result = Measurement(server=chosen.info())
            reporter.server(chosen.info())
            reporter.phase("ping")
            try:
                async with transfer.client(1) as http:
                    try:
                        response = await http.get(_nonce_url(chosen, chosen.ip, "&isp=true"))
                        if response.status_code == 200:
                            result.external_ip, result.isp = parse_ip_info(response)
                    except httpx.HTTPError:
                        pass
                    samples = await transfer.measure_latency(
                        http, lambda backend=chosen: _nonce_url(backend, backend.ping), reporter, count=10
                    )
                break
            except MeasurementError as exc:
                if index == len(candidates) - 1:
                    raise
                logger.info("LibreSpeed server %s did not answer (%s), trying the next one", chosen.name, exc.detail)

        def nonce_url(path: str, extra: str = "") -> str:
            return _nonce_url(chosen, path, extra)

        latency = transfer.summarize_latency(samples)
        result.ping_ms = latency["ping_ms"]
        result.jitter_ms = latency["jitter_ms"]
        result.ping_low_ms = latency["ping_low_ms"]
        result.ping_high_ms = latency["ping_high_ms"]

        ping_url = lambda: nonce_url(chosen.ping)
        reporter.phase("download")
        result.download_mbps, result.bytes_down, result.loaded_down_ms = await transfer.download(
            lambda: nonce_url(chosen.dl, "&ckSize=100"), ping_url, reporter
        )
        reporter.phase("upload")
        result.upload_mbps, result.bytes_up, result.loaded_up_ms = await transfer.upload(
            lambda: nonce_url(chosen.ul), ping_url, reporter
        )
        return result


def _nonce_url(backend: Backend, path: str, extra: str = "") -> str:
    # Gegen Zwischenspeicher unterwegs: jede Anfrage eine andere Adresse.
    return backend.url(path) + f"?r={secrets.token_hex(4)}" + extra


def parse_ip_info(response: httpx.Response) -> tuple[str, str]:
    """``processedString`` sieht aus wie ``203.0.113.1 - Example ISP, DE (12 km)``."""
    try:
        data = response.json()
    except ValueError:
        return response.text.strip()[:64], ""
    text = str(data.get("processedString") or "")
    ip, _, rest = text.partition(" - ")
    isp = rest.split(" (")[0].strip()
    raw = data.get("rawIspInfo") or {}
    if isinstance(raw, dict) and raw.get("org") and not isp:
        isp = str(raw["org"])
    return ip.strip(), isp


async def find_backend_prefix(base: str) -> str:
    """Wo auf einem eigenen Server die Endpunkte liegen: direkt oder unter ``backend/``."""
    async with transfer.client(1) as http:
        for prefix in ("", "backend/"):
            url = base.rstrip("/") + "/" + prefix + "empty.php"
            try:
                response = await http.get(url, timeout=5)
            except httpx.HTTPError:
                continue
            if response.status_code == 200:
                return prefix
    raise MeasurementError("librespeed_not_found", f"No LibreSpeed backend at {base}")
