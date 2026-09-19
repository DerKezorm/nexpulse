"""Jede Fehlerkennung, die der Server schickt, braucht einen Satz in beiden Sprachen.

Sonst sieht der Nutzer die englische Rueckfallmeldung oder, bei gespeicherten
Fehlern einer Messung, die rohe Kennung.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
I18N = Path(__file__).resolve().parent.parent.parent / "frontend" / "src" / "i18n"

#: Mit eigenem Satz ausserhalb von errors.byCode (siehe api/client.ts).
SPECIAL = {"internal_error", "too_many_attempts"}

PATTERNS = [
    re.compile(r'fehler\(\s*"([a-z_]+)"'),
    re.compile(r'meldung\(\s*"([a-z_]+)"'),
    re.compile(r'MeasurementError\(\s*"([a-z_]+)"'),
    re.compile(r'NotifyError\(\s*"([a-z_]+)"'),
    re.compile(r'status, code = "[a-z]+", "([a-z_]+)"'),
    re.compile(r'"failed", "([a-z_]+)"'),
    re.compile(r'error_code = "([a-z_]+)"'),
]


def codes_in_code() -> set[str]:
    found: set[str] = set()
    for path in APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in PATTERNS:
            found.update(pattern.findall(text))
    return found


def test_every_code_is_translated() -> None:
    codes = codes_in_code()
    # Bodenschwelle: Findet das Muster nichts mehr, soll der Test nicht still bestehen.
    assert len(codes) > 30
    for language in ("de", "en"):
        by_code = json.loads((I18N / f"{language}.json").read_text(encoding="utf-8"))["errors"]["byCode"]
        missing = sorted(code for code in codes - SPECIAL if code not in by_code)
        assert missing == [], f"{language}.json lacks errors.byCode for {missing}"
