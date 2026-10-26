"""Wann nexpulse Bescheid gibt, und was drinsteht."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.models import Result
from app.services import notify
from app.services.settings_service import DEFAULTS

from .conftest import UI


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


#: Erfunden, und bewusst nicht in Telegrams Form (sonst schlagen die Scanner an).
BOT_TOKEN = "12345:example-token-for-tests-only"


def capture(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        notify.httpx, "AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs)
    )
    return seen


def test_telegram_gets_the_whole_message(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = capture(monkeypatch)
    asyncio.run(notify.send("telegram", "-1001234567890", BOT_TOKEN, "nexpulse: slow connection", "down 4 < 5", {}))
    assert [str(request.url) for request in seen] == [f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"]
    sent = json.loads(seen[0].content)
    assert sent["chat_id"] == "-1001234567890"
    assert sent["parse_mode"] == "HTML"
    assert sent["text"] == "<b>nexpulse: slow connection</b>\ndown 4 &lt; 5"


@pytest.mark.parametrize(
    ("chat", "token"),
    [("-100123", "12345:../../evil/path?x=" + "a" * 20), ("https://example.com", BOT_TOKEN), ("@ab", BOT_TOKEN)],
)
def test_telegram_refuses_odd_values_before_sending(monkeypatch: pytest.MonkeyPatch, chat: str, token: str) -> None:
    seen = capture(monkeypatch)
    with pytest.raises(notify.NotifyError) as caught:
        asyncio.run(notify.send("telegram", chat, token, "t", "b", {}))
    assert caught.value.code == "notify_not_configured"
    assert seen == []


def test_settings_check_telegram_values(client: TestClient) -> None:
    def put(body: dict[str, Any]) -> Any:
        return client.put("/api/settings", json=body, headers=UI)

    wrong = put({"notify_kind": "telegram", "notify_url": "https://example.com/hook", "notify_token": BOT_TOKEN})
    assert wrong.json()["detail"]["code"] == "invalid_chat_id"
    wrong = put({"notify_kind": "telegram", "notify_url": "@nexpulse_alerts", "notify_token": "not-a-token"})
    assert wrong.json()["detail"]["code"] == "invalid_bot_token"
    saved = put({"notify_kind": "telegram", "notify_url": "@nexpulse_alerts", "notify_token": BOT_TOKEN})
    assert saved.status_code == 200
    assert saved.json()["notify_kind"] == "telegram"
    # Die Chat-ID ist keine Adresse: Wer zum Webhook wechselt, muss eine angeben.
    assert put({"notify_kind": "webhook"}).json()["detail"]["code"] == "invalid_url"
    assert put({"notify_kind": "webhook", "notify_url": "https://example.com/hook"}).status_code == 200
    assert put({"notify_kind": "telegram"}).json()["detail"]["code"] == "invalid_chat_id"
