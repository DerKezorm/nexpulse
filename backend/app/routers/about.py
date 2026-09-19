"""Angaben fuer die Ueber-Seite: Version, Herkunft, Update-Hinweis, Messquellen."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from .. import __version__
from ..deps import DbSession, UiAccess
from ..services import settings_service, updates

router = APIRouter(prefix="/api/about", tags=["about"], dependencies=[UiAccess])


class AboutInfo(BaseModel):
    version: str
    repo_url: str
    release_url: str
    license: str = "AGPL-3.0-or-later"
    update_check: bool = False
    update_checked: bool = False
    latest_version: str | None = None
    update_available: bool = False
    checked_at: datetime | None = None


async def _info(db: DbSession, force: bool) -> AboutInfo:
    info = AboutInfo(version=__version__, repo_url=updates.REPO_URL, release_url=updates.RELEASES_URL)
    if not settings_service.get(db, "update_check"):
        return info
    stand = await updates.status(enabled=True, force=force)
    info.update_check = True
    info.update_checked = stand.checked_at is not None
    info.latest_version = stand.latest
    info.update_available = stand.update_available
    info.checked_at = stand.checked_at
    return info


@router.get("", response_model=AboutInfo, summary="Version and update state")
async def about(db: DbSession) -> AboutInfo:
    return await _info(db, force=False)


@router.post("/check", response_model=AboutInfo, summary="Check for updates now")
async def check_now(db: DbSession) -> AboutInfo:
    return await _info(db, force=True)
