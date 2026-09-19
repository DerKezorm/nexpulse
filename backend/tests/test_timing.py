from __future__ import annotations

import random
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.timing import Cron, CronError, Plan, next_local, next_run, random_slots, upcoming

BERLIN = ZoneInfo("Europe/Berlin")


def local(text: str) -> datetime:
    return datetime.fromisoformat(text)


def test_interval_is_aligned_to_midnight() -> None:
    plan = Plan(mode="interval", interval_minutes=120)
    assert next_local(plan, local("2026-09-19 09:13")) == local("2026-09-19 10:00")
    assert next_local(plan, local("2026-09-19 10:00")) == local("2026-09-19 12:00")
    assert next_local(plan, local("2026-09-19 23:30")) == local("2026-09-20 00:00")


def test_window_and_weekdays() -> None:
    # Montag bis Freitag, 19:00 bis 23:00, alle 30 Minuten. 19.09.2026 ist ein Samstag.
    plan = Plan(mode="interval", interval_minutes=30, days=0b0011111, window_from="19:00", window_to="23:00")
    assert next_local(plan, local("2026-09-18 22:40")) == local("2026-09-18 23:00")
    assert next_local(plan, local("2026-09-18 23:00")) == local("2026-09-21 19:00")


def test_window_over_midnight() -> None:
    plan = Plan(mode="interval", interval_minutes=60, window_from="22:00", window_to="02:00")
    assert next_local(plan, local("2026-09-19 12:00")) == local("2026-09-19 22:00")
    assert next_local(plan, local("2026-09-19 23:00")) == local("2026-09-20 00:00")
    assert next_local(plan, local("2026-09-20 02:00")) == local("2026-09-20 22:00")


def test_daily() -> None:
    plan = Plan(mode="daily", daily_time="04:00")
    assert next_local(plan, local("2026-09-19 03:59")) == local("2026-09-19 04:00")
    assert next_local(plan, local("2026-09-19 04:00")) == local("2026-09-20 04:00")


def test_no_days_means_never() -> None:
    assert next_local(Plan(mode="daily", days=0), local("2026-09-19 03:00")) is None


def test_daily_stays_at_wall_clock_over_dst_change() -> None:
    # Umstellung auf Winterzeit am 25.10.2026: 04:00 bleibt 04:00, in UTC eine Stunde spaeter.
    plan = Plan(mode="daily", daily_time="04:00")
    before = next_run(plan, datetime(2026, 10, 24, 12, 0, tzinfo=UTC), BERLIN, random_offset=False)
    after = next_run(plan, datetime(2026, 10, 25, 12, 0, tzinfo=UTC), BERLIN, random_offset=False)
    assert before == datetime(2026, 10, 25, 3, 0, tzinfo=UTC)
    assert after == datetime(2026, 10, 26, 3, 0, tzinfo=UTC)


def test_random_offset_stays_within_five_minutes() -> None:
    plan = Plan(mode="daily", daily_time="04:00")
    now = datetime(2026, 9, 19, 0, 0, tzinfo=UTC)
    exact = next_run(plan, now, BERLIN, random_offset=False)
    rng = random.Random(1)
    for _ in range(200):
        moment = next_run(plan, now, BERLIN, random_offset=True, rng=rng)
        assert moment is not None and exact is not None
        assert abs((moment - exact).total_seconds()) <= 300


def test_cron() -> None:
    cron = Cron.parse("*/15 8-17 * * 1-5")
    assert cron.next_after(local("2026-09-18 17:50")) == local("2026-09-21 08:00")
    assert cron.next_after(local("2026-09-21 08:00")) == local("2026-09-21 08:15")
    # Sonntag als 0 und als 7
    assert Cron.parse("0 4 * * 0").next_after(local("2026-09-19 12:00")) == local("2026-09-20 04:00")
    assert Cron.parse("0 4 * * 7").next_after(local("2026-09-19 12:00")) == local("2026-09-20 04:00")


def test_cron_day_or_weekday() -> None:
    # Wie crontab: am 1. des Monats ODER montags.
    cron = Cron.parse("0 6 1 * 1")
    assert cron.next_after(local("2026-09-22 07:00")) == local("2026-09-28 06:00")
    assert cron.next_after(local("2026-09-29 07:00")) == local("2026-10-01 06:00")


@pytest.mark.parametrize("expression", ["", "* * * *", "61 * * * *", "* 24 * * *", "*/0 * * * *", "a * * * *"])
def test_cron_rejects_nonsense(expression: str) -> None:
    with pytest.raises(CronError):
        Cron.parse(expression)


def test_upcoming_lists_five() -> None:
    runs = upcoming(Plan(mode="interval", interval_minutes=360), datetime(2026, 9, 19, 7, 0, tzinfo=UTC), BERLIN)
    assert [run.astimezone(BERLIN).hour for run in runs] == [12, 18, 0, 6, 12]


def test_random_times_cover_the_whole_day() -> None:
    plan = Plan(mode="random", per_day=6, seed=42)
    slots = random_slots(plan, local("2026-09-19 00:00"))
    assert len(slots) == 6
    # Je ein Test in jedem Vierstundenblock: nichts ballt sich, der Abend fehlt nie.
    assert [slot // 240 for slot in slots] == [0, 1, 2, 3, 4, 5]


def test_random_times_change_daily_but_stay_fixed_for_a_day() -> None:
    plan = Plan(mode="random", per_day=6, seed=42)
    monday = random_slots(plan, local("2026-09-21 00:00"))
    assert monday == random_slots(plan, local("2026-09-21 00:00"))
    assert monday != random_slots(plan, local("2026-09-22 00:00"))
    assert monday != random_slots(Plan(mode="random", per_day=6, seed=7), local("2026-09-21 00:00"))


def test_random_times_respect_window_and_days() -> None:
    plan = Plan(mode="random", per_day=4, seed=1, window_from="18:00", window_to="23:00", days=0b0011111)
    for slot in random_slots(plan, local("2026-09-21 00:00")):
        assert 18 * 60 <= slot <= 23 * 60
    # Samstag 19.09.2026 ist ausgenommen, der naechste Lauf liegt am Montag.
    first = next_local(plan, local("2026-09-19 12:00"))
    assert first is not None and first.date().isoformat() == "2026-09-21"


def test_preview_and_run_agree_for_random_times() -> None:
    plan = Plan(mode="random", per_day=8, seed=99)
    now = datetime(2026, 9, 19, 6, 0, tzinfo=UTC)
    preview = upcoming(plan, now, BERLIN, count=3)
    assert next_run(plan, now, BERLIN, random_offset=True) == preview[0]
