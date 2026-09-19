"""Tarif, Warnungen, Benachrichtigung, Aufbewahrung und Zeitzone."""

from __future__ import annotations

from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..config import get_settings
from ..crypto import mask
from ..deps import DbSession, UiAccess
from ..meldungen import fehler
from ..services import notify, settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[UiAccess])


class SettingsIn(BaseModel):
    plan_down: float | None = Field(default=None, ge=0, le=100000)
    plan_up: float | None = Field(default=None, ge=0, le=100000)
    threshold_pct: int | None = Field(default=None, ge=0, le=100)
    alert_below_plan: bool | None = None
    alert_ping_enabled: bool | None = None
    alert_ping_ms: int | None = Field(default=None, ge=1, le=10000)
    alert_failed: bool | None = None
    notify_kind: Literal["", "ntfy", "gotify", "webhook"] | None = None
    #: Leer lassen heisst: nicht aendern. Zum Entfernen notify_kind leeren.
    notify_url: str | None = Field(default=None, max_length=500)
    notify_token: str | None = Field(default=None, max_length=500)
    retention_days: int | None = Field(default=None, ge=0, le=3650)
    timezone: str | None = Field(default=None, max_length=64)
    update_check: bool | None = None


def public(db: Any) -> dict[str, Any]:
    settings = settings_service.load(db)
    return {
        "plan_down": settings["plan_down"],
        "plan_up": settings["plan_up"],
        "threshold_pct": settings["threshold_pct"],
        "alert_below_plan": settings["alert_below_plan"],
        "alert_ping_enabled": settings["alert_ping_enabled"],
        "alert_ping_ms": settings["alert_ping_ms"],
        "alert_failed": settings["alert_failed"],
        "notify_kind": settings["notify_kind"],
        # Die Adresse kann einen Zugang enthalten (ntfy-Thema, Webhook-Geheimnis).
        # Gezeigt wird nur das Ende, wie bei allen Zugangsdaten.
        "notify_url_masked": mask(settings["notify_url"]),
        "notify_url_set": bool(settings["notify_url"]),
        "notify_token_set": bool(settings["notify_token"]),
        "retention_days": settings["retention_days"],
        "timezone": settings_service.timezone(db).key,
        "timezone_default": get_settings().default_timezone,
        "update_check": settings["update_check"],
    }


@router.get("", summary="All settings, secrets masked")
def get_all(db: DbSession) -> dict[str, Any]:
    return public(db)


@router.get("/timezones", summary="Time zones to choose from")
def timezones() -> list[str]:
    return sorted(available_timezones())


@router.put("", summary="Change settings")
def put(payload: SettingsIn, db: DbSession) -> dict[str, Any]:
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("timezone"):
        try:
            ZoneInfo(changes["timezone"])
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise fehler("invalid_timezone", "Unknown time zone.", 422) from exc
    for secret in ("notify_url", "notify_token"):
        if secret in changes and not changes[secret]:
            del changes[secret]
    if changes.get("notify_kind") == "":
        changes["notify_url"] = ""
        changes["notify_token"] = ""
    if "notify_url" in changes and not changes["notify_url"].lower().startswith(("http://", "https://")):
        raise fehler("invalid_url", "This is not a valid address.", 422)
    settings_service.save(db, changes)
    if "timezone" in changes:
        # Andere Zeitzone, andere Termine.
        from sqlalchemy import select

        from ..models import Schedule
        from ..services.scheduler import reschedule

        for schedule in db.scalars(select(Schedule)):
            reschedule(db, schedule)
        db.commit()
    return public(db)


@router.post("/notify/test", summary="Send a test notification")
async def test_notification(db: DbSession) -> dict[str, bool]:
    settings = settings_service.load(db)
    try:
        await notify.send(
            settings["notify_kind"],
            settings["notify_url"],
            settings["notify_token"],
            "nexpulse: test notification",
            "If you can read this, alerts from nexpulse will reach you.",
            {"event": "test"},
        )
    except notify.NotifyError as exc:
        raise fehler(exc.code, "The notification could not be sent.", 502, reason=exc.detail) from exc
    return {"sent": True}
