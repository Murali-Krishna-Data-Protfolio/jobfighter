"""
Cron due-ness math for per-profile scheduling (M3), plus the hard
run-frequency cap shared with the manual "Run search now" button (M2).

A profile is "due" when both hold:
  1. its schedule_cron has a scheduled fire time between its last run and
     now, evaluated in the profile's own `timezone` (a plain 5-field
     crontab string is meaningless without a timezone — "daily 08:00"
     must mean 08:00 in Paris for a Paris-based profile, not 08:00 on
     whatever region the host happens to run in).
  2. the hard per-profile run-frequency cap has not already been hit by a
     more recent run.

**Why a hard cap exists at all** (docs/architecture.md's API-budget
note): Adzuna/JSearch keys are shared/global across every tenant, not
per-user — enforce a server-side ceiling (default 1 run/24h) so one
misconfigured `schedule_cron` (or a user mashing "Run search now") can't
exhaust the shared quota for everyone else. Applied identically to both
the scheduler sweep and the manual endpoint via `run_cap_remaining()` —
neither path can be used to bypass it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from croniter import croniter

MIN_RUN_INTERVAL = timedelta(hours=24)


def last_scheduled_fire_time(schedule_cron: str, tz_name: str, now: datetime) -> datetime:
    """The most recent time schedule_cron was due to fire at or before
    `now`, returned as a tz-aware UTC datetime."""
    tz = ZoneInfo(tz_name)
    now_local = now.astimezone(tz)
    prev_local = croniter(schedule_cron, now_local).get_prev(datetime)
    return prev_local.astimezone(dt_timezone.utc)


def run_cap_remaining(last_run_started_at: datetime | None, now: datetime | None = None) -> timedelta | None:
    """None if a run is allowed right now; otherwise how much longer the
    caller must wait before the hard cap clears."""
    now = now or datetime.now(dt_timezone.utc)
    if last_run_started_at is None:
        return None
    elapsed = now - last_run_started_at
    if elapsed >= MIN_RUN_INTERVAL:
        return None
    return MIN_RUN_INTERVAL - elapsed


def is_due(
    schedule_cron: str,
    tz_name: str,
    last_run_started_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    """Whether the scheduler sweep should run this profile now."""
    now = now or datetime.now(dt_timezone.utc)
    if run_cap_remaining(last_run_started_at, now) is not None:
        return False
    if last_run_started_at is None:
        return True
    scheduled = last_scheduled_fire_time(schedule_cron, tz_name, now)
    return last_run_started_at < scheduled
