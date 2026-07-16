"""Lambda entrypoint: routes EventBridge Scheduler payloads to the right run."""

import json
import logging
import os

log = logging.getLogger()
log.setLevel(logging.INFO)

DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"


def lambda_handler(event, context):
    run_type = (event or {}).get("run_type", "unknown")
    log.info(json.dumps({"msg": "run started", "run_type": run_type, "dry_run": DRY_RUN}))

    # Filled in by the agent-brain phase; skeleton confirms wiring end to end.
    result = {"run_type": run_type, "dry_run": DRY_RUN, "status": "skeleton-ok"}

    log.info(json.dumps({"msg": "run finished", **result}))
    return result
