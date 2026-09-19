"""API-Schluessel fuer nexdeck, Home Assistant und andere, die von aussen abfragen."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import DbSession, UiAccess
from ..meldungen import fehler
from ..models import ApiKey
from ..security import KEY_PREFIX, hash_api_key, new_api_key

router = APIRouter(prefix="/api/keys", tags=["api keys"], dependencies=[UiAccess])


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scope: Literal["read", "run"] = "read"


def key_dict(key: ApiKey) -> dict[str, Any]:
    return {
        "id": key.id,
        "name": key.name,
        "prefix": key.prefix,
        "scope": key.scope,
        "created_at": key.created_at.isoformat(),
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
    }


@router.get("", summary="All API keys, without the keys themselves")
def list_keys(db: DbSession) -> list[dict[str, Any]]:
    return [key_dict(key) for key in db.scalars(select(ApiKey).order_by(ApiKey.id))]


@router.post("", status_code=201, summary="Create a key. It is shown exactly once.")
def create(payload: KeyIn, db: DbSession) -> dict[str, Any]:
    raw = new_api_key()
    key = ApiKey(
        name=payload.name.strip(),
        prefix=raw[: len(KEY_PREFIX) + 4],
        key_hash=hash_api_key(raw),
        scope=payload.scope,
    )
    db.add(key)
    db.commit()
    return {**key_dict(key), "key": raw}


@router.delete("/{key_id}", status_code=204, summary="Revoke a key")
def revoke(key_id: int, db: DbSession) -> None:
    key = db.get(ApiKey, key_id)
    if key is None:
        raise fehler("not_found", "Not found.", 404)
    db.delete(key)
    db.commit()
