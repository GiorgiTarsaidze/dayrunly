"""SES delivery + HTML templates for the brief and preview emails."""

import logging

import boto3

from . import settings

log = logging.getLogger()

STYLE = "font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1a2e;line-height:1.5"


def send(subject, html):
    email = settings.delivery_email()
    if settings.DRY_RUN:
        log.info(f"DRY_RUN: would send '{subject}' ({len(html)} bytes)")
        return
    boto3.client("ses").send_email(
        Source=f"Dayrunly <{email}>",
        Destination={"ToAddresses": [email]},
        Message={"Subject": {"Data": subject},
                 "Body": {"Html": {"Data": html}}},
    )


def _section(title, inner):
    return (f'<h3 style="margin:22px 0 8px;font-size:15px;color:#16537e;'
            f'border-bottom:1px solid #e0e0e0;padding-bottom:4px">{title}</h3>{inner}')


def _list(items):
    lis = "".join(f'<li style="margin:4px 0">{i}</li>' for i in items)
    return f'<ul style="margin:6px 0;padding-left:20px">{lis}</ul>'


def _page(heading, sub, body):
    return (f'<div style="{STYLE};max-width:600px;margin:0 auto;padding:16px">'
            f'<h2 style="margin:0;font-size:20px">{heading}</h2>'
            f'<p style="margin:4px 0 0;color:#666;font-size:13px">{sub}</p>'
            f'{body}'
            f'<p style="margin-top:28px;color:#999;font-size:12px">— Dayrunly, your day, run for you 🤖</p></div>')


def _alerts(alerts):
    if not alerts:
        return ""
    inner = "".join(f'<p style="margin:6px 0">⚠️ {a}</p>' for a in alerts)
    return (f'<div style="background:#fff3e0;border-left:4px solid #ef6c00;'
            f'padding:8px 12px;margin:14px 0;border-radius:4px">{inner}</div>')


def _agenda(items):
    if not items:
        return "<p>Nothing scheduled — a clean slate.</p>"
    rows = "".join(
        f'<tr><td style="padding:3px 12px 3px 0;color:#16537e;white-space:nowrap;'
        f'font-variant-numeric:tabular-nums">{i["time"]}</td>'
        f'<td style="padding:3px 0">{i["title"]}</td></tr>' for i in items)
    return f'<table style="border-collapse:collapse;font-size:14px">{rows}</table>'


def _rundown(r, teaser):
    if not r:
        return "<p>No rundown available today.</p>"
    when = "Today's rundown" if r["is_today"] else f"Latest rundown (from {r['date']} — today's isn't ready yet)"
    tops = _list(f"<b>{s['topic']}</b>: {s['overview']}" for s in r["sections"] if s["overview"])
    return (f'<p style="margin:6px 0">{teaser}</p>{tops}'
            f'<p><a href="{r["link"]}" style="color:#16537e">📰 {when} — {r["story_count"]} stories →</a></p>')


def brief_html(d):
    body = _alerts(d.get("alerts", []))
    body += _section("Your day at a glance", f'<p style="margin:6px 0">{d["summary"]}</p>'
                     f'<p style="margin:6px 0;color:#555">🌤 {d["weather"]}</p>')
    body += _section("Agenda", _agenda(d["agenda"]))
    body += _section("The news, run down", _rundown(d.get("rundown"), d.get("teaser", "")))
    body += _section("What I did to your calendar today",
                     _list(d["actions"]) if d.get("actions") else "<p>Nothing — your day didn't need me.</p>")
    if d.get("recap"):
        body += _section("Weekly recap", _list(d["recap"]))
    return _page(f'☀️ Morning Brief — {d["date_label"]}', d.get("mode_note", ""), body)


def preview_html(d):
    body = _alerts(d.get("alerts", []))
    body += _section("Tomorrow at a glance", f'<p style="margin:6px 0">{d["summary"]}</p>'
                     f'<p style="margin:6px 0;color:#555">🌤 {d["weather"]}</p>')
    body += _section("Agenda", _agenda(d["agenda"]))
    return _page(f'🌙 Tomorrow Preview — {d["date_label"]}', d.get("mode_note", ""), body)
