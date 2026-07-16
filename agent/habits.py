"""Habit engine: pure functions, no AWS, no AI.

Config shape (stored in the audit table as config#habits):
  {"habit_titles": ["Gym", "Sleep"], "sleep": {"start": "01:00", "end": "08:30"}}
Sleep defines the waking window; free slots never touch sleep or habits.
"""

from datetime import datetime, time, timedelta

from .settings import TZ

MIN_SLOT_MIN = 15


def _hhmm(s):
    h, m = s.split(":")
    return time(int(h), int(m))


def simplify(raw_events):
    """Google API events -> flat dicts the rest of the engine understands."""
    out = []
    for e in raw_events:
        all_day = "date" in e.get("start", {})
        if all_day:
            start = datetime.fromisoformat(e["start"]["date"]).replace(tzinfo=TZ)
            end = datetime.fromisoformat(e["end"]["date"]).replace(tzinfo=TZ)
        else:
            start = datetime.fromisoformat(e["start"]["dateTime"]).astimezone(TZ)
            end = datetime.fromisoformat(e["end"]["dateTime"]).astimezone(TZ)
        out.append({
            "id": e.get("id"),
            "title": e.get("summary", "(no title)"),
            "start": start,
            "end": end,
            "all_day": all_day,
            "is_dayrunly": bool(e.get("extendedProperties", {}).get("private", {}).get("dayrunly")),
        })
    return sorted(out, key=lambda x: x["start"])


def is_habit(title, config):
    return title.strip().casefold() in {t.casefold() for t in config["habit_titles"]}


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def waking_window(date, config):
    """Planning window for a date: sleep end -> next sleep start."""
    s, e = _hhmm(config["sleep"]["start"]), _hhmm(config["sleep"]["end"])
    wake = datetime.combine(date, e, tzinfo=TZ)
    bed_day = date if s > e else date + timedelta(days=1)
    bed = datetime.combine(bed_day, s, tzinfo=TZ)
    return wake, bed


def free_slots(events, date, config, min_minutes=MIN_SLOT_MIN):
    """Gaps inside the waking window not taken by any timed event."""
    wake, bed = waking_window(date, config)
    busy = sorted((e["start"], e["end"]) for e in events if not e["all_day"])
    slots, cursor = [], wake
    for start, end in busy:
        if start > cursor:
            slots.append((cursor, min(start, bed)))
        cursor = max(cursor, end)
        if cursor >= bed:
            break
    if cursor < bed:
        slots.append((cursor, bed))
    return [(s, e) for s, e in slots if (e - s) >= timedelta(minutes=min_minutes)]


def pick_slot(slots, duration_min, not_before=None):
    """First slot that fits the duration (optionally after a given time)."""
    need = timedelta(minutes=duration_min)
    for start, end in slots:
        if not_before and end <= not_before:
            continue
        begin = max(start, not_before) if not_before else start
        if end - begin >= need:
            return begin, begin + need
    return None


def find_collisions(events, config):
    """Habit events overlapped by ordinary timed events."""
    habits = [e for e in events if not e["all_day"] and is_habit(e["title"], config)]
    others = [e for e in events if not e["all_day"] and not is_habit(e["title"], config) and not e["is_dayrunly"]]
    return [(h, o) for h in habits for o in others
            if _overlaps(h["start"], h["end"], o["start"], o["end"])]


def events_in_sleep(events, date, config):
    """Ordinary events that intrude into the sleep window around this date."""
    s, e = _hhmm(config["sleep"]["start"]), _hhmm(config["sleep"]["end"])
    bed_day = date + timedelta(days=1) if s < e else date
    sleep_start = datetime.combine(bed_day, s, tzinfo=TZ)
    sleep_end = datetime.combine(bed_day, e, tzinfo=TZ)
    return [ev for ev in events
            if not ev["all_day"] and not is_habit(ev["title"], config) and not ev["is_dayrunly"]
            and _overlaps(ev["start"], ev["end"], sleep_start, sleep_end)]


def reschedule_slot(habit, events, date, config):
    """Nearest free slot today that fits the collided habit's duration."""
    duration = int((habit["end"] - habit["start"]).total_seconds() // 60)
    slots = free_slots(events, date, config, min_minutes=min(duration, MIN_SLOT_MIN))
    return pick_slot(slots, duration, not_before=habit["start"])
