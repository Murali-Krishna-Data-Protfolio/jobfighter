# JobFighter — New Multi-Tenant Repo, Built From Scratch

## Context

The existing tool at `C:\Claude\job_tracker` is a single-user, locally-run script (Task Scheduler + Excel + one hardcoded profile). The user sketched a new target architecture (source fan-in → location filter → two-tier English scoring → fan-out to Excel/Telegraph/git-archive) and asked for a **brand-new, separate git repository**, explicitly "no messy," built to **connect many users and scale** — confirmed as a genuine multi-tenant hosted product for real strangers, not just a personal tool.

This plan carries forward everything that was hard-won and correct in the old tool (fail-closed classification, the 403-is-not-dead link-check asymmetry, rebuild-not-delete Excel writes, UTF-8-safe I/O, profile-driven config) and redesigns everything that was single-user-only (auth, storage, scheduling, hosting, compliance).

**Confirmed decisions** (from user + this session):
1. New, separate repo (`jobfighter`) — no shared history with `job_tracker`.
2. Single hosted multi-tenant service (not "everyone runs their own copy").
3. Real public product for strangers → GDPR-conscious design, privacy policy/ToS, and abuse-resistant shared API quotas are **required from early on**, not deferred hardening.
4. Source layer: extensible plugin architecture; implement Adzuna + JSearch (covers LinkedIn/Glassdoor) now; France Travail low-priority/disabled-by-default; Station F and named company career pages (Allianz/AXA/BD) get a generic Greenhouse/Lever-backed `CareerPageSource`, not bespoke scrapers.
5. Two-tier scoring replaces the old single-confidence model: description-in-English + fluent-English-required → **1.0**; description-in-English only → **0.5**; anything else → **discarded, never stored**.
6. Job postings (public data) are versioned in a **separate** git repo (`jobfighter-data`) as monthly-chunked JSONL, auto-committed after each run — kept entirely separate from private per-user account data in Postgres.
7. Telegraph is **dropped entirely, no replacement** — the web dashboard is the "any browser" view.

---

## Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Backend | **Python + FastAPI** | Reuses all proven Python logic (classifier, Excel writer, source fetchers) directly; async fits concurrent per-user fetch runs. |
| Database | **PostgreSQL** (managed — Render/Neon/Supabase) | Real multi-tenant relational data with concurrent writers; SQLite is wrong here (file locking, ephemeral hosting filesystems). |
| ORM/migrations | **SQLAlchemy 2.0 (async) + Alembic** | Schema evolves over time (new source types, new fields) — migrations, not manual ALTERs. |
| Scheduler | **In-process (APScheduler / cron-triggered sweep) through M3; RQ + Redis only if a real trigger condition is hit (M4+)** | Build the pipeline as one plain async function (`run_pipeline_for_user`) from day one, callable from CLI, scheduler, or a future queue — migration is a deployment change, not a rewrite. RQ over Celery if/when needed: simpler ops surface for a solo maintainer. |
| Auth | **Passwordless magic-link email** | No password storage/hashing/reset flow to secure — smaller attack surface, appropriate given this holds real personal job-search data. |
| Transactional email | **Resend (or Postmark/SES) from day one — NOT Gmail SMTP** | Elevated from the original recommendation: magic-link login is the critical path for real strangers — deliverability failures here mean users literally cannot log in. Gmail SMTP's sending-reputation/quota limits are not acceptable for that path at public-product scale. |
| Frontend | **Server-rendered (Jinja2 + HTMX + Chart.js)**, no SPA | Core need is CRUD + reporting (job table, filters, status, dashboard charts) — a full SPA is unjustified complexity for a solo-maintained tool. |
| Hosting | **Render**, EU region (Frankfurt) | Native Cron Job + Background Worker service types map directly onto the phased build; EU region is the sensible default given the France-focused, EU-user-facing product and GDPR data-residency practicality. |

---

## Multi-Tenant Data Model

Two deliberately separate stores:

