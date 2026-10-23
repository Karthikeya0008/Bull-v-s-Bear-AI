"""FastAPI application.

Run with: python -m uvicorn backend.api.main:app --port 8000
All routes live under ``/api``; the Vite dev server proxies ``/api`` to this app.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from backend.agents.orchestrator import debate_payload, run_debate
from backend.backtest import backtest
from backend.db import session_scope
from backend.knowledge.models import Chunk, Debate, Document, FinancialRow, Ipo, Metric
from backend.metrics.engine import compute_and_store, metric_dict
from backend.retrieval.hybrid import HybridRetriever

app = FastAPI(title="Bull vs Bear AI", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173",
                                                  "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
_retriever: HybridRetriever | None = None


def retriever() -> HybridRetriever:
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever()
    return _retriever


def ipo_dict(i: Ipo, chunks: int = 0, debates: int = 0) -> dict:
    return {"ipo_id": i.ipo_id, "company": i.company, "status": i.status, "sector": i.sector,
            "exchanges": i.exchanges, "price_band_low": i.price_band_low,
            "price_band_high": i.price_band_high, "lot_size": i.lot_size,
            "issue_open": i.issue_open.isoformat() if i.issue_open else None,
            "issue_close": i.issue_close.isoformat() if i.issue_close else None,
            "listing_date": i.listing_date.isoformat() if i.listing_date else None,
            "fresh_issue_cr": i.fresh_issue_cr, "ofs_cr": i.ofs_cr, "nse_symbol": i.nse_symbol,
            "source": i.source, "chunks": chunks, "debates": debates}


@app.get("/api/health")
def health() -> dict:
    """Liveness plus a count of what has been ingested."""
    with session_scope() as s:
        return {"status": "ok",
                "ipos": s.scalar(select(func.count()).select_from(Ipo)),
                "documents": s.scalar(select(func.count()).select_from(Document)),
                "chunks": s.scalar(select(func.count()).select_from(Chunk))}


@app.get("/api/ipos")
def list_ipos(status: str | None = None, analysed_only: bool = False) -> list[dict]:
    """All IPOs in the registry, optionally filtered by status (upcoming / open / listed)."""
    with session_scope() as s:
        chunks = dict(s.execute(select(Chunk.ipo_id, func.count()).group_by(Chunk.ipo_id)).all())
        debates = dict(s.execute(select(Debate.ipo_id, func.count())
                                 .where(Debate.status == "done").group_by(Debate.ipo_id)).all())
        q = select(Ipo).order_by(Ipo.company)
        if status:
            q = q.where(Ipo.status == status)
        out = [ipo_dict(i, chunks.get(i.ipo_id, 0), debates.get(i.ipo_id, 0))
               for i in s.scalars(q)]
    if analysed_only:
        out = [i for i in out if i["chunks"]]
    return sorted(out, key=lambda i: (i["chunks"] == 0, i["status"], i["company"]))


@app.get("/api/ipos/{ipo_id}")
def get_ipo(ipo_id: str) -> dict:
    """One IPO with its documents."""
    with session_scope() as s:
        ipo = s.get(Ipo, ipo_id)
        if ipo is None:
            raise HTTPException(404, "unknown ipo_id")
        docs = s.scalars(select(Document).where(Document.ipo_id == ipo_id)
                         .order_by(Document.filed_date.desc())).all()
        n = s.scalar(select(func.count()).select_from(Chunk).where(Chunk.ipo_id == ipo_id))
        out = ipo_dict(ipo, n or 0)
        out["documents"] = [{"doc_id": d.doc_id, "doc_type": d.doc_type,
                             "filed_date": d.filed_date.isoformat() if d.filed_date else None,
                             "source_url": d.source_url, "pages": d.n_pages,
                             "chunks": d.n_chunks, "table_rows": d.n_table_rows,
                             "status": d.status} for d in docs]
    return out


@app.get("/api/ipos/{ipo_id}/metrics")
def get_metrics(ipo_id: str, recompute: bool = False) -> list[dict]:
    """Computed metrics with formula, inputs and source pages."""
    with session_scope() as s:
        if s.get(Ipo, ipo_id) is None:
            raise HTTPException(404, "unknown ipo_id")
        rows = s.scalars(select(Metric).where(Metric.ipo_id == ipo_id)).all()
        if recompute or not rows:
            rows = compute_and_store(s, ipo_id)
        return [metric_dict(m) for m in rows]


@app.get("/api/ipos/{ipo_id}/financials")
def get_financials(ipo_id: str) -> list[dict]:
    """Extracted statement rows of the latest document."""
    with session_scope() as s:
        doc = s.scalars(select(Document).where(Document.ipo_id == ipo_id)
                        .order_by(Document.filed_date.desc())).first()
        if doc is None:
            return []
        return [{"statement": r.statement, "line_item": r.line_item, "period": r.period,
                 "value_inr_mn": r.value_inr_mn, "page": r.page, "raw_label": r.raw_label,
                 "basis": r.basis, "is_override": r.is_override}
                for r in s.scalars(select(FinancialRow).where(FinancialRow.doc_id == doc.doc_id))]


class SearchRequest(BaseModel):
    query: str
    k: int = 8
    sections: list[str] | None = None


@app.post("/api/ipos/{ipo_id}/search")
def search(ipo_id: str, req: SearchRequest) -> list[dict]:
    """Hybrid (BM25 + dense, RRF-fused) search within one IPO's latest offer document."""
    hits = retriever().search(ipo_id, req.query, k=req.k, sections=req.sections)
    return [h.as_dict() for h in hits]


