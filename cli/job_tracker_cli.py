"""
job_tracker_cli.py — M1 entrypoint.

Runs run_pipeline_for_user() for ONE profile, loaded from profiles/<id>.json
(mirrors the old single-user tool's profile model intentionally — M1's job
is to prove the pipeline logic end to end, not multi-tenancy, which arrives
in M2 with a real Postgres-backed multi-user web app using this exact same
pipeline function).

Usage:
    python cli/job_tracker_cli.py                  # uses ACTIVE_PROFILE from .env, default "example"
    python cli/job_tracker_cli.py --profile murali
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Some terminals default stdout to cp1252, which crashes (not just
# mis-renders) on the accented French text unavoidable in French job
# titles/companies. Never let a print() kill a run.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env", override=True)
except ImportError:
    pass

from packages.core.pipeline import run_pipeline_for_user
from packages.outputs.excel_export import write_excel
from packages.outputs.jsonl_store import append_new, load_existing
from packages.sources.adzuna import AdzunaSource
from packages.sources.base import JobSource


def load_profile(profile_id: str) -> dict:
    path = PROJECT_ROOT / "profiles" / f"{profile_id}.json"
    if not path.exists():
        print(f"[ERROR] Profile not found: {path}")
        print("  Copy profiles/example.json to profiles/<your_id>.json and fill it in.")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_sources() -> list[JobSource]:
    """M1: Adzuna only (the one reliable source proven in the old tool).
    Adding a source here is exactly one line once its class exists in
    packages/sources/ — see registry.py for the extensible version this
    grows into once sources are configured per-profile from the DB."""
    sources: list[JobSource] = []
    if os.environ.get("ADZUNA_APP_ID") and os.environ.get("ADZUNA_APP_KEY"):
        sources.append(AdzunaSource({
            "app_id": os.environ["ADZUNA_APP_ID"],
            "app_key": os.environ["ADZUNA_APP_KEY"],
        }))
    return sources


def banner(text: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)


async def main_async(profile_id: str) -> int:
    start = time.time()
    banner(f"Job Tracker CLI (M1)  |  profile={profile_id}")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key or not api_key.startswith("sk-"):
        print("\n[ERROR] ANTHROPIC_API_KEY not set or invalid — see .env.example.")
        return 1

    profile = load_profile(profile_id)
    sources = build_sources()
    if not sources:
        print("\n[ERROR] No sources configured — set ADZUNA_APP_ID / ADZUNA_APP_KEY in .env.")
        return 1

    jsonl_path = PROJECT_ROOT / "outputs" / profile_id / "tracked_jobs.jsonl"
    xlsx_path = PROJECT_ROOT / "outputs" / profile_id / "job_applications.xlsx"

    print(f"\n[1/4] Loading existing tracked jobs from {jsonl_path}...")
    existing_ids, existing_jobs = load_existing(jsonl_path)
    print(f"  Already tracked: {len(existing_jobs)}")

    print(f"\n[2/4] Running pipeline ({len(sources)} source(s), {len(profile.get('target_roles', []))} queries)...")
    run, new_jobs = await run_pipeline_for_user(
        profile=profile,
        sources=sources,
        existing_job_ids=existing_ids,
        anthropic_api_key=api_key,
    )

    if run.status == "failed":
        print(f"\n[ERROR] Pipeline run failed: {run.error_summary}")
        return 1

    print(f"\n[3/4] Saving results...")
    append_new(jsonl_path, new_jobs)
    all_jobs = existing_jobs + new_jobs
    write_excel(all_jobs, xlsx_path)

    print(f"\n[4/4] Done.")
    elapsed = time.time() - start
    banner("Run Complete")
    print(f"  Jobs fetched          : {run.jobs_fetched}")
    print(f"  New (not yet tracked) : {run.jobs_deduped_new}")
    print(f"  Discarded by scoring  : {run.jobs_discarded}")
    print(f"  Dead links dropped    : {run.dead_links_dropped}")
    print(f"  New jobs kept         : {run.jobs_scored_kept}")
    print(f"  Total tracked         : {len(all_jobs)}")
    print(f"  Excel                 : {xlsx_path}")
    print(f"  JSONL store           : {jsonl_path}")
    print(f"  Elapsed               : {elapsed:.1f}s")
    print()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Job Tracker CLI (M1)")
    parser.add_argument("--profile", default=os.environ.get("ACTIVE_PROFILE", "example"))
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args.profile)))


if __name__ == "__main__":
    main()
