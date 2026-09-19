"""Messung mit Ooklas Speedtest-CLI.

⚠️ **nexpulse liefert die CLI nicht mit.** Sie wird erst geladen, wenn der
Betreiber in den Einstellungen zustimmt. Ooklas Lizenz erlaubt die CLI nur
"for your personal, non-commercial use on a single personal computer" und
verbietet ausdruecklich, sie auf einem Geraet zu betreiben, das mehrere Geraete
im Netz erreichen koennen, oder auf "any router, modem, or other non-personal
computer device". Ein Container im Heimnetz faellt darunter. Das steht so in
der Oberflaeche, und der Betreiber verantwortet die Nutzung selbst
(entschieden am 19.09.2026).

Ausgabe mit ``-f jsonl -p yes``: eine JSON-Zeile je Ereignis (``testStart``,
``ping``, ``download``, ``upload``, ``result``, ``log``). Bandbreiten sind
**Bytes je Sekunde**, nicht Bits.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import platform
import shutil
import stat
import tarfile
from pathlib import Path
from typing import Any

import httpx

from ...config import get_settings
from . import transfer
from .base import Measurement, MeasurementError, Reporter, ServerInfo

logger = logging.getLogger("nexpulse.ookla")

VERSION = "1.2.0"
DOWNLOAD = "https://install.speedtest.net/app/cli/ookla-speedtest-{version}-linux-{arch}.tgz"
ARCHES = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64", "armv7l": "armhf"}
ACCEPT = ["--accept-license", "--accept-gdpr"]
TIMEOUT = 120


def folder() -> Path:
    return get_settings().tools_dir / "ookla"


def binary() -> Path:
    return folder() / "speedtest"


def installed() -> bool:
    return binary().is_file()


def _env() -> dict[str, str]:
    # Die CLI merkt sich die Zustimmung unter ~/.config/ookla. Das Zuhause liegt
    # deshalb im Datenverzeichnis und ueberlebt so ein Update des Containers.
    home = folder() / "home"
    home.mkdir(parents=True, exist_ok=True)
    return {**os.environ, "HOME": str(home)}


def arch() -> str:
    machine = platform.machine().lower()
    if platform.system() != "Linux" or machine not in ARCHES:
        raise MeasurementError("ookla_unsupported", f"{platform.system()} {machine}")
    return ARCHES[machine]


async def install() -> str:
    """CLI von Ookla laden und ins Datenverzeichnis legen. Gibt die Fassung zurueck."""
    url = DOWNLOAD.format(version=VERSION, arch=arch())
    try:
        async with transfer.client(1) as http:
            response = await http.get(url, timeout=60)
    except httpx.HTTPError as exc:
        raise MeasurementError("ookla_download_failed", type(exc).__name__) from exc
    if response.status_code != 200:
        raise MeasurementError("ookla_download_failed", f"HTTP {response.status_code}")
    try:
        with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as archive:
            member = next(
                (m for m in archive.getmembers() if m.name.split("/")[-1] == "speedtest" and m.isfile()), None
            )
            if member is None:
                raise MeasurementError("ookla_download_failed", "archive without speedtest binary")
            extracted = archive.extractfile(member)
            data = extracted.read() if extracted else b""
    except tarfile.TarError as exc:
        raise MeasurementError("ookla_download_failed", "broken archive") from exc
    target = binary()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".new")
    temporary.write_bytes(data)
    temporary.chmod(temporary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    temporary.replace(target)
    version = await run_version()
    logger.info("Ookla Speedtest CLI %s installed", version)
    return version


def uninstall() -> None:
    shutil.rmtree(folder(), ignore_errors=True)


async def _run(args: list[str], timeout: float = 30) -> tuple[int, str, str]:
    if not installed():
        raise MeasurementError("ookla_not_installed")
    process = await asyncio.create_subprocess_exec(
        str(binary()), *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=_env()
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError as exc:
        process.kill()
        raise MeasurementError("ookla_timeout") from exc
    return process.returncode or 0, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace")


async def run_version() -> str:
    code, out, err = await _run(["--version", *ACCEPT])
    if code != 0:
        raise MeasurementError("ookla_failed", (err or out)[-500:])
    first = out.strip().splitlines()[0] if out.strip() else ""
    return first.replace("Speedtest by Ookla", "").strip() or VERSION


def parse_servers(text: str) -> list[ServerInfo]:
    try:
        data: Any = json.loads(text)
    except ValueError:
        return []
    items = data.get("servers", []) if isinstance(data, dict) else data
    servers = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or "id" not in item:
            continue
        location = ", ".join(str(part) for part in (item.get("location"), item.get("country")) if part)
        servers.append(
            ServerInfo(
                id=str(item["id"]),
                name=str(item.get("name") or item["id"]),
                location=location,
                sponsor=str(item.get("name") or ""),
                host=str(item.get("host") or ""),
            )
        )
    return servers


def mbps(bytes_per_second: Any) -> float | None:
    try:
        return float(bytes_per_second) * 8 / 1e6
    except (TypeError, ValueError):
        return None


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def apply_result(data: dict[str, Any], result: Measurement) -> None:
    ping = data.get("ping") or {}
    download = data.get("download") or {}
    upload = data.get("upload") or {}
    server = data.get("server") or {}
    result.ping_ms = _num(ping.get("latency"))
    result.jitter_ms = _num(ping.get("jitter"))
    result.ping_low_ms = _num(ping.get("low"))
    result.ping_high_ms = _num(ping.get("high"))
    result.download_mbps = mbps(download.get("bandwidth"))
    result.upload_mbps = mbps(upload.get("bandwidth"))
    result.bytes_down = int(download["bytes"]) if isinstance(download.get("bytes"), int) else None
    result.bytes_up = int(upload["bytes"]) if isinstance(upload.get("bytes"), int) else None
    result.loaded_down_ms = _num((download.get("latency") or {}).get("iqm"))
    result.loaded_up_ms = _num((upload.get("latency") or {}).get("iqm"))
    result.packet_loss = _num(data.get("packetLoss"))
    result.isp = str(data.get("isp") or "")
    result.external_ip = str((data.get("interface") or {}).get("externalIp") or "")
    result.result_url = str((data.get("result") or {}).get("url") or "")
    if server:
        result.server = ServerInfo(
            id=str(server.get("id", "")),
            name=str(server.get("name") or ""),
            location=", ".join(str(p) for p in (server.get("location"), server.get("country")) if p),
            sponsor=str(server.get("name") or ""),
            host=str(server.get("host") or ""),
        )


class OoklaEngine:
    name = "ookla"

    async def servers(self) -> list[ServerInfo]:
        code, out, err = await _run(["-L", "-f", "json", *ACCEPT])
        if code != 0:
            raise MeasurementError("ookla_failed", (err or out)[-500:])
        return parse_servers(out)

    async def measure(self, server_id: str | None, reporter: Reporter) -> Measurement:
        if not installed():
            raise MeasurementError("ookla_not_installed")
        args = ["-f", "jsonl", "-p", "yes", *ACCEPT]
        if server_id:
            args += ["-s", server_id]
        process = await asyncio.create_subprocess_exec(
            str(binary()), *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=_env()
        )
        assert process.stdout is not None
        result = Measurement()
        errors: list[str] = []
        phase = ""
        finished = False
        loop = asyncio.get_running_loop()
        deadline = loop.time() + TIMEOUT
        try:
            while True:
                if reporter.cancelled():
                    process.kill()
                    reporter.check()
                if loop.time() > deadline:
                    process.kill()
                    raise MeasurementError("ookla_timeout")
                try:
                    line = await asyncio.wait_for(process.stdout.readline(), timeout=0.5)
                except TimeoutError:
                    continue
                if not line:
                    break
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                kind = event.get("type")
                if kind == "testStart":
                    apply_result({"server": event.get("server"), "isp": event.get("isp")}, result)
                    if result.server:
                        reporter.server(result.server)
                elif kind in ("ping", "download", "upload"):
                    if kind != phase:
                        phase = kind
                        reporter.phase(kind)
                    body = event.get(kind) or {}
                    if kind == "ping":
                        latency = _num(body.get("latency"))
                        if latency is not None:
                            reporter.ping(latency)
                    else:
                        value = mbps(body.get("bandwidth"))
                        if value is not None:
                            reporter.value(kind, value)
                elif kind == "result":
                    apply_result(event, result)
                    finished = True
                elif kind == "log" and str(event.get("level", "")).lower() == "error":
                    errors.append(str(event.get("message", ""))[:300])
        finally:
            if process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except TimeoutError:
                    process.kill()
        stderr = (await process.stderr.read()).decode("utf-8", "replace") if process.stderr else ""
        if not finished:
            raise MeasurementError("ookla_failed", "; ".join(errors) or stderr[-500:] or f"exit {process.returncode}")
        return result
