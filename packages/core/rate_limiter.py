"""
Process-wide, per-source_type token-bucket rate limiter.

Adzuna/JSearch API keys are shared/global across every tenant (see
docs/architecture.md's API-budget note), so one bad actor or bug on one
profile's run must not be able to exhaust the shared quota for everyone
else. This is enforced centrally in pipeline.py's _fetch_all(), not inside
each JobSource — one code path, so both the M2 manual "Run search now"
button and the M3 scheduler sweep get the same protection for free, and a
new source type is covered automatically without editing this file.

In-process only (module-level state) — correct for the current
single-process design (docs/architecture.md: "In-process ... through
M3"). A multi-process deployment would need a shared store (Redis)
instead, which is exactly the RQ+Redis migration trigger M4 already
anticipates — do not try to make this cross-process now.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import defaultdict, deque

_DEFAULT_MAX_CALLS = 60
_DEFAULT_PERIOD_SECONDS = 60.0

_buckets: dict[str, deque[float]] = defaultdict(deque)
_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


def _limit_for(source_type: str) -> tuple[int, float]:
    """RATE_LIMIT_<SOURCE_TYPE>_MAX_CALLS / _PERIOD_SECONDS env overrides,
    falling back to a conservative shared default."""
    prefix = f"RATE_LIMIT_{source_type.upper()}_"
    max_calls = int(os.environ.get(f"{prefix}MAX_CALLS", _DEFAULT_MAX_CALLS))
    period_seconds = float(os.environ.get(f"{prefix}PERIOD_SECONDS", _DEFAULT_PERIOD_SECONDS))
    return max_calls, period_seconds


async def acquire(source_type: str) -> None:
    """Block until a call slot is free under this source_type's shared
    quota. Sliding-window token bucket: at most max_calls calls in any
    period_seconds window, across every concurrent profile run in this
    process. Holding the lock across the (short) sleep is deliberate — it
    serializes waiters in arrival order rather than letting them all wake
    up and race for the same freed slot."""
    max_calls, period_seconds = _limit_for(source_type)
    lock = _locks[source_type]
    async with lock:
        window = _buckets[source_type]
        while True:
            now = time.monotonic()
            while window and now - window[0] >= period_seconds:
                window.popleft()
            if len(window) < max_calls:
                window.append(now)
                return
            await asyncio.sleep(max(period_seconds - (now - window[0]), 0.05))


def reset() -> None:
    """Test-only: clear all bucket state between test cases."""
    _buckets.clear()
