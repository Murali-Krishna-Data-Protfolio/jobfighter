"""
Regression test for packages/core/rate_limiter.py — the global per-
source_type token bucket that protects the shared Adzuna/JSearch API
quota (docs/architecture.md's API-budget note) across every concurrent
profile run in the M3 scheduler sweep.
"""

import asyncio
import time

import pytest

from packages.core import rate_limiter


@pytest.fixture(autouse=True)
def _reset_buckets(monkeypatch):
    # Isolate each test's quota window and keep the default limit out of
    # the way — every test sets its own via env vars.
    rate_limiter.reset()
    yield
    rate_limiter.reset()


async def test_acquire_allows_up_to_the_limit_immediately(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_TESTSRC_MAX_CALLS", "2")
    monkeypatch.setenv("RATE_LIMIT_TESTSRC_PERIOD_SECONDS", "60")

    start = time.monotonic()
    await rate_limiter.acquire("testsrc")
    await rate_limiter.acquire("testsrc")
    elapsed = time.monotonic() - start

    assert elapsed < 0.5  # both well within the window, no waiting needed


async def test_acquire_blocks_the_call_beyond_the_limit(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_TESTSRC_MAX_CALLS", "1")
    monkeypatch.setenv("RATE_LIMIT_TESTSRC_PERIOD_SECONDS", "0.3")

    await rate_limiter.acquire("testsrc")  # consumes the only slot
    start = time.monotonic()
    await rate_limiter.acquire("testsrc")  # must wait out the window
    elapsed = time.monotonic() - start

    assert elapsed >= 0.2  # allow a little scheduling slack under 0.3s


async def test_different_source_types_have_independent_buckets(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_SRCA_MAX_CALLS", "1")
    monkeypatch.setenv("RATE_LIMIT_SRCA_PERIOD_SECONDS", "60")
    monkeypatch.setenv("RATE_LIMIT_SRCB_MAX_CALLS", "1")
    monkeypatch.setenv("RATE_LIMIT_SRCB_PERIOD_SECONDS", "60")

    await rate_limiter.acquire("srca")  # exhausts srca's bucket only

    start = time.monotonic()
    await rate_limiter.acquire("srcb")  # unaffected by srca's state
    elapsed = time.monotonic() - start

    assert elapsed < 0.5


async def test_concurrent_callers_are_all_eventually_served(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_TESTSRC_MAX_CALLS", "1")
    monkeypatch.setenv("RATE_LIMIT_TESTSRC_PERIOD_SECONDS", "0.2")

    results = []

    async def _caller(n):
        await rate_limiter.acquire("testsrc")
        results.append(n)

    await asyncio.gather(*(_caller(i) for i in range(3)))
    assert sorted(results) == [0, 1, 2]
