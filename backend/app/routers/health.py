"""Lebenszeichen und was die Oberflaeche vor der Anmeldung wissen muss."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from .. import __version__
from ..deps import DbSession, signed_in
from ..services import settings_service

router = APIRouter(tags=["health"])


@router.get("/api/health", summary="Liveness check")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/api/config", summary="Public facts the interface needs before sign-in")
def public_config(request: Request, db: DbSession) -> dict[str, Any]:
    return {
        "version": __version__,
        "password_required": bool(settings_service.password_hash(db)),
        "signed_in": signed_in(request, db),
    }
