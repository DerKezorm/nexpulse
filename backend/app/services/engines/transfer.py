"""Download, Upload und Laufzeit ueber HTTP, geteilt von Cloudflare und LibreSpeed.

Beide Quellen funktionieren gleich: Grosse Antworten herunterladen, grosse
Anfragen hochladen, mehrere Verbindungen gleichzeitig, eine feste Zeit lang.
Waehrenddessen misst eine eigene Verbindung die Laufzeit unter Last
(Bufferbloat).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable

import httpx

from ... import __version__
from .base import MeasurementError, Reporter, ThroughputMeter, jitter, median

logger = logging.getLogger("nexpulse.transfer")

USER_AGENT = f"nexpulse/{__version__} (+https://github.com/DerKezorm/nexpulse)"

STREAMS = 6
DURATION = 10.0
WARMUP = 2.0
UPLOAD_REQUEST_BYTES = 25 * 1024 * 1024
#: So viele Fehler in Folge, dann gibt eine Verbindung auf.
MAX_FAILURES = 5
#: So viele Laufzeiten muessen mindestens durchkommen, und so viele Versuche duerfen es mehr sein.
MIN_LATENCY_SAMPLES = 3
LATENCY_SPARE = 5
#: So viele Sekunden nach dem Anlauf reichen fuer ein Ergebnis, wenn der Server bremst.
MIN_MEASURED = 2.0
CHUNK = 64 * 1024
#: Zufaellige Daten fuer den Upload, einmal erzeugt. Nullen koennte eine
#: Zwischenstation komprimieren und damit zu schnell messen.
_UPLOAD_BLOCK = os.urandom(1024 * 1024)

#: Liefert fuer eine Antwort die Zeit, die der Server selbst gebraucht hat (Sekunden).
ServerTime = Callable[[httpx.Response], float]


def client(streams: int = STREAMS) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(15.0, connect=8.0),
        limits=httpx.Limits(max_connections=streams + 2, max_keepalive_connections=streams + 2),
        follow_redirects=True,
    )


def no_server_time(_response: httpx.Response) -> float:
    return 0.0


async def latency_sample(http: httpx.AsyncClient, url: str, server_time: ServerTime) -> float:
    """Eine Laufzeit in Millisekunden: Zeit bis zum ersten Byte, abzueglich Serverzeit."""
    started = time.perf_counter()
    async with http.stream("GET", url, headers={"Cache-Control": "no-cache"}) as response:
        first_byte = time.perf_counter()
        if response.status_code >= 400:
            raise MeasurementError("server_error", f"HTTP {response.status_code} from {url}")
        await response.aread()
    raw = (first_byte - started) * 1000
    return max(0.1, raw - server_time(response) * 1000)


async def measure_latency(
    http: httpx.AsyncClient,
    url: Callable[[], str],
    reporter: Reporter,
    server_time: ServerTime = no_server_time,
    count: int = 20,
) -> list[float]:
    """Laufzeiten auf einer warmen Verbindung. Die erste zaehlt nicht, sie enthaelt den Aufbau.

    Einzelne abgewiesene Proben werden uebersprungen: Am 19.09.2026 antwortete ein
    LibreSpeed-Server nach einem kurzen Download einmal mit 403 und der ganze Test war
    verloren. Erst wenn weniger als ``MIN_LATENCY_SAMPLES`` durchkommen, gilt der Server
    als nicht erreichbar.
    """
    samples: list[float] = []
    failed: list[str] = []
    for attempt in range(count + 1 + LATENCY_SPARE):
        if len(samples) >= count:
            break
        reporter.check()
        try:
            sample = await latency_sample(http, url(), server_time)
        except (httpx.HTTPError, MeasurementError) as exc:
            failed.append(describe(exc))
            await asyncio.sleep(0.2)
            continue
        if attempt == 0:
            continue
        samples.append(sample)
        reporter.ping(median(samples) or sample)
    if len(samples) < MIN_LATENCY_SAMPLES:
        raise MeasurementError("unreachable", "ping: " + summarize_errors(failed))
    if failed:
        logger.info("ping: %s probes failed and were skipped (%s)", len(failed), summarize_errors(failed))
    return samples


def unreliable(elapsed: float, needed: float, failed: int, accepted: int, streams: int) -> bool:
    """Ob eine Uebertragung keine verlaessliche Zahl ergibt.

    Zwei Faelle: Es wurde kuerzer gemessen als ``needed`` (die halbe Messzeit, oder Anlauf
    plus zwei Sekunden, wenn der Server bremst; sonst waere die Zahl hochgerechnet), oder
    mindestens so viele Anfragen scheiterten, wie es Verbindungen gibt, und keine kam
    durch. Laufende Anfragen ohne Fehler zaehlen nicht
    dagegen: Bei langsamem Upload wird eine 10-MB-Anfrage in der Messzeit womoeglich nie
    fertig, und ein einzelner Abbruch neben fuenf gesunden Verbindungen (am 19.09.2026
    gesehen) macht die Messung nicht wertlos.
    """
    return elapsed < needed or (failed >= streams and accepted == 0)


def describe(exc: BaseException) -> str:
    """Kurz, fuers Protokoll: ``HTTP 429`` oder der Name des Fehlers."""
    if isinstance(exc, MeasurementError) and exc.detail.startswith("HTTP "):
        return exc.detail.split(" from ")[0]
    return type(exc).__name__


def summarize_errors(descriptions: list[str]) -> str:
    return ", ".join(f"{name} x{count}" for name, count in Counter(descriptions).most_common()) or "no answer"


async def _loaded_pings(
    url: Callable[[], str], server_time: ServerTime, stop: asyncio.Event, meter: ThroughputMeter
) -> list[float]:
    """Laufzeit waehrend der Uebertragung, auf einer eigenen Verbindung."""
    samples: list[float] = []
    async with client(1) as http:
        while not stop.is_set():
            try:
                sample = await asyncio.wait_for(latency_sample(http, url(), server_time), timeout=3)
                if meter.elapsed() >= WARMUP:
                    samples.append(sample)
            except (httpx.HTTPError, TimeoutError, MeasurementError):
                pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.3)
            except TimeoutError:
                pass
    return samples


async def _run_transfer(
    phase: str,
    worker: Callable[[httpx.AsyncClient, ThroughputMeter, asyncio.Event], Awaitable[None]],
    ping_url: Callable[[], str],
    server_time: ServerTime,
    reporter: Reporter,
    streams: int | None,
    duration: float | None,
) -> tuple[float | None, int, float | None]:
    # Erst hier aufgeloest, damit Tests die Messzeit kuerzen koennen.
    streams = streams or STREAMS
    duration = duration or DURATION
    meter = ThroughputMeter(WARMUP)
    stop = asyncio.Event()
    errors: list[str] = []
    #: Anfragen, die der Server angenommen hat. Beim Upload zaehlen Bytes schon beim
    #: Absenden: Scheitern Anfragen und kommt keine durch, waere die Zahl erfunden.
    accepted: list[int] = []
    #: Der Server hat mit 429 gebremst. Cloudflare deckelt die Menge je kurzem Zeitfenster
    #: (am 19.09.2026: nach genau 900 MB). Wer danach weiter misst, zaehlt Wartezeit mit.
    throttled = asyncio.Event()

    async def guarded(http: httpx.AsyncClient, delay: float) -> None:
        # Versetzt starten, wie LibreSpeed: Sonst kaempfen alle Verbindungen
        # gleichzeitig im Langsamstart und der Anlauf dauert laenger.
        await asyncio.sleep(delay)
        failures = 0
        while not stop.is_set():
            # Einmal je Anfrage abgeben: Antwortet ein Server ohne Wartezeit (lokal, im
            # Test), kaeme sonst die Schleife, die die Messzeit beendet, nie mehr dran.
            await asyncio.sleep(0)
            try:
                await worker(http, meter, stop)
                accepted.append(1)
                failures = 0
            except (httpx.HTTPError, MeasurementError) as exc:
                # ⚠️ Eine abgebrochene Anfrage beendet die Verbindung nicht. Cloudflare setzt
                # Uploads sporadisch zurueck (gemessen 19.09.2026, auch bei 2 MB). Frueher
                # endete die Verbindung damit, die Messung stoppte nach wenigen Sekunden und
                # rechnete den Rest hoch: 25 statt 60 Mbit/s.
                errors.append(describe(exc))
                failures += 1
                if failures >= MAX_FAILURES:
                    return
                # Abgewiesen (403, 429): nicht gleich nachlegen, das haelt die Sperre nur am Leben.
                refused = isinstance(exc, MeasurementError) and exc.detail.startswith("HTTP 4")
                if isinstance(exc, MeasurementError) and exc.detail.startswith("HTTP 429"):
                    throttled.set()
                await asyncio.sleep(1.0 if refused else 0.2)

    async with client(streams) as http:
        pinger = asyncio.create_task(_loaded_pings(ping_url, server_time, stop, meter))
        workers = [asyncio.create_task(guarded(http, index * 0.2)) for index in range(streams)]
        try:
            while meter.elapsed() < duration:
                await asyncio.sleep(0.1)
                reporter.value(phase, meter.current_mbps())
                reporter.check()
                if all(task.done() for task in workers):
                    break
                if throttled.is_set() and meter.elapsed() >= WARMUP + MIN_MEASURED:
                    break
            # ⚠️ Jetzt festhalten, nicht nach dem Aufraeumen: Das Warten auf den letzten
            # Ping unter Last dauert bis zu drei Sekunden und zaehlte sonst als Messzeit.
            elapsed = meter.elapsed()
            result = meter.result_mbps()
        finally:
            stop.set()
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            loaded = await asyncio.gather(pinger, return_exceptions=True)
    if meter.total == 0:
        raise MeasurementError("unreachable", f"{phase}: {summarize_errors(errors) if errors else 'no data'}")
    if errors:
        logger.info("%s: %s requests failed and were repeated (%s)", phase, len(errors), summarize_errors(errors))
    needed = WARMUP + MIN_MEASURED if throttled.is_set() else duration * 0.5
    if unreliable(elapsed, needed, len(errors), len(accepted), streams):
        raise MeasurementError("unstable", f"{phase}: {summarize_errors(errors)}")
    if result is not None:
        reporter.value(phase, result, force=True)
    loaded_samples = loaded[0] if loaded and isinstance(loaded[0], list) else []
    return result, meter.total, median(loaded_samples)


async def download(
    url: Callable[[], str],
    ping_url: Callable[[], str],
    reporter: Reporter,
    server_time: ServerTime = no_server_time,
    streams: int | None = None,
    duration: float | None = None,
) -> tuple[float | None, int, float | None]:
    async def worker(http: httpx.AsyncClient, meter: ThroughputMeter, stop: asyncio.Event) -> None:
        async with http.stream("GET", url(), headers={"Cache-Control": "no-cache"}) as response:
            if response.status_code >= 400:
                raise MeasurementError("server_error", f"HTTP {response.status_code}")
            async for chunk in response.aiter_raw(CHUNK):
                meter.add(len(chunk))
                if stop.is_set():
                    return

    return await _run_transfer("download", worker, ping_url, server_time, reporter, streams, duration)


async def upload(
    url: Callable[[], str],
    ping_url: Callable[[], str],
    reporter: Reporter,
    server_time: ServerTime = no_server_time,
    streams: int | None = None,
    duration: float | None = None,
    request_bytes: int | None = None,
) -> tuple[float | None, int, float | None]:
    size = request_bytes or UPLOAD_REQUEST_BYTES

    async def body(meter: ThroughputMeter, stop: asyncio.Event) -> AsyncIterator[bytes]:
        # Der Koerper endet nie vorzeitig: Die Laenge steht schon in der Kopfzeile.
        # Am Ende der Messzeit wird der ganze Auftrag abgebrochen.
        sent = 0
        while sent < size:
            offset = sent % len(_UPLOAD_BLOCK)
            piece = _UPLOAD_BLOCK[offset : offset + CHUNK]
            sent += len(piece)
            meter.add(len(piece))
            yield piece

    async def worker(http: httpx.AsyncClient, meter: ThroughputMeter, stop: asyncio.Event) -> None:
        response = await http.post(
            url(),
            content=body(meter, stop),
            headers={"Content-Type": "application/octet-stream", "Content-Length": str(size)},
        )
        if response.status_code >= 400 and not stop.is_set():
            raise MeasurementError("server_error", f"HTTP {response.status_code}")

    return await _run_transfer("upload", worker, ping_url, server_time, reporter, streams, duration)


def summarize_latency(samples: list[float]) -> dict[str, float | None]:
    return {
        "ping_ms": median(samples),
        "jitter_ms": jitter(samples),
        "ping_low_ms": min(samples) if samples else None,
        "ping_high_ms": max(samples) if samples else None,
    }
