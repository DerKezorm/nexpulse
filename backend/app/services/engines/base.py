"""Was jede Messquelle liefert, und die Rechenwege, die alle teilen."""

from __future__ import annotations

import itertools
import statistics
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol


class MeasurementError(Exception):
    """Eine Messung ist gescheitert. ``code`` landet in der Datenbank und in der Oberflaeche."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


class Cancelled(Exception):
    """Der Nutzer hat abgebrochen."""


@dataclass
class ServerInfo:
    id: str
    name: str
    location: str = ""
    sponsor: str = ""
    distance_km: float | None = None
    host: str = ""


@dataclass
class Measurement:
    download_mbps: float | None = None
    upload_mbps: float | None = None
    ping_ms: float | None = None
    jitter_ms: float | None = None
    ping_low_ms: float | None = None
    ping_high_ms: float | None = None
    packet_loss: float | None = None
    loaded_down_ms: float | None = None
    loaded_up_ms: float | None = None
    bytes_down: int | None = None
    bytes_up: int | None = None
    server: ServerInfo | None = None
    isp: str = ""
    external_ip: str = ""
    result_url: str = ""


@dataclass
class Reporter:
    """Meldet den Fortschritt an die Liveansicht und fragt, ob abgebrochen wurde.

    ``emit`` bekommt Ereignisse wie ``{"type": "phase", "phase": "download"}``.
    """

    emit: Callable[[dict[str, object]], None]
    cancelled: Callable[[], bool] = lambda: False
    _last_value: float = field(default=0.0, repr=False)

    def phase(self, name: str) -> None:
        self.check()
        self.emit({"type": "phase", "phase": name})

    def server(self, server: ServerInfo) -> None:
        self.emit({"type": "server", "name": server.name, "location": server.location})

    def ping(self, ms: float) -> None:
        self.emit({"type": "ping", "ms": round(ms, 1)})

    def value(self, phase: str, mbps: float, force: bool = False) -> None:
        # Hoechstens acht Werte je Sekunde, mehr zeichnet die Oberflaeche ohnehin nicht.
        now = time.monotonic()
        if not force and now - self._last_value < 0.125:
            return
        self._last_value = now
        self.emit({"type": "value", "phase": phase, "mbps": round(mbps, 2)})

    def check(self) -> None:
        if self.cancelled():
            raise Cancelled()


class Engine(Protocol):
    name: str

    async def servers(self) -> list[ServerInfo]: ...

    async def measure(self, server_id: str | None, reporter: Reporter) -> Measurement: ...


def jitter(samples: list[float]) -> float | None:
    """Mittlere Abweichung aufeinanderfolgender Laufzeiten, wie Ookla und LibreSpeed es rechnen."""
    if len(samples) < 2:
        return None
    return statistics.fmean(abs(b - a) for a, b in itertools.pairwise(samples))


def median(samples: list[float]) -> float | None:
    return statistics.median(samples) if samples else None


def percentile(samples: list[float], p: float) -> float | None:
    """Perzentil mit linearer Interpolation, ``p`` zwischen 0 und 1."""
    if not samples:
        return None
    ordered = sorted(samples)
    rank = (len(ordered) - 1) * p
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


class ThroughputMeter:
    """Zaehlt uebertragene Bytes ueber die Zeit.

    Das Ergebnis ist der Durchsatz nach dem Anlauf: Die erste Phase, in der TCP
    das Fenster erst aufzieht, zaehlt nicht mit. So machen es auch Ookla und
    LibreSpeed, sonst waere jede schnelle Leitung zu langsam gemessen.
    """

    def __init__(self, warmup_seconds: float) -> None:
        self.warmup = warmup_seconds
        self.start = time.monotonic()
        self.total = 0
        self._after_warmup = 0
        self._warm_start: float | None = None
        self._window: deque[tuple[float, int]] = deque()

    def add(self, count: int) -> None:
        now = time.monotonic()
        self.total += count
        if now - self.start >= self.warmup:
            if self._warm_start is None:
                self._warm_start = now
            else:
                self._after_warmup += count
        self._window.append((now, count))
        cutoff = now - 1.0
        while self._window and self._window[0][0] < cutoff:
            self._window.popleft()

    def elapsed(self) -> float:
        return time.monotonic() - self.start

    def current_mbps(self) -> float:
        """Durchsatz der letzten Sekunde, fuer den Tacho."""
        if len(self._window) < 2:
            return 0.0
        span = max(self._window[-1][0] - self._window[0][0], 0.05)
        return (sum(count for _, count in self._window) - self._window[0][1]) * 8 / span / 1e6

    def result_mbps(self) -> float | None:
        now = time.monotonic()
        if self._warm_start is not None and now - self._warm_start >= 0.5:
            return self._after_warmup * 8 / (now - self._warm_start) / 1e6
        # Zu kurz fuer einen Anlauf, etwa bei sehr langsamer Leitung: dann alles.
        span = now - self.start
        return self.total * 8 / span / 1e6 if span > 0 and self.total else None
