"""
Data-access functions. Kept as plain functions (not a repository class
hierarchy) — this is a small enough schema that the extra indirection
wouldn't earn its keep; every function takes an AsyncSession explicitly so
callers (routers, the CLI, the scheduler) control the transaction boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from packages.core.models import RunResult, ScoredJob
from packages.db.models import CandidateProfile, JobPosting, Run, TrackedJob, User


async def get_or_create_user(session: AsyncSession, email: str) -> User:
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(email=email)
        session.add(user)
        await session.flush()
    return user


async def get_user_by_email(session: AsyncSession, email: str) -> Optional[User]:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user(session: AsyncSession, user_id: str) -> Optional[User]:
    return await session.get(User, user_id)


async def accept_privacy_policy(session: AsyncSession, user: User) -> None:
    user.privacy_policy_accepted_at = datetime.now(timezone.utc)
    await session.flush()


async def delete_user(session: AsyncSession, user: User) -> None:
    """The GDPR right-to-erasure mechanism. Deletes the user row; the
    cascade="all, delete-orphan" relationships on User (see
    packages/db/models.py) take care of candidate_profiles -> runs and
    tracked_jobs. JobPosting rows are NEVER touched here — they are shared
    public data, not personal data belonging to this user."""
    await session.delete(user)
    await session.flush()


# ── Candidate profiles ──────────────────────────────────────────────────────

async def create_profile(session: AsyncSession, user_id: str, **fields) -> CandidateProfile:
    profile = CandidateProfile(user_id=user_id, **fields)
    session.add(profile)
    await session.flush()
    return profile


async def get_profiles_for_user(session: AsyncSession, user_id: str) -> list[CandidateProfile]:
    result = await session.execute(select(CandidateProfile).where(CandidateProfile.user_id == user_id))
    return list(result.scalars().all())


async def get_profile(session: AsyncSession, profile_id: str) -> Optional[CandidateProfile]:
    return await session.get(CandidateProfile, profile_id)


async def get_active_profiles(session: AsyncSession) -> list[CandidateProfile]:
    """Every active profile across every user — the scheduler sweep's
    (M3) candidate set. Unlike get_profiles_for_user, deliberately not
    scoped to one user: the sweep has to consider every tenant."""
    result = await session.execute(select(CandidateProfile).where(CandidateProfile.is_active.is_(True)))
    return list(result.scalars().all())


async def update_profile(session: AsyncSession, profile: CandidateProfile, **fields) -> CandidateProfile:
    for key, value in fields.items():
        setattr(profile, key, value)
    await session.flush()
    return profile


# ── Job postings (shared) + tracked jobs (private) ──────────────────────────

async def upsert_job_posting(session: AsyncSession, scored: ScoredJob) -> JobPosting:
    """Insert or refresh the shared JobPosting row for one ScoredJob. Score
    is a property of the job's language, not of any one candidate's fit —
    see docs/architecture.md's note on why job_postings rows are shared
    across every user whose profile happens to surface the same job."""
    result = await session.execute(select(JobPosting).where(JobPosting.job_id == scored.job.job_id))
    posting = result.scalar_one_or_none()
    if posting is None:
        posting = JobPosting(
            job_id=scored.job.job_id,
            title=scored.job.title,
            company=scored.job.company,
            location=scored.job.location,
            url=scored.job.url,
            description=scored.job.description,
            source=scored.job.source,
            search_query=scored.job.search_query,
            score=scored.result.score,
            description_is_english=scored.result.description_is_english,
            requires_fluent_english=scored.result.requires_fluent_english,
            link_status=scored.result.link_status,
        )
        session.add(posting)
    else:
        posting.link_status = scored.result.link_status
        posting.last_seen_at = datetime.now(timezone.utc)
    await session.flush()
    return posting


async def track_job(session: AsyncSession, user_id: str, job_posting_id: str) -> TrackedJob:
    result = await session.execute(
        select(TrackedJob).where(TrackedJob.user_id == user_id, TrackedJob.job_posting_id == job_posting_id)
    )
    tracked = result.scalar_one_or_none()
    if tracked is None:
        tracked = TrackedJob(user_id=user_id, job_posting_id=job_posting_id)
        session.add(tracked)
        await session.flush()
    return tracked


async def get_tracked_jobs_for_user(session: AsyncSession, user_id: str) -> list[TrackedJob]:
    """Eagerly loads .posting — templates read t.posting.* after the
    request's session has closed (Jinja2 rendering happens outside the
    route's async context), so that relationship must already be
    populated in memory or it 500s with a MissingGreenlet error trying to
    lazy-load mid-render."""
    result = await session.execute(
        select(TrackedJob)
        .where(TrackedJob.user_id == user_id)
        .options(selectinload(TrackedJob.posting))
        .order_by(TrackedJob.added_at.desc())
    )
    return list(result.scalars().all())


async def update_tracked_job_status(session: AsyncSession, tracked: TrackedJob, status: str) -> TrackedJob:
    tracked.status = status
    tracked.status_changed_at = datetime.now(timezone.utc)
    await session.flush()
    return tracked


async def get_existing_job_ids(session: AsyncSession) -> set[str]:
    """All job_ids already known globally — used as the dedup set for the
    pipeline's fetch step (mirrors M1's JSONL-backed dedup, now DB-backed)."""
    result = await session.execute(select(JobPosting.job_id))
    return set(result.scalars().all())


# ── Runs ─────────────────────────────────────────────────────────────────────

async def save_run(session: AsyncSession, run: RunResult) -> Run:
    row = Run(
        profile_id=run.profile_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=run.status,
        jobs_fetched=run.jobs_fetched,
        jobs_scored_kept=run.jobs_scored_kept,
        jobs_discarded=run.jobs_discarded,
        dead_links_dropped=run.dead_links_dropped,
        error_summary=run.error_summary,
    )
    session.add(row)
    await session.flush()
    return row


async def get_latest_run_for_profile(session: AsyncSession, profile_id: str) -> Optional[Run]:
    """Most recent run for one profile, or None if it has never run —
    the input to both the scheduler's cron due-ness check and the manual
    "Run search now" endpoint's hard run-frequency cap (see
    packages/core/schedule.py)."""
    result = await session.execute(
        select(Run).where(Run.profile_id == profile_id).order_by(Run.started_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()
