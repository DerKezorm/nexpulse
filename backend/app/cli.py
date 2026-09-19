"""Werkzeuge fuer die Kommandozeile.

``python -m app.cli remove-password`` schaltet das Passwort ab, falls es
vergessen wurde. Im Container: ``docker exec nexpulse python -m app.cli remove-password``.
"""

from __future__ import annotations

import sys

from .db import SessionLocal, init_db
from .services import settings_service


def remove_password() -> None:
    init_db()
    with SessionLocal() as db:
        settings_service.save(db, {"password_hash": ""})
    print("Password removed. nexpulse is open again until you set a new one.")


def main(argv: list[str]) -> int:
    if argv[:1] == ["remove-password"]:
        remove_password()
        return 0
    print("Usage: python -m app.cli remove-password")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
