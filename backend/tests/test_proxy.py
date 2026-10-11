"""Was ein Proxy ueber die Anfrage sagt, gilt nur von einem vertrauten (NEXPULSE_TRUSTED_PROXIES)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.proxy import forwarded_proto
from app.security import SESSION_COOKIE, brake

from .conftest import UI

PROXY = "203.0.113.1"
VISITOR = "203.0.113.10"
PASSWORD = "correct-horse-1"


@pytest.fixture
def trusted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "trusted_proxies", f"{PROXY}, 198.51.100.0/24")


@pytest.fixture
def password(client: TestClient) -> None:
    assert client.put("/api/auth/password", json={"password": PASSWORD}, headers=UI).status_code == 204


def _secure(client: TestClient, sender: str, *proto: str) -> bool:
    """Meldet sich von ``sender`` an, mit je einer Zeile X-Forwarded-Proto, und sagt, ob das Cookie Secure traegt."""
    headers = [("X-Requested-By", "nexpulse"), *(("X-Forwarded-Proto", value) for value in proto)]
    response = TestClient(client.app, client=(sender, 40000)).post(
        "/api/auth/login", json={"password": PASSWORD}, headers=headers
    )
    assert response.status_code == 204
    cookie = next(c for c in response.headers.get_list("set-cookie") if c.startswith(SESSION_COOKIE + "="))
    return "secure" in [part.strip().lower() for part in cookie.split(";")]


def test_nobody_is_trusted_by_default(client: TestClient, password: None) -> None:
    assert get_settings().trusted_proxies == ""
    assert _secure(client, PROXY, "https") is False
    assert _secure(client, "127.0.0.1", "https") is False


def test_an_untrusted_sender_cannot_claim_https(client: TestClient, password: None, trusted: None) -> None:
    assert _secure(client, VISITOR, "https") is False


def test_a_trusted_proxy_makes_the_cookie_secure(client: TestClient, password: None, trusted: None) -> None:
    assert _secure(client, PROXY, "https") is True
    assert _secure(client, "198.51.100.20", "https") is True
    assert _secure(client, PROXY, "http") is False
    assert _secure(client, PROXY) is False


def test_the_rightmost_value_of_the_last_line_counts(client: TestClient, password: None, trusted: None) -> None:
    # Links kann der Besucher selbst etwas angehaengt haben, rechts schreibt der Proxy.
    assert _secure(client, PROXY, "https, http") is False
    assert _secure(client, PROXY, "http, HTTPS") is True
    assert _secure(client, PROXY, "https", "http") is False
    assert _secure(client, PROXY, "http", " https ") is True
    # Fuer eine gewoehnliche Anfrage nur http und https.
    assert _secure(client, PROXY, "wss") is False


def test_forwarded_proto_per_kind() -> None:
    lines = [(b"x-forwarded-proto", b"http"), (b"X-Forwarded-Proto", b"ws, HTTPS")]
    assert forwarded_proto(lines) == "https"
    assert forwarded_proto(lines, "websocket") == "wss"
    assert forwarded_proto([(b"x-forwarded-proto", b"wss")], "websocket") == "wss"
    assert forwarded_proto([(b"x-forwarded-proto", b"wss")]) == ""
    assert forwarded_proto([(b"x-forwarded-proto", b"ftp")]) == ""
    assert forwarded_proto([]) == ""


def _fail_five(client: TestClient, sender: str, forwarded_for: str) -> int:
    """Fuenf falsche Passwoerter, dann das richtige; gibt den Status des letzten Versuchs zurueck."""
    browser = TestClient(client.app, client=(sender, 40000))
    headers = {**UI, "X-Forwarded-For": forwarded_for}
    for _ in range(5):
        assert browser.post("/api/auth/login", json={"password": "wrong"}, headers=headers).status_code == 401
    return browser.post("/api/auth/login", json={"password": PASSWORD}, headers=headers).status_code


def test_the_brake_counts_visitors_behind_a_trusted_proxy(client: TestClient, password: None, trusted: None) -> None:
    try:
        assert _fail_five(client, PROXY, f"198.51.100.200, {VISITOR}") == 429
        # Ein anderer Besucher hinter demselben Proxy ist nicht mitgesperrt.
        other = TestClient(client.app, client=(PROXY, 40000))
        headers = {**UI, "X-Forwarded-For": "203.0.113.11"}
        assert other.post("/api/auth/login", json={"password": PASSWORD}, headers=headers).status_code == 204
    finally:
        brake._fails.clear()


def test_an_untrusted_sender_cannot_dodge_the_brake(client: TestClient, password: None, trusted: None) -> None:
    try:
        browser = TestClient(client.app, client=(VISITOR, 40000))
        for number in range(5):
            headers = {**UI, "X-Forwarded-For": f"203.0.113.{100 + number}"}
            assert browser.post("/api/auth/login", json={"password": "wrong"}, headers=headers).status_code == 401
        headers = {**UI, "X-Forwarded-For": "203.0.113.99"}
        assert browser.post("/api/auth/login", json={"password": PASSWORD}, headers=headers).status_code == 429
    finally:
        brake._fails.clear()
