from __future__ import annotations

import time
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Result, Schedule, utcnow
from app.services import scheduler, settings_service
from app.services.runner import runner

from .conftest import UI, FakeEngine


def wait_done(client: TestClient, seconds: float = 5) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not client.get("/api/tests/live").json()["running"]:
            return
        time.sleep(0.02)
    raise AssertionError("test did not finish")


def results() -> list[Result]:
    with SessionLocal() as db:
        return list(db.scalars(select(Result).order_by(Result.id)))


def test_manual_test_is_saved(client: TestClient, fake_engine: FakeEngine) -> None:
    response = client.post("/api/tests", json={"source": "cloudflare"}, headers=UI)
    assert response.status_code == 202
    wait_done(client)
    [result] = results()
    assert result.status == "ok"
    assert result.trigger == "manual"
    assert result.download_mbps == 900.0
    assert result.upload_mbps == 45.0
    assert result.ping_ms == 12.0
    assert result.server_name == "Fake server"
    assert client.get("/api/results/latest").json()["id"] == result.id


def test_failure_is_saved_with_its_code(client: TestClient, fake_engine: FakeEngine) -> None:
    fake_engine.fail = "unreachable"
    client.post("/api/tests", json={"source": "cloudflare"}, headers=UI)
    wait_done(client)
    [result] = results()
    assert result.status == "failed"
    assert result.error_code == "unreachable"
    assert result.download_mbps is None


def test_below_plan_is_marked(client: TestClient, fake_engine: FakeEngine) -> None:
    client.put("/api/settings", json={"plan_down": 1000, "plan_up": 50, "threshold_pct": 95}, headers=UI)
    client.post("/api/tests", json={"source": "cloudflare"}, headers=UI)
    wait_done(client)
    assert results()[0].below_plan is True
    client.put("/api/settings", json={"threshold_pct": 75}, headers=UI)
    client.post("/api/tests", json={"source": "cloudflare"}, headers=UI)
    wait_done(client)
    assert results()[1].below_plan is False


def test_turned_off_source_is_refused(client: TestClient, fake_engine: FakeEngine) -> None:
    response = client.post("/api/tests", json={"source": "ookla"}, headers=UI)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "source_disabled"
    assert client.post("/api/tests", json={"source": "nope"}, headers=UI).status_code == 422


def test_last_source_cannot_be_turned_off(client: TestClient) -> None:
    response = client.put("/api/sources", json={"sources": {"cloudflare": False, "librespeed": False}}, headers=UI)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "last_source"


def test_stats_and_csv(client: TestClient, fake_engine: FakeEngine) -> None:
    for down in (800.0, 900.0):
        fake_engine.down = down
        client.post("/api/tests", json={"source": "cloudflare"}, headers=UI)
        wait_done(client)
    stats = client.get("/api/results/stats?range=24h").json()
    assert stats["tests"] == 2
    assert stats["download_mbps"]["avg"] == 850.0
    with SessionLocal() as db:
        db.get(Result, results()[0].id).isp = "=HYPERLINK(1)"
        db.commit()
    csv = client.get("/api/results/export.csv").text
    assert csv.splitlines()[0].startswith("id,started_at,source")
    assert "'=HYPERLINK(1)" in csv


def test_schedule_runs_when_due(client: TestClient, fake_engine: FakeEngine) -> None:
    created = client.post(
        "/api/schedules",
        json={"name": "Every hour", "mode": "interval", "interval_minutes": 60, "random_offset": False},
        headers=UI,
    ).json()
    assert created["next_run_at"] is not None
    with SessionLocal() as db:
        schedule = db.get(Schedule, created["id"])
        schedule.next_run_at = utcnow() - timedelta(seconds=5)
        db.commit()

    async def tick() -> None:
        scheduler.tick()

    client.portal.call(tick)
    wait_done(client)
    [result] = results()
    assert result.trigger == "schedule"
    assert result.schedule_id == created["id"]
    with SessionLocal() as db:
        schedule = db.get(Schedule, created["id"])
        assert schedule.last_run_at is not None
        assert schedule.next_run_at > utcnow()


