"""IPO watcher: polls SEBI/NSE/BSE, records new filings, and picks up manually dropped PDFs.

Run once with ``python -m backend.ingest --watch`` or on a schedule with ``--schedule``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.db import session_scope
from backend.ingestion import registry
from backend.ingestion.downloader import register_document
from backend.ingestion.sources import local_drop
from backend.ingestion.sources.base import FilingRecord, Source
from backend.ingestion.sources.bse import BseSource
from backend.ingestion.sources.nse import NseSource
from backend.ingestion.sources.sebi import SebiSource
from backend.knowledge.models import Ipo

log = logging.getLogger(__name__)


@dataclass
class WatchReport:
    """Summary of one watcher run."""

    fetched: dict[str, int] = field(default_factory=dict)
    new_filings: list[str] = field(default_factory=list)
    local_docs: list[str] = field(default_factory=list)


def default_sources() -> list[Source]:
    """Sources in priority order. Each one fails soft."""
    lookback = get_settings().watcher_lookback_days
    return [SebiSource(lookback_days=lookback), NseSource(lookback_days=lookback), BseSource()]


def apply_records(session: Session, records: list[FilingRecord], report: WatchReport) -> None:
    """Store filings (deduplicated) and merge exchange listing data into the registry."""
    for rec in records:
        rec.extra.pop("_section", None)
        if rec.doc_type == "LISTING":
            ipo = registry.get_or_create_ipo(session, rec.company, rec.source)
            registry.apply_fields(ipo, rec.extra, overwrite=ipo.source != "seed")
            continue
        _, created = registry.record_filing(session, rec)
        if created:
            report.new_filings.append(rec.title)


def scan_local(session: Session, report: WatchReport) -> None:
    """Register every PDF under ``data/raw/<ipo_id>/`` (the manual fallback)."""
    raw_dir = get_settings().raw_dir
    for ipo_id, pdfs in local_drop.scan(raw_dir).items():
        ipo = session.get(Ipo, ipo_id) or registry.get_or_create_ipo(
            session, local_drop.company_from_folder(ipo_id), "local")
        for pdf in pdfs:
            doc = register_document(session, ipo.ipo_id, pdf,
                                    local_drop.doc_type_from_filename(pdf))
            if doc.status == "pending":
                report.local_docs.append(str(pdf))


def run_once(sources: list[Source] | None = None, seed: bool = True) -> WatchReport:
    """Run every source once, then scan the drop folder. Safe to call repeatedly."""
    report = WatchReport()
    settings = get_settings()
    with session_scope() as session:
        if seed:
            seed_path = settings.resolve(settings.config_dir) / "seed_ipos.yaml"
            if seed_path.exists():
                registry.load_seed(session, seed_path)
        for src in sources if sources is not None else default_sources():
            records = src.fetch()
            report.fetched[src.name] = len(records)
            apply_records(session, records, report)
        scan_local(session, report)
        registry.refresh_statuses(session)
    log.info("Watcher: fetched=%s new=%d local=%d", report.fetched,
             len(report.new_filings), len(report.local_docs))
    return report


def run_scheduled() -> None:
    """Block forever, running the watcher every ``WATCHER_INTERVAL_MINUTES``."""
    from apscheduler.schedulers.blocking import BlockingScheduler

    minutes = get_settings().watcher_interval_minutes
    scheduler = BlockingScheduler()
    scheduler.add_job(run_once, "interval", minutes=minutes, next_run_time=None)
    log.info("Watcher scheduled every %d minutes (Ctrl+C to stop)", minutes)
    run_once()
    scheduler.start()


def list_ipos(session: Session) -> list[Ipo]:
    """Return all IPOs ordered by status then company."""
    return list(session.scalars(select(Ipo).order_by(Ipo.status, Ipo.company)))