@app.get("/api/chunks/{chunk_id:path}")
def get_chunk(chunk_id: str) -> dict:
    """Full text and provenance of one chunk (used by citation chips)."""
    with session_scope() as s:
        c = s.get(Chunk, chunk_id)
        if c is None:
            raise HTTPException(404, "unknown chunk")
        d = s.get(Document, c.doc_id)
        return {"chunk_id": c.chunk_id, "ipo_id": c.ipo_id, "doc_id": c.doc_id,
                "doc_type": d.doc_type, "section": c.section, "page": c.page,
                "page_end": c.page_end, "text": c.text, "source_url": d.source_url,
                "pdf_url": f"/api/documents/{c.doc_id}/pdf#page={c.page}"}


@app.get("/api/documents/{doc_id}/pdf")
def get_pdf(doc_id: str) -> FileResponse:
    """Serve the local copy of an offer document (open with #page=N)."""
    with session_scope() as s:
        d = s.get(Document, doc_id)
        if d is None or not Path(d.local_path).exists():
            raise HTTPException(404, "unknown document")
        return FileResponse(d.local_path, media_type="application/pdf",
                            headers={"Content-Disposition": "inline"})


# ---------------------------------------------------------------------------------------------
# Debates (Server-Sent Events)
# ---------------------------------------------------------------------------------------------
def _sse(event: dict) -> str:
    return f"event: {event.get('type', 'message')}\ndata: {json.dumps(event, default=str)}\n\n"


async def _stream_debate(ipo_id: str):
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def emit(event: dict) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    def worker() -> None:
        try:
            run_debate(ipo_id, emit)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=worker, daemon=True).start()
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=15)
        except asyncio.TimeoutError:
            yield ": keep-alive\n\n"
            continue
        if event is None:
            break
        yield _sse(event)


def _check_ipo(ipo_id: str) -> None:
    with session_scope() as s:
        if s.get(Ipo, ipo_id) is None:
            raise HTTPException(404, "unknown ipo_id")
        if not s.scalar(select(func.count()).select_from(Chunk).where(Chunk.ipo_id == ipo_id)):
            raise HTTPException(409, "IPO has no ingested documents yet")


@app.post("/api/ipos/{ipo_id}/debate")
async def start_debate(ipo_id: str) -> StreamingResponse:
    """Run a new debate and stream its progress as Server-Sent Events."""
    _check_ipo(ipo_id)
    return StreamingResponse(_stream_debate(ipo_id), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/ipos/{ipo_id}/debate/stream")
async def start_debate_get(ipo_id: str) -> StreamingResponse:
    """Same as POST, for EventSource clients."""
    return await start_debate(ipo_id)


@app.get("/api/ipos/{ipo_id}/debates")
def list_debates(ipo_id: str) -> list[dict]:
    """Past debates for an IPO, newest first."""
    with session_scope() as s:
        rows = s.scalars(select(Debate).where(Debate.ipo_id == ipo_id)
                         .order_by(Debate.created_at.desc())).all()
        return [{"debate_id": d.debate_id, "status": d.status,
                 "verdict": json.loads(d.verdict_json or "{}").get("verdict"),
                 "models": json.loads(d.models_json or "{}"),
                 "created_at": d.created_at.isoformat() if d.created_at else None} for d in rows]


@app.get("/api/debates/{debate_id}")
def get_debate(debate_id: str) -> dict:
    """A stored debate: claims, verification results, verdict and models used."""
    with session_scope() as s:
        d = s.get(Debate, debate_id)
        if d is None:
            raise HTTPException(404, "unknown debate")
        return debate_payload(d)


@app.get("/api/debates/{debate_id}/replay")
async def replay(debate_id: str, speed: float = Query(4.0, gt=0)) -> StreamingResponse:
    """Re-stream a saved debate's events (works fully offline)."""
    with session_scope() as s:
        d = s.get(Debate, debate_id)
        if d is None:
            raise HTTPException(404, "unknown debate")
        events = json.loads(d.events_json or "[]")

    async def gen():
        for e in events:
            delay = {"claim": 1.2, "verification": 0.25, "round": 0.8}.get(e.get("type"), 0.4)
            await asyncio.sleep(delay / speed)
            yield _sse({**e, "replay": True})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@app.get("/api/backtest")
def get_backtest() -> list[dict]:
    """Verdict vs listing-day gain and current return for listed IPOs."""
    with session_scope() as s:
        return backtest(s)
