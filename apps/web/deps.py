"""Shared FastAPI dependencies."""

from __future__ import annotations

from typing import Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.web.auth_utils import SESSION_COOKIE_NAME, verify_session_cookie_value
from packages.db.crud import get_user
from packages.db.models import User
from packages.db.session import get_session  # noqa: F401  (re-exported for router imports)


async def get_current_user(request: Request, session: AsyncSession) -> Optional[User]:
    """Returns the logged-in User, or None. Routes that require auth check
    for None themselves and redirect to /login — kept explicit rather than
    exception-based so the redirect logic lives with the page, not buried
    in a dependency."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    user_id = verify_session_cookie_value(token)
    if not user_id:
        return None
    return await get_user(session, user_id)
