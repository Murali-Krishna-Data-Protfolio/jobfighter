# JobFighter (M1)

A multi-tenant, English-only job tracker — currently at **M1**: the core
pipeline, proven end-to-end via CLI, no web app / auth / database yet.
See [docs/architecture.md](docs/architecture.md) for the full multi-tenant
SaaS plan (M1–M4).

## What M1 does

Fetches jobs (Adzuna), filters to France, classifies each one for
English-workplace fit with Claude (fail-closed — see below), checks that
its apply link still resolves, and writes the result to Excel. Every kept
job is appended to a local JSONL store (`outputs/<profile>/tracked_jobs.jsonl`)
so re-runs only classify genuinely new jobs — this file format is the same
one planned for the M3 git-versioned public archive.

## Scoring

Replaces the old single-confidence model with two explicit, independently
checked facts about the posting:

| description is English | fluent English required | Score |
|---|---|---|
| yes | yes | **1.0** |
| yes | no | **0.5** |
| no | — | discarded, never stored |

**Fail-closed**: any classification error discards the job — it is never
guessed in. **Link check is asymmetric on purpose**: only HTTP 404/410 mean
"dead"; 403 (common bot-blocking on corporate career sites) and network
errors are kept as "unconfirmed," not silently dropped. Both properties are
covered by regression tests in `tests/` — see the module docstrings in
`packages/scoring/classifier.py` and `packages/scoring/link_check.py` for
why.

## Quickstart

```bash
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
copy .env.example .env    # fill in ANTHROPIC_API_KEY, ADZUNA_APP_ID, ADZUNA_APP_KEY
copy profiles\example.json profiles\<your_id>.json   # fill in your details
```
Set `ACTIVE_PROFILE=<your_id>` in `.env`, then:
```bash
python cli/job_tracker_cli.py
```
Output: `outputs/<your_id>/job_applications.xlsx` (+ `tracked_jobs.jsonl`).

## Tests

```bash
python -m pytest tests/ -v
```

## Project layout

```
packages/
  core/       pipeline.py (run_pipeline_for_user — the one reusable entrypoint), models.py
  sources/    JobSource plugin architecture — base.py, registry.py, adzuna.py
  scoring/    classifier.py, prompt.py, link_check.py
  outputs/    excel_export.py, jsonl_store.py
cli/          M1 entrypoint
tests/        regression tests for the two correctness-critical properties above
docs/         architecture.md — the full M1–M4 plan
legal/        privacy policy / ToS drafts — NOT legal advice, need real review before real users (M2+)
```

`packages/*` has no web-framework code — the same `run_pipeline_for_user()`
this CLI calls is what the M2+ scheduler and web app will call too.
