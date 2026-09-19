"""Fuehrt Messungen aus, eine zur Zeit, und verteilt den Fortschritt an die Liveansicht.

⚠️ **Nie zwei Messungen gleichzeitig.** Zwei Tests teilen sich die Leitung und
messen beide Unsinn. Ein zweiter Auftrag wird abgewiesen (``busy``), der
Zeitplan wartet und versucht es beim naechsten Durchlauf.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Result, utcnow
from . import notify, settings_service
from .engines import registry
from .engines.base import Cancelled, Measurement, MeasurementError, Reporter

logger = logging.getLogger("nexpulse.runner")


class Busy(Exception):
    """Es laeuft schon eine Messung."""


@dataclass
class Live:
    """Was die Liveansicht ueber die laufende Messung wissen muss."""

    result_id: int
    source: str
    trigger: str
    started_at: datetime
    phase: str = "starting"
    server: str = ""
    location: str = ""
    ping_ms: float | None = None
    download_mbps: float | None = None
    upload_mbps: float | None = None
    current_mbps: float = 0.0
    samples: list[dict[str, Any]] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "type": "snapshot",
            "running": True,
            "result_id": self.result_id,
            "source": self.source,
            "trigger": self.trigger,
            "started_at": self.started_at.isoformat(),
            "phase": self.phase,
            "server": self.server,
            "location": self.location,
            "ping_ms": self.ping_ms,
            "download_mbps": self.download_mbps,
            "upload_mbps": self.upload_mbps,
            "current_mbps": self.current_mbps,
            "samples": self.samples[-240:],
        }


class Runner:
    def __init__(self) -> None:
        self.live: Live | None = None
        self._task: asyncio.Task[None] | None = None
        self._cancel = False
        self._listeners: set[asyncio.Queue[dict[str, Any]]] = set()

    # --- Zuhoerer --------------------------------------------------------

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        self._listeners.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._listeners.discard(queue)

    def _publish(self, event: dict[str, Any]) -> None:
        for queue in list(self._listeners):
            if queue.full():
                # Wer nicht mitkommt, verliert die aeltesten Werte, nicht die neuesten.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)

    def _on_event(self, event: dict[str, Any]) -> None:
        live = self.live
        if live is None:
            return
        kind = event.get("type")
        if kind == "phase":
            live.phase = str(event["phase"])
            live.current_mbps = 0.0
        elif kind == "server":
            live.server = str(event.get("name", ""))
            live.location = str(event.get("location", ""))
        elif kind == "ping":
            live.ping_ms = float(event["ms"])  # type: ignore[arg-type]
        elif kind == "value":
            mbps = float(event["mbps"])  # type: ignore[arg-type]
            live.current_mbps = mbps
            live.samples.append({"phase": event["phase"], "mbps": mbps})
            if event["phase"] == "download":
                live.download_mbps = mbps
            elif event["phase"] == "upload":
                live.upload_mbps = mbps
        self._publish(event)

    # --- Auftraege -------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def cancel(self) -> bool:
        if not self.running:
            return False
        self._cancel = True
        # Die Quellen fragen den Abbruch selbst ab. Haengt eine trotzdem, etwa in
        # einer Verbindung ohne Antwort, wird sie nach fuenf Sekunden abgeschossen.
        task = self._task
        if task is not None:
            asyncio.get_running_loop().call_later(5, lambda: None if task.done() else task.cancel())
        return True

    def start(
        self,
        db: Session,
        source: str,
        server_id: str | None = None,
        trigger: str = "manual",
        schedule_id: int | None = None,
    ) -> Result:
        if self.running:
            raise Busy()
        result = Result(source=source, trigger=trigger, schedule_id=schedule_id, status="running")
        db.add(result)
        db.commit()
        self._cancel = False
        self.live = Live(result_id=result.id, source=source, trigger=trigger, started_at=result.started_at)
        self._publish(self.live.snapshot())
        self._task = asyncio.create_task(self._run(result.id, source, server_id))
        return result

    async def wait(self) -> None:
        """Fuer Tests und das Herunterfahren: bis die laufende Messung fertig ist."""
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self, result_id: int, source: str, server_id: str | None) -> None:
        reporter = Reporter(emit=self._on_event, cancelled=lambda: self._cancel)
        status, code, detail = "ok", "", ""
        measurement: Measurement | None = None
        try:
            engine = registry.engine(source)
            measurement = await engine.measure(server_id or None, reporter)
        except Cancelled:
            status, code = "cancelled", "cancelled"
        except MeasurementError as exc:
            status, code, detail = "failed", exc.code, exc.detail
            logger.warning("Speed test %s via %s failed: %s %s", result_id, source, exc.code, exc.detail)
        except asyncio.CancelledError:
            status, code = "cancelled", "cancelled"
        except Exception as exc:
            status, code, detail = "failed", "unexpected", f"{type(exc).__name__}: {exc}"
            logger.exception("Speed test %s via %s crashed", result_id, source)
        result = self._save(result_id, status, code, detail, measurement)
        final = {"type": "done", "result": result_dict(result) if result else None}
        self.live = None
        self._publish(final)
        if result is not None and status != "cancelled":
            await notify.after_result(result)

    def _save(
        self, result_id: int, status: str, code: str, detail: str, measurement: Measurement | None
    ) -> Result | None:
        with SessionLocal() as db:
            result = db.get(Result, result_id)
            if result is None:
                return None
            result.status = status
            result.error_code = code
            result.error_detail = detail[:2000]
            result.finished_at = utcnow()
            if measurement is not None and status == "ok":
                apply_measurement(result, measurement)
                result.below_plan = below_plan(db, result)
            db.commit()
            db.refresh(result)
            logger.info(
                "Speed test %s via %s: %s, down %s, up %s, ping %s",
                result.id,
                result.source,
                status,
                _fmt(result.download_mbps),
                _fmt(result.upload_mbps),
                _fmt(result.ping_ms),
            )
            return result


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def apply_measurement(result: Result, m: Measurement) -> None:
    for name in (
        "download_mbps",
        "upload_mbps",
        "ping_ms",
        "jitter_ms",
        "ping_low_ms",
        "ping_high_ms",
        "packet_loss",
        "loaded_down_ms",
        "loaded_up_ms",
        "bytes_down",
        "bytes_up",
    ):
        setattr(result, name, getattr(m, name))
    result.isp = m.isp[:160]
    result.external_ip = m.external_ip[:64]
    result.result_url = m.result_url[:255]
    if m.server is not None:
        result.server_id = m.server.id[:80]
        result.server_name = (m.server.sponsor or m.server.name)[:160]
        result.server_location = m.server.location[:160]


def below_plan(db: Session, result: Result) -> bool:
    """Liegt Download oder Upload unter der eingestellten Schwelle des Tarifs?"""
    settings = settings_service.load(db)
    share = float(settings["threshold_pct"] or 0) / 100
    if share <= 0:
        return False
    for measured, booked in ((result.download_mbps, settings["plan_down"]), (result.upload_mbps, settings["plan_up"])):
        if measured is not None and booked and measured < float(booked) * share:
            return True
    return False


def result_dict(result: Result) -> dict[str, Any]:
    return {
        "id": result.id,
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat() if result.finished_at else None,
        "source": result.source,
        "trigger": result.trigger,
        "schedule_id": result.schedule_id,
        "status": result.status,
        "error_code": result.error_code or None,
        "server_id": result.server_id,
        "server_name": result.server_name,
        "server_location": result.server_location,
        "isp": result.isp,
        "external_ip": result.external_ip,
        "result_url": result.result_url or None,
        "download_mbps": result.download_mbps,
        "upload_mbps": result.upload_mbps,
        "ping_ms": result.ping_ms,
        "jitter_ms": result.jitter_ms,
        "ping_low_ms": result.ping_low_ms,
        "ping_high_ms": result.ping_high_ms,
        "packet_loss": result.packet_loss,
        "loaded_down_ms": result.loaded_down_ms,
        "loaded_up_ms": result.loaded_up_ms,
        "bytes_down": result.bytes_down,
        "bytes_up": result.bytes_up,
        "below_plan": result.below_plan,
    }


runner = Runner()
