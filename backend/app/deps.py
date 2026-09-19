"""Wer darf was.

Zwei Wege hinein, sauber getrennt:

- **Oberflaeche** (``/api/...``): offen, solange kein Passwort gesetzt ist.
  Mit Passwort braucht jede Anfrage das Sitzungs-Cookie.
- **Schnittstelle** (``/api/v1/...``): immer mit API-Schluessel, auch ohne
  Passwort. Ein Schluessel oeffnet die Oberflaeche nicht und umgekehrt.

Veraendernde Anfragen der Oberflaeche brauchen zusaetzlich die Kopfzeile
``X-Requested-By: nexpulse``. Ein fremdes Browserfenster kann sie nicht ohne
Rueckfrage des Browsers setzen. Ohne diese Pruefung koennte jede Webseite, die
jemand im Heimnetz oeffnet, Tests ausloesen oder ein Passwort setzen, gerade
dann, wenn keines gesetzt ist.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .meldungen import fehler, meldung
from .middleware import set_actor
from .models import ApiKey, utcnow
from .security import SESSION_COOKIE, hash_api_key, session_valid
from .services import settings_service

DbSession = Annotated[Session, Depends(get_db)]

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_HEADER = "x-requested-by"


def signed_in(request: Request, db: Session) -> bool:
    password_hash = settings_service.password_hash(db)
    if not password_hash:
        return True
    token = request.cookies.get(SESSION_COOKIE)
    return bool(token) and session_valid(token, password_hash)


def require_ui(request: Request, db: DbSession) -> None:
    if request.method in UNSAFE and request.headers.get(CSRF_HEADER) != "nexpulse":
        raise fehler("missing_header", "This request needs the header X-Requested-By: nexpulse.", 403)
    if not signed_in(request, db):
        raise HTTPException(status_code=401, detail=meldung("not_signed_in", "Not signed in."))
    set_actor("ui")


UiAccess = Depends(require_ui)


def _key_from(authorization: str | None, x_api_key: str | None) -> str:
    if x_api_key:
        return x_api_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def _api_key(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> ApiKey:
    raw = _key_from(authorization, x_api_key)
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == hash_api_key(raw))) if raw else None
    if key is None:
        raise HTTPException(
            status_code=401,
            detail=meldung("invalid_api_key", "Missing or unknown API key."),
            headers={"WWW-Authenticate": "Bearer"},
        )
    now = utcnow()
    # Nur alle paar Minuten schreiben: Ein Dashboard fragt oft, und jede
    # Schreibsperre haelt eine laufende Messung beim Speichern auf.
    if key.last_used_at is None or (now - key.last_used_at).total_seconds() > 300:
        key.last_used_at = now
        db.commit()
    set_actor(f"key:{key.name}")
    return key


def require_read_key(key: Annotated[ApiKey, Depends(_api_key)]) -> ApiKey:
    return key


def require_run_key(key: Annotated[ApiKey, Depends(_api_key)]) -> ApiKey:
    if key.scope != "run":
        raise fehler("key_read_only", "This API key may only read.", 403)
    return key


ReadKey = Annotated[ApiKey, Depends(require_read_key)]
RunKey = Annotated[ApiKey, Depends(require_run_key)]
