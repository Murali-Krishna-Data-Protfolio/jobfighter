"""
Regression tests for the CRUD helpers the M3 scheduler sweep relies on:
get_active_profiles() must see every tenant's profiles (not scoped to one
user, unlike get_profiles_for_user), and get_latest_run_for_profile()
must return the most recent run — the exact input schedule.is_due() needs.
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.core.models import RunResult
from packages.db.crud import (
    create_profile,
    get_active_profiles,
    get_latest_run_for_profile,
    get_or_create_user,
    save_run,
)
from packages.db.models import Base


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


async def _mkprofile(session, user_id, **overrides):
    fields = dict(candidate_name="Test", target_roles=[], skills=[], languages={},
                  notification_email="t@test.com")
    fields.update(overrides)
    return await create_profile(session, user_id=user_id, **fields)


async def test_active_profiles_span_multiple_users(session):
    alice = await get_or_create_user(session, "alice@test.com")
    bob = await get_or_create_user(session, "bob@test.com")
    await _mkprofile(session, alice.id, candidate_name="Alice")
    await _mkprofile(session, bob.id, candidate_name="Bob")
    await session.commit()

    active = await get_active_profiles(session)
    names = {p.candidate_name for p in active}
    assert names == {"Alice", "Bob"}


async def test_inactive_profiles_excluded_from_sweep(session):
    user = await get_or_create_user(session, "carol@test.com")
    await _mkprofile(session, user.id, candidate_name="Carol", is_active=False)
    await session.commit()

    assert await get_active_profiles(session) == []


async def test_latest_run_is_none_for_a_profile_that_never_ran(session):
    user = await get_or_create_user(session, "dave@test.com")
    profile = await _mkprofile(session, user.id, candidate_name="Dave")
    await session.commit()

    assert await get_latest_run_for_profile(session, profile.id) is None


async def test_latest_run_returns_the_most_recent_of_several(session):
    from datetime import datetime, timedelta, timezone

    user = await get_or_create_user(session, "erin@test.com")
    profile = await _mkprofile(session, user.id, candidate_name="Erin")
    await session.commit()

    t0 = datetime(2026, 8, 20, tzinfo=timezone.utc)
    older = RunResult(profile_id=profile.id, started_at=t0, finished_at=t0)
    newer = RunResult(profile_id=profile.id, started_at=t0 + timedelta(days=1), finished_at=t0 + timedelta(days=1))
    await save_run(session, older)
    await save_run(session, newer)
    await session.commit()

    latest = await get_latest_run_for_profile(session, profile.id)
    # SQLite round-trips DateTime(timezone=True) as a naive value even
    # though it went in tz-aware — compare on the naive wall-clock value,
    # which is what's actually preserved.
    assert latest.started_at.replace(tzinfo=timezone.utc) == newer.started_at
