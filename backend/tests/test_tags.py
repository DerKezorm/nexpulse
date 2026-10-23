"""Issue #6: Tags an eigenen Servern, Zeitplaene nach Tag, jedes Ergebnis melden, Ookla-Nummer von Hand."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Result, Schedule, utcnow
from app.services import notify, scheduler, settings_service, tags
from app.services.engines import iperf3, librespeed

from .conftest import UI


@pytest.fixture(autouse=True)
def iperf3_there(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(iperf3, "available", lambda: True)

    async def check(host: str, port: int, family: str = "auto") -> None:
        return None

    monkeypatch.setattr(iperf3, "check", check)


def targets(*entries: tuple[str, list[str]]) -> list[str]:
    """iperf3-Ziele mit Tags speichern, zurueck kommen ihre Kennungen."""
    with SessionLocal() as db:
        settings_service.save(
            db,
            {"iperf3_servers": [{"name": host, "host": host, "port": 5201, "tags": found} for host, found in entries]},
        )
    return [iperf3.target_id(host, 5201) for host, _ in entries]


def test_tags_are_cleaned() -> None:
    assert tags.clean(["  JP ", "jp", "", "office   home", "x" * 40]) == ["JP", "office home", "x" * 32]
    assert len(tags.clean([f"t{n}" for n in range(30)])) == tags.MAX_TAGS


def test_iperf3_tags_are_saved_and_can_change(client: TestClient) -> None:
    added = client.post(
        "/api/sources/iperf3/servers",
        json={"name": "Tokyo", "host": "jp.example.com", "tags": ["JP", " Pro ", "jp"]},
        headers=UI,
    )
    [server] = added.json()["iperf3"]["servers"]
    assert server["tags"] == ["JP", "Pro"]
    changed = client.put(
        f"/api/sources/iperf3/servers/{server['id']}", json={"name": "Tokyo", "tags": ["T1"]}, headers=UI
    )
    assert changed.json()["iperf3"]["servers"][0]["tags"] == ["T1"]


def test_librespeed_tags_are_saved_and_can_change(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def prefix(base: str) -> str:
        return "backend/"

    monkeypatch.setattr(librespeed, "find_backend_prefix", prefix)
    added = client.post(
        "/api/sources/librespeed/servers",
        json={"name": "Office", "url": "speed.example.com", "tags": ["office"]},
        headers=UI,
    )
    [server] = added.json()["librespeed"]["servers"]
    assert server["tags"] == ["office"]
    changed = client.put(
        f"/api/sources/librespeed/servers/{server['id']}",
        json={"name": "Office 2", "tags": ["office", "EB"]},
        headers=UI,
    )
    [server] = changed.json()["librespeed"]["servers"]
    assert (server["name"], server["tags"], server["url"]) == (
        "Office 2",
        ["office", "EB"],
        "http://speed.example.com/",
    )
    gone = client.put("/api/sources/librespeed/servers/own-00000000", json={"name": "x"}, headers=UI)
    assert gone.status_code == 404


def test_servers_from_before_tags_have_none(client: TestClient) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"iperf3_servers": [{"name": "old", "host": "old.example.com", "port": 5201}]})
    assert client.get("/api/sources", headers=UI).json()["iperf3"]["servers"][0]["tags"] == []


def test_a_tag_schedule_takes_the_matching_servers_in_turn(client: TestClient) -> None:
    jp_pro, jp, us_pro = targets(
        ("a.example.com", ["JP", "Pro"]), ("b.example.com", ["jp"]), ("c.example.com", ["US", "Pro"])
    )
    with SessionLocal() as db:
        any_jp = Schedule(name="jp", source="iperf3", server_mode="tags", tags=["JP"], tag_match="any", rotate_index=0)
        assert [scheduler.pick_server(db, any_jp) for _ in range(3)] == [jp_pro, jp, jp_pro]
        either = Schedule(name="jp or us", source="iperf3", server_mode="tags", tags=["JP", "US"], rotate_index=0)
        assert [scheduler.pick_server(db, either) for _ in range(3)] == [jp_pro, jp, us_pro]
        both = Schedule(name="jp pro", source="iperf3", server_mode="tags", tags=["JP", "pro"], tag_match="all")
        both.rotate_index = 0
        assert [scheduler.pick_server(db, both) for _ in range(2)] == [jp_pro, jp_pro]
        nothing = Schedule(name="de", source="iperf3", server_mode="tags", tags=["DE"], rotate_index=0)
        with pytest.raises(scheduler.NoTaggedServer):
            scheduler.pick_server(db, nothing)


def test_iperf3_rotates_through_its_own_favorites(client: TestClient) -> None:
    # Bis 0.4.4 nahm "reihum" bei iperf3 die Favoriten von LibreSpeed.
    with SessionLocal() as db:
        settings_service.save(db, {"librespeed_favorites": ["ls"], "iperf3_favorites": ["t1", "t2"]})
        schedule = Schedule(name="r", source="iperf3", server_mode="rotate", rotate_index=0)
        assert [scheduler.pick_server(db, schedule) for _ in range(3)] == ["t1", "t2", "t1"]


def test_a_run_without_a_matching_server_is_written_down(client: TestClient) -> None:
    targets(("a.example.com", ["JP"]))
    with SessionLocal() as db:
        settings_service.save(db, {"sources": {**settings_service.DEFAULTS["sources"], "iperf3": True}})
    created = client.post(
        "/api/schedules",
        json={"name": "Germany", "source": "iperf3", "server_mode": "tags", "tags": ["DE"], "random_offset": False},
        headers=UI,
    ).json()
    with SessionLocal() as db:
        db.get(Schedule, created["id"]).next_run_at = utcnow() - timedelta(seconds=5)
        db.commit()

    async def tick() -> None:
        scheduler.tick()

    client.portal.call(tick)
    with SessionLocal() as db:
        [result] = db.scalars(select(Result))
        schedule = db.get(Schedule, created["id"])
        assert (result.status, result.error_code, result.trigger) == ("failed", "no_tagged_server", "schedule")
        assert result.schedule_id == created["id"]
        assert schedule.next_run_at is not None and schedule.next_run_at > utcnow()


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"source": "cloudflare", "server_mode": "tags", "tags": ["JP"]}, "tags_not_supported"),
        ({"source": "iperf3", "server_mode": "tags", "tags": [" "]}, "tags_required"),
        ({"source": "ookla", "server_mode": "fixed", "server_id": "--help"}, "invalid_server_id"),
    ],
)
def test_schedules_refuse(client: TestClient, body: dict[str, Any], code: str) -> None:
    response = client.post("/api/schedules", json={"name": "x", **body}, headers=UI)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code


def test_a_schedule_keeps_its_tags_and_switch(client: TestClient) -> None:
    created = client.post(
        "/api/schedules",
        json={
            "name": "Japan",
            "source": "librespeed",
            "server_mode": "tags",
            "tags": ["JP", " jp ", "Pro"],
            "tag_match": "all",
            "notify_every": True,
        },
        headers=UI,
    ).json()
    assert (created["tags"], created["tag_match"], created["notify_every"]) == (["JP", "Pro"], "all", True)
    ookla = client.post(
        "/api/schedules",
        json={"name": "Tokyo", "source": "ookla", "server_mode": "fixed", "server_id": "24333"},
        headers=UI,
    )
    assert ookla.status_code == 201


def test_a_manual_ookla_test_needs_a_number(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_service, "source_enabled", lambda db, source: True)
    response = client.post("/api/tests", json={"source": "ookla", "server_id": "-s 1"}, headers=UI)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_server_id"


def schedule_with(every: bool) -> Schedule:
    return Schedule(name="Night", notify_every=every)


def result(**values: Any) -> Result:
    base: dict[str, Any] = {
        "source": "iperf3",
        "status": "ok",
        "trigger": "schedule",
        "download_mbps": 480.0,
        "upload_mbps": 95.5,
        "ping_ms": 31.0,
        "server_name": "Tokyo",
        "server_location": "own server",
    }
    return Result(**{**base, **values})


def test_every_result_only_for_schedules_that_ask() -> None:
    assert notify.every_result(result(), schedule_with(True)) == ["result"]
    assert notify.every_result(result(status="failed"), schedule_with(True)) == ["failed"]
    assert notify.every_result(result(), schedule_with(False)) == []
    assert notify.every_result(result(trigger="manual"), schedule_with(True)) == []
    assert notify.every_result(result(status="cancelled"), schedule_with(True)) == []
    assert notify.every_result(result(), None) == []


def test_a_result_message_names_server_and_schedule() -> None:
    title, body = notify.compose(result(), ["result"], dict(settings_service.DEFAULTS), "Night")
    assert title == "nexpulse: speed test result"
    assert body.splitlines() == [
        "down 480 Mbit/s, up 95.5 Mbit/s, ping 31 ms",
        "Server: Tokyo, own server",
        "Schedule: Night",
    ]


@pytest.mark.parametrize(("every", "sent"), [(True, 1), (False, 0)])
def test_after_result_sends_every_result_when_asked(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, every: bool, sent: int
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def send(
        kind: str, url: str, token: str, title: str, body: str, payload: dict[str, Any], reason: str = ""
    ) -> None:
        calls.append((title, payload))

    monkeypatch.setattr(notify, "send", send)
    with SessionLocal() as db:
        settings_service.save(db, {"notify_kind": "webhook", "notify_url": "https://example.com/hook"})
        schedule = Schedule(name="Night", notify_every=every)
        db.add(schedule)
        db.commit()
        saved = result(schedule_id=schedule.id)
        db.add(saved)
        db.commit()
        db.refresh(saved)
    asyncio.run(notify.after_result(saved))
    assert len(calls) == sent
    if sent:
        assert calls[0][1]["event"] == "speedtest.result"
