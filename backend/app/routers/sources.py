"""Messquellen: ein- und ausschalten, Server auflisten, Ookla freischalten, eigene LibreSpeed- und iperf3-Server."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..deps import DbSession, UiAccess
from ..meldungen import fehler
from ..models import utcnow
from ..services import settings_service
from ..services.engines import iperf3, librespeed, ookla, registry
from ..services.engines.base import MeasurementError
from ..services.runner import runner
from ..services.settings_service import SOURCES

router = APIRouter(prefix="/api/sources", tags=["sources"], dependencies=[UiAccess])


class SourcesIn(BaseModel):
    sources: dict[str, bool] | None = None
    librespeed_public: bool | None = None
    ookla_favorites: list[str] | None = Field(default=None, max_length=20)
    librespeed_favorites: list[str] | None = Field(default=None, max_length=20)
    iperf3_favorites: list[str] | None = Field(default=None, max_length=20)


class OwnServerIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=4, max_length=255)


class TargetIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=iperf3.DEFAULT_PORT, ge=1, le=65535)


class ActivateIn(BaseModel):
    #: Muss ausdruecklich wahr sein: Der Betreiber hat Ooklas Bedingungen gelesen.
    accept_license: bool = False


def state(db: Any) -> dict[str, Any]:
    settings = settings_service.load(db)
    return {
        "sources": {
            source: {
                "enabled": settings_service.source_enabled(db, source),
                "switched_on": bool(settings["sources"].get(source)),
            }
            for source in SOURCES
        },
        "ookla": {
            "accepted_at": settings["ookla_accepted_at"] or None,
            "installed": ookla.installed(),
            "version": ookla.VERSION,
            "favorites": settings["ookla_favorites"],
        },
        "iperf3": {
            "available": iperf3.available(),
            "port": iperf3.DEFAULT_PORT,
            "servers": [
                {"id": target.id, "name": target.name, "host": target.host, "port": target.port}
                for target in iperf3.parse_targets(settings["iperf3_servers"])
            ],
            "favorites": settings["iperf3_favorites"],
        },
        "librespeed": {
            "public": settings["librespeed_public"],
            "servers": [
                {"id": librespeed.own_id(item["base"]), "name": item["name"], "url": item["base"]}
                for item in settings["librespeed_servers"]
            ],
            "favorites": settings["librespeed_favorites"],
        },
    }


@router.get("", summary="State of all sources")
def get_sources(db: DbSession) -> dict[str, Any]:
    return state(db)


@router.put("", summary="Turn sources on or off, set favorites")
def put_sources(payload: SourcesIn, db: DbSession) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    if payload.sources is not None:
        current = settings_service.load(db)["sources"]
        for source, on in payload.sources.items():
            if source not in SOURCES:
                raise fehler("unknown_source", "This source does not exist.", 422)
            current[source] = bool(on)
        if not any(current.values()):
            raise fehler("last_source", "At least one source has to stay on.", 422)
        changes["sources"] = current
    for name in ("librespeed_public", "ookla_favorites", "librespeed_favorites", "iperf3_favorites"):
        value = getattr(payload, name)
        if value is not None:
            changes[name] = value
    settings_service.save(db, changes)
    return state(db)


@router.get("/{source}/servers", summary="Servers a source can measure against")
async def servers(source: str, db: DbSession) -> list[dict[str, Any]]:
    if source not in SOURCES:
        raise fehler("unknown_source", "This source does not exist.", 422)
    if source == "ookla" and not settings_service.source_enabled(db, "ookla"):
        return []
    if runner.running and source == "ookla":
        # Die CLI zweimal gleichzeitig verfaelscht die laufende Messung.
        raise fehler("busy", "A test is already running.", 409)
    try:
        found = await registry.engine(source).servers()
    except MeasurementError as exc:
        raise fehler(exc.code, "The server list could not be loaded.", 502) from exc
    return [{"id": s.id, "name": s.name, "location": s.location, "sponsor": s.sponsor, "host": s.host} for s in found]


@router.post("/iperf3/servers", status_code=201, summary="Add your own iperf3 server")
async def add_target(payload: TargetIn, db: DbSession) -> dict[str, Any]:
    host = payload.host.strip()
    if "://" in host or "/" in host or " " in host:
        raise fehler("invalid_host", "Enter the host name or IP address only, without a protocol or path.", 422)
    if runner.running:
        # Eine zweite Messung gegen dasselbe Ziel verfaelscht die laufende.
        raise fehler("busy", "A test is already running.", 409)
    existing = settings_service.load(db)["iperf3_servers"]
    if any(iperf3.target_id(item["host"], item["port"]) == iperf3.target_id(host, payload.port) for item in existing):
        raise fehler("server_exists", "This server is already in the list.", 409)
    try:
        await iperf3.check(host, payload.port)
    except MeasurementError as exc:
        raise fehler("iperf3_not_found", "No iperf3 server answered at this address.", 422, reason=exc.detail) from exc
    settings_service.save(
        db, {"iperf3_servers": [*existing, {"name": payload.name.strip(), "host": host, "port": payload.port}]}
    )
    return state(db)


@router.delete("/iperf3/servers/{server_id}", summary="Remove your own iperf3 server")
def remove_target(server_id: str, db: DbSession) -> dict[str, Any]:
    settings = settings_service.load(db)
    remaining = [
        item for item in settings["iperf3_servers"] if iperf3.target_id(item["host"], item["port"]) != server_id
    ]
    favorites = [item for item in settings["iperf3_favorites"] if item != server_id]
    settings_service.save(db, {"iperf3_servers": remaining, "iperf3_favorites": favorites})
    return state(db)


@router.post("/librespeed/servers", status_code=201, summary="Add your own LibreSpeed server")
async def add_own(payload: OwnServerIn, db: DbSession) -> dict[str, Any]:
    url = payload.url.strip()
    if "://" not in url:
        url = "http://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise fehler("invalid_url", "This is not a valid address.", 422)
    base = url.rstrip("/") + "/"
    existing = settings_service.load(db)["librespeed_servers"]
    if any(item["base"] == base for item in existing):
        raise fehler("server_exists", "This server is already in the list.", 409)
    try:
        prefix = await librespeed.find_backend_prefix(base)
    except MeasurementError as exc:
        raise fehler("librespeed_not_found", "No LibreSpeed server answered at this address.", 422) from exc
    settings_service.save(
        db, {"librespeed_servers": [*existing, {"name": payload.name.strip(), "base": base, "prefix": prefix}]}
    )
    return state(db)


@router.delete("/librespeed/servers/{server_id}", summary="Remove your own LibreSpeed server")
def remove_own(server_id: str, db: DbSession) -> dict[str, Any]:
    settings = settings_service.load(db)
    remaining = [item for item in settings["librespeed_servers"] if librespeed.own_id(item["base"]) != server_id]
    favorites = [item for item in settings["librespeed_favorites"] if item != server_id]
    settings_service.save(db, {"librespeed_servers": remaining, "librespeed_favorites": favorites})
    return state(db)


@router.post("/ookla/activate", summary="Download the Ookla CLI after accepting its license")
async def activate_ookla(payload: ActivateIn, db: DbSession) -> dict[str, Any]:
    if not payload.accept_license:
        raise fehler("license_not_accepted", "Accept Ookla's license first.", 422)
    try:
        await ookla.install()
    except MeasurementError as exc:
        raise fehler(exc.code, "Ookla could not be activated.", 502, reason=exc.detail) from exc
    current = settings_service.load(db)["sources"]
    current["ookla"] = True
    settings_service.save(db, {"ookla_accepted_at": utcnow().isoformat(), "sources": current})
    return state(db)


@router.delete("/ookla", summary="Remove the Ookla CLI and withdraw the acceptance")
def deactivate_ookla(db: DbSession) -> dict[str, Any]:
    if runner.running and runner.live and runner.live.source == "ookla":
        raise fehler("busy", "A test is already running.", 409)
    ookla.uninstall()
    current = settings_service.load(db)["sources"]
    current["ookla"] = False
    if not any(current.values()):
        current["cloudflare"] = True
    settings_service.save(db, {"ookla_accepted_at": "", "ookla_favorites": [], "sources": current})
    return state(db)
