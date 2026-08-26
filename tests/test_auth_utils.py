"""
Regression tests for magic-link auth: a token must work exactly once, and
a tampered/unknown token must never verify — manually confirmed during M2
development against the running app; codified here so it can't regress.
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.web.auth_utils import create_magic_link_token, verify_and_consume_magic_link_token
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


async def test_valid_token_verifies_once(session):
    token = await create_magic_link_token(session, "alice@test.com")
    await session.commit()

    email = await verify_and_consume_magic_link_token(session, token)
    await session.commit()
    assert email == "alice@test.com"


async def test_token_cannot_be_reused(session):
    """The core regression: forwarding/leaking a login link URL must only
    grant one login, not repeated access until expiry."""
    token = await create_magic_link_token(session, "alice@test.com")
    await session.commit()

    first = await verify_and_consume_magic_link_token(session, token)
    await session.commit()
    assert first == "alice@test.com"

    second = await verify_and_consume_magic_link_token(session, token)
    assert second is None


async def test_unknown_token_never_verifies(session):
    assert await verify_and_consume_magic_link_token(session, "not-a-real-token") is None


async def test_token_from_different_secret_is_rejected(session):
    """A tampered/forged token (wrong signature) must fail — this is what
    itsdangerous's signing actually buys over a plain random string."""
    real = await create_magic_link_token(session, "alice@test.com")
    await session.commit()
    tampered = real[:-1] + ("a" if real[-1] != "a" else "b")
    assert await verify_and_consume_magic_link_token(session, tampered) is None
