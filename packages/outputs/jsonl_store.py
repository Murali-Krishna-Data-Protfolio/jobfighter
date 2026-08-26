"""
Local JSONL persistence for M1 (CLI-only, no database yet).

This is deliberately the *same* file format the confirmed architecture
plans for the M3 git-versioned public archive (one job per line, JSONL —
diff-friendly, append-friendly, no full-file rewrite on every update). In
M1 it doubles as "the database": it's how existing_job_ids gets populated
for dedup across CLI runs. In M2+, this responsibility moves to a real
Postgres query and a separate git-archive commit step — but the file
format carries straight over.
"""

from __future__ import annotations

import json
from pathlib import Path

from packages.core.models import ScoredJob


def load_existing(path: str | Path) -> tuple[set[str], list[ScoredJob]]:
    """Read every previously kept job. Returns (set of job_ids, list of
    ScoredJob) — empty if the file doesn't exist yet (first run)."""
    p = Path(path)
    if not p.exists():
        return set(), []

    ids: set[str] = set()
    jobs: list[ScoredJob] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            sj = ScoredJob.model_validate(json.loads(line))
            ids.add(sj.job.job_id)
            jobs.append(sj)
    return ids, jobs


def append_new(path: str | Path, new_jobs: list[ScoredJob]) -> None:
    """Append newly-kept jobs. Never rewrites existing lines — this is
    additive by construction, the same "rebuild is only ever additive or a
    full regenerate, never an in-place row edit" principle that avoids the
    Excel delete_rows corruption class of bug."""
    if not new_jobs:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        for sj in new_jobs:
            f.write(sj.model_dump_json() + "\n")
