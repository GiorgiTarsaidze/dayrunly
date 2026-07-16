"""Shared config: env vars, cached SSM lookups, timezone."""

import os
from datetime import timedelta, timezone
from functools import lru_cache

import boto3

TZ = timezone(timedelta(hours=4))  # Asia/Tbilisi, no DST
AUDIT_TABLE = os.environ.get("AUDIT_TABLE", "dayrunly-audit")
RUNDOWNLY_TABLE = os.environ.get("RUNDOWNLY_TABLE", "rundownly-main")
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"


@lru_cache(maxsize=None)
def param(name, decrypt=False):
    ssm = boto3.client("ssm")
    return ssm.get_parameter(Name=f"/dayrunly/{name}", WithDecryption=decrypt)["Parameter"]["Value"]


def delivery_email():
    return param("config/email")


def rundownly_url():
    return param("config/rundownly_url")
