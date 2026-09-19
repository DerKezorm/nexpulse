"""Die Schnittstelle fuer Dashboards (nexdeck, Home Assistant, Homepage ...).

Immer mit API-Schluessel, als ``X-Api-Key: npk_...`` oder
``Authorization: Bearer npk_...``. Ein Schluessel mit Lesezugriff sieht
Ergebnisse und Zusammenfassungen, einer mit "run" darf auch Tests starten.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from .. import __version__
from ..deps import DbSession, ReadKey, RunKey
from ..meldungen import fehler
from ..models import Result
from ..services import history
from ..services.runner import result_dict, runner
from .tests import start_test

router = APIRouter(prefix="/api/v1", tags=["api v1"])

MAX_RESULTS = 5000


class StartV1(BaseModel):
    """Die Quelle ist hier Pflicht.

    ⚠️ Mit einem Standardwert startete ``{}`` stillschweigend eine Cloudflare-Messung. Wer
    nur wissen wollte, ob sein Schluessel starten darf, und dazu einen leeren Koerper
    schickte, loeste damit bei jedem Versuch einen echten Test aus. Fuer diese Frage gibt
    es ``GET /api/v1/me``.
    """

    source: str = Field(max_length=16)
    server_id: str | None = Field(default=None, max_length=80)


@router.get("/me", summary="What this API key is allowed to do")
def me(key: ReadKey) -> dict[str, Any]:
    return {"name": key.name, "scope": key.scope, "can_run_tests": key.scope == "run", "version": __version__}


@router.get("/status", summary="Version, whether a test is running, and the latest result")
def status(_key: ReadKey, db: DbSession) -> dict[str, Any]:
    latest = history.latest(db)
    return {
        "version": __version__,
        "running": runner.running,
        "live": runner.live.snapshot() if runner.live else None,
        "latest": result_dict(latest) if latest else None,
    }


@router.get("/latest", summary="The newest successful result")
def latest(_key: ReadKey, db: DbSession, source: str | None = None) -> dict[str, Any] | None:
    result = history.latest(db, source=source or None)
    return result_dict(result) if result else None


@router.get("/results", summary="Results between two points in time, oldest first")
def results(
    _key: ReadKey,
    db: DbSession,
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    source: str | None = None,
    limit: int = Query(default=500, ge=1, le=MAX_RESULTS),
) -> list[dict[str, Any]]:
    found = history.query(db, start=start, end=end, source=source or None, limit=limit, newest_first=True)
    return [result_dict(result) for result in reversed(found)]


@router.get("/stats", summary="Averages and counts for 24h, 7d, 30d, 90d or all")
def stats(
    _key: ReadKey, db: DbSession, range_name: str = Query(default="7d", alias="range"), source: str | None = None
) -> dict[str, Any]:
    try:
        start = history.since(range_name)
    except ValueError as exc:
        raise fehler("invalid_range", "Unknown range.", 422) from exc
    return {"range": range_name, **history.stats(history.query(db, start=start, source=source or None))}


@router.post("/tests", status_code=202, summary="Start a test (needs a key with run access)")
async def start(payload: StartV1, _key: RunKey, db: DbSession) -> dict[str, Any]:
    return start_test(db, payload.source, payload.server_id, "api")


@router.get("/tests/{result_id}", summary="One test, with live progress while it runs")
def test(result_id: int, _key: ReadKey, db: DbSession) -> dict[str, Any]:
    result = db.get(Result, result_id)
    if result is None:
        raise fehler("not_found", "Not found.", 404)
    body = result_dict(result)
    if runner.live and runner.live.result_id == result_id:
        body["live"] = runner.live.snapshot()
    return body
