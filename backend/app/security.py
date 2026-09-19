"""Passwort, Sitzung, API-Schluessel und die Bremse gegen Raten.

nexpulse kennt keine Konten. Es gibt hoechstens ein Passwort fuer die
Oberflaeche, und API-Schluessel fuer alles, was von aussen abfragt.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from .config import get_settings

ALGORITHM = "HS256"
SESSION_COOKIE = "nexpulse_session"
KEY_PREFIX = "npk_"

# bcrypt verarbeitet hoechstens 72 Bytes. bcrypt 5 wirft bei laengeren Eingaben.
_BCRYPT_MAX_BYTES = 72


def _signing_key() -> bytes:
    # Das Praefix trennt diesen Schluessel von dem der Verschluesselung.
    secret = get_settings().resolved_secret_key().encode("utf-8")
    return hashlib.sha256(b"nexpulse-session:" + secret).digest()


def hash_password(password: str) -> str:
    rounds = get_settings().bcrypt_rounds
    return bcrypt.hashpw(password.encode("utf-8")[:_BCRYPT_MAX_BYTES], bcrypt.gensalt(rounds)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:_BCRYPT_MAX_BYTES], password_hash.encode("utf-8"))
    except ValueError:
        return False


def password_version(password_hash: str) -> str:
    """Kennung des aktuellen Passworts. Wechselt es, gelten alte Sitzungen nicht mehr."""
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def create_session_token(password_hash: str) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "type": "session",
        "pwv": password_version(password_hash),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=get_settings().session_days)).timestamp()),
    }
    return jwt.encode(payload, _signing_key(), algorithm=ALGORITHM)


def session_valid(token: str, password_hash: str) -> bool:
    try:
        payload = jwt.decode(token, _signing_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return False
    return payload.get("type") == "session" and secrets.compare_digest(
        str(payload.get("pwv", "")), password_version(password_hash)
    )


def new_api_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(24)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class Brake:
    """Wartezeit nach falschen Passwoertern, je Absender.

    Die ersten fuenf Versuche sind frei, danach verdoppelt sich die Wartezeit bis
    hoechstens 15 Minuten. Nur im Arbeitsspeicher: Ein Neustart setzt zurueck, das
    ist fuer ein einzelnes Passwort im Heimnetz genug.
    """

    FREE = 5
    MAX_WAIT = 900

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fails: dict[str, tuple[int, float]] = {}

    def wait_seconds(self, key: str) -> int:
        with self._lock:
            count, last = self._fails.get(key, (0, 0.0))
        if count < self.FREE:
            return 0
        wait = min(self.MAX_WAIT, 2 ** (count - self.FREE) * 5)
        remaining = last + wait - time.monotonic()
        return max(0, int(remaining + 0.999))

    def failed(self, key: str) -> None:
        with self._lock:
            count, _ = self._fails.get(key, (0, 0.0))
            self._fails[key] = (count + 1, time.monotonic())

    def succeeded(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


brake = Brake()
