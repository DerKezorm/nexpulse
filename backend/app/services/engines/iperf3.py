"""Messung gegen einen eigenen iperf3-Server.

iperf3 ist der uebliche Weg, die Anbindung eines eigenen Servers zu messen:
auf dem Ziel laeuft ``iperf3 -s``, nexpulse ist die Gegenstelle. Ein
Verzeichnis oeffentlicher Server gibt es nicht und soll es hier auch nicht
geben, der Betreiber traegt Adresse und Port selbst ein.

``--json-stream`` gibt eine JSON-Zeile je Ereignis aus (``start``,
``interval``, ``end``, ``error``), wie Ooklas ``-f jsonl``. Bandbreiten sind
**Bits je Sekunde**. Gemessen wird ueblicherweise zweimal: einmal rueckwaerts
(``-R``, das ist der Download) und einmal vorwaerts (Upload). Je Ziel laesst
sich einstellen, welche Richtungen, mit wie vielen Verbindungen und ueber
welche IP-Fassung gemessen wird (Wunsch aus Issue #1, 23.09.2026).

Was iperf3 ueber TCP nicht liefert: Paketverlust, Anbieter und aeussere
Adresse. Die Laufzeit unter Last kommt aus den TCP-Werten des Senders und gibt
es deshalb nur fuer den Upload; im Download sendet die Gegenstelle, und ihre
Werte stehen nicht in der Ausgabe des Clients.

⚠️ ``--connect-timeout`` deckt nur den Verbindungsaufbau. Ein Port, der die
Verbindung annimmt und dann schweigt (gemessen am 23.09.2026 gegen einen
Horchposten ohne iperf3), laesst den Client endlos warten. Deshalb hat jeder
Lauf hier seine eigene Frist.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import time
from dataclasses import dataclass
from typing import Any

from ...db import SessionLocal
from .. import settings_service
from . import transfer
from .base import Measurement, MeasurementError, Reporter, ServerInfo

logger = logging.getLogger("nexpulse.iperf3")

BINARY = "iperf3"
DEFAULT_PORT = 5201
#: Sekunden je Richtung. Dazu kommt ``OMIT``, das sind zwei Laeufe zu elf Sekunden.
DURATION = 10
#: Die erste Sekunde zaehlt nicht mit, solange zieht TCP das Fenster erst auf.
OMIT = 1
#: Eine einzelne Verbindung fuellt eine schnelle Leitung mit Laufzeit nicht aus.
STREAMS = 4
MAX_STREAMS = 32
#: Welche Richtungen ein Ziel misst. Wer nur wissen will, was ankommt, spart die Haelfte der Zeit.
DIRECTIONS = ("both", "down", "up")
#: IP-Fassung erzwingen. Ein Name mit A- und AAAA-Eintrag laesst iperf3 sonst selbst waehlen.
FAMILIES = {"auto": [], "ipv4": ["-4"], "ipv6": ["-6"]}
CONNECT_TIMEOUT_MS = 5000
PING_SAMPLES = 10
PING_TIMEOUT = 3.0
#: Der Server horcht erst wieder, wenn er den letzten Test aufgeraeumt hat.
BETWEEN_RUNS = 1.0
#: So lange laeuft die Probe beim Eintragen eines Ziels.
CHECK_SECONDS = 1


def available() -> bool:
    return shutil.which(BINARY) is not None


def target_id(host: str, port: int) -> str:
    return "tgt-" + hashlib.sha1(f"{host}:{port}".encode()).hexdigest()[:8]


@dataclass
class Target:
    id: str
    name: str
    host: str
    port: int
    #: both, down oder up
    directions: str = "both"
    streams: int = STREAMS
    #: auto, ipv4 oder ipv6
    family: str = "auto"

    def info(self) -> ServerInfo:
        return ServerInfo(id=self.id, name=self.name, location="own server", host=f"{self.host}:{self.port}")

    def measures(self, direction: str) -> bool:
        return self.directions in ("both", direction)


def _int(value: Any, default: int, low: int, high: int) -> int:
    try:
        return min(max(int(value), low), high)
    except (TypeError, ValueError):
        return default


def parse_targets(items: list[dict[str, Any]]) -> list[Target]:
    """Aus den Einstellungen. Ziele von vor 0.3.0 haben die Wahlmoeglichkeiten nicht und bekommen die Vorgaben."""
    targets = []
    for item in items:
        host = str(item.get("host") or "")
        if not host:
            continue
        port = _int(item.get("port"), DEFAULT_PORT, 1, 65535)
        directions = str(item.get("directions") or "both")
        family = str(item.get("family") or "auto")
        targets.append(
            Target(
                id=target_id(host, port),
                name=str(item.get("name") or host),
                host=host,
                port=port,
                directions=directions if directions in DIRECTIONS else "both",
                streams=_int(item.get("streams"), STREAMS, 1, MAX_STREAMS),
                family=family if family in FAMILIES else "auto",
            )
        )
    return targets


def targets() -> list[Target]:
    with SessionLocal() as db:
        return parse_targets(settings_service.load(db)["iperf3_servers"])


async def tcp_ping(host: str, port: int, timeout: float = PING_TIMEOUT) -> float:
    """Eine Laufzeit in Millisekunden: TCP-Verbindung aufbauen und gleich wieder schliessen.

    Der iperf3-Server hat keinen eigenen Ping. Der Handschlag ist genau eine
    Runde und damit das, was ein Ping auch misst; der Server nimmt es nicht
    uebel, ein Test direkt danach laeuft normal (gemessen am 23.09.2026).
    """
    started = time.perf_counter()
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
    except (TimeoutError, OSError) as exc:
        raise MeasurementError("unreachable", f"{host}:{port} {type(exc).__name__}") from exc
    elapsed = (time.perf_counter() - started) * 1000
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return max(0.1, elapsed)


async def ping_samples(target: Target, reporter: Reporter | None = None, count: int = PING_SAMPLES) -> list[float]:
    """Laufzeiten zum Ziel. Zwei Fehlversuche sind erlaubt, beim dritten ist das Ziel weg."""
    samples: list[float] = []
    failed = 0
    while len(samples) < count:
        if reporter is not None:
            reporter.check()
        try:
            samples.append(await tcp_ping(target.host, target.port))
        except MeasurementError:
            failed += 1
            if failed > 2:
                raise
            await asyncio.sleep(0.2)
            continue
        if reporter is not None:
            reporter.ping(min(samples))
        await asyncio.sleep(0.05)
    return samples


def rate_mbps(bits_per_second: Any) -> float | None:
    try:
        value = float(bits_per_second)
    except (TypeError, ValueError):
        return None
    return value / 1e6 if value > 0 else None


def received(end: dict[str, Any]) -> tuple[float | None, int | None]:
    """Was tatsaechlich angekommen ist. ``sum_sent`` zaehlt auch, was noch im Puffer steckt."""
    summary = end.get("sum_received") or end.get("sum_sent") or {}
    byte_count = summary.get("bytes")
    return rate_mbps(summary.get("bits_per_second")), int(byte_count) if isinstance(byte_count, int) else None


def sender_rtt_ms(end: dict[str, Any]) -> float | None:
    """Mittlere TCP-Laufzeit waehrend der Uebertragung, von iperf3 in Mikrosekunden gemeldet.

    Nur der Sender kennt sie. Im Download (``-R``) sendet die Gegenstelle, dort
    stehen ueberall Nullen, und der Wert bleibt leer.
    """
    values = []
    for stream in end.get("streams") or []:
        sender = stream.get("sender") if isinstance(stream, dict) else None
        if isinstance(sender, dict) and sender.get("sender") and isinstance(sender.get("mean_rtt"), int | float):
            values.append(float(sender["mean_rtt"]) / 1000)
    usable = [value for value in values if value > 0]
    return sum(usable) / len(usable) if usable else None


def error_code(message: str) -> str:
    return "iperf3_busy" if "busy" in message.lower() else "iperf3_failed"


def arguments(target: Target, reverse: bool, duration: int = DURATION, streams: int | None = None) -> list[str]:
    args = [
        "-c",
        target.host,
        "-p",
        str(target.port),
        "-t",
        str(duration),
        "-P",
        str(target.streams if streams is None else streams),
        "-i",
        "0.5",
        "--connect-timeout",
        str(CONNECT_TIMEOUT_MS),
        "--json-stream",
        *FAMILIES.get(target.family, []),
    ]
    if duration > OMIT:
        args += ["-O", str(OMIT)]
    if reverse:
        args.append("-R")
    return args


async def _stream(args: list[str], phase: str, reporter: Reporter | None, timeout: float) -> dict[str, Any]:
    """Einen Lauf starten und seine Zeilen lesen. Gibt den Inhalt von ``end`` zurueck."""
    process = await asyncio.create_subprocess_exec(
        shutil.which(BINARY) or BINARY, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    assert process.stdout is not None
    end: dict[str, Any] = {}
    errors: list[str] = []
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        while True:
            if reporter is not None and reporter.cancelled():
                process.kill()
                reporter.check()
            if loop.time() > deadline:
                process.kill()
                raise MeasurementError("iperf3_timeout", f"{phase} took longer than {timeout:.0f} s")
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
            kind = event.get("event")
            data = event.get("data")
            if kind == "interval" and isinstance(data, dict) and reporter is not None:
                value = rate_mbps((data.get("sum") or {}).get("bits_per_second"))
                if value is not None:
                    reporter.value(phase, value)
            elif kind == "end" and isinstance(data, dict):
                end = data
            elif kind == "error":
                errors.append(str(data)[:300])
    finally:
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
    if errors:
        raise MeasurementError(error_code(errors[0]), "; ".join(errors))
    if not end.get("streams"):
        stderr = (await process.stderr.read()).decode("utf-8", "replace") if process.stderr else ""
        raise MeasurementError("iperf3_failed", stderr[-500:] or f"exit {process.returncode}")
    return end


async def run(
    target: Target, reverse: bool, phase: str, reporter: Reporter | None = None, duration: int = DURATION
) -> dict[str, Any]:
    """Ein Lauf, mit einem zweiten Versuch, falls die Gegenstelle noch aufraeumt."""
    args = arguments(target, reverse, duration)
    timeout = duration + OMIT + 25
    try:
        return await _stream(args, phase, reporter, timeout)
    except MeasurementError as exc:
        if exc.code != "iperf3_busy":
            raise
        logger.info("iperf3 server %s was still busy, trying once more", target.name)
        await asyncio.sleep(2.0)
        return await _stream(args, phase, reporter, timeout)


async def check(host: str, port: int, family: str = "auto") -> None:
    """Beim Eintragen: steht dort wirklich ein iperf3-Server? Ein Lauf ueber eine Sekunde.

    Die IP-Fassung zaehlt mit: Wer IPv6 erzwingt, soll es hier merken und nicht erst beim ersten Test.
    """
    if not available():
        raise MeasurementError("iperf3_not_installed")
    target = Target(id=target_id(host, port), name=host, host=host, port=port, streams=1, family=family)
    await run(target, reverse=False, phase="check", duration=CHECK_SECONDS)


class Iperf3Engine:
    name = "iperf3"

    async def servers(self) -> list[ServerInfo]:
        return [target.info() for target in targets()]

    async def nearest(self, candidates: list[Target]) -> Target:
        """Bei "automatisch": das eingetragene Ziel mit der kuerzesten Laufzeit."""

        async def probe(target: Target) -> tuple[Target, float | None]:
            try:
                samples = await ping_samples(target, count=3)
            except MeasurementError:
                return target, None
            return target, min(samples) if samples else None

        results = await asyncio.gather(*(probe(target) for target in candidates))
        reachable = sorted(((t, ms) for t, ms in results if ms is not None), key=lambda pair: pair[1])
        if not reachable:
            raise MeasurementError("unreachable", "No iperf3 server answered.")
        return reachable[0][0]

    async def measure(self, server_id: str | None, reporter: Reporter) -> Measurement:
        if not available():
            raise MeasurementError("iperf3_not_installed")
        candidates = targets()
        if not candidates:
            raise MeasurementError("no_server", "No iperf3 server is configured.")
        reporter.phase("selecting")
        if server_id:
            found = next((target for target in candidates if target.id == server_id), None)
            if found is None:
                raise MeasurementError("server_gone", f"Server {server_id} is no longer in the list.")
            target = found
        else:
            target = await self.nearest(candidates)

        result = Measurement(server=target.info())
        reporter.server(target.info())
        reporter.phase("ping")
        samples = await ping_samples(target, reporter)
        latency = transfer.summarize_latency(samples)
        result.ping_ms = latency["ping_ms"]
        result.jitter_ms = latency["jitter_ms"]
        result.ping_low_ms = latency["ping_low_ms"]
        result.ping_high_ms = latency["ping_high_ms"]
        await asyncio.sleep(0.3)

        if target.measures("down"):
            reporter.phase("download")
            end = await run(target, reverse=True, phase="download", reporter=reporter)
            result.download_mbps, result.bytes_down = received(end)

        if target.measures("down") and target.measures("up"):
            # Der Server horcht erst wieder, wenn er den ersten Lauf aufgeraeumt hat.
            await asyncio.sleep(BETWEEN_RUNS)

        if target.measures("up"):
            reporter.check()
            reporter.phase("upload")
            end = await run(target, reverse=False, phase="upload", reporter=reporter)
            result.upload_mbps, result.bytes_up = received(end)
            result.loaded_up_ms = sender_rtt_ms(end)
        return result
