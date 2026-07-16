#!/usr/bin/env python3
"""Phase 1.4 verification: exercises the calendar client end-to-end.

Lists today's events, creates a [Dayrunly] test event tonight, verifies it is
findable via the extended-property marker, moves it 15 minutes, then deletes it.

Run from the repo root with AWS credentials exported (SSM access needed):
    python3 scripts/test_calendar.py
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import google_calendar as gcal


def fmt(event):
    start = event["start"].get("dateTime", event["start"].get("date", "?"))
    return f"  {start}  {event.get('summary', '(no title)')}"


def main():
    token = gcal.get_access_token()
    print("Access token obtained (refresh flow works).")

    today = datetime.now(gcal.TZ).date().isoformat()
    events = gcal.list_events(today, token=token)
    print(f"\nEvents today ({today}): {len(events)}")
    for e in events:
        print(fmt(e))

    start = datetime.now(gcal.TZ).replace(microsecond=0) + timedelta(minutes=5)
    end = start + timedelta(minutes=15)
    created = gcal.create_event(
        "[Dayrunly] connectivity test — will self-delete",
        start.isoformat(), end.isoformat(),
        description="Created by scripts/test_calendar.py; deleted automatically.",
        marker="test", token=token,
    )
    print(f"\nCreated test event: {created['id']}\n  {created.get('htmlLink')}")

    found = gcal.find_dayrunly_events(today, marker="test", token=token)
    assert any(e["id"] == created["id"] for e in found), "marker lookup failed"
    print("Marker lookup (idempotency mechanism) works.")

    moved_start = start + timedelta(minutes=15)
    moved_end = end + timedelta(minutes=15)
    gcal.update_event(created["id"], {
        "start": {"dateTime": moved_start.isoformat(), "timeZone": gcal.TIMEZONE},
        "end": {"dateTime": moved_end.isoformat(), "timeZone": gcal.TIMEZONE},
    }, token=token)
    print("Move (patch) works.")

    input("\nCheck your calendar UI now if you like — press Enter to delete the test event... ")
    gcal.delete_event(created["id"], token=token)
    print("Deleted. All Phase 1.4 checks passed.")


if __name__ == "__main__":
    main()
