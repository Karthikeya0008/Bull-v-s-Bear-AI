"""End-to-end ingestion for one document: parse -> sections -> chunks -> embeddings -> tables."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.knowledge.embeddings import Embedder
from backend.knowledge.models import Chunk, Document, FinancialRow, Ipo
from backend.knowledge.vector_store import VectorStore
from backend.processing import tables
from backend.processing.chunker import chunk_document
from backend.processing.pdf_parser import parse_pdf
from backend.processing.sections import detect_sections

log = logging.getLogger(__name__)


@dataclass
class IngestResult:
    """What one document produced."""

    doc_id: str
    path: str
    pages: int
    sections: int
    chunks: int
    table_rows: int
    seconds: float


def ingest_document(session: Session, doc: Document, *, embed: bool = True,
                    extract_tables: bool = True, embedder: Embedder | None = None,
                    store: VectorStore | None = None) -> IngestResult:
    """Ingest one registered document, replacing any previous chunks/rows for it."""
    t0 = time.perf_counter()
    settings = get_settings()
    ipo = session.get(Ipo, doc.ipo_id)
    path = Path(doc.local_path)
    log.info("[%s] parsing %s", doc.ipo_id, path.name)
    parsed = parse_pdf(path)
    starts = detect_sections(parsed)
    log.info("[%s] %d pages, %d section starts", doc.ipo_id, parsed.n_pages, len(starts))

    chunks = chunk_document(parsed, doc.ipo_id, doc.doc_id, doc.doc_type,
                            settings.chunk_size, settings.chunk_overlap, starts)
    session.execute(delete(Chunk).where(Chunk.doc_id == doc.doc_id))
    session.add_all(Chunk(chunk_id=c.chunk_id, ipo_id=doc.ipo_id, doc_id=doc.doc_id,
                          section=c.section, page=c.page, page_end=c.page_end,
                          ordinal=c.ordinal, text=c.text) for c in chunks)
    # Commit now: the embedding cache writes through its own connection, and SQLite allows
    # one writer at a time.
    session.commit()

    if embed and chunks:
        embedder = embedder or Embedder()
        store = store or VectorStore()
        vectors = embedder.embed([c.text for c in chunks])
        metadatas = [{
            "ipo_id": doc.ipo_id, "company": ipo.company, "doc_id": doc.doc_id,
            "doc_type": doc.doc_type, "source_url": doc.source_url or "",
            "page": c.page, "page_end": c.page_end, "section": c.section,
            "filed_date": doc.filed_date.isoformat() if doc.filed_date else "",
        } for c in chunks]
        store.delete_doc(doc.ipo_id, doc.doc_id)
        store.upsert(doc.ipo_id, [c.chunk_id for c in chunks], vectors,
                     [c.text for c in chunks], metadatas)

    n_rows = 0
    if extract_tables:
        rows = tables.extract_financials(path, starts, parsed)
        rows = tables.apply_overrides(rows, settings.processed_dir / doc.ipo_id
                                      / "financials_override.csv")
        session.execute(delete(FinancialRow).where(FinancialRow.doc_id == doc.doc_id))
        session.add_all(FinancialRow(ipo_id=doc.ipo_id, doc_id=doc.doc_id, **r.as_dict())
                        for r in rows)
        n_rows = len(rows)

    _write_processed(doc, starts, chunks)
    doc.n_pages, doc.n_chunks, doc.n_table_rows = parsed.n_pages, len(chunks), n_rows
    doc.status, doc.error, doc.ingested_at = "parsed", None, datetime.now()
    secs = time.perf_counter() - t0
    log.info("[%s] %s: %d chunks, %d table rows in %.1fs", doc.ipo_id, path.name,
             len(chunks), n_rows, secs)
    return IngestResult(doc.doc_id, str(path), parsed.n_pages, len(starts), len(chunks),
                        n_rows, secs)


def _write_processed(doc: Document, starts, chunks) -> None:
    """Dump sections and chunks to ``data/processed/<ipo_id>/`` for inspection."""
    out = get_settings().processed_dir / doc.ipo_id
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(doc.local_path).stem
    (out / f"{stem}.sections.json").write_text(json.dumps(
        [{"page": s.page, "section": s.name, "heading": s.heading} for s in starts],
        indent=2, ensure_ascii=False), encoding="utf-8")
    with (out / f"{stem}.chunks.jsonl").open("w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps({"chunk_id": c.chunk_id, "section": c.section, "page": c.page,
                                 "page_end": c.page_end, "text": c.text},
                                ensure_ascii=False) + "\n")


def documents_for(session: Session, ipo_id: str | None, force: bool) -> list[Document]:
    """Documents to ingest: pending ones (or all with ``force``), optionally for one IPO."""
    q = select(Document)
    if ipo_id:
        q = q.where(Document.ipo_id == ipo_id)
    if not force:
        q = q.where(Document.status != "parsed")
    return list(session.scalars(q.order_by(Document.ipo_id, Document.filed_date)))
