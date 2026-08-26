"""
Regression test for the GDPR right-to-erasure mechanism: deleting a user
must cascade through candidate_profiles -> tracked_jobs, but must NEVER
touch job_postings (shared public data, not personal to any one user).

Manually verified end-to-end against the running app + a real SQLite file
during M2 development (two test users, real HTTP requests, real cascade) —
this test codifies that same property at the ORM level so it can't
silently regress.
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from packages.core.models import NormalizedJob, ScoreResult, ScoredJob
from packages.db.crud import (
    create_profile,
    delete_user,
    get_or_create_user,
    get_profiles_for_user,
    get_tracked_jobs_for_user,
    track_job,
    upsert_job_posting,
)
from packages.db.models import Base
from sqlalchemy import select
from packages.db.models import JobPosting


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


async def test_delete_user_cascades_private_data_only(session):
    user = await get_or_create_user(session, "alice@test.com")
    await create_profile(
        session, user_id=user.id, candidate_name="Alice", target_roles=["Data Analyst"],
        skills=[], languages={}, notification_email="alice@test.com",
    )
    scored = ScoredJob(
        job=NormalizedJob(job_id="j1", title="Data Analyst", company="Acme", location="Paris",
                           url="https://example.com/1", source="Adzuna"),
        result=ScoreResult(description_is_english=True, requires_fluent_english=True, score=1.0),
    )
    posting = await upsert_job_posting(session, scored)
    await track_job(session, user.id, posting.id)
    await session.commit()

    # sanity: everything's there before deletion
    assert len(await get_profiles_for_user(session, user.id)) == 1
    assert len(await get_tracked_jobs_for_user(session, user.id)) == 1

    await delete_user(session, user)
    await session.commit()

    # private data gone
    assert await get_profiles_for_user(session, user.id) == []
    assert await get_tracked_jobs_for_user(session, user.id) == []

    # the shared job posting must survive — it is public data, not user data
    remaining_postings = (await session.execute(select(JobPosting))).scalars().all()
    assert len(remaining_postings) == 1
    assert remaining_postings[0].id == posting.id


async def test_second_users_data_untouched_by_first_users_deletion(session):
    alice = await get_or_create_user(session, "alice@test.com")
    bob = await get_or_create_user(session, "bob@test.com")
    await create_profile(session, user_id=bob.id, candidate_name="Bob", target_roles=["Business Analyst"],
                          skills=[], languages={}, notification_email="bob@test.com")
    await session.commit()

    await delete_user(session, alice)
    await session.commit()

    bob_profiles = await get_profiles_for_user(session, bob.id)
    assert len(bob_profiles) == 1
    assert bob_profiles[0].candidate_name == "Bob"
