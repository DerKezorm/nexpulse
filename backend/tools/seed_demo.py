"""Beispieldaten fuer die Entwicklung und fuer Bildschirmfotos.

Legt 30 Tage erfundener Messungen alle zwei Stunden an, dazu zwei Zeitplaene
und einen Tarif. Nur fuer ein Wegwerf-Datenverzeichnis gedacht:

    NEXPULSE_DATA_DIR=data-dev python tools/seed_demo.py
"""

from __future__ import annotations

import random
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import delete  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Result, Schedule, utcnow  # noqa: E402
from app.services import settings_service  # noqa: E402
from app.services.scheduler import reschedule  # noqa: E402


def main() -> None:
    init_db()
    rng = random.Random(42)
    now = utcnow().replace(minute=0, second=0, microsecond=0)
    with SessionLocal() as db:
        db.execute(delete(Result))
        db.execute(delete(Schedule))
        for step in range(360, 0, -1):
            started = now - timedelta(hours=2 * step)
            hour = (started.hour + 2) % 24
            evening = 0.72 + rng.random() * 0.15 if 19 <= hour <= 23 else 0.9 + rng.random() * 0.1
            dip = 0.35 if 100 < step < 106 else 1.0
            source = "librespeed" if hour == 5 else "cloudflare"
            failed = rng.random() < 0.01
            result = Result(
                started_at=started,
                finished_at=started + timedelta(seconds=25),
                source=source,
                trigger="schedule",
                status="failed" if failed else "ok",
                error_code="unreachable" if failed else "",
            )
            if not failed:
                result.download_mbps = 1000 * evening * dip * (0.93 + rng.random() * 0.05)
                result.upload_mbps = 50 * (0.9 + rng.random() * 0.08) * (0.6 if dip < 1 else 1)
                result.ping_ms = (15 if 19 <= hour <= 23 else 10) + rng.random() * 4 + (25 if dip < 1 else 0)
                result.jitter_ms = 1 + rng.random() * 2 + (8 if dip < 1 else 0)
                result.ping_low_ms = result.ping_ms - 1.5
                result.ping_high_ms = result.ping_ms + 4
                result.loaded_down_ms = result.ping_ms + 12 + rng.random() * 10
                result.loaded_up_ms = result.ping_ms + 40 + rng.random() * 20
                result.server_name = "Cloudflare" if source == "cloudflare" else "Frankfurt, Germany (Example)"
                result.server_location = "FRA · DE" if source == "cloudflare" else "Frankfurt, Germany"
                result.isp = "Example Broadband"
                result.external_ip = "203.0.113.24"
                result.below_plan = result.download_mbps < 750 or result.upload_mbps < 37.5
            db.add(result)
        for name, mode, interval, source in (
            ("Regular check", "interval", 120, "cloudflare"),
            ("Night test", "daily", 0, "librespeed"),
        ):
            schedule = Schedule(
                name=name, mode=mode, interval_minutes=interval or 120, daily_time="05:00", source=source, random_offset=True
            )
            reschedule(db, schedule)
            db.add(schedule)
        db.commit()
        settings_service.save(db, {"plan_down": 1000, "plan_up": 50, "timezone": "Europe/Berlin"})
    print("Demo data written.")


if __name__ == "__main__":
    main()
