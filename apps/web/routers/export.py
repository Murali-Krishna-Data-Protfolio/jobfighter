"""On-demand Excel export — generated fresh from the DB on every request,
never from a persisted workbook (see packages/outputs/excel_export.py's
docstring for why that matters)."""

from __future__ import annotations

import io

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from apps.web.deps import get_current_user
from packages.core.models import NormalizedJob, ScoreResult, ScoredJob
from packages.db.crud import get_tracked_jobs_for_user
from packages.db.session import get_session
from packages.outputs.excel_export import write_excel

router = APIRouter()


@router.get("/export/xlsx")
async def export_xlsx(request: Request, session: AsyncSession = Depends(get_session)):
    user = await get_current_user(request, session)
    if not user:
        return RedirectResponse("/login", status_code=303)

    tracked = await get_tracked_jobs_for_user(session, user.id)
    scored_jobs = [
        ScoredJob(
            job=NormalizedJob(
                job_id=t.posting.job_id, title=t.posting.title, company=t.posting.company,
                location=t.posting.location, url=t.posting.url, description=t.posting.description,
                source=t.posting.source, search_query=t.posting.search_query,
            ),
            result=ScoreResult(
                description_is_english=t.posting.description_is_english,
                requires_fluent_english=t.posting.requires_fluent_english,
                score=t.posting.score, link_status=t.posting.link_status,
            ),
            date_seen=t.added_at.date(),
            status=t.status,
        )
        for t in tracked
    ]

    # write_excel() saves to a path (same function the CLI uses); write to
    # a throwaway temp file and stream its bytes back rather than touching
    # any persisted/shared file — nothing else ever reads this path.
    import tempfile
    from pathlib import Path

    buffer = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_path = Path(tmp_dir) / "job_applications.xlsx"
        write_excel(scored_jobs, out_path)
        data = out_path.read_bytes()

    buffer.write(data)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=job_applications.xlsx"},
    )
