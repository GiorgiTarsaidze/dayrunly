"""Lambda entrypoint: morning brief and evening preview runs."""

import json
import logging
from datetime import datetime, timedelta

from . import audit, brain, emailer, habits, rundown, settings, weather
from . import google_calendar as gcal

log = logging.getLogger()
log.setLevel(logging.INFO)

READ_MIN = 20
DEFAULT_CFG = {"habit_titles": ["Sleep", "Gym", "Reading session"],
               "sleep": {"start": "01:15", "end": "09:15"}}


def lambda_handler(event, context=None):
    event = event or {}
    run_type = event.get("run_type", "morning")
    today = datetime.now(settings.TZ).date()
    key = audit.run_key(today.isoformat(), run_type)

    if not event.get("force") and audit.already_ran(key):
        log.info(json.dumps({"msg": "skipped", "key": key, "reason": "already ran"}))
        return {"status": "skipped", "key": key}

    result = _morning(today, event) if run_type == "morning" else _evening(today)
    audit.record_run(key, result["actions"], status=result["status"])
    log.info(json.dumps({"msg": "run finished", "key": key, **result}))
    return result


def _gather(date):
    cfg = audit.get_habit_config() or DEFAULT_CFG
    token = gcal.get_access_token()
    events = habits.simplify(gcal.list_events(date.isoformat(), token=token))
    return cfg, token, events


def _agenda(events):
    return [{"time": "all day" if e["all_day"] else e["start"].strftime("%H:%M"),
             "title": e["title"]} for e in events]


def _habit_alerts(events, date, cfg):
    alerts = []
    for habit, other in habits.find_collisions(events, cfg):
        alerts.append(f"'{other['title']}' overlaps your {habit['title']} "
                      f"({habit['start'].strftime('%H:%M')}–{habit['end'].strftime('%H:%M')}).")
    for e in habits.events_in_sleep(events, date, cfg):
        alerts.append(f"'{e['title']}' sits inside your sleep window.")
    return alerts


def _fmt_slot(s, e):
    return f"{s.strftime('%H:%M')}–{e.strftime('%H:%M')}"


def _merge_alerts(habit_alerts, model_alerts):
    """The model tends to echo habit alerts back; keep only genuinely new ones."""
    known = {a.casefold() for a in habit_alerts}
    return habit_alerts + [a for a in model_alerts if a.casefold() not in known]


