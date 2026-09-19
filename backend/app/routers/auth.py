"""Anmelden und abmelden, und das eine Passwort setzen oder entfernen."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..config import get_settings
from ..deps import CSRF_HEADER, DbSession, UiAccess
from ..meldungen import fehler, meldung
from ..security import SESSION_COOKIE, brake, create_session_token, hash_password, verify_password
from ..services import settings_service

router = APIRouter(prefix="/api/auth", tags=["auth"])

MIN_PASSWORD = 10


class LoginIn(BaseModel):
    password: str = Field(max_length=200)


class PasswordIn(BaseModel):
    #: Leer oder fehlend schaltet das Passwort ab.
    password: str | None = Field(default=None, max_length=200)


def _secure(request: Request) -> bool:
    mode = get_settings().cookie_secure.lower()
    if mode == "on":
        return True
    if mode == "off":
        return False
    forwarded = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or forwarded.split(",")[0].strip() == "https"


def _set_session(response: Response, request: Request, password_hash: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(password_hash),
        max_age=get_settings().session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=_secure(request),
        path="/",
    )


def _client(request: Request) -> str:
    return request.client.host if request.client else "-"


@router.post("/login", status_code=204, summary="Sign in with the password")
def login(payload: LoginIn, request: Request, response: Response, db: DbSession) -> None:
    if request.headers.get(CSRF_HEADER) != "nexpulse":
        raise fehler("missing_header", "This request needs the header X-Requested-By: nexpulse.", 403)
    password_hash = settings_service.password_hash(db)
    if not password_hash:
        return
    key = "login:" + _client(request)
    wait = brake.wait_seconds(key)
    if wait:
        raise HTTPException(
            status_code=429,
            detail=meldung("too_many_attempts", "Too many wrong passwords. Try again later.", retry_after=wait),
            headers={"Retry-After": str(wait)},
        )
    if not verify_password(payload.password, password_hash):
        brake.failed(key)
        raise fehler("wrong_password", "The password is wrong.", 401)
    brake.succeeded(key)
    _set_session(response, request, password_hash)


@router.post("/logout", status_code=204, summary="Sign out in this browser")
def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.put("/password", status_code=204, dependencies=[UiAccess], summary="Set, change or remove the password")
def set_password(payload: PasswordIn, request: Request, response: Response, db: DbSession) -> None:
    new = (payload.password or "").strip()
    if not new:
        settings_service.save(db, {"password_hash": ""})
        response.delete_cookie(SESSION_COOKIE, path="/")
        return
    if len(new) < MIN_PASSWORD:
        raise fehler("password_too_short", "Use at least 10 characters.", 422, minimum=MIN_PASSWORD)
    password_hash = hash_password(new)
    settings_service.save(db, {"password_hash": password_hash})
    # Wer das Passwort setzt, bleibt in diesem Browser angemeldet. Alle anderen
    # Sitzungen gelten mit dem neuen Passwort nicht mehr.
    _set_session(response, request, password_hash)
