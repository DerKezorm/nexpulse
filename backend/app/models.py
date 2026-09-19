"""Datenmodell: Messungen, Zeitplaene, API-Schluessel und Einstellungen."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator[datetime]):
    """SQLite vergisst die Zeitzone. Gespeichert wird UTC, gelesen wird UTC mit Zone."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=True)


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    #: interval, daily oder cron
    mode: Mapped[str] = mapped_column(String(16), default="interval")
    interval_minutes: Mapped[int] = mapped_column(Integer, default=120)
    daily_time: Mapped[str] = mapped_column(String(5), default="04:00")
    cron: Mapped[str] = mapped_column(String(120), default="")
    #: Wochentage als Bitmaske, Montag ist Bit 0. 127 heisst jeden Tag.
    days: Mapped[int] = mapped_column(Integer, default=127)
    #: Zeitfenster "HH:MM". Gleiche Werte heissen: kein Fenster.
    window_from: Mapped[str] = mapped_column(String(5), default="00:00")
    window_to: Mapped[str] = mapped_column(String(5), default="00:00")
    source: Mapped[str] = mapped_column(String(16), default="cloudflare")
    #: auto (naechster Server), fixed (server_id) oder rotate (Favoriten reihum)
    server_mode: Mapped[str] = mapped_column(String(8), default="auto")
    server_id: Mapped[str] = mapped_column(String(80), default="")
    random_offset: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    #: Zaehler fuer "reihum"
    rotate_index: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class Result(Base):
    __tablename__ = "results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(16), index=True)
    #: manual, schedule oder api
    trigger: Mapped[str] = mapped_column(String(16), default="manual")
    schedule_id: Mapped[int | None] = mapped_column(ForeignKey("schedules.id", ondelete="SET NULL"), nullable=True)
    #: running, ok, failed, cancelled
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    error_code: Mapped[str] = mapped_column(String(48), default="")
    error_detail: Mapped[str] = mapped_column(Text, default="")

    server_id: Mapped[str] = mapped_column(String(80), default="")
    server_name: Mapped[str] = mapped_column(String(160), default="")
    server_location: Mapped[str] = mapped_column(String(160), default="")
    isp: Mapped[str] = mapped_column(String(160), default="")
    external_ip: Mapped[str] = mapped_column(String(64), default="")
    result_url: Mapped[str] = mapped_column(String(255), default="")

    download_mbps: Mapped[float | None] = mapped_column(Float, nullable=True)
    upload_mbps: Mapped[float | None] = mapped_column(Float, nullable=True)
    ping_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    jitter_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    ping_low_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    ping_high_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Prozent. Nicht jede Quelle misst ihn, dann bleibt er leer.
    packet_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    loaded_down_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    loaded_up_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    bytes_down: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes_up: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Lag der Test unter der Schwelle des Tarifs? Festgehalten zum Zeitpunkt der Messung.
    below_plan: Mapped[bool] = mapped_column(Boolean, default=False)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    #: Die ersten Zeichen, damit man den Schluessel in der Liste wiedererkennt.
    prefix: Mapped[str] = mapped_column(String(16))
    #: SHA-256 des ganzen Schluessels. Der Schluessel selbst wird nie gespeichert.
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    #: read oder run
    scope: Mapped[str] = mapped_column(String(8), default="read")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