def test_missed_slot_is_skipped_not_caught_up(client: TestClient, fake_engine: FakeEngine) -> None:
    created = client.post("/api/schedules", json={"name": "Late", "random_offset": False}, headers=UI).json()
    with SessionLocal() as db:
        db.get(Schedule, created["id"]).next_run_at = utcnow() - timedelta(hours=2)
        db.commit()

    async def tick() -> None:
        scheduler.tick()

    client.portal.call(tick)
    assert not runner.running
    assert results() == []


def test_schedule_with_turned_off_source_does_not_run(client: TestClient, fake_engine: FakeEngine) -> None:
    created = client.post("/api/schedules", json={"name": "Ookla", "source": "ookla"}, headers=UI).json()
    with SessionLocal() as db:
        db.get(Schedule, created["id"]).next_run_at = utcnow() - timedelta(seconds=5)
        db.commit()

    async def tick() -> None:
        scheduler.tick()

    client.portal.call(tick)
    assert results() == []


def test_invalid_cron_is_refused(client: TestClient) -> None:
    response = client.post("/api/schedules", json={"name": "x", "mode": "cron", "cron": "99 * * * *"}, headers=UI)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_cron"


def test_preview(client: TestClient) -> None:
    client.put("/api/settings", json={"timezone": "Europe/Berlin"}, headers=UI)
    response = client.post(
        "/api/schedules/preview", json={"name": "x", "mode": "daily", "daily_time": "04:00"}, headers=UI
    )
    body = response.json()
    assert body["timezone"] == "Europe/Berlin"
    assert len(body["runs"]) == 5


def test_rotate_takes_favorites_in_turn(client: TestClient) -> None:
    with SessionLocal() as db:
        settings_service.save(db, {"librespeed_favorites": ["a", "b"]})
        schedule = Schedule(name="r", source="librespeed", server_mode="rotate", rotate_index=0)
        picked = [scheduler.pick_server(db, schedule) for _ in range(3)]
    assert picked == ["a", "b", "a"]


def test_retention_removes_old_results(client: TestClient) -> None:
    with SessionLocal() as db:
        db.add(Result(source="cloudflare", status="ok", started_at=utcnow() - timedelta(days=400)))
        db.add(Result(source="cloudflare", status="ok", started_at=utcnow() - timedelta(days=10)))
        db.commit()
    assert scheduler.clean_up() == 1
    assert len(results()) == 1


def test_interrupted_tests_are_marked_after_restart(client: TestClient) -> None:
    with SessionLocal() as db:
        db.add(Result(source="cloudflare", status="running"))
        db.commit()
    scheduler.mark_interrupted()
    assert results()[0].status == "failed"
    assert results()[0].error_code == "interrupted"


def test_random_schedule_gets_a_seed_and_keeps_it(client: TestClient) -> None:
    body = {"name": "Random", "mode": "random", "per_day": 6}
    created = client.post("/api/schedules", json=body, headers=UI).json()
    assert created["seed"] > 0
    assert created["next_run_at"] is not None
    updated = client.put(f"/api/schedules/{created['id']}", json={**body, "name": "Renamed"}, headers=UI).json()
    assert updated["seed"] == created["seed"]
    assert updated["next_run_at"] == created["next_run_at"]


def test_unsaved_schedule_uses_the_defaults(client: TestClient) -> None:
    # Im Code angelegt, noch nicht gespeichert: SQLAlchemy hat die Standardwerte noch nicht gesetzt.
    with SessionLocal() as db:
        schedule = Schedule(name="Fresh", mode="daily", daily_time="05:00")
        scheduler.reschedule(db, schedule)
    assert schedule.next_run_at is not None
