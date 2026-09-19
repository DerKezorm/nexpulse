from __future__ import annotations

from fastapi.testclient import TestClient

from app.security import brake

from .conftest import UI


def test_open_without_password(client: TestClient) -> None:
    assert client.get("/api/config").json()["password_required"] is False
    assert client.get("/api/settings").status_code == 200


def test_changes_need_the_header(client: TestClient) -> None:
    # Ohne Kopfzeile koennte jede fremde Webseite im Heimnetz Tests ausloesen oder ein Passwort setzen.
    response = client.put("/api/auth/password", json={"password": "correct-horse-1"})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "missing_header"
    assert client.get("/api/config").json()["password_required"] is False


def test_password_locks_the_interface(client: TestClient) -> None:
    assert client.put("/api/auth/password", json={"password": "correct-horse-1"}, headers=UI).status_code == 204
    # Wer es gesetzt hat, bleibt angemeldet.
    assert client.get("/api/settings").status_code == 200

    stranger = TestClient(client.app)
    assert stranger.get("/api/settings").status_code == 401
    assert stranger.get("/api/config").json()["signed_in"] is False
    wrong = stranger.post("/api/auth/login", json={"password": "nope"}, headers=UI)
    assert wrong.status_code == 401
    assert stranger.post("/api/auth/login", json={"password": "correct-horse-1"}, headers=UI).status_code == 204
    assert stranger.get("/api/settings").status_code == 200


def test_changing_the_password_ends_other_sessions(client: TestClient) -> None:
    client.put("/api/auth/password", json={"password": "correct-horse-1"}, headers=UI)
    other = TestClient(client.app)
    other.post("/api/auth/login", json={"password": "correct-horse-1"}, headers=UI)
    assert other.get("/api/settings").status_code == 200
    client.put("/api/auth/password", json={"password": "correct-horse-2"}, headers=UI)
    assert other.get("/api/settings").status_code == 401
    assert client.get("/api/settings").status_code == 200


def test_short_password_is_refused(client: TestClient) -> None:
    response = client.put("/api/auth/password", json={"password": "short"}, headers=UI)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "password_too_short"


def test_removing_the_password_opens_again(client: TestClient) -> None:
    client.put("/api/auth/password", json={"password": "correct-horse-1"}, headers=UI)
    assert client.put("/api/auth/password", json={"password": ""}, headers=UI).status_code == 204
    assert TestClient(client.app).get("/api/settings").status_code == 200


def test_brake_after_five_wrong_passwords(client: TestClient) -> None:
    client.put("/api/auth/password", json={"password": "correct-horse-1"}, headers=UI)
    stranger = TestClient(client.app)
    try:
        for _ in range(5):
            assert stranger.post("/api/auth/login", json={"password": "wrong"}, headers=UI).status_code == 401
        blocked = stranger.post("/api/auth/login", json={"password": "correct-horse-1"}, headers=UI)
        assert blocked.status_code == 429
        assert blocked.json()["detail"]["code"] == "too_many_attempts"
    finally:
        brake._fails.clear()


def test_api_needs_a_key_even_without_password(client: TestClient) -> None:
    response = client.get("/api/v1/latest")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_api_key"
    assert client.get("/api/v1/latest", headers={"X-Api-Key": "npk_made_up"}).status_code == 401


def test_read_key_reads_but_does_not_run(client: TestClient, fake_engine: object) -> None:
    created = client.post("/api/keys", json={"name": "nexdeck", "scope": "read"}, headers=UI).json()
    key = created["key"]
    assert key.startswith("npk_")
    assert "key" not in client.get("/api/keys").json()[0]
    assert client.get("/api/v1/status", headers={"X-Api-Key": key}).status_code == 200
    assert client.get("/api/v1/stats", headers={"Authorization": f"Bearer {key}"}).status_code == 200
    denied = client.post("/api/v1/tests", json={}, headers={"X-Api-Key": key})
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "key_read_only"


def test_run_key_starts_a_test(client: TestClient, fake_engine: object) -> None:
    key = client.post("/api/keys", json={"name": "ha", "scope": "run"}, headers=UI).json()["key"]
    response = client.post("/api/v1/tests", json={"source": "cloudflare"}, headers={"X-Api-Key": key})
    assert response.status_code == 202
    assert response.json()["trigger"] == "api"


def test_revoked_key_stops_working(client: TestClient) -> None:
    created = client.post("/api/keys", json={"name": "old", "scope": "read"}, headers=UI).json()
    assert client.delete(f"/api/keys/{created['id']}", headers=UI).status_code == 204
    assert client.get("/api/v1/status", headers={"X-Api-Key": created["key"]}).status_code == 401


def test_key_does_not_open_the_interface(client: TestClient) -> None:
    key = client.post("/api/keys", json={"name": "k", "scope": "run"}, headers=UI).json()["key"]
    client.put("/api/auth/password", json={"password": "correct-horse-1"}, headers=UI)
    stranger = TestClient(client.app)
    assert stranger.get("/api/settings", headers={"X-Api-Key": key}).status_code == 401


def test_me_tells_what_a_key_may_do(client: TestClient) -> None:
    read = client.post("/api/keys", json={"name": "nexdeck", "scope": "read"}, headers=UI).json()["key"]
    run = client.post("/api/keys", json={"name": "ha", "scope": "run"}, headers=UI).json()["key"]
    assert client.get("/api/v1/me", headers={"X-Api-Key": read}).json() == {
        "name": "nexdeck",
        "scope": "read",
        "can_run_tests": False,
        "version": client.get("/api/health").json()["version"],
    }
    assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {run}"}).json()["can_run_tests"] is True
    assert client.get("/api/v1/me").status_code == 401


def test_empty_body_never_starts_a_test(client: TestClient, fake_engine: object) -> None:
    # Frueher galt Cloudflare als Standard, und {} startete eine echte Messung.
    run = client.post("/api/keys", json={"name": "ha", "scope": "run"}, headers=UI).json()["key"]
    response = client.post("/api/v1/tests", json={}, headers={"X-Api-Key": run})
    assert response.status_code == 422
    assert client.get("/api/tests/live").json()["running"] is False
