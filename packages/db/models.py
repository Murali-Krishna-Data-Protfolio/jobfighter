"""
SQLAlchemy 2.0 (async) models — the multi-tenant schema from
docs/architecture.md §Multi-Tenant Data Model.

Two deliberately separate concerns, both live here as tables but with a
hard line between them:
  - PRIVATE data (users, candidate_profiles, tracked_jobs, runs) — deleting
    a user cascades through candidate_profiles -> tracked_jobs -> runs.
    This cascade IS the GDPR right-to-erasure mechanism (see delete_user()
    in packages/db/crud.py) — required from M2 per the "real public
    product" decision, not deferred hardening.
  - SHARED/PUBLIC data (job_postings) — a mirror of the git-versioned
    public archive (docs/architecture.md §Output Layer). Never deleted by
    a user's account deletion; not personal data.

UUIDs are stored as 36-char strings rather than a Postgres-native UUID
type, and JSON columns use SQLAlchemy's generic JSON (not JSONB) — both
choices keep this schema portable between SQLite (local dev, no
Docker/Postgres required to run M2 locally) and Postgres (production
target per docs/architecture.md). No Postgres-only column types anywhere.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    is_active: Mapped[bool] = mapped_column(default=True)
    privacy_policy_accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    profiles: Mapped[list["CandidateProfile"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    tracked_jobs: Mapped[list["TrackedJob"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    profile_name: Mapped[str] = mapped_column(String(120), default="Default")
    candidate_name: Mapped[str] = mapped_column(String(200))
    education: Mapped[str] = mapped_column(String(300), default="")
    location: Mapped[str] = mapped_column(String(120), default="France")
    country_code: Mapped[str] = mapped_column(String(2), default="FR")
    languages: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    min_salary_hourly_eur: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    target_roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    notification_email: Mapped[str] = mapped_column(String(320))

    schedule_cron: Mapped[str] = mapped_column(String(60), default="0 8 * * *")  # daily 08:00
    timezone: Mapped[str] = mapped_column(String(60), default="Europe/Paris")
    is_active: Mapped[bool] = mapped_column(default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user: Mapped["User"] = relationship(back_populates="profiles")
    runs: Mapped[list["Run"]] = relationship(back_populates="profile", cascade="all, delete-orphan")

    def to_pipeline_dict(self) -> dict[str, Any]:
        """Adapt this row into the plain dict shape packages/core/pipeline.py
        expects (the same shape profiles/*.json used in M1) — this is what
        keeps run_pipeline_for_user() itself unchanged between M1 and M2."""
        return {
            "profile_id": self.id,
            "candidate_name": self.candidate_name,
            "education": self.education,
            "location": self.location,
            "country_code": self.country_code,
            "languages": self.languages,
            "min_salary_hourly_eur": self.min_salary_hourly_eur,
            "target_roles": self.target_roles,
            "skills": self.skills,
            "notification_email": self.notification_email,
        }


class JobPosting(Base):
    """SHARED/PUBLIC data — mirrors the git-versioned archive. Never tied
    to a user_id, never touched by account deletion."""

    __tablename__ = "job_postings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(200))
    location: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(1000))
    description: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(60))
    search_query: Mapped[str] = mapped_column(String(120), default="")

    score: Mapped[float] = mapped_column(Float)
    description_is_english: Mapped[bool] = mapped_column(default=False)
    requires_fluent_english: Mapped[bool] = mapped_column(default=False)
    link_status: Mapped[str] = mapped_column(String(20), default="unconfirmed")

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    tracked_by: Mapped[list["TrackedJob"]] = relationship(back_populates="posting")


class TrackedJob(Base):
    """THE private, per-user data — created only when a user explicitly
    saves a posting, never auto-populated for every fetch result."""

    __tablename__ = "tracked_jobs"
    __table_args__ = (UniqueConstraint("user_id", "job_posting_id", name="uq_user_posting"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_posting_id: Mapped[str] = mapped_column(ForeignKey("job_postings.id"), index=True)

    status: Mapped[str] = mapped_column(String(20), default="Saved")
    notes: Mapped[str] = mapped_column(Text, default="")
    status_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped["User"] = relationship(back_populates="tracked_jobs")
    posting: Mapped["JobPosting"] = relationship(back_populates="tracked_by")


class Run(Base):
    """Audit history of one pipeline execution — populated by both the
    manual-trigger endpoint (M2) and the scheduler (M3)."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    profile_id: Mapped[str] = mapped_column(ForeignKey("candidate_profiles.id", ondelete="CASCADE"), index=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="success")

    jobs_fetched: Mapped[int] = mapped_column(default=0)
    jobs_scored_kept: Mapped[int] = mapped_column(default=0)
    jobs_discarded: Mapped[int] = mapped_column(default=0)
    dead_links_dropped: Mapped[int] = mapped_column(default=0)
    error_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    profile: Mapped["CandidateProfile"] = relationship(back_populates="runs")


class MagicLinkToken(Base):
    """Single-use login tokens. Not strictly required if tokens are
    stateless (itsdangerous-signed + expiry, see apps/web/auth_utils.py),
    but tracked here so a token can be explicitly invalidated after first
    use even within its expiry window — closes the replay window a purely
    stateless signed token would otherwise leave open."""

    __tablename__ = "magic_link_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
