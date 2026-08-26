"""
JSearch (RapidAPI) source — covers LinkedIn Jobs + Glassdoor under one API.

Second source, added specifically to prove the plugin registry works with
more than one JobSource: nothing in packages/core or the CLI changed to
add this — only this file plus one line wherever sources get built
(apps/web routers / cli/job_tracker_cli.py's build_sources()).

Ported from the old single-user tool's job_fetcher.py:_fetch_jsearch.
"""

from __future__ import annotations

from typing import Any

import httpx

from packages.core.models import NormalizedJob
from packages.sources.base import JobSource
from packages.sources.registry import register_source

JSEARCH_URL = "https://jsearch.p.rapidapi.com/search"


@register_source("jsearch")
class JSearchSource(JobSource):
    """config: {"rapidapi_key": ...}"""

    async def fetch(self, query: str, location: str, country_code: str) -> list[dict[str, Any]]:
        api_key = self.config.get("rapidapi_key")
        if not api_key:
            return []

        params = {
            "query": f"{query} in {location}",
            "num_pages": "1",
            "language": "en",
            "country": country_code.lower(),
        }
        headers = {"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(JSEARCH_URL, params=params, headers=headers)
            if r.status_code != 200:
                return []
            return r.json().get("data", [])
        except (httpx.HTTPError, ValueError):
            return []

    def normalize(self, raw: dict[str, Any], query: str) -> NormalizedJob:
        smin, smax = raw.get("job_min_salary"), raw.get("job_max_salary")
        scurr = raw.get("job_salary_currency", "EUR")
        salary: str | None = None
        if smin and smax:
            salary = f"{int(smin):,}–{int(smax):,} {scurr}"

        publisher = raw.get("job_publisher", "")  # "LinkedIn", "Glassdoor", ...
        source_label = publisher or "JSearch"
        city = raw.get("job_city", "")
        country = raw.get("job_country", "")

        return NormalizedJob(
            job_id=str(raw.get("job_id", "")),
            title=str(raw.get("job_title", "")).strip(),
            company=str(raw.get("employer_name", "")).strip(),
            location=f"{city}, {country}".strip(", ") or "France",
            salary=salary,
            url=raw.get("job_apply_link") or raw.get("job_google_link", ""),
            description=(raw.get("job_description") or "")[:500],
            source=source_label,
            search_query=query,
        )
