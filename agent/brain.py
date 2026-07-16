"""Bedrock agentic loop. The model sees data and decides; it never executes.

Flow: model calls get_context, reasons, then submit_plan. The reading slot is
chosen by index into code-computed candidates, so an invalid time can't exist.
"""

import json
import logging
import os

import boto3

log = logging.getLogger()

MODEL_ID = os.environ.get("MODEL_ID", "amazon.nova-lite-v1:0")
MAX_TURNS = 8

SYSTEM = {
    "morning": (
        "You are Dayrunly, a personal morning agent for one user in Tbilisi. "
        "Call get_context first. Then choose the best candidate slot for reading the news "
        "(prefer a relaxed gap, not right before a meeting), write a one-line teaser of the "
        "most interesting stories (plain text, never links), a warm 2-3 sentence summary of "
        "the day ahead weaving in weather and workload, and extra alerts only if something "
        "genuinely needs attention. Finish by calling submit_plan exactly once."
    ),
    "evening": (
        "You are Dayrunly, a personal evening agent for one user in Tbilisi. "
        "Call get_context first. Then write a calm 2-3 sentence preview of tomorrow "
        "(first commitment, overall shape of the day, weather) and extra alerts only if "
        "something genuinely needs attention. Finish by calling submit_plan exactly once."
    ),
}


def _tools(mode):
    props = {
        "summary": {"type": "string", "description": "2-3 sentence overview for the email"},
        "alerts": {"type": "array", "items": {"type": "string"},
                   "description": "extra warnings; empty if none"},
    }
    required = ["summary"]
    if mode == "morning":
        props["slot_index"] = {"type": "integer",
                               "description": "index of the chosen reading slot from candidate_slots"}
        props["teaser"] = {"type": "string",
                           "description": "one-line news teaser, plain text, no links"}
        required += ["slot_index", "teaser"]
    return {"tools": [
        {"toolSpec": {"name": "get_context",
                      "description": "Everything known about the day: agenda, weather, habits, news.",
                      "inputSchema": {"json": {"type": "object", "properties": {}}}}},
        {"toolSpec": {"name": "submit_plan",
                      "description": "Submit the final plan. Call exactly once, after get_context.",
                      "inputSchema": {"json": {"type": "object", "properties": props,
                                               "required": required}}}},
    ]}


def _result(tool_use, content, error=False):
    block = {"toolUseId": tool_use["toolUseId"], "content": [{"text": json.dumps(content)}]}
    if error:
        block["status"] = "error"
    return {"toolResult": block}


def run(mode, payload, model_id=None):
    """Drive the tool loop; returns the validated plan dict."""
    client = boto3.client("bedrock-runtime")
    model = model_id or MODEL_ID
    n_slots = len(payload.get("candidate_slots", []))
    messages = [{"role": "user", "content": [{"text": f"Plan my {mode}."}]}]

    for _ in range(MAX_TURNS):
        resp = client.converse(
            modelId=model,
            system=[{"text": SYSTEM[mode]}],
            messages=messages,
            toolConfig=_tools(mode),
            inferenceConfig={"maxTokens": 1200, "temperature": 0.3},
        )
        msg = resp["output"]["message"]
        messages.append(msg)
        tool_uses = [c["toolUse"] for c in msg["content"] if "toolUse" in c]

        if not tool_uses:
            messages.append({"role": "user", "content": [
                {"text": "Use the tools: get_context, then submit_plan."}]})
            continue

        results = []
        for tu in tool_uses:
            if tu["name"] == "get_context":
                results.append(_result(tu, payload))
            elif tu["name"] == "submit_plan":
                plan = dict(tu["input"])
                if mode == "morning" and n_slots and not (isinstance(plan.get("slot_index"), int)
                                                          and 0 <= plan["slot_index"] < n_slots):
                    results.append(_result(tu, {"error": f"slot_index must be 0..{n_slots - 1}"},
                                           error=True))
                    continue
                if "http" in plan.get("teaser", ""):
                    plan["teaser"] = plan["teaser"].split("http")[0].strip()
                plan["alerts"] = plan.get("alerts") or []
                log.info(json.dumps({"msg": "plan accepted", "model": model, "plan": plan}))
                return plan
        messages.append({"role": "user", "content": results})

    raise RuntimeError(f"no plan after {MAX_TURNS} turns")
