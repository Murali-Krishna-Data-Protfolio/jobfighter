"""
Magic-link auth: sign-up and login are the same flow — "enter email,
receive a single-use link, click it, get a session cookie." No password
field exists anywhere in the schema (see packages/db/models.py:User).

Two layers of protection on the link itself:
  1. itsdangerous signs + timestamps the token, so it can't be forged and
     expires on its own (MAGIC_LINK_MAX_AGE) even if never explicitly used.
  2. A hashed copy is tracked in magic_link_tokens (packages/db/models.py)
     and marked used on first verification, closing the replay window a
     purely stateless signed token would otherwise leave open within its
     expiry window — someone forwarding/leaking the link URL only gets one
     use out of it, not repeated logins until expiry.
"""

from __future__ import annotations

import hashlib
import os
import warnings
from datetime import datetime, timezone

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import MagicLinkToken

MAGIC_LINK_MAX_AGE = 15 * 60          # 15 minutes
SESSION_MAX_AGE = 30 * 24 * 60 * 60   # 30 days
SESSION_COOKIE_NAME = "jf_session"

_SESSION_SECRET = os.environ.get("SESSION_SECRET")
if not _SESSION_SECRET:
    warnings.warn(
        "SESSION_SECRET not set — using an insecure dev-only fallback. "
        "Set a real random SESSION_SECRET in .env before deploying.",
        stacklevel=2,
    )
    _SESSION_SECRET = "dev-only-insecure-secret-do-not-use-in-production"

_magic_link_serializer = URLSafeTimedSerializer(_SESSION_SECRET, salt="magic-link")
_session_serializer = URLSafeTimedSerializer(_SESSION_SECRET, salt="session")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_magic_link_token(session: AsyncSession, email: str) -> str:
    """Returns the raw token to embed in the emailed link
    (?token=<this>). A hash of it is stored so it can be invalidated after
    first use."""
    token = _magic_link_serializer.dumps(email)
    row = MagicLinkToken(email=email, token_hash=_hash_token(token))
    session.add(row)
    await session.flush()
    return token


async def verify_and_consume_magic_link_token(session: AsyncSession, token: str) -> str | None:
    """Returns the email if the token is valid, unexpired, and not yet
    used — and marks it used. Returns None otherwise (caller shows a
    generic "link invalid or expired" message either way, never
    distinguishing which failure mode to an attacker)."""
    try:
        email = _magic_link_serializer.loads(token, max_age=MAGIC_LINK_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None

    token_hash = _hash_token(token)
    result = await session.execute(select(MagicLinkToken).where(MagicLinkToken.token_hash == token_hash))
    row = result.scalar_one_or_none()
    if row is None or row.used_at is not None:
        return None

    row.used_at = datetime.now(timezone.utc)
    await session.flush()
    return email


def create_session_cookie_value(user_id: str) -> str:
    return _session_serializer.dumps(user_id)


def verify_session_cookie_value(value: str) -> str | None:
    try:
        return _session_serializer.loads(value, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
