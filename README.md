# JobFighter (M2)

A multi-tenant, English-only job tracker — at **M2**: real multi-tenant
Postgres/SQLite-backed web app, magic-link auth, privacy/ToS pages, and
GDPR account deletion, on top of the M1 pipeline core. No scheduler yet
(runs are user-triggered) — that's M3. See
[docs/architecture.md](docs/architecture.md) for the full M1–M4 plan.

## What it does

Sign up with just an email (a one-time link logs you in, no password).
Set up a profile — target roles, location, skills — and click "Run search
now" to fetch jobs (Adzuna + JSearch), filter to your country, classify
each one for English-workplace fit with Claude (fail-closed — see below),
and check that its apply link still resolves. Matching jobs show up under
**Latest Matches**; save the ones you want to **My Tracked Jobs**, update
their status, and export to Excel any time.

## Scoring

Two explicit, independently checked facts about the posting, not a single
opaque confidence score:

| description is English | fluent English required | Score |
|---|---|---|
| yes | yes | **1.0** |
| yes | no | **0.5** |
| no | — | discarded, never stored |

**Fail-closed**: any classification error discards the job — it is never
guessed in. **Link check is asymmetric on purpose**: only HTTP 404/410
mean "dead"; 403 (common bot-blocking on corporate career sites) and
network errors are kept as "unconfirmed," not silently dropped. Both
properties — and the account-deletion cascade and magic-link single-use
enforcement below — are covered by regression tests in `tests/`.

## Data model

Two deliberately separate stores (see `docs/architecture.md` for the full
schema): **private** account data (`users`, `candidate_profiles`,
`tracked_jobs`, `runs`) that cascades away completely when you delete your
account, and **shared/public** `job_postings` (the actual job listings —
public data, never deleted by any one user's account deletion, never tied
to a user_id).

## Quickstart

```bash
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
copy .env.example .env    # fill in ANTHROPIC_API_KEY, ADZUNA_APP_ID/KEY, SESSION_SECRET
alembic upgrade head      # creates jobfighter.db (local SQLite) — no Postgres/Docker needed for dev
uvicorn apps.web.main:app --reload
```
Open http://127.0.0.1:8000 — enter your email, and the login link prints
to the server console (set `RESEND_API_KEY` in `.env` for real delivery
instead).

CLI (M1, still works — single profile, no web app):
```bash
copy profiles\example.json profiles\<your_id>.json   # fill in your details
python cli/job_tracker_cli.py --profile <your_id>
```

## Tests

```bash
python -m pytest tests/ -v
```

## Project layout

```
apps/web/       FastAPI app — routers (auth, dashboard, profile, export, legal), Jinja2 templates
packages/
  core/         pipeline.py (run_pipeline_for_user — the one reusable entrypoint), models.py, source_config.py
  sources/      JobSource plugin architecture — base.py, registry.py, adzuna.py, jsearch.py
  scoring/      classifier.py, prompt.py, link_check.py
  outputs/      excel_export.py, jsonl_store.py, email_sender.py
  db/           SQLAlchemy models.py, crud.py, session.py, migrations/ (Alembic)
cli/            M1 entrypoint — still works, single-profile, no web app needed
tests/          regression tests: fail-closed scoring, 403-vs-404 link check,
                magic-link single-use, GDPR delete cascade
docs/           architecture.md — the full M1–M4 plan
legal/          privacy policy / ToS — rendered live at /privacy and /terms;
                NOT legal advice, need real review before real users
```

`packages/*` has no web-framework code — `run_pipeline_for_user()` is
called identically by the CLI and by the web app's `/run` endpoint; the
M3 scheduler will call the exact same function.
