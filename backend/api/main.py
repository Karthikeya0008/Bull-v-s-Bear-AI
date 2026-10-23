"""FastAPI application. Phase 1 exposes only a health check; IPO, metrics and search
endpoints arrive in Phase 2, debate endpoints in Phase 3.

Run with: python -m uvicorn backend.api.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import func, select

from backend.db import session_scope
from backend.knowledge.models import Chunk, Document, Ipo

app = FastAPI(title="Bull vs Bear AI", version="0.1.0")


@app.get("/health")
def health() -> dict:
    """Liveness plus a count of what has been ingested."""
    with session_scope() as s:
        return {
            "status": "ok",
            "ipos": s.scalar(select(func.count()).select_from(Ipo)),
            "documents": s.scalar(select(func.count()).select_from(Document)),
            "chunks": s.scalar(select(func.count()).select_from(Chunk)),
        }
