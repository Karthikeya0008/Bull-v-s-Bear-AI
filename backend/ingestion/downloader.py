"""Download offer-document PDFs into ``data/raw/<ipo_id>/`` and register them as documents."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from backend.ingestion.registry import OFFER_DOC_TYPES
from backend.ingestion.sources import sebi
from backend.ingestion.sources.base import http_client
from backend.knowledge.models import Document, Filing

log = logging.getLogger(__name__)


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file, read in 1 MB blocks."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def target_path(raw_dir: Path, filing: Filing) -> Path:
    """Deterministic file name, e.g. ``data/raw/jio-platforms/DRHP_2026-06-19.pdf``."""
    stamp = filing.filed_date.isoformat() if filing.filed_date else f"id{filing.id}"
    return raw_dir / filing.ipo_id / f"{filing.doc_type}_{stamp}.pdf"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20),
       retry=retry_if_exception_type(httpx.TransportError), reraise=True)
def _stream_to(client: httpx.Client, url: str, dest: Path) -> None:
    tmp = dest.with_suffix(".part")
    with client.stream("GET", url) as resp:
        resp.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in resp.iter_bytes(1 << 16):
                fh.write(chunk)
    with tmp.open("rb") as fh:
        if fh.read(5) != b"%PDF-":
            tmp.unlink()
            raise ValueError(f"{url} did not return a PDF")
    tmp.replace(dest)


def register_document(session: Session, ipo_id: str, path: Path, doc_type: str,
                      filed_date=None, source_url: str | None = None) -> Document:
    """Create (or return the existing) ``Document`` row for a PDF on disk, keyed by its hash."""
    doc_id = sha256_file(path)
    doc = session.get(Document, doc_id)
    if doc is None:
        doc = Document(doc_id=doc_id, ipo_id=ipo_id, doc_type=doc_type, filed_date=filed_date,
                       source_url=source_url or path.resolve().as_uri(),
                       local_path=str(path), status="pending")
        session.add(doc)
        session.flush()
    elif source_url and doc.source_url.startswith("file:"):
        doc.source_url = source_url
    return doc


def download_filings(session: Session, raw_dir: Path, ipo_id: str | None = None) -> list[Path]:
    """Download every offer-document filing (optionally for one IPO) that is not on disk yet.

    Returns the list of newly downloaded paths. Failures are logged, not raised.
    """
    query = select(Filing).where(Filing.doc_type.in_(OFFER_DOC_TYPES))
    if ipo_id:
        query = query.where(Filing.ipo_id == ipo_id)
    new_paths: list[Path] = []
    with http_client() as client:
        for filing in session.scalars(query):
            dest = target_path(raw_dir, filing)
            if dest.exists():
                register_document(session, filing.ipo_id, dest, filing.doc_type,
                                  filing.filed_date, filing.pdf_url or filing.page_url)
                continue
            if not filing.pdf_url and filing.page_url and "sebi.gov.in" in filing.page_url:
                filing.pdf_url = sebi.resolve_pdf_url(filing.page_url, client)
            if not filing.pdf_url:
                log.warning("No PDF URL for %s (%s)", filing.title, filing.page_url)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            log.info("Downloading %s -> %s", filing.pdf_url, dest)
            try:
                _stream_to(client, filing.pdf_url, dest)
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("Download failed for %s: %s", filing.pdf_url, exc)
                continue
            register_document(session, filing.ipo_id, dest, filing.doc_type,
                              filing.filed_date, filing.pdf_url)
            new_paths.append(dest)
    return new_paths
