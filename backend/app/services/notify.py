"""Benachrichtigungen nach einer Messung: ntfy, Gotify oder ein Webhook.

Nur wenn etwas auffaellt: Test gescheitert, Tarif unterschritten, Ping zu hoch.
Die Texte sind englisch, wie alles, was nexpulse nach draussen schickt.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..db import SessionLocal
from ..models import Result
from . import settings_service

logger = logging.getLogger("nexpulse.notify")

KINDS = ("ntfy", "gotify", "webhook")


class NotifyError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


def reasons(result: Result, settings: dict[str, Any]) -> list[str]:
    """Warum dieser Test eine Nachricht wert ist. Leer heisst: keine Nachricht."""
    found: list[str] = []
    if result.status == "failed":
        if settings["alert_failed"]:
            found.append("failed")
        return found
    if result.status != "ok":
        return found
    if settings["alert_below_plan"] and result.below_plan:
        found.append("below_plan")
    limit = settings["alert_ping_ms"]
    if settings["alert_ping_enabled"] and limit and result.ping_ms is not None and result.ping_ms > float(limit):
        found.append("ping")
    return found


def compose(result: Result, found: list[str], settings: dict[str, Any]) -> tuple[str, str]:
    if "failed" in found:
        title = "nexpulse: speed test failed"
        body = f"The {result.source} test could not finish ({result.error_code or 'unknown error'})."
        return title, body
    parts = []
    if result.download_mbps is not None:
        parts.append(f"down {result.download_mbps:.0f} Mbit/s")
    if result.upload_mbps is not None:
        parts.append(f"up {result.upload_mbps:.1f} Mbit/s")
    if result.ping_ms is not None:
        parts.append(f"ping {result.ping_ms:.0f} ms")
    lines = [", ".join(parts)]
    if "below_plan" in found:
        lines.append(
            f"Below {settings['threshold_pct']} % of your plan "
            f"({settings['plan_down'] or '-'} / {settings['plan_up'] or '-'} Mbit/s)."
        )
    if "ping" in found:
        lines.append(f"Ping is above {settings['alert_ping_ms']} ms.")
    title = "nexpulse: slow connection" if "below_plan" in found else "nexpulse: high ping"
    return title, "\n".join(lines)


async def send(kind: str, url: str, token: str, title: str, body: str, payload: dict[str, Any]) -> None:
    if kind not in KINDS or not url:
        raise NotifyError("notify_not_configured")
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            if kind == "ntfy":
                headers = {"Title": title, "Tags": "chart_with_downwards_trend"}
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                response = await client.post(url, content=body.encode("utf-8"), headers=headers)
            elif kind == "gotify":
                headers = {"X-Gotify-Key": token} if token else {}
                target = url.rstrip("/") + "/message"
                response = await client.post(
                    target, json={"title": title, "message": body, "priority": 5}, headers=headers
                )
            else:
                headers = {"Authorization": f"Bearer {token}"} if token else {}
                response = await client.post(url, json={"title": title, "message": body, **payload}, headers=headers)
    except httpx.HTTPError as exc:
        raise NotifyError("notify_unreachable", type(exc).__name__) from exc
    if response.status_code >= 400:
        # Nie den Antworttext ins Protokoll: Er kann Zugangsdaten zurueckspiegeln.
        raise NotifyError("notify_rejected", f"HTTP {response.status_code}")


async def after_result(result: Result) -> None:
    with SessionLocal() as db:
        settings = settings_service.load(db)
    found = reasons(result, settings)
    if not found or not settings["notify_kind"] or not settings["notify_url"]:
        return
    from .runner import result_dict

    title, body = compose(result, found, settings)
    try:
        await send(
            settings["notify_kind"],
            settings["notify_url"],
            settings["notify_token"],
            title,
            body,
            {"event": "speedtest." + found[0], "reasons": found, "result": result_dict(result)},
        )
        logger.info("Sent %s notification for test %s (%s)", settings["notify_kind"], result.id, ", ".join(found))
    except NotifyError as exc:
        logger.warning("Notification for test %s failed: %s %s", result.id, exc.code, exc.detail)
