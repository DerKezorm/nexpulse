"""Welche Quelle hinter welchem Namen steht."""

from __future__ import annotations

from .base import Engine, MeasurementError
from .cloudflare import CloudflareEngine
from .librespeed import LibreSpeedEngine
from .ookla import OoklaEngine

_ENGINES: dict[str, Engine] = {
    "cloudflare": CloudflareEngine(),
    "librespeed": LibreSpeedEngine(),
    "ookla": OoklaEngine(),
}


def engine(source: str) -> Engine:
    try:
        return _ENGINES[source]
    except KeyError as exc:
        raise MeasurementError("unknown_source", source) from exc


def replace(source: str, replacement: Engine) -> Engine:
    """Fuer Tests: eine Quelle gegen eine Attrappe tauschen. Gibt die alte zurueck."""
    previous = _ENGINES[source]
    _ENGINES[source] = replacement
    return previous
