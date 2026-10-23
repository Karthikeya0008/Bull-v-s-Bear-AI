"""SQLite schema: IPO registry, filings, documents, chunks, financial rows and the cache."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base

class Ipo(Base):
    """One row per issuer going public. ``ipo_id`` is a stable slug such as ``jio-platforms``."""

    __tablename__ = "ipos"

    ipo_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    company: Mapped[str] = mapped_column(String(255))
    issuer_norm: Mapped[str] = mapped_column(String(255), index=True, unique=True)
    status: Mapped[str] = mapped_column(String(20), default="upcoming")  # upcoming/open/listed
    sector: Mapped[str | None] = mapped_column(String(120))
    exchanges: Mapped[str | None] = mapped_column(String(40))
    price_band_low: Mapped[float | None] = mapped_column(Float)
    price_band_high: Mapped[float | None] = mapped_column(Float)
    lot_size: Mapped[int | None] = mapped_column(Integer)
    issue_open: Mapped[date | None] = mapped_column(Date)
    issue_close: Mapped[date | None] = mapped_column(Date)
    listing_date: Mapped[date | None] = mapped_column(Date)
    fresh_issue_shares: Mapped[int | None] = mapped_column(Integer)
    ofs_shares: Mapped[int | None] = mapped_column(Integer)
    fresh_issue_cr: Mapped[float | None] = mapped_column(Float)
    ofs_cr: Mapped[float | None] = mapped_column(Float)
    face_value: Mapped[float | None] = mapped_column(Float)
    nse_symbol: Mapped[str | None] = mapped_column(String(40))
    bse_code: Mapped[str | None] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(40), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Filing(Base):
    """An offer document discovered by the watcher or seeded manually (not yet downloaded)."""

    __tablename__ = "filings"
    __table_args__ = (UniqueConstraint("issuer_norm", "filed_date", "doc_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ipo_id: Mapped[str] = mapped_column(ForeignKey("ipos.ipo_id", ondelete="CASCADE"), index=True)
    issuer_norm: Mapped[str] = mapped_column(String(255))
    doc_type: Mapped[str] = mapped_column(String(20))  # DRHP / RHP / PROSPECTUS / ADDENDUM
    filed_date: Mapped[date | None] = mapped_column(Date)
    title: Mapped[str] = mapped_column(String(500))
    page_url: Mapped[str | None] = mapped_column(String(1000))
    pdf_url: Mapped[str | None] = mapped_column(String(1000))
    source: Mapped[str] = mapped_column(String(40))  # sebi / nse / bse / local / seed
    discovered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Document(Base):
    """A PDF on disk that belongs to an IPO. ``doc_id`` is the SHA-256 of the file bytes."""

    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ipo_id: Mapped[str] = mapped_column(ForeignKey("ipos.ipo_id", ondelete="CASCADE"), index=True)
    doc_type: Mapped[str] = mapped_column(String(20))
    filed_date: Mapped[date | None] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    local_path: Mapped[str] = mapped_column(String(1000))
    n_pages: Mapped[int | None] = mapped_column(Integer)
    n_chunks: Mapped[int | None] = mapped_column(Integer)
    n_table_rows: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/parsed/failed
    error: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime)


class Chunk(Base):
    """A retrievable passage. The same id is used as the ChromaDB document id."""

    __tablename__ = "chunks"

    chunk_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    ipo_id: Mapped[str] = mapped_column(ForeignKey("ipos.ipo_id", ondelete="CASCADE"), index=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.doc_id", ondelete="CASCADE"))
    section: Mapped[str] = mapped_column(String(120), index=True)
    page: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)


class FinancialRow(Base):
    """One extracted figure: (IPO, statement, line item, fiscal period) -> value in INR million."""

    __tablename__ = "financial_rows"
    __table_args__ = (
        UniqueConstraint("ipo_id", "doc_id", "statement", "line_item", "period", "basis"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ipo_id: Mapped[str] = mapped_column(ForeignKey("ipos.ipo_id", ondelete="CASCADE"), index=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("documents.doc_id", ondelete="CASCADE"))
    statement: Mapped[str] = mapped_column(String(20))  # pnl / balance_sheet / cash_flow
    line_item: Mapped[str] = mapped_column(String(80))  # canonical name, see line_items.py
    raw_label: Mapped[str] = mapped_column(String(500))
    period: Mapped[str] = mapped_column(String(20))  # FY2026, or 3M-2026-06 for stub periods
    period_end: Mapped[date | None] = mapped_column(Date)
    basis: Mapped[str] = mapped_column(String(20), default="consolidated")
    value_raw: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20))  # million / crore / lakh / thousand / rupees
    value_inr_mn: Mapped[float] = mapped_column(Float)
    page: Mapped[int] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(120))
    is_override: Mapped[int] = mapped_column(Integer, default=0)


class CacheEntry(Base):
    """Content-addressed cache for embeddings and (from Phase 3) LLM responses."""

    __tablename__ = "cache"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    namespace: Mapped[str] = mapped_column(String(40), index=True)
    value: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Metric(Base):
    """A computed metric. ``inputs_json`` lists every input figure with its source page."""

    __tablename__ = "metrics"

    metric_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    ipo_id: Mapped[str] = mapped_column(ForeignKey("ipos.ipo_id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    label: Mapped[str] = mapped_column(String(120))
    period: Mapped[str] = mapped_column(String(20))
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20))
    formula: Mapped[str] = mapped_column(Text)
    inputs_json: Mapped[str] = mapped_column(Text)
    source_pages: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(10))  # ok / skipped
    note: Mapped[str | None] = mapped_column(Text)
    doc_id: Mapped[str | None] = mapped_column(String(64))
    computed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Debate(Base):
    """One debate run, with everything needed to audit or replay it."""

    __tablename__ = "debates"

    debate_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    ipo_id: Mapped[str] = mapped_column(ForeignKey("ipos.ipo_id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running/done/failed
    models_json: Mapped[str] = mapped_column(Text, default="{}")
    claims_json: Mapped[str] = mapped_column(Text, default="[]")
    verification_json: Mapped[str] = mapped_column(Text, default="[]")
    verdict_json: Mapped[str] = mapped_column(Text, default="{}")
    events_json: Mapped[str] = mapped_column(Text, default="[]")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class LlmCall(Base):
    """Token and latency log for every LLM request (cached hits included)."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    debate_id: Mapped[str | None] = mapped_column(String(32), index=True)
    role: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(80))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    cached: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
