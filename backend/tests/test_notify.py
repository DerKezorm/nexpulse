"""Wann nexpulse Bescheid gibt, und was drinsteht."""

from __future__ import annotations

from typing import Any

from app.models import Result
from app.services import notify
from app.services.settings_service import DEFAULTS


def settings(**changes: Any) -> dict[str, Any]:
    return {**DEFAULTS, **changes}


def result(**values: Any) -> Result:
    base: dict[str, Any] = {"source": "cloudflare", "status": "ok", "below_plan": False, "ping_ms": 12.0}
    return Result(**{**base, **values})


def test_quiet_when_nothing_is_wrong() -> None:
    assert notify.reasons(result(), settings(alert_ping_enabled=True, alert_ping_ms=40)) == []


def test_failed_test() -> None:
    assert notify.reasons(result(status="failed", error_code="unreachable"), settings()) == ["failed"]
    assert notify.reasons(result(status="failed"), settings(alert_failed=False)) == []
    # Ein abgebrochener Test ist keine Stoerung.
    assert notify.reasons(result(status="cancelled"), settings()) == []


def test_below_plan_and_ping() -> None:
    slow = result(below_plan=True, ping_ms=80.0, download_mbps=400.0, upload_mbps=20.0)
    assert notify.reasons(slow, settings(alert_ping_enabled=True, alert_ping_ms=40)) == ["below_plan", "ping"]
    assert notify.reasons(slow, settings(alert_below_plan=False)) == []


def test_message_names_the_numbers() -> None:
    slow = result(below_plan=True, download_mbps=412.4, upload_mbps=20.0, ping_ms=15.0)
    title, body = notify.compose(slow, ["below_plan"], settings(plan_down=1000, plan_up=50, threshold_pct=75))
    assert title == "nexpulse: slow connection"
    assert "down 412 Mbit/s" in body
    assert "Below 75 % of your plan (1000 / 50 Mbit/s)." in body
