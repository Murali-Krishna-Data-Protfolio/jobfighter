"""Renders legal/*.md directly — one source of truth, no content drift
between the drafts reviewers see and what's actually shown in the app."""

from __future__ import annotations

from pathlib import Path

import markdown
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from apps.web.deps import get_current_user
from packages.db.session import get_session

router = APIRouter()
templates = Jinja2Templates(directory="apps/web/templates")
LEGAL_DIR = Path(__file__).resolve().parent.parent.parent.parent / "legal"


async def _render(request: Request, session: AsyncSession, filename: str, title: str):
    user = await get_current_user(request, session)
    md_text = (LEGAL_DIR / filename).read_text(encoding="utf-8")
    html = markdown.markdown(md_text)
    return templates.TemplateResponse(
        request, "legal.html", {"user": user, "page_title": title, "content_html": html}
    )


@router.get("/privacy")
async def privacy(request: Request, session: AsyncSession = Depends(get_session)):
    return await _render(request, session, "privacy-policy.md", "Privacy Policy")


@router.get("/terms")
async def terms(request: Request, session: AsyncSession = Depends(get_session)):
    return await _render(request, session, "terms-of-service.md", "Terms of Service")
