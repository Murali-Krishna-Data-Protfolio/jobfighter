"""
Adzuna source — official free API, covers APEC/Monster France/Cadremploi/
RegionsJob and 10+ more French boards under one endpoint.

Ported from the single-user tool's job_fetcher.py:_fetch_adzuna, same field
mapping and salary formatting, adapted to async httpx and the new
NormalizedJob/JobSource contract.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from packages.core.models import NormalizedJob, make_job_id
from packages.sources.base import JobSource
from packages.sources.registry import register_source

ADZUNA_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"


@register_source("adzuna")
class AdzunaSource(JobSource):
    """config: {"app_id": ..., "app_key": ..., "max_days_old": 14}"""

    async def fetch(self, query: str, location: str, country_code: str) -> list[dict[str, Any]]:
        app_id = self.config.get("app_id")
        app_key = self.config.get("app_key")
        if not (app_id and app_key):
            return []

        url = ADZUNA_URL.format(country=country_code.lower())
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": 20,
            "what": query,
            "where": location,
            "content-type": "application/json",
            "sort_by": "date",
            "max_days_old": self.config.get("max_days_old", 14),
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(url, params=params)
            if r.status_code != 200:
                return []
            data = r.json()
            return data.get("results", [])
        except (httpx.HTTPError, ValueError):
            # Network/JSON errors here must not take down the whole fetch
            # step for other sources — return empty, let the caller move on.
            return []

    def normalize(self, raw: dict[str, Any], query: str) -> NormalizedJob:
        company = (raw.get("company") or {}).get("display_name", "")
        location = (raw.get("location") or {}).get("display_name", "France")

        salary_min = raw.get("salary_min")
        salary_max = raw.get("salary_max")
        salary: str | None = None
        if salary_min and salary_max:
            salary = f"{int(salary_min):,}–{int(salary_max):,} EUR"
        elif salary_min:
            salary = f"From {int(salary_min):,} EUR"

        title = str(raw.get("title", "")).strip()
        job_id = str(raw.get("id") or make_job_id(title, company, "adzuna"))

        return NormalizedJob(
            job_id=job_id,
            title=title,
            company=company,
            location=location,
            salary=salary,
            url=raw.get("redirect_url", ""),
            description=(raw.get("description") or "")[:500],
            source="Adzuna",
            search_query=query,
        )

    async def check_rate_limit(self) -> None:
        await asyncio.sleep(0.8)  # same politeness delay as the old tool