**A. Git-versioned public archive** (`jobfighter-data` repo, separate from the app repo) — `archive/YYYY-MM.jsonl`, one row per posting: `job_id, title, company, location, url, description, source, search_query, score, description_is_english, requires_fluent_english, date_seen, date_last_seen`. Monthly chunking from day one (the old tool's Telegraph `CONTENT_TOO_BIG` failure at ~500 rows in one blob is the direct lesson here). Committed/pushed via a dedicated bot identity + scoped deploy key, never the developer's personal credentials. This is public data (job postings), so no personal-data/GDPR concerns attach to this store.

**B. Private Postgres** (all account/personal data — the GDPR-relevant store):
```
users(id, email, created_at, is_active, privacy_policy_accepted_at)
candidate_profiles(id, user_id→users, profile_name, candidate_name, education, location,
                    country_code, languages jsonb, min_salary_hourly_eur,
                    target_roles jsonb, skills jsonb, notification_email,
                    schedule_cron, timezone, is_active, created_at, updated_at)
sources(id, source_type, display_name, config jsonb, is_global, owner_user_id?, enabled)
profile_sources(profile_id→, source_id→)
job_postings(id, job_id unique, title, company, location, url, description, source,
             search_query, score, description_is_english, requires_fluent_english,
             first_seen_at, last_seen_at, link_status)   -- mirrors store A, queryable
tracked_jobs(id, user_id→, job_posting_id→, status, notes, status_changed_at,
             added_at, unique(user_id, job_posting_id))  -- THE private per-user data
runs(id, profile_id→, started_at, finished_at, status, jobs_fetched, jobs_scored,
     jobs_added, error_summary)
```
`job_postings` rows are **shared** across every user who happens to match that job (the score is a property of the job's language, not of a specific candidate) — `tracked_jobs` is the only per-user, private data, created only when a user explicitly saves a job (not auto-populated for every fetch result). Account deletion cascades `candidate_profiles` → `tracked_jobs` → `runs`; it never touches `job_postings` or the git archive (not personal data). This cascade is the concrete mechanism for GDPR right-to-erasure — build it in M2, not deferred.

---

## Source Plugin Architecture

One `JobSource` ABC (`fetch`, `normalize`, `check_rate_limit`) in `packages/sources/base.py`, registered via `@register_source("adzuna")` into a `SOURCE_REGISTRY` dict. Adding a source = one new file, zero pipeline changes.
- **Adzuna, JSearch**: port `job_fetcher.py`'s `_fetch_adzuna`/`_fetch_jsearch` field mappings almost unchanged, wrapped as async (`httpx.AsyncClient`).
- **France Travail**: implement against the real API (not HTML scrape), disabled-by-default per profile — old tool already found ~0 English hits here.
- **Generic `CareerPageSource`**: config-driven (`careers_url`, `ats_platform`, `company_name`), targets Greenhouse/Lever's own public JSON job-board APIs where a company uses one — this is the concrete fix for the exact 403 bot-blocking problem hit repeatedly with direct corporate-ATS scraping (BNP Paribas, Capgemini, Accenture, Thales, PwC, Sopra Steria, BCG all did this to the old tool). Allianz/AXA/BD/Station F: check for a Greenhouse/Lever backend first; if none exists, treat as **not automatable in this plan** — documented, not bespoke-scraped.

**API budget note (elevated because this is a public product):** Adzuna/JSearch keys are shared/global across all tenants, not per-user. Enforce a **global token-bucket rate limiter per source_type** plus a **hard per-profile run-frequency cap** (server-enforced, e.g. max 1 scheduled run/24h regardless of what a user sets), so one bad actor or bug can't exhaust the shared quota for everyone. Build this in M2/M3, not as later hardening.

---

## Filter/Scoring Engine

Claude response schema (replaces old `is_english_role`+confidence):
```json
{"description_is_english": true, "requires_fluent_english": false, "reason": "..."}
```
```python
def score_job(description_is_english, requires_fluent_english) -> float | None:
    if description_is_english and requires_fluent_english: return 1.0
    if description_is_english: return 0.5
    return None  # discarded, never stored
```
**Reuse verbatim, these are correctness-critical, not stylistic:**
- `_extract_json_object`'s `json.JSONDecoder().raw_decode()` approach (survives trailing text after the JSON that broke the old regex-only parser).
- **Fail-closed**: any parse/API error → job discarded, never stored with a guessed score. One retry, then drop.
- Prompt caching (`cache_control: ephemeral`) — same mechanism as `profile_cache.py`, prompt now built per-profile for context in the "reason" field even though scoring itself is profile-independent.
- Claude Haiku — no reason to upgrade for this task.
- `check_url()`/`filter_valid_links()`'s **404/410 = dead, 403/network-errors/other = kept** asymmetry — store as `job_postings.link_status ∈ {live, unconfirmed, dead}`, surfaced in the dashboard rather than silently binary.
- Location (FR) sub-filter applied as a cheap deterministic pre-filter **before** the Claude call — no wasted API spend on out-of-scope jobs.

---

## Scheduler & Multi-Tenant Isolation

- `candidate_profiles.schedule_cron` + `timezone` per profile (default daily 08:00 local).
- M1–M3: in-process/cron-triggered sweep queries due profiles, runs `run_pipeline_for_user(profile_id)` with bounded concurrency (`asyncio.Semaphore`).
- **Per-user failure isolation is structural**: each run opens its own DB session/transaction, wrapped in try/except writing a `runs` row (`status='failed'`, `error_summary`) on error, then continues — one user's bad API key or malformed response can never block or corrupt another's run. This directly avoids the old tool's monolithic-`main()` failure mode.
- Migrate to RQ+Redis only when the scheduling window is actually observed to overrun, or per-job retry-with-backoff is actually needed — not speculatively.

---

## Output Layer

- **Excel export**: on-demand `GET /export/xlsx`, generated fresh from `tracked_jobs` each request — reuses `excel_writer.py`'s Jobs+Dashboard structure and (critically) the *rebuild-from-scratch* pattern, which is moot-by-construction here since nothing is incrementally mutated anymore.
- **Git archive**: pipeline step after scoring — upsert into `jobfighter-data`, monthly JSONL files, commit message `"run {run_id}: +{n_new} jobs, {n_updated} link updates — {date}"`, push via bot deploy key.
- **No Telegraph, no share-link** (per decision) — dashboard is the only "browser view."
- **Email digest**: port the existing HTML template structure (gradient header/KPI row/breakdown tables) into Jinja2, sent via the transactional provider, triggered per-user-run by the scheduler. CTA links back into the web dashboard.

---

## Repo Structure

```
jobfighter/
├── apps/web/                 # FastAPI: routers (auth, dashboard, profile, export, internal), Jinja2 templates
├── packages/
│   ├── core/                 # pipeline.py: run_pipeline_for_user() — the one reusable entrypoint
│   ├── sources/               # base.py, registry.py, adzuna.py, jsearch.py, france_travail.py, career_page.py
│   ├── scoring/                # classifier.py (ported _extract_json_object), prompt.py, link_check.py
│   ├── outputs/                 # excel_export.py, git_archive.py, email_digest.py
│   └── db/                       # models.py, session.py, migrations/ (Alembic)
├── scheduler/run_due_profiles.py
├── cli/job_tracker_cli.py     # M1 entrypoint, kept for local dev/debugging after M1
├── tests/                      # test_scoring.py (fail-closed edge cases), test_link_check.py (403-vs-404), test_pipeline.py
├── legal/                      # privacy-policy.md, terms-of-service.md — STARTING DRAFTS, need real review before real users
├── Dockerfile, render.yaml, alembic.ini, pyproject.toml, .env.example, README.md

jobfighter-data/               # SEPARATE repo — archive/*.jsonl only, no app code, no user data
```

`packages/*` has zero HTTP-framework code — CLI, scheduler, and web app all import the same pipeline, which is what keeps M1's CLI build directly reusable rather than thrown away.

---

## Phased Build Plan

Each phase is independently demonstrable.

- **M1 — Core pipeline, one source (Adzuna), scoring engine, CLI only, no web/auth/multi-tenant DB.** Prove the fail-closed JSON extraction and 403-vs-404 link logic with unit tests here first. Demo: CLI run → correctly scored Excel file, one profile, live data.
- **M2 — Postgres schema + multi-tenant web dashboard + magic-link auth (via transactional email) + privacy policy/ToS pages + account-deletion cascade.** Pipeline still manually triggered. Add JSearch as second source (proves plugin registry). GDPR-relevant pieces (consent checkbox at signup, deletion cascade, `legal/` pages) land **here**, not deferred — required given "real public product." Demo: two independent test users, isolated data, manual run, Excel export each.
- **M3 — Scheduler + real multi-tenant isolation + git archive + global rate limiter/per-profile run cap.** Demo: 24h+ unattended run across several seeded profiles on different schedules; confirm per-user isolation on an induced failure; confirm real git-archive commits with sensible diffs.
- **M4 — Remaining sources (France Travail, generic CareerPageSource) + email digest wiring + hardening pass (structured logging/error monitoring, auth-endpoint rate limiting, RQ/Redis only if the M3 data shows it's actually needed).**

---

## Open Items for the User (not blocking the plan, but worth a decision before/during the relevant phase)

- Confirm Render (EU/Frankfurt) as the hosting target, or name a preference.
- Confirm 1:1 user↔profile is fine for v1 (schema already supports multiple profiles per user later without a breaking change).
- If Allianz/AXA/BD specifically (not just "some multinational") matter, confirm whether the Greenhouse/Lever-only `CareerPageSource` limitation (§ Source Plugin Architecture) is acceptable, or whether bespoke scraping for those three is wanted despite the fragility.
- `legal/` privacy policy & ToS drafts are a starting point only — get them reviewed before onboarding real users; this plan cannot provide legal advice.

---

## Critical Files to Port From (reference, `C:\Claude\job_tracker`)

- `src/job_fetcher.py` — `_extract_json_object` (fail-closed JSON parsing), `check_url`/`filter_valid_links` (403-vs-404 asymmetry), Adzuna/JSearch fetch+normalize mappings.
- `src/excel_writer.py` — Jobs+Dashboard sheet structure, `rewrite_jobs_sheet` rebuild pattern.
- `src/profile_cache.py` — prompt-caching system-message pattern, adapt for the two-boolean scoring schema.
- `profiles/murali.json`, `profiles/example.json` — field set to extend into `candidate_profiles`.
- `src/job_tracker.py` — email HTML template structure and step sequencing, restructured into `run_pipeline_for_user()`.

---

## Verification (end-to-end, per phase)

- **M1**: `python cli/job_tracker_cli.py` → inspect the produced `.xlsx` for correct scores (1.0/0.5) and confirm zero rows exist that failed classification (fail-closed proof). Run `pytest tests/test_scoring.py tests/test_link_check.py` — both must cover the exact regression cases from the old tool (trailing-text-after-JSON parses correctly; a 403 response is kept, a 404 is dropped).
- **M2**: sign up two test accounts via magic link (confirm email actually arrives, not just logs to console), confirm each sees only their own `tracked_jobs`, confirm account deletion actually removes `candidate_profiles`/`tracked_jobs` and leaves `job_postings` untouched, confirm Excel export downloads correctly.
- **M3**: seed 3-5 profiles with different `schedule_cron`, leave running 24h+, check `runs` table for accurate per-run status, check `jobfighter-data` repo for real commits, deliberately break one profile's config and confirm the others still ran.
- **M4**: confirm France Travail and CareerPageSource sources register and (if enabled) fetch without errors; confirm digest emails render correctly and arrive via the transactional provider; load-test the rate limiter against the shared API quota.
