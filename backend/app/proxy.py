"""Was ein vertrauter Proxy ueber die Anfrage sagt.

Ein Proxy, der TLS beendet, reicht die Anfrage als ``http`` weiter und nennt in
``X-Forwarded-Proto`` das Schema, mit dem sie bei ihm ankam, in
``X-Forwarded-For`` den Absender. Geglaubt wird das nur einem Proxy aus
``NEXPULSE_TRUSTED_PROXIES``. Ab Werk ist die Liste leer, dann glaubt nexpulse
niemandem: Jeder koennte die Kopfzeilen sonst selbst mitschicken. uvicorn startet
deshalb mit ``--no-proxy-headers`` (Dockerfile), sonst glaubte es 127.0.0.1.

Regel: rechtester
Wert der letzten Kopfzeile, ohne Gross und klein, nur ``http`` und ``https``
(fuer einen WebSocket ``ws`` und ``wss``). Links davon kann der Besucher selbst
etwas angehaengt haben.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Any

from uvicorn.middleware.proxy_headers import _TrustedHosts

from .config import get_settings

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]

#: Welche Schemata ein vertrauter Proxy je Verbindungsart nennen darf.
_SCHEMES = {
    "http": {"http": "http", "https": "https"},
    "websocket": {"http": "ws", "https": "wss", "ws": "ws", "wss": "wss"},
}


def forwarded_proto(headers: list[tuple[bytes, bytes]], kind: str = "http") -> str:
    """Das Schema aus ``X-Forwarded-Proto``: rechtester Wert der letzten Zeile, sonst ein leerer Text."""
    said: bytes | None = None
    for name, value in headers:
        if name.lower() == b"x-forwarded-proto":
            said = value
    if said is None:
        return ""
    return _SCHEMES.get(kind, {}).get(said.decode("latin-1").rsplit(",", 1)[-1].strip().lower(), "")


@lru_cache(maxsize=8)
def _trusted(text: str) -> _TrustedHosts:
    # Leerer Text: die Liste enthaelt nur "", und das traut uvicorn keinem Absender zu.
    return _TrustedHosts(text.strip())


def is_trusted_proxy(host: str | None) -> bool:
    """Die Adresse gehoert zu einem Proxy aus ``NEXPULSE_TRUSTED_PROXIES``."""
    text = get_settings().trusted_proxies
    return bool(text.strip()) and host in _trusted(text)


class TrustedProxyMiddleware:
    """Schema und Absender nur von vertrauten Proxys. Reines ASGI, damit nichts puffert."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            peer = scope.get("client")
            if peer and is_trusted_proxy(str(peer[0])):
                scope = self._rewrite(scope)
        await self.app(scope, receive, send)

    @staticmethod
    def _rewrite(scope: Scope) -> Scope:
        headers = scope.get("headers", [])
        scope = dict(scope)
        scheme = forwarded_proto(headers, scope["type"])
        if scheme:
            scope["scheme"] = scheme
        hops = [value for name, value in headers if name.lower() == b"x-forwarded-for"]
        if hops:
            # Von rechts der erste Absender, der kein vertrauter Proxy ist (wie uvicorn).
            host, port = _trusted(get_settings().trusted_proxies).get_trusted_client_address(
                b", ".join(hops).decode("latin-1")
            )
            if host:
                scope["client"] = (host, port)
        return scope
