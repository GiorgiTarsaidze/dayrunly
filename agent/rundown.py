"""Read-only access to Rundownly's digests. The model never sees URLs."""

from datetime import datetime

import boto3

from . import settings


def get_latest_rundown():
    """Newest digest as plain data: sections with numbered headlines, app link."""
    table = boto3.resource("dynamodb").Table(settings.RUNDOWNLY_TABLE)
    resp = table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("PK").eq("DIGEST"),
        ScanIndexForward=False,
        Limit=1,
    )
    if not resp["Items"]:
        return None

    item = resp["Items"][0]
    created = datetime.fromisoformat(item["createdAt"])
    local_date = created.astimezone(settings.TZ).date()
    today = datetime.now(settings.TZ).date()

    sections = [{
        "topic": s.get("topicName", ""),
        "overview": s.get("overview", ""),
        "headlines": [i.get("title", "") for i in s.get("items", [])],
    } for s in item.get("sections", [])]

    return {
        "date": local_date.isoformat(),
        "is_today": local_date == today,
        "link": settings.rundownly_url(),
        "sections": sections,
        "story_count": sum(len(s["headlines"]) for s in sections),
    }
