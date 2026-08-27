"""
Regression tests for packages/core/schedule.py — the M3 cron due-ness
math and the hard run-frequency cap shared with the M2 manual "Run
search now" endpoint.
"""

from datetime import datetime, timedelta, timezone

from packages.core.schedule import is_due, last_scheduled_fire_time, run_cap_remaining

UTC = timezone.utc


def _at(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


# ── run_cap_remaining(): the hard 1-run/24h ceiling ─────────────────────────

def test_run_cap_none_when_never_run():
    assert run_cap_remaining(None, now=_at(2026, 8, 27, 12)) is None


def test_run_cap_blocks_within_24h():
    last_run = _at(2026, 8, 27, 0)
    now = _at(2026, 8, 27, 12)  # 12h later
    remaining = run_cap_remaining(last_run, now=now)
    assert remaining == timedelta(hours=12)


def test_run_cap_clears_after_24h():
    last_run = _at(2026, 8, 26, 12)
    now = _at(2026, 8, 27, 12, 1)  # 24h1m later
    assert run_cap_remaining(last_run, now=now) is None


# ── last_scheduled_fire_time(): timezone-aware cron math ────────────────────

def test_last_scheduled_fire_time_respects_profile_timezone():
    # "0 8 * * *" (daily 08:00) in Europe/Paris (UTC+2 in August/DST) is
    # 06:00 UTC — a naive UTC interpretation of the same cron string would
    # get this wrong by the DST offset.
    now = _at(2026, 8, 27, 10)  # 10:00 UTC = 12:00 Paris
    fire = last_scheduled_fire_time("0 8 * * *", "Europe/Paris", now)
    assert fire == _at(2026, 8, 27, 6)


# ── is_due(): combines both rules ───────────────────────────────────────────

def test_is_due_true_for_a_profile_that_has_never_run():
    now = _at(2026, 8, 27, 12)
    assert is_due("0 8 * * *", "Europe/Paris", None, now=now) is True


def test_is_due_false_when_already_run_since_last_scheduled_fire():
    # last fire was 06:00 UTC; profile ran at 07:00 UTC (after it) — not due again yet
    now = _at(2026, 8, 27, 12)
    last_run = _at(2026, 8, 27, 7)
    assert is_due("0 8 * * *", "Europe/Paris", last_run, now=now) is False


def test_is_due_true_when_last_run_predates_the_latest_scheduled_fire():
    # last run was yesterday, well before today's 06:00 UTC fire time
    now = _at(2026, 8, 27, 12)
    last_run = _at(2026, 8, 26, 7)
    assert is_due("0 8 * * *", "Europe/Paris", last_run, now=now) is True


def test_is_due_false_when_hard_cap_not_yet_cleared_even_if_cron_says_due():
    # cron would fire again (next day's 08:00 already passed), but the
    # profile only ran 2h ago — the hard cap wins regardless of schedule_cron.
    now = _at(2026, 8, 27, 12)
    last_run = _at(2026, 8, 27, 10)
    assert is_due("0 8 * * *", "Europe/Paris", last_run, now=now) is False
