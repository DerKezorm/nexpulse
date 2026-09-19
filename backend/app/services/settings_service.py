"""Einstellungen, die der Betreiber in der Oberflaeche aendert.

Jede Einstellung ist eine Zeile in ``settings``. ``DEFAULTS`` sagt, was gilt,
solange niemand etwas gespeichert hat. Geheimnisse (Adresse und Zugang fuer
Benachrichtigungen) liegen verschluesselt, siehe ``crypto.py``.
"""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..crypto import decrypt, encrypt
from ..models import Setting

SOURCES = ("cloudflare", "librespeed", "ookla")

DEFAULTS: dict[str, Any] = {
    "password_hash": "",
    "sources": {"cloudflare": True, "librespeed": True, "ookla": False},
    "ookla_accepted_at": "",
    "ookla_favorites": [],
    "librespeed_public": True,
    "librespeed_servers": [],
    "librespeed_favorites": [],
    "plan_down": None,
    "plan_up": None,
    "threshold_pct": 75,
    "alert_below_plan": True,
    "alert_ping_enabled": False,
    "alert_ping_ms": 40,
    "alert_failed": True,
    "notify_kind": "",
    "notify_url": "",
    "notify_token": "",
    "retention_days": 365,
    "timezone": "",
    "update_check": True,
}

#: Diese Werte stehen verschluesselt in der Datenbank.
SECRET_KEYS = {"notify_url", "notify_token"}


def _raw(db: Session) -> dict[str, Any]:
    return {row.key: row.value for row in db.scalars(select(Setting))}


def get(db: Session, key: str) -> Any:
    row = db.get(Setting, key)
    value = DEFAULTS.get(key) if row is None else row.value
    if key in SECRET_KEYS and isinstance(value, str):
        return decrypt(value)
    return value


def load(db: Session) -> dict[str, Any]:
    stored = _raw(db)
    result = {key: stored.get(key, default) for key, default in DEFAULTS.items()}
    for key in SECRET_KEYS:
        if isinstance(result[key], str):
            result[key] = decrypt(result[key])
    # Neue Quellen, die es beim Speichern noch nicht gab, bekommen ihren Standard.
    result["sources"] = {**DEFAULTS["sources"], **(result["sources"] or {})}
    return result


def save(db: Session, values: dict[str, Any]) -> None:
    for key, value in values.items():
        if key not in DEFAULTS:
            raise KeyError(key)
        if key in SECRET_KEYS and isinstance(value, str) and value:
            value = encrypt(value)
        row = db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=value))
        else:
            row.value = value
    db.commit()


def password_hash(db: Session) -> str:
    return str(get(db, "password_hash") or "")


def timezone(db: Session) -> ZoneInfo:
    name = str(get(db, "timezone") or get_settings().default_timezone)
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def source_enabled(db: Session, source: str) -> bool:
    settings = load(db)
    if source == "ookla" and not settings["ookla_accepted_at"]:
        return False
    return bool(settings["sources"].get(source))
