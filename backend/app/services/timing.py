"""Wann ein Zeitplan das naechste Mal misst.

Alle Zeiten eines Zeitplans meinen die Ortszeit des Betreibers (Einstellung
"Zeitzone"). Gespeichert und verglichen wird in UTC. Eine Sommerzeit-Umstellung
verschiebt deshalb nichts: 04:00 bleibt 04:00 an der Wanduhr.

Drei Arten:

- ``interval``: alle n Minuten, ausgerichtet an Mitternacht. "Alle 2 Stunden"
  heisst 00:00, 02:00, 04:00 und nicht "2 Stunden nach dem Speichern".
- ``daily``: einmal am Tag zur angegebenen Uhrzeit.
- ``cron``: fuenf Felder wie in crontab (Minute, Stunde, Tag, Monat, Wochentag).
- ``random``: n Tests am Tag zu zufaelligen Zeiten. Der Tag (oder das Zeitfenster) wird in
  n gleiche Abschnitte geteilt, in jedem liegt ein Test zu einer zufaelligen Minute. Rein
  zufaellige Zeiten koennten sich ballen und die Abendstunden auslassen; so ist jeder Tag
  anders und trotzdem ganz abgedeckt. Die Zeiten eines Tages werden aus Zeitplan und Datum
  ausgelost und bleiben fest, damit Vorschau und Lauf dasselbe sagen. Zweck: Engpaesse zu
  bestimmten Tageszeiten sichtbar machen, ohne dass immer zur selben Minute gemessen wird.

Wochentage und Zeitfenster gelten fuer ``interval``, ``daily`` und ``random``. Bei ``cron``
steht beides schon im Ausdruck.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


class CronError(ValueError):
    pass


def parse_hhmm(value: str) -> int:
    """ "HH:MM" als Minuten seit Mitternacht."""
    try:
        hours, minutes = value.split(":")
        total = int(hours) * 60 + int(minutes)
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"not a time: {value!r}") from exc
    if not (0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59):
        raise ValueError(f"not a time: {value!r}")
    return total


def _field(text: str, low: int, high: int) -> set[int]:
    values: set[int] = set()
    for part in text.split(","):
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronError(f"bad step in {text!r}")
            step = int(step_text)
        if part == "*":
            start, end = low, high
        elif "-" in part:
            a, b = part.split("-", 1)
            if not (a.isdigit() and b.isdigit()):
                raise CronError(f"bad range in {text!r}")
            start, end = int(a), int(b)
        elif part.isdigit():
            start = end = int(part)
            if step != 1:
                end = high
        else:
            raise CronError(f"bad value in {text!r}")
        if start < low or end > high or start > end:
            raise CronError(f"{text!r} is out of range {low}-{high}")
        values.update(range(start, end + 1, step))
    return values


@dataclass(frozen=True)
class Cron:
    minutes: set[int]
    hours: set[int]
    days: set[int]
    months: set[int]
    weekdays: set[int]  # 0 = Montag, wie datetime.weekday()
    day_restricted: bool
    weekday_restricted: bool

    @classmethod
    def parse(cls, expression: str) -> Cron:
        parts = expression.split()
        if len(parts) != 5:
            raise CronError("a cron expression has five fields")
        cron_weekdays = _field(parts[4], 0, 7)
        # crontab: 0 und 7 sind Sonntag. datetime: Montag ist 0, Sonntag 6.
        weekdays = {(day - 1) % 7 for day in cron_weekdays}
        return cls(
            minutes=_field(parts[0], 0, 59),
            hours=_field(parts[1], 0, 23),
            days=_field(parts[2], 1, 31),
            months=_field(parts[3], 1, 12),
            weekdays=weekdays,
            day_restricted=parts[2] != "*",
            weekday_restricted=parts[4] != "*",
        )

    def day_matches(self, moment: datetime) -> bool:
        if moment.month not in self.months:
            return False
        by_day = moment.day in self.days
        by_weekday = moment.weekday() in self.weekdays
        # Wie crontab: Sind Tag und Wochentag beide eingeschraenkt, reicht einer.
        if self.day_restricted and self.weekday_restricted:
            return by_day or by_weekday
        return by_day and by_weekday

    def next_after(self, after: datetime) -> datetime | None:
        """Naechster Zeitpunkt nach ``after`` (Ortszeit, ohne Sekunden), hoechstens ein Jahr voraus."""
        day = after.replace(hour=0, minute=0, second=0, microsecond=0)
        for _ in range(367):
            if self.day_matches(day):
                for hour in sorted(self.hours):
                    for minute in sorted(self.minutes):
                        candidate = day.replace(hour=hour, minute=minute)
                        if candidate > after:
                            return candidate
            day = (day + timedelta(days=1)).replace(hour=0, minute=0)
        return None


@dataclass(frozen=True)
class Plan:
    """Die zeitlichen Angaben eines Zeitplans, unabhaengig von der Datenbank."""

    mode: str
    interval_minutes: int = 120
    daily_time: str = "04:00"
    cron: str = ""
    days: int = 127
    window_from: str = "00:00"
    window_to: str = "00:00"
    per_day: int = 6
    #: Macht die ausgelosten Zeiten je Zeitplan verschieden. Legt die Oberflaeche beim
    #: Anlegen fest, damit die Vorschau schon vor dem Speichern die echten Zeiten zeigt.
    seed: int = 0


def _window_minutes(plan: Plan) -> list[int]:
    """Alle Minuten des Tages im Zeitfenster, in zeitlicher Reihenfolge ab dessen Beginn."""
    start, end = parse_hhmm(plan.window_from), parse_hhmm(plan.window_to)
    if start == end:
        return list(range(24 * 60))
    if start < end:
        return list(range(start, end + 1))
    return list(range(start, 24 * 60)) + list(range(end + 1))


def random_slots(plan: Plan, day: datetime) -> list[int]:
    """Die ausgelosten Minuten eines Tages, sortiert. Gleicher Plan und Tag, gleiche Zeiten."""
    minutes = _window_minutes(plan)
    count = max(1, min(int(plan.per_day), len(minutes)))
    rng = random.Random(f"{plan.seed}:{day.date().isoformat()}:{count}:{plan.window_from}-{plan.window_to}")
    size = len(minutes) / count
    picked = {minutes[int(index * size + rng.random() * size)] for index in range(count)}
    return sorted(picked)


def _in_window(minute_of_day: int, window_from: str, window_to: str) -> bool:
    start, end = parse_hhmm(window_from), parse_hhmm(window_to)
    if start == end:
        return True
    if start < end:
        return start <= minute_of_day <= end
    # Ueber Mitternacht, etwa 22:00 bis 02:00.
    return minute_of_day >= start or minute_of_day <= end


def _slots_of_day(plan: Plan) -> list[int]:
    if plan.mode == "daily":
        return [parse_hhmm(plan.daily_time)]
    if plan.mode == "random":
        raise ValueError("random slots depend on the day")
    step = max(5, int(plan.interval_minutes))
    return list(range(0, 24 * 60, step))


def next_local(plan: Plan, after: datetime) -> datetime | None:
    """Naechster Termin in Ortszeit, streng nach ``after``."""
    after = after.replace(second=0, microsecond=0)
    if plan.mode == "cron":
        return Cron.parse(plan.cron).next_after(after)
    if not plan.days & 127:
        return None
    if plan.mode != "random":
        fixed = [slot for slot in _slots_of_day(plan) if _in_window(slot, plan.window_from, plan.window_to)]
        if not fixed:
            return None
    day = after.replace(hour=0, minute=0)
    for _ in range(8):
        if plan.days & (1 << day.weekday()):
            # Ein Zeitfenster ueber Mitternacht gehoert beim Auslosen zum Kalendertag: Die
            # Minuten nach Mitternacht zaehlen zum Tag, an dem sie liegen.
            slots = random_slots(plan, day) if plan.mode == "random" else fixed
            for slot in slots:
                # Wanduhrzeit setzen statt Minuten addieren: Ueber eine Zeitumstellung
                # hinweg waere "Mitternacht plus 240 Minuten" sonst 03:00 oder 05:00.
                candidate = day.replace(hour=slot // 60, minute=slot % 60)
                if candidate > after:
                    return candidate
        day = (day + timedelta(days=1)).replace(hour=0, minute=0)
    return None


def next_run(
    plan: Plan, now: datetime, tz: ZoneInfo, random_offset: bool, rng: random.Random | None = None
) -> datetime | None:
    """Naechster Termin in UTC, mit Zufallsversatz von bis zu fuenf Minuten nach Wunsch."""
    local = now.astimezone(tz).replace(tzinfo=None)
    target = next_local(plan, local)
    if target is None:
        return None
    moment = target.replace(tzinfo=tz).astimezone(UTC)
    if random_offset and plan.mode != "random":
        offset = (rng or random).uniform(-300, 300)
        moment = max(moment + timedelta(seconds=offset), now + timedelta(seconds=30))
    return moment


def upcoming(plan: Plan, now: datetime, tz: ZoneInfo, count: int = 5) -> list[datetime]:
    """Die naechsten Termine ohne Versatz, fuer die Vorschau beim Bearbeiten."""
    result: list[datetime] = []
    cursor = now
    for _ in range(count):
        moment = next_run(plan, cursor, tz, random_offset=False)
        if moment is None:
            break
        result.append(moment)
        cursor = moment
    return result
