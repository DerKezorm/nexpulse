"""Zeitplaene anlegen, aendern, loeschen und vorab sehen, wann sie messen."""

from __future__ import annotations

import secrets
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import DbSession, UiAccess
from ..meldungen import fehler
from ..models import Schedule, utcnow
from ..services import settings_service, timing
from ..services.scheduler import plan_of, reschedule
from ..services.settings_service import SOURCES

router = APIRouter(prefix="/api/schedules", tags=["schedules"], dependencies=[UiAccess])

TIME = r"^([01]\d|2[0-3]):[0-5]\d$"


class ScheduleIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    mode: Literal["interval", "daily", "cron", "random"] = "interval"
    interval_minutes: int = Field(default=120, ge=5, le=1440)
    daily_time: str = Field(default="04:00", pattern=TIME)
    cron: str = Field(default="", max_length=120)
    #: Bei ``random``. Hoechstens 48: Cloudflare weist sehr haeufige Tests ab.
    per_day: int = Field(default=6, ge=1, le=48)
    seed: int = Field(default=0, ge=0, le=2**31 - 1)
    days: int = Field(default=127, ge=1, le=127)
    window_from: str = Field(default="00:00", pattern=TIME)
    window_to: str = Field(default="00:00", pattern=TIME)
    source: str = "cloudflare"
    server_mode: Literal["auto", "fixed", "rotate"] = "auto"
    server_id: str = Field(default="", max_length=80)
    random_offset: bool = True


def schedule_dict(schedule: Schedule) -> dict[str, Any]:
    return {
        "id": schedule.id,
        "name": schedule.name,
        "enabled": schedule.enabled,
        "mode": schedule.mode,
        "interval_minutes": schedule.interval_minutes,
        "daily_time": schedule.daily_time,
        "cron": schedule.cron,
        "per_day": schedule.per_day,
        "seed": schedule.seed,
        "days": schedule.days,
        "window_from": schedule.window_from,
        "window_to": schedule.window_to,
        "source": schedule.source,
        "server_mode": schedule.server_mode,
        "server_id": schedule.server_id,
        "random_offset": schedule.random_offset,
        "next_run_at": schedule.next_run_at.isoformat() if schedule.next_run_at else None,
        "last_run_at": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
    }


def _validate(payload: ScheduleIn) -> None:
    if payload.source not in SOURCES:
        raise fehler("unknown_source", "This source does not exist.", 422)
    if payload.mode == "cron":
        try:
            timing.Cron.parse(payload.cron)
        except timing.CronError as exc:
            raise fehler("invalid_cron", "This cron expression is not valid.", 422, reason=str(exc)) from exc
    if payload.server_mode == "fixed" and not payload.server_id:
        raise fehler("server_required", "Choose a server.", 422)


def _apply(schedule: Schedule, payload: ScheduleIn) -> None:
    for name, value in payload.model_dump().items():
        if name == "seed" and not value:
            # Ein Aufruf ohne Startwert soll die ausgelosten Zeiten nicht neu mischen.
            continue
        setattr(schedule, name, value.strip() if isinstance(value, str) else value)


@router.get("", summary="All schedules")
def list_schedules(db: DbSession) -> list[dict[str, Any]]:
    return [schedule_dict(schedule) for schedule in db.scalars(select(Schedule).order_by(Schedule.id))]


@router.post("", status_code=201, summary="Add a schedule")
def create(payload: ScheduleIn, db: DbSession) -> dict[str, Any]:
    _validate(payload)
    schedule = Schedule()
    _apply(schedule, payload)
    if not schedule.seed:
        # Ohne Startwert von der Oberflaeche (etwa ueber die API): einen auslosen.
        schedule.seed = secrets.randbelow(2**31 - 1) + 1
    reschedule(db, schedule)
    db.add(schedule)
    db.commit()
    return schedule_dict(schedule)


@router.put("/{schedule_id}", summary="Change a schedule")
def update(schedule_id: int, payload: ScheduleIn, db: DbSession) -> dict[str, Any]:
    schedule = db.get(Schedule, schedule_id)
    if schedule is None:
        raise fehler("not_found", "Not found.", 404)
    _validate(payload)
    _apply(schedule, payload)
    reschedule(db, schedule)
    db.commit()
    return schedule_dict(schedule)


@router.delete("/{schedule_id}", status_code=204, summary="Delete a schedule")
def delete(schedule_id: int, db: DbSession) -> None:
    schedule = db.get(Schedule, schedule_id)
    if schedule is None:
        raise fehler("not_found", "Not found.", 404)
    db.delete(schedule)
    db.commit()


@router.post("/preview", summary="The next five runs, without saving")
def preview(payload: ScheduleIn, db: DbSession) -> dict[str, Any]:
    _validate(payload)
    schedule = Schedule()
    _apply(schedule, payload)
    runs = timing.upcoming(plan_of(schedule), utcnow(), settings_service.timezone(db))
    return {"runs": [run.isoformat() for run in runs], "timezone": settings_service.timezone(db).key}
