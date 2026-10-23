"""Tags an eigenen LibreSpeed- und iperf3-Servern, und welche Server ein Zeitplan damit meint.

Wunsch aus Issue #6: Wer Dutzende eigene Server hat, will einen Zeitplan nicht Server fuer
Server einstellen, sondern "alle mit JP" oder "alle mit office und Pro" sagen.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from . import settings_service

#: Nur eigene Server tragen Tags: Die oeffentlichen kommen jedes Mal frisch aus einer Liste.
SOURCES = ("librespeed", "iperf3")
MAX_TAGS = 12
MAX_LENGTH = 32


def clean(values: list[str]) -> list[str]:
    """Leerraum weg, doppelte weg (ohne Ruecksicht auf Gross und Klein), hoechstens ``MAX_TAGS``."""
    found: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = " ".join(str(value).split())[:MAX_LENGTH]
        if not tag or tag.casefold() in seen:
            continue
        seen.add(tag.casefold())
        found.append(tag)
    return found[:MAX_TAGS]


def _own_servers(db: Session, source: str) -> list[tuple[str, list[str]]]:
    """Kennung und Tags jedes eigenen Servers, in der Reihenfolge der Liste."""
    # Erst hier importiert: Die Quellen lesen ihre Ziele aus ``settings_service``.
    from .engines import iperf3, librespeed

    settings = settings_service.load(db)
    if source == "iperf3":
        items: list[dict[str, Any]] = settings["iperf3_servers"]
        return [(target.id, target.tags) for target in iperf3.parse_targets(items)]
    if source == "librespeed":
        return [
            (librespeed.own_id(str(item["base"])), clean(item.get("tags") or []))
            for item in settings["librespeed_servers"]
            if item.get("base")
        ]
    return []


def matching(db: Session, source: str, wanted: list[str], match: str = "any") -> list[str]:
    """Die eigenen Server, die die Tags tragen: mit ``any`` einen davon, mit ``all`` jeden."""
    want = {tag.casefold() for tag in clean(wanted)}
    if not want:
        return []
    found = []
    for server_id, server_tags in _own_servers(db, source):
        have = {tag.casefold() for tag in server_tags}
        if (want <= have) if match == "all" else (want & have):
            found.append(server_id)
    return found
