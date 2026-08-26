"""
The English-workplace classifier — fail-closed, two-tier scoring.

Carries forward the two hard-won correctness properties from the old
single-user tool's job_fetcher.py (see docs/data-workflow.html / the
job-tracker-english-filter-fix note in that project for the full story):

1. _extract_json_object() uses json.JSONDecoder().raw_decode() instead of
   a regex that only strips a fence at the exact start/end of the string.
   Root cause it fixes: Claude sometimes adds a trailing sentence after the
   closing '}', which broke json.loads() with "Extra data" — raw_decode()
   parses just the first valid object and ignores anything after it.

2. Fail CLOSED: any error (API failure, malformed response, missing
   fields) means the job is discarded — score=None — never stored with a
   guessed value. The old bug was catching the parse error and adding the
   job anyway with a fabricated confidence=0.5; that is exactly what must
   never happen again. One retry is allowed before giving up, so a
   transient hiccup doesn't cost a real English job.
"""

from __future__ import annotations

import json
import re
from typing import Any

import anthropic

from packages.core.models import NormalizedJob, ScoreResult
from packages.scoring.prompt import build_system_prompt

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
MAX_ATTEMPTS = 2


def _extract_json_object(text: str) -> dict[str, Any]:
    """Pull the JSON object out of a Claude response, tolerating markdown
    fences and any commentary before/after the JSON."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
    cleaned = re.sub(r"\n?```$", "", cleaned.strip())
    start = cleaned.find("{")
    if start == -1:
        raise ValueError(f"no JSON object in response: {cleaned[:120]!r}")
    obj, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    return obj


def score_job(description_is_english: bool, requires_fluent_english: bool) -> float | None:
    """The two-tier scoring rule from the confirmed architecture.
    None means discard — never stored."""
    if description_is_english and requires_fluent_english:
        return 1.0
    if description_is_english:
        return 0.5
    return None


class Classifier:
    """One instance per pipeline run (holds the Anthropic client + the
    per-profile cached system prompt, so prompt caching actually pays off
    across every job in the run — same pattern as the old tool's
    profile_cache.get_cached_system_message())."""

    def __init__(self, api_key: str, profile: dict[str, Any]):
        self.client = anthropic.Anthropic(api_key=api_key)
        self._system_block = {
            "type": "text",
            "text": build_system_prompt(profile),
            "cache_control": {"type": "ephemeral"},
        }

    def classify(self, job: NormalizedJob) -> ScoreResult:
        """Fail-closed: returns a ScoreResult with score=None on any error,
        never raises out of here (the pipeline should not crash a whole
        run over one bad job)."""
        job_text = (
            f"Title: {job.title}\n"
            f"Company: {job.company}\n"
            f"Location: {job.location}\n"
            f"Source: {job.source}\n"
            f"Description: {job.description}"
        )

        last_err: Exception | None = None
        for _attempt in range(MAX_ATTEMPTS):
            try:
                resp = self.client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=256,
                    system=[self._system_block],
                    messages=[{"role": "user", "content": job_text}],
                )
                result = _extract_json_object(resp.content[0].text)
                description_is_english = bool(result.get("description_is_english", False))
                requires_fluent_english = bool(result.get("requires_fluent_english", False))
                reason = str(result.get("reason", ""))
                return ScoreResult(
                    description_is_english=description_is_english,
                    requires_fluent_english=requires_fluent_english,
                    reason=reason,
                    score=score_job(description_is_english, requires_fluent_english),
                )
            except Exception as e:  # noqa: BLE001 — intentionally broad, see fail-closed note above
                last_err = e
                continue

        # Both attempts failed: fail closed, never guess.
        return ScoreResult(
            description_is_english=False,
            requires_fluent_english=False,
            reason=f"excluded: classification failed ({last_err})",
            score=None,
        )


def classify_jobs(api_key: str, profile: dict[str, Any], jobs: list[NormalizedJob]) -> list[tuple[NormalizedJob, ScoreResult]]:
    """Classify a batch, returning (job, result) pairs. Callers filter on
    result.score is not None to get the kept set — nothing here silently
    drops the discarded ones, so a caller can still log/inspect them."""
    classifier = Classifier(api_key, profile)
    return [(job, classifier.classify(job)) for job in jobs]
