"""Die Historie in der Oberflaeche: Liste, Zusammenfassung, Export, Loeschen."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import Response

from ..deps import DbSession, UiAccess
from ..meldungen import fehler
from ..models import Result
from ..services import history
from ..services.runner import result_dict

router = APIRouter(prefix="/api/results", tags=["results"], dependencies=[UiAccess])


def _range(range_name: str | None) -> datetime | None:
    try:
        return history.since(range_name)
    except ValueError as exc:
        raise fehler("invalid_range", "Unknown range.", 422) from exc


@router.get("", summary="Results in a range, oldest first")
def list_results(
    db: DbSession,
    range_name: str = Query(default="7d", alias="range"),
    source: str | None = None,
) -> list[dict[str, Any]]:
    return [result_dict(result) for result in history.query(db, start=_range(range_name), source=source or None)]


@router.get("/latest", summary="The newest successful result")
def latest(db: DbSession) -> dict[str, Any] | None:
    result = history.latest(db)
    return result_dict(result) if result else None


@router.get("/stats", summary="Averages and counts for a range")
def stats(
    db: DbSession,
    range_name: str = Query(default="7d", alias="range"),
    source: str | None = None,
) -> dict[str, Any]:
    return history.stats(history.query(db, start=_range(range_name), source=source or None))


@router.get("/export.csv", summary="All results as CSV")
def export(db: DbSession) -> Response:
    return Response(
        history.to_csv(history.query(db)),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="nexpulse-results.csv"'},
    )


@router.delete("/{result_id}", status_code=204, summary="Delete one result")
def delete(result_id: int, db: DbSession) -> None:
    result = db.get(Result, result_id)
    if result is None:
        raise fehler("not_found", "Not found.", 404)
    if result.status == "running":
        raise fehler("busy", "A test is already running.", 409)
    db.delete(result)
    db.commit()
