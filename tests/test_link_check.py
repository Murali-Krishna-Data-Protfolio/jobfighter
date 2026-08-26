"""
Regression tests for the link-check asymmetry: only 404/410 are "dead".
403 and network errors are "unconfirmed" and must be KEPT, not discarded —
this is the direct fix for real data loss the first time this check ran
against live corporate career pages (BNP Paribas, Capgemini, Accenture,
Thales, PwC, Sopra Steria, Boston Consulting Group all 403 bots while the
listing was genuinely still live).
"""

import httpx
import pytest
import respx

from packages.scoring.link_check import check_url


@pytest.mark.asyncio
@respx.mock
async def test_200_is_live():
    respx.head("https://example.com/job/1").mock(return_value=httpx.Response(200))
    status, reason = await check_url("https://example.com/job/1")
    assert status == "live"


@pytest.mark.asyncio
@respx.mock
async def test_404_is_dead():
    respx.head("https://example.com/job/gone").mock(return_value=httpx.Response(404))
    status, reason = await check_url("https://example.com/job/gone")
    assert status == "dead"
    assert "404" in reason


@pytest.mark.asyncio
@respx.mock
async def test_410_is_dead():
    respx.head("https://example.com/job/removed").mock(return_value=httpx.Response(410))
    status, reason = await check_url("https://example.com/job/removed")
    assert status == "dead"
    assert "410" in reason


@pytest.mark.asyncio
@respx.mock
async def test_403_is_kept_not_dead():
    """The core regression: a bot-blocked corporate career page must NOT
    be treated as a dead listing."""
    respx.head("https://careers.example-corp.com/job/1").mock(return_value=httpx.Response(403))
    respx.get("https://careers.example-corp.com/job/1").mock(return_value=httpx.Response(403))
    status, reason = await check_url("https://careers.example-corp.com/job/1")
    assert status == "unconfirmed"
    assert status != "dead"


@pytest.mark.asyncio
@respx.mock
async def test_head_not_allowed_falls_back_to_get():
    respx.head("https://example.com/job/2").mock(return_value=httpx.Response(405))
    respx.get("https://example.com/job/2").mock(return_value=httpx.Response(200))
    status, reason = await check_url("https://example.com/job/2")
    assert status == "live"


@pytest.mark.asyncio
@respx.mock
async def test_network_error_is_kept_not_dead():
    respx.head("https://unreachable.example.com/job/1").mock(side_effect=httpx.ConnectError("nope"))
    status, reason = await check_url("https://unreachable.example.com/job/1")
    assert status == "unconfirmed"
    assert status != "dead"


@pytest.mark.asyncio
async def test_malformed_url_is_dead():
    status, reason = await check_url("")
    assert status == "dead"
    status, reason = await check_url("not-a-url")
    assert status == "dead"
