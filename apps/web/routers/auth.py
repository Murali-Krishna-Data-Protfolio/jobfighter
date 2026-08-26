"""Magic-link sign-up/login — the same flow for both, no password anywhere."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from apps.web.auth_utils import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE,
    create_magic_link_token,
    create_session_cookie_value,
    verify_and_consume_magic_link_token,
)
from packages.db.crud import get_or_create_user, get_profiles_for_user
from packages.db.session import get_session
from packages.outputs.email_sender import get_email_backend

router = APIRouter()
templates = Jinja2Templates(directory="apps/web/templates")


@router.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"user": None})


@router.post("/auth/request-link")
async def request_link(request: Request, email: str = Form(...), session: AsyncSession = Depends(get_session)):
    email = email.strip().lower()
    token = await create_magic_link_token(session, email)
    await session.commit()

    base_url = str(request.base_url).rstrip("/")
    link = f"{base_url}/auth/verify?token={token}"
    backend = get_email_backend()
    await backend.send(
        to=email,
        subject="Your JobFighter login link",
        html_body=(
            f"<p>Click to log in (expires in 15 minutes, works once):</p>"
            f'<p><a href="{link}">{link}</a></p>'
        ),
    )
    return templates.TemplateResponse(request, "check_email.html", {"user": None, "email": email})


@router.get("/auth/verify")
async def verify(request: Request, token: str, session: AsyncSession = Depends(get_session)):
    email = await verify_and_consume_magic_link_token(session, token)
    if not email:
        await session.rollback()
        return RedirectResponse("/login?error=That+link+is+invalid+or+expired.+Request+a+new+one.", status_code=303)

    user = await get_or_create_user(session, email)
    await session.commit()

    profiles = await get_profiles_for_user(session, user.id)
    destination = "/dashboard" if profiles else "/onboarding"

    response = RedirectResponse(destination, status_code=303)
    response.set_cookie(
        SESSION_COOKIE_NAME, create_session_cookie_value(user.id),
        max_age=SESSION_MAX_AGE, httponly=True, samesite="lax",
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response
