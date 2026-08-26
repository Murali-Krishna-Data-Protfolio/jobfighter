"""FastAPI app factory — mounts routers, static files, loads .env.

Run locally:
    uvicorn apps.web.main:app --reload
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env", override=True)
except ImportError:
    pass

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from apps.web.routers import auth, dashboard, export, legal, profile

app = FastAPI(title="JobFighter")
app.mount("/static", StaticFiles(directory="apps/web/static"), name="static")

app.include_router(auth.router)
app.include_router(profile.router)
app.include_router(dashboard.router)
app.include_router(export.router)
app.include_router(legal.router)
