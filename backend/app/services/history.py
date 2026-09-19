"""Ergebnisse abfragen und zusammenfassen, fuer Oberflaeche und Schnittstelle gleich."""

from __future__ import annotations

import csv
import io
import statistics
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Result, utcnow

RANGES = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30), "90d": timedelta(days=90)}


def since(range_name: str | None) -> datetime | None:
    if not range_name or range_name == "all":
        return None
    delta = RANGES.get(range_name)
    if delta is None:
        raise ValueError(range_name)
    return utcnow() - delta


def query(
    db: Session,
    start: datetime | None = None,
    end: datetime | None = None,
    source: str | None = None,
    status: str | None = None,
    limit: int | None = None,
    newest_first: bool = False,
) -> list[Result]:
    statement = select(Result).where(Result.status != "running")
    if start is not None:
        statement = statement.where(Result.started_at >= start)
    if end is not None:
        statement = statement.where(Result.started_at <= end)
    if source:
        statement = statement.where(Result.source == source)
    if status:
        statement = statement.where(Result.status == status)
    statement = statement.order_by(Result.started_at.desc() if newest_first else Result.started_at)
    if limit:
        statement = statement.limit(limit)
    return list(db.scalars(statement))


def latest(db: Session, source: str | None = None) -> Result | None:
    results = query(db, source=source, status="ok", limit=1, newest_first=True)
    return results[0] if results else None


def _values(results: Iterable[Result], name: str) -> list[float]:
    return [value for value in (getattr(result, name) for result in results) if value is not None]


def _describe(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"avg": None, "min": None, "max": None, "median": None}
    return {
        "avg": statistics.fmean(values),
        "min": min(values),
        "max": max(values),
        "median": statistics.median(values),
    }


def stats(results: list[Result]) -> dict[str, Any]:
    ok = [result for result in results if result.status == "ok"]
    return {
        "tests": len(results),
        "ok": len(ok),
        "failed": sum(1 for result in results if result.status == "failed"),
        "below_plan": sum(1 for result in ok if result.below_plan),
        "download_mbps": _describe(_values(ok, "download_mbps")),
        "upload_mbps": _describe(_values(ok, "upload_mbps")),
        "ping_ms": _describe(_values(ok, "ping_ms")),
        "jitter_ms": _describe(_values(ok, "jitter_ms")),
        "packet_loss": _describe(_values(ok, "packet_loss")),
    }


CSV_COLUMNS = [
    "id",
    "started_at",
    "source",
    "trigger",
    "status",
    "error_code",
    "server_name",
    "server_location",
    "isp",
    "download_mbps",
    "upload_mbps",
    "ping_ms",
    "jitter_ms",
    "packet_loss",
    "loaded_down_ms",
    "loaded_up_ms",
    "below_plan",
]


def to_csv(results: list[Result]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for result in results:
        row = []
        for column in CSV_COLUMNS:
            value = getattr(result, column)
            if isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, float):
                value = f"{value:.3f}"
            elif isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
                # Kein Formelanfang: Eine Tabellenkalkulation wuerde ihn ausfuehren.
                value = "'" + value
            row.append("" if value is None else value)
        writer.writerow(row)
    return buffer.getvalue()
