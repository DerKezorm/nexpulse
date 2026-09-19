"""Hintergrund: Zeitplaene ausfuehren und alte Ergebnisse aufraeumen."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import Result, Schedule, utcnow
from . import settings_service, timing
from .runner import Busy, runner

logger = logging.getLogger("nexpulse.scheduler")

TICK_SECONDS = 15
#: Wie lange ein verpasster Termin nachgeholt wird, etwa weil gerade ein Test lief.
#: Wer laenger wartet, misst zur falschen Zeit und verfaelscht die Tageskurve.
CATCH_UP = timedelta(minutes=30)


def plan_of(schedule: Schedule) -> timing.Plan:
    """Die zeitlichen Angaben eines Zeitplans.

    Ein im Code angelegter, noch nicht gespeicherter Zeitplan hat seine Standardwerte noch
    nicht (die setzt SQLAlchemy erst beim Speichern). Dann gelten die von ``timing.Plan``.
    """
    defaults = timing.Plan(mode="interval")

    def value(name: str) -> object:
        current = getattr(schedule, name)
        return getattr(defaults, name) if current is None else current

    return timing.Plan(
        mode=str(value("mode")),
        interval_minutes=int(value("interval_minutes")),  # type: ignore[arg-type]
        daily_time=str(value("daily_time")),
        cron=str(value("cron")),
        days=int(value("days")),  # type: ignore[arg-type]
        window_from=str(value("window_from")),
        window_to=str(value("window_to")),
        per_day=int(value("per_day")),  # type: ignore[arg-type]
        seed=int(value("seed")),  # type: ignore[arg-type]
    )


def reschedule(db: Session, schedule: Schedule, now: datetime | None = None) -> None:
    now = now or utcnow()
    try:
        schedule.next_run_at = timing.next_run(
            plan_of(schedule), now, settings_service.timezone(db), schedule.random_offset is not False
        )
    except (ValueError, timing.CronError):
        schedule.next_run_at = None


def pick_server(db: Session, schedule: Schedule) -> str | None:
    if schedule.server_mode == "fixed" and schedule.server_id:
        return schedule.server_id
    if schedule.server_mode == "rotate":
        key = "ookla_favorites" if schedule.source == "ookla" else "librespeed_favorites"
        favorites = [str(item) for item in settings_service.get(db, key) or []]
        if favorites:
            server = favorites[schedule.rotate_index % len(favorites)]
            schedule.rotate_index += 1
            return server
    return None


def tick(now: datetime | None = None) -> None:
    now = now or utcnow()
    with SessionLocal() as db:
        schedules = list(db.scalars(select(Schedule).where(Schedule.enabled.is_(True)).order_by(Schedule.id)))
        for schedule in schedules:
            if schedule.next_run_at is None:
                reschedule(db, schedule, now)
                continue
            if schedule.next_run_at > now:
                continue
            if now - schedule.next_run_at > CATCH_UP:
                logger.info("Schedule %s missed its slot at %s, skipping it", schedule.id, schedule.next_run_at)
                reschedule(db, schedule, now)
                continue
            if runner.running:
                # Naechster Durchlauf versucht es wieder, bis CATCH_UP vorbei ist.
                continue
            if not settings_service.source_enabled(db, schedule.source):
                logger.info("Schedule %s skipped: source %s is turned off", schedule.id, schedule.source)
                reschedule(db, schedule, now)
                continue
            server = pick_server(db, schedule)
            try:
                runner.start(db, schedule.source, server, trigger="schedule", schedule_id=schedule.id)
            except Busy:
                continue
            schedule.last_run_at = now
            reschedule(db, schedule, now + timedelta(minutes=1))
        db.commit()


def clean_up(now: datetime | None = None) -> int:
    now = now or utcnow()
    with SessionLocal() as db:
        days = int(settings_service.get(db, "retention_days") or 0)
        if days <= 0:
            return 0
        cutoff = now - timedelta(days=days)
        removed = db.execute(delete(Result).where(Result.started_at < cutoff, Result.status != "running")).rowcount
        db.commit()
    if removed:
        logger.info("Removed %s results older than %s days", removed, days)
    return int(removed or 0)


def mark_interrupted() -> None:
    """Nach einem Neustart: Was als laufend gespeichert ist, lief beim Beenden und ist abgebrochen."""
    with SessionLocal() as db:
        for result in db.scalars(select(Result).where(Result.status == "running")):
            result.status = "failed"
            result.error_code = "interrupted"
            result.finished_at = result.finished_at or utcnow()
        db.commit()


async def run(stop: asyncio.Event) -> None:
    last_cleanup: datetime | None = None
    while not stop.is_set():
        try:
            tick()
            now = utcnow()
            if last_cleanup is None or now - last_cleanup > timedelta(hours=1):
                clean_up(now)
                last_cleanup = now
        except Exception:
            logger.exception("Scheduler tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=TICK_SECONDS)
        except TimeoutError:
            pass
