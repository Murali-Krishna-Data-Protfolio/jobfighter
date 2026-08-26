"""
Link validity check — asymmetric on purpose.

Only 404 (not found) and 410 (gone) are treated as confirmed-dead. A 403 is
deliberately NOT treated as dead: plenty of large employers front their
career sites with bot-protection that 403s any automated request whether or
not the listing is still live — confirmed empirically against the old
single-user tool's real data (BNP Paribas, Capgemini, Accenture, Thales,
PwC, Sopra Steria, Boston Consulting Group all did this while their
listings were still genuinely open). Treating 403 as dead deleted real,
live jobs the first time this check was run for real. Network errors and
any other unexpected status are likewise inconclusive, not proof — silently
dropping a real job is worse than occasionally keeping one stale link.
"""

from __future__ import annotations

import httpx

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
}


async def check_url(url: str, timeout: float = 10.0) -> tuple[str, str]:
    """Returns (link_status, reason) where link_status is one of
    'live' | 'unconfirmed' | 'dead'."""
    if not url or not url.startswith("http"):
        return "dead", "missing or malformed URL"

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            r = await client.head(url, headers=HEADERS)
            if r.status_code in (405, 403):
                r2 = await client.get(url, headers=HEADERS)
                r = r2

        if r.status_code in (404, 410):
            return "dead", f"HTTP {r.status_code}"
        if r.status_code == 403:
            return "unconfirmed", "HTTP 403 (bot-blocked, treated as still live)"
        if 200 <= r.status_code < 400:
            return "live", f"HTTP {r.status_code}"
        return "unconfirmed", f"HTTP {r.status_code} (inconclusive)"
    except httpx.HTTPError as e:
        return "unconfirmed", f"unreachable ({type(e).__name__})"
