"""Audit log + idempotency + config storage (DynamoDB, TTL 30 days)."""

import json
import time
from datetime import datetime, timedelta

import boto3

from . import settings

TTL_DAYS = 30


def _table():
    return boto3.resource("dynamodb").Table(settings.AUDIT_TABLE)


def run_key(date_iso, run_type):
    return f"run#{date_iso}#{run_type}"


def already_ran(key):
    return "Item" in _table().get_item(Key={"pk": key})


def record_run(key, actions, status="ok"):
    if settings.DRY_RUN:
        return
    _table().put_item(Item={
        "pk": key,
        "at": datetime.now(settings.TZ).isoformat(),
        "status": status,
        "actions": json.dumps(actions),
        "ttl": int(time.time()) + TTL_DAYS * 86400,
    })


def get_habit_config():
    item = _table().get_item(Key={"pk": "config#habits"}).get("Item")
    return json.loads(item["value"]) if item else None


def put_habit_config(config):
    _table().put_item(Item={"pk": "config#habits", "value": json.dumps(config)})


def week_runs(end_date):
    """Run records for the 7 days ending at end_date (for the Sunday recap)."""
    table, out = _table(), []
    for i in range(7):
        day = (end_date - timedelta(days=i)).isoformat()
        for rt in ("morning", "evening"):
            item = table.get_item(Key={"pk": run_key(day, rt)}).get("Item")
            if item:
                out.append({"date": day, "run_type": rt,
                            "actions": json.loads(item.get("actions", "[]"))})
    return out
