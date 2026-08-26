"""Onboarding (first profile) + profile editing + account deletion
(the GDPR right-to-erasure endpoint — see packages/db/crud.delete_user)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from apps.web.auth_utils import SESSION_COOKIE_NAME
from apps.web.deps import get_current_user
from packages.db.crud import (
    accept_privacy_policy,
    create_profile,
    delete_user,
    get_profiles_for_user,
    update_profile,
)
from packages.db.session import get_session

router = APIRouter()
templates = Jinja2Templates(directory="apps/web/templates")


def _split_roles(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _split_skills(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


@router.get("/onboarding")
async def onboarding_form(request: Request, session: AsyncSession = Depends(get_session)):
    user = await get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request, "profile_form.html", {"user": user, "profile": None, "is_onboarding": True}
    )


@router.post("/onboarding")
async def onboarding_submit(
    request: Request,
    session: AsyncSession = Depends(get_session),
    candidate_name: str = Form(...),
    education: str = Form(""),
    location: str = Form("France"),
    country_code: str = Form("FR"),
    target_roles: str = Form(...),
    skills: str = Form(""),
    min_salary_hourly_eur: str = Form(""),
    notification_email: str = Form(...),
    accept_privacy: str = Form(...),
):
    user = await get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)

    await accept_privacy_policy(session, user)
    await create_profile(
        session,
        user_id=user.id,
        candidate_name=candidate_name,
        education=education,
        location=location,
        country_code=country_code.upper()[:2],
        target_roles=_split_roles(target_roles),
        skills=_split_skills(skills),
        min_salary_hourly_eur=float(min_salary_hourly_eur) if min_salary_hourly_eur else None,
        notification_email=notification_email,
        languages={"English": "Native"},
    )
    await session.commit()
    return RedirectResponse("/dashboard?flash=Profile+created.+Run+your+first+search+below.", status_code=303)


@router.get("/profile")
async def profile_edit_form(request: Request, session: AsyncSession = Depends(get_session)):
    user = await get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    profiles = await get_profiles_for_user(session, user.id)
    if not profiles:
        return RedirectResponse("/onboarding", status_code=303)
    return templates.TemplateResponse(
        request, "profile_form.html", {"user": user, "profile": profiles[0], "is_onboarding": False}
    )


@router.post("/profile")
async def profile_edit_submit(
    request: Request,
    session: AsyncSession = Depends(get_session),
    candidate_name: str = Form(...),
    education: str = Form(""),
    location: str = Form("France"),
    country_code: str = Form("FR"),
    target_roles: str = Form(...),
    skills: str = Form(""),
    min_salary_hourly_eur: str = Form(""),
    notification_email: str = Form(...),
):
    user = await get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    profiles = await get_profiles_for_user(session, user.id)
    if not profiles:
        return RedirectResponse("/onboarding", status_code=303)

    await update_profile(
        session, profiles[0],
        candidate_name=candidate_name, education=education, location=location,
        country_code=country_code.upper()[:2], target_roles=_split_roles(target_roles),
        skills=_split_skills(skills),
        min_salary_hourly_eur=float(min_salary_hourly_eur) if min_salary_hourly_eur else None,
        notification_email=notification_email,
    )
    await session.commit()
    return RedirectResponse("/dashboard?flash=Profile+updated.", status_code=303)


@router.get("/settings/delete-account")
async def delete_account_confirm(request: Request, session: AsyncSession = Depends(get_session)):
    user = await get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "delete_account.html", {"user": user})


@router.post("/settings/delete-account")
async def delete_account_submit(request: Request, session: AsyncSession = Depends(get_session)):
    user = await get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)
    await delete_user(session, user)
    await session.commit()
    response = RedirectResponse("/login?flash=Your+account+has+been+deleted.", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response
