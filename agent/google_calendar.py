"""Minimal Google Calendar client for Dayrunly.

Deterministic tool layer: the LLM never calls Google directly — this code does.
Stdlib HTTP only; boto3 is used solely to read OAuth credentials from SSM.
Calendar ID is always "primary" so no account identifiers appear in code.
"""

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import boto3

SSM_PREFIX = "/dayrunly/google/"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/calendar/v3"
CALENDAR_ID = "primary"
TIMEZONE = "Asia/Tbilisi"
TZ = timezone(timedelta(hours=4))  # Asia/Tbilisi, no DST
# Marker in extendedProperties so Dayrunly can find its own events (idempotency)
DAYRUNLY_PROP = "dayrunly"


@lru_cache(maxsize=1)
def _google_creds():
    ssm = boto3.client("ssm")
    resp = ssm.get_parameters(
        Names=[SSM_PREFIX + n for n in ("client_id", "client_secret", "refresh_token")],
        WithDecryption=True,
    )
    if resp.get("InvalidParameters"):
        raise RuntimeError(f"Missing SSM parameters: {resp['InvalidParameters']}")
    return {p["Name"].rsplit("/", 1)[-1]: p["Value"] for p in resp["Parameters"]}


def get_access_token():
    creds = _google_creds()
    body = urllib.parse.urlencode({
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body)) as resp:
        return json.load(resp)["access_token"]


def _request(method, path, token, body=None, params=None):
    url = f"{API_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def day_bounds(date_iso):
    """('2026-07-16') -> RFC3339 start/end of that day in Tbilisi time."""
    start = datetime.fromisoformat(date_iso).replace(tzinfo=TZ)
    return start.isoformat(), (start + timedelta(days=1)).isoformat()


def list_events(date_iso, token=None):
    """All events overlapping the given local date, expanded and time-ordered."""
    token = token or get_access_token()
    time_min, time_max = day_bounds(date_iso)
    items, page_token = [], None
    while True:
        params = {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": "250",
        }
        if page_token:
            params["pageToken"] = page_token
        resp = _request("GET", f"/calendars/{CALENDAR_ID}/events", token, params=params)
        items.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            return items


def create_event(summary, start_iso, end_iso, description="", marker="1", token=None):
    """Create a [Dayrunly]-marked timed event. start/end are RFC3339 with offset."""
    token = token or get_access_token()
    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_iso, "timeZone": TIMEZONE},
        "end": {"dateTime": end_iso, "timeZone": TIMEZONE},
        "extendedProperties": {"private": {DAYRUNLY_PROP: marker}},
    }
    return _request("POST", f"/calendars/{CALENDAR_ID}/events", token, body=body)


def update_event(event_id, patch, token=None):
    """Patch fields of an existing event (e.g. move: new start/end dicts)."""
    token = token or get_access_token()
    return _request("PATCH", f"/calendars/{CALENDAR_ID}/events/{event_id}", token, body=patch)


def delete_event(event_id, token=None):
    token = token or get_access_token()
    _request("DELETE", f"/calendars/{CALENDAR_ID}/events/{event_id}", token)


def find_dayrunly_events(date_iso, marker=None, token=None):
    """Dayrunly's own events on a date — the idempotency lookup."""
    events = list_events(date_iso, token=token)
    mine = [e for e in events
            if e.get("extendedProperties", {}).get("private", {}).get(DAYRUNLY_PROP)]
    if marker is not None:
        mine = [e for e in mine
                if e["extendedProperties"]["private"][DAYRUNLY_PROP] == marker]
    return mine
