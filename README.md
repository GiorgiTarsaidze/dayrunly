# Dayrunly

**Your day, run for you.** An always-on personal agent built for the AWS Builder Center "Build an Always-On Agent" Weekend Challenge — sibling of [Rundownly](https://github.com/GiorgiTarsaidze/rundownly), last week's challenge app, which now feeds this one.

## Architecture

```mermaid
flowchart TD
    S1["EventBridge Scheduler<br/>09:00 — Morning Brief"] --> L
    S2["EventBridge Scheduler<br/>21:30 — Tomorrow Preview"] --> L
    L["Dayrunly Lambda<br/>(Python 3.13)"] <-->|"agentic loop:<br/>reason → tool calls"| B["Amazon Bedrock<br/>(Nova Lite)"]
    L --> SSM["SSM Parameter Store<br/>Google OAuth + config<br/>(SecureString)"]
    L --> GC["Google Calendar API<br/>read day · create/move<br/>[Dayrunly] events"]
    L --> RD[("DynamoDB<br/>rundownly-main<br/>(read-only: latest rundown)")]
    L --> AU[("DynamoDB<br/>dayrunly-audit<br/>actions log · idempotency · TTL")]
    L --> W["Open-Meteo<br/>weather"]
    L --> SES["Amazon SES<br/>morning brief · preview emails"]
```

No buttons anywhere. Two schedules wake the agent; everything else happens while its owner sleeps.

## What it does

**Morning run (09:00, right after Rundownly publishes at 08:00):**
- Pulls the day's fresh news rundown from Rundownly's DynamoDB table and books a 20-minute *"📰 Read your rundown"* slot into a genuinely free gap, with an AI-written teaser and the link.
- Runs **Habit Guardian**: recurring habits (gym, sleep, reading) are protected. A meeting dropped over the gym slot gets a clearly-labeled `[Dayrunly] Gym (moved)` replacement in the nearest free slot; anything intruding into the sleep window is flagged. Originals are never edited or deleted.
- Emails a **Morning Brief**: friendly AI summary of the day, weather, full agenda, top news topics, habit alerts, and a transparent *"What I did to your calendar today"* action log. Sundays append a weekly recap.

**Evening run (21:30):** a short **Tomorrow Preview** email — first commitment, shape of the day, weather, collision warnings — so problems are fixed before sleep.

## How the agent thinks

The Lambda drives a Bedrock Converse **tool loop**: the model calls `get_context` (agenda, weather, habit analysis, numbered headlines, candidate free slots), reasons, then calls `submit_plan`. Three guardrails inherited from Rundownly:

1. **Deterministic code fetches and mutates; the model only decides.** It never sees credentials and never produces URLs — links are attached by code.
2. **The reading slot is chosen by index** into code-computed free slots, so a hallucinated time physically cannot reach the calendar.
3. **Graceful degradation:** if Bedrock is down, a deterministic fallback still books the reading slot and ships a plain brief marked *(fallback mode)*. A briefing that shows up beats a perfect one that does not.

Every run is idempotent (audit record + extended-property markers on events), so retries never duplicate anything.

## AWS services

| Service | Role |
|---|---|
| EventBridge Scheduler | the two cron triggers (`Asia/Tbilisi`) |
| Lambda (Python 3.13) | the agent runtime |
| Amazon Bedrock (Nova Lite) | the reasoning loop (chosen over Nova Pro in a bake-off: better summaries, ~13× cheaper) |
| DynamoDB | audit log + config (`dayrunly-audit`, TTL 30d); read-only access to Rundownly's digests |
| Amazon SES | email delivery |
| SSM Parameter Store | Google OAuth SecureStrings + personal config (nothing personal lives in this repo) |
| CDK (TypeScript) | all infrastructure as code |

Running cost: roughly **$0.05–0.10/month** — mostly Nova Lite at ~a fifth of a cent per morning.

## Repo layout

```
agent/     Lambda package: handler, Bedrock brain, habit engine, tools
infra/     CDK app (stack, schedules, IAM, table)
scripts/   one-shot OAuth helper + live calendar test
tests/     unit tests for the habit engine
```

## Deploy your own

You need: an AWS account (Bedrock Nova access, an SES-verified email identity) and a Google Cloud project with the Calendar API enabled and an OAuth *Desktop app* client.

```bash
# 1. Google refresh token (calendar scope only) -> SSM SecureStrings /dayrunly/google/*
python3 scripts/get_refresh_token.py client_secret.json --push-ssm

# 2. Personal config
aws ssm put-parameter --name /dayrunly/config/email --type String --value you@example.com
# optional news source link:
aws ssm put-parameter --name /dayrunly/config/rundownly_url --type String --value https://your-news-app

# 3. Deploy
cd infra && npm install && npx cdk deploy
```

Habit config lives in DynamoDB (`pk=config#habits`):

```json
{"habit_titles": ["Sleep", "Gym", "Reading session"], "sleep": {"start": "01:15", "end": "09:15"}}
```

Without a `rundownly-main` table the news section degrades gracefully — the brief still arrives.

## Security notes

- No secrets, emails, account IDs, or personal URLs in this repo — all live in SSM, resolved at deploy/run time.
- Google OAuth scope is **Calendar only**; the agent has no access to mail or anything else.
- Least-privilege IAM: Bedrock limited to Nova models, SES to one identity, DynamoDB read-only on the news table.
- Every resource is tagged `product=dayrunly` for cost tracking.