def _morning(today, event):
    cfg, token, events = _gather(today)
    try:
        r = rundown.get_latest_rundown()
    except Exception:
        log.exception("rundown fetch failed, continuing without it")
        r = None
    try:
        wline = weather.forecast(today.isoformat())["line"]
    except Exception:
        wline = "Forecast unavailable"

    slots = habits.free_slots(events, today, cfg)
    now = datetime.now(settings.TZ)
    candidates = [(max(s, now), max(s, now) + timedelta(minutes=READ_MIN))
                  for s, e in slots if e - max(s, now) >= timedelta(minutes=READ_MIN)][:5]
    habit_alerts = _habit_alerts(events, today, cfg)

    payload = {
        "date": today.isoformat(),
        "weekday": today.strftime("%A"),
        "weather": wline,
        "agenda": _agenda(events),
        "habit_alerts": habit_alerts,
        "candidate_slots": [f"{i}: {_fmt_slot(s, e)}" for i, (s, e) in enumerate(candidates)],
        "news": None if not r else {
            "date": r["date"], "is_today": r["is_today"],
            "topics": [{"topic": s["topic"], "overview": s["overview"],
                        "headlines": s["headlines"]} for s in r["sections"]],
        },
    }

    plan, status = _plan("morning", payload, r)
    actions = []

    # Rundown reading event — idempotent via marker
    if r and candidates:
        slot = candidates[plan["slot_index"]]
        existing = gcal.find_dayrunly_events(today.isoformat(), marker="rundown", token=token)
        if existing:
            actions.append(f"Reading slot already on calendar ({existing[0]['summary']}).")
        elif settings.DRY_RUN:
            actions.append(f"DRY_RUN: would add reading slot {_fmt_slot(*slot)}.")
        else:
            gcal.create_event(
                "[Dayrunly] 📰 Read your rundown",
                slot[0].isoformat(), slot[1].isoformat(),
                description=f"{plan['teaser']}\n\n{r['link']}",
                marker="rundown", token=token,
            )
            actions.append(f"Added a {READ_MIN}-min rundown reading slot at {_fmt_slot(*slot)}.")

    # Habit Guardian — reschedule collided habits (never touches originals)
    for habit, other in habits.find_collisions(events, cfg):
        marker = f"moved:{habit['title'].casefold()}"
        if gcal.find_dayrunly_events(today.isoformat(), marker=marker, token=token):
            continue
        slot = habits.reschedule_slot(habit, events, today, cfg)
        if not slot:
            actions.append(f"Couldn't find a free slot to reschedule {habit['title']} — see alerts.")
        elif settings.DRY_RUN:
            actions.append(f"DRY_RUN: would move {habit['title']} to {_fmt_slot(*slot)}.")
        else:
            gcal.create_event(
                f"[Dayrunly] {habit['title']} (moved)",
                slot[0].isoformat(), slot[1].isoformat(),
                description=f"Original {habit['title']} at "
                            f"{_fmt_slot(habit['start'], habit['end'])} overlaps '{other['title']}'.",
                marker=marker, token=token,
            )
            actions.append(f"Rescheduled {habit['title']} to {_fmt_slot(*slot)} "
                           f"(original overlaps '{other['title']}').")

    data = {
        "date_label": today.strftime("%A, %b %d"),
        "summary": plan["summary"],
        "weather": wline,
        "agenda": _agenda(events),
        "alerts": _merge_alerts(habit_alerts, plan["alerts"]),
        "actions": actions,
        "rundown": r,
        "teaser": plan.get("teaser", ""),
        "mode_note": "(fallback mode)" if status == "fallback" else "",
    }
    if today.weekday() == 6 or event.get("force_recap"):
        data["recap"] = _recap(today)

    emailer.send(f"☀️ Your day, run down — {today.strftime('%b %d')}", emailer.brief_html(data))
    actions.append("Sent the morning brief.")
    return {"status": status, "actions": actions}


def _evening(today):
    tomorrow = today + timedelta(days=1)
    cfg, token, events = _gather(tomorrow)
    try:
        wline = weather.forecast(tomorrow.isoformat())["line"]
    except Exception:
        wline = "Forecast unavailable"

    habit_alerts = _habit_alerts(events, tomorrow, cfg)
    timed = [e for e in events if not e["all_day"]]
    payload = {
        "date": tomorrow.isoformat(),
        "weekday": tomorrow.strftime("%A"),
        "weather": wline,
        "agenda": _agenda(events),
        "habit_alerts": habit_alerts,
        "first_event": None if not timed else
            f"{timed[0]['title']} at {timed[0]['start'].strftime('%H:%M')}",
    }

    plan, status = _plan("evening", payload, None)
    data = {
        "date_label": tomorrow.strftime("%A, %b %d"),
        "summary": plan["summary"],
        "weather": wline,
        "agenda": _agenda(events),
        "alerts": _merge_alerts(habit_alerts, plan["alerts"]),
        "mode_note": "(fallback mode)" if status == "fallback" else "",
    }
    emailer.send(f"🌙 Tomorrow, previewed — {tomorrow.strftime('%b %d')}",
                 emailer.preview_html(data))
    return {"status": status, "actions": ["Sent the tomorrow preview."]}


def _plan(mode, payload, r):
    try:
        return brain.run(mode, payload), "ok"
    except Exception:
        log.exception("brain failed, using deterministic fallback")
        return _fallback(mode, payload, r), "fallback"


def _fallback(mode, payload, r):
    n = len(payload["agenda"])
    plan = {"summary": f"You have {n} event(s) on {payload['weekday']}. {payload['weather']}.",
            "alerts": []}
    if mode == "morning":
        plan["slot_index"] = 0
        heads = [h for t in (r or {"sections": []}).get("sections", []) for h in t["headlines"]]
        plan["teaser"] = " · ".join(heads[:3]) or "Fresh stories are waiting."
    return plan


def _recap(today):
    runs = audit.week_runs(today)
    total_actions = sum(len(r["actions"]) for r in runs)
    moved = sum(1 for r in runs for a in r["actions"] if "Rescheduled" in a)
    return [f"{len(runs)} autonomous runs this week.",
            f"{total_actions} actions taken, {moved} habit(s) protected by rescheduling."]
