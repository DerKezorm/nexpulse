"""Die Verwaltung der Quellen ueber die API: eigene iperf3-Ziele eintragen und entfernen."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.services.engines import iperf3

from .conftest import UI


@pytest.fixture(autouse=True)
def iperf3_there(monkeypatch: pytest.MonkeyPatch) -> None:
    """iperf3 ist auf diesem Rechner nicht unbedingt installiert, im Abbild schon."""
    monkeypatch.setattr(iperf3, "available", lambda: True)


def answering(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, int]]:
    asked: list[tuple[str, int]] = []

    async def check(host: str, port: int) -> None:
        asked.append((host, port))

    monkeypatch.setattr(iperf3, "check", check)
    return asked


def test_a_target_is_asked_before_it_is_saved(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    asked = answering(monkeypatch)
    response = client.post(
        "/api/sources/iperf3/servers", json={"name": "VPS", "host": "vps.example.com", "port": 5202}, headers=UI
    )
    assert response.status_code == 201
    assert asked == [("vps.example.com", 5202)]
    [server] = response.json()["iperf3"]["servers"]
    assert (server["host"], server["port"]) == ("vps.example.com", 5202)

    gone = client.delete(f"/api/sources/iperf3/servers/{server['id']}", headers=UI)
    assert gone.json()["iperf3"]["servers"] == []


def test_a_target_that_does_not_answer_is_not_saved(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def check(_host: str, _port: int) -> None:
        raise iperf3.MeasurementError("iperf3_failed", "connection refused")

    monkeypatch.setattr(iperf3, "check", check)
    response = client.post("/api/sources/iperf3/servers", json={"name": "VPS", "host": "vps.example.com"}, headers=UI)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "iperf3_not_found"
    assert client.get("/api/sources", headers=UI).json()["iperf3"]["servers"] == []


@pytest.mark.parametrize("host", ["http://vps.example.com", "vps.example.com/speed", "vps example"])
def test_an_address_is_a_host_not_a_url(client: TestClient, monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    asked = answering(monkeypatch)
    response = client.post("/api/sources/iperf3/servers", json={"name": "VPS", "host": host}, headers=UI)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_host"
    assert asked == []


def test_the_same_target_is_not_added_twice(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    answering(monkeypatch)
    body: dict[str, Any] = {"name": "VPS", "host": "vps.example.com"}
    assert client.post("/api/sources/iperf3/servers", json=body, headers=UI).status_code == 201
    again = client.post("/api/sources/iperf3/servers", json={**body, "name": "Same one"}, headers=UI)
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "server_exists"


def test_removing_a_target_forgets_it_as_a_favorite(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    answering(monkeypatch)
    created = client.post("/api/sources/iperf3/servers", json={"name": "VPS", "host": "vps.example.com"}, headers=UI)
    server_id = created.json()["iperf3"]["servers"][0]["id"]
    saved = client.put("/api/sources", json={"iperf3_favorites": [server_id]}, headers=UI)
    assert saved.json()["iperf3"]["favorites"] == [server_id]
    gone = client.delete(f"/api/sources/iperf3/servers/{server_id}", headers=UI)
    assert gone.json()["iperf3"]["favorites"] == []


def test_iperf3_stays_off_without_the_program(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(iperf3, "available", lambda: False)
    client.put("/api/sources", json={"sources": {"iperf3": True}}, headers=UI)
    state = client.get("/api/sources", headers=UI).json()
    assert state["iperf3"]["available"] is False
    # Der Schalter steht auf an, benutzbar ist die Quelle trotzdem nicht.
    assert state["sources"]["iperf3"] == {"switched_on": True, "enabled": False}
