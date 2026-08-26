"""My Tracked Jobs, Latest Matches, run-now, save/track, status updates."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.web.deps import get_current_user
from packages.core.pipeline import run_pipeline_for_user
from packages.core.source_config import build_sources
from packages.db.crud import (
    get_existing_job_ids,
    get_profiles_for_user,
    get_tracked_jobs_for_user,
    save_run,
    track_job,
    update_tracked_job_status,
    upsert_job_posting,
)
from packages.db.models import JobPosting, TrackedJob
from packages.db.session import get_session
from packages.outputs.excel_export import STATUS_CHOICES

router = APIRouter()
templates = Jinja2Templates(directory="apps/web/templates")


async def _require_user_and_profile(request: Request, session: AsyncSession):
    user = await get_current_user(request, session)
    if not user:
        return None, None
    profiles = await get_profiles_for_user(session, user.id)
    profile = profiles[0] if profiles else None
    return user, profile


@router.get("/")
async def root(request: Request, session: AsyncSession = Depends(get_session)):
    user, profile = await _require_user_and_profile(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/dashboard" if profile else "/onboarding", status_code=303)


@router.get("/dashboard")
async def dashboard(request: Request, session: AsyncSession = Depends(get_session)):
    user, profile = await _require_user_and_profile(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not profile:
        return RedirectResponse("/onboarding", status_code=303)

    tracked = await get_tracked_jobs_for_user(session, user.id)
    return templates.TemplateResponse(
        request, "dashboard.html",
        {"user": user, "profile": profile, "tracked": tracked, "status_choices": STATUS_CHOICES},
    )


@router.get("/matches")
async def matches(request: Request, session: AsyncSession = Depends(get_session)):
    user, profile = await _require_user_and_profile(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not profile:
        return RedirectResponse("/onboarding", status_code=303)

    already_tracked_ids = {t.job_posting_id for t in await get_tracked_jobs_for_user(session, user.id)}

    result = await session.execute(
        select(JobPosting).where(JobPosting.link_status != "dead").order_by(JobPosting.first_seen_at.desc())
    )
    all_postings = list(result.scalars().all())

    target_roles_lower = [r.lower() for r in (profile.target_roles or [])]
    match_list = [
        p for p in all_postings
        if p.id not in already_tracked_ids
        and (not target_roles_lower or any(r in p.title.lower() for r in target_roles_lower))
    ]

    return templates.TemplateResponse(request, "matches.html", {"user": user, "matches": match_list})


@router.post("/run")
async def run_now(request: Request, session: AsyncSession = Depends(get_session)):
    user, profile = await _require_user_and_profile(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not profile:
        return RedirectResponse("/onboarding", status_code=303)

    sources = build_sources()
    if not sources:
        return RedirectResponse("/dashboard?error=No+sources+configured+on+the+server.", status_code=303)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    existing_ids = await get_existing_job_ids(session)

    run_result, scored_jobs = await run_pipeline_for_user(
        profile=profile.to_pipeline_dict(),
        sources=sources,
        existing_job_ids=existing_ids,
        anthropic_api_key=api_key,
    )

    for scored in scored_jobs:
        await upsert_job_posting(session, scored)
    await save_run(session, run_result)
    await session.commit()

    if run_result.status == "failed":
        return RedirectResponse(f"/dashboard?error=Run+failed%3A+{run_result.error_summary}", status_code=303)
    msg = f"Run complete+%E2%80%94+{run_result.jobs_scored_kept}+new+matches+found."
    return RedirectResponse(f"/matches?flash={msg}", status_code=303)


@router.post("/track/{job_posting_id}")
async def track(request: Request, job_posting_id: str, session: AsyncSession = Depends(get_session)):
    user = await get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    await track_job(session, user.id, job_posting_id)
    await session.commit()
    return ""  # HTMX swap target removed — empty body is enough


@router.post("/status/{tracked_job_id}")
async def set_status(
    request: Request, tracked_job_id: str, status: str = Form(...), session: AsyncSession = Depends(get_session)
):
    user = await get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    tracked = await session.get(TrackedJob, tracked_job_id)
    if tracked and tracked.user_id == user.id and status in STATUS_CHOICES:
        await update_tracked_job_status(session, tracked, status)
        await session.commit()
    return ""
