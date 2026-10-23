"""IPO registry: issuer normalisation, upserts, filing deduplication and status derivation."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ingestion.sources.base import FilingRecord, parse_date
from backend.knowledge.models import Filing, Ipo

_SUFFIXES = {"limited", "ltd", "pvt", "private", "the"}

_DOC_TYPE_PATTERNS: list[tuple[str, str]] = [
    (r"\baddendum\b", "ADDENDUM"),
    (r"\bcorrigendum\b", "CORRIGENDUM"),
    (r"\budrhp\b|updated draft red herring", "UDRHP"),
    (r"\bdrhp\b|draft red herring", "DRHP"),
    (r"\brhp\b|red herring", "RHP"),
    (r"\bprospectus\b", "PROSPECTUS"),
]

# Document types that contain the full offer document and are worth ingesting.
OFFER_DOC_TYPES = {"DRHP", "UDRHP", "RHP", "PROSPECTUS"}


def normalize_issuer(name: str) -> str:
    """Normalise an issuer name so the same company matches across sources.

    ``"Orient Cables (India) Ltd."`` and ``"ORIENT CABLES (INDIA) LIMITED"`` both become
    ``"orient cables india"``.
    """
    text = name.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [t for t in text.split() if t not in _SUFFIXES]
    return " ".join(tokens)


def slugify(issuer_norm: str) -> str:
    """Turn a normalised issuer name into an ``ipo_id`` (``jio platforms`` -> ``jio-platforms``)."""
    return re.sub(r"\s+", "-", issuer_norm.strip())[:80]


def detect_doc_type(title: str) -> str:
    """Infer the document type from a filing title; defaults to ``OTHER``."""
    lowered = title.lower()
    for pattern, doc_type in _DOC_TYPE_PATTERNS:
        if re.search(pattern, lowered):
            return doc_type
    return "OTHER"


def issuer_from_title(title: str) -> str:
    """Strip the document-type suffix from a SEBI title such as ``"Soleos Energy Limited – DRHP"``."""
    head = re.split(
        r"\s*[–—:-]\s*(?=(?:addendum|corrigendum|u?drhp|rhp|red herring|draft|prospectus)\b)",
        title, maxsplit=1, flags=re.IGNORECASE,
    )[0]
    head = re.sub(r"[-–—:\s]+$", "", head)
    return head.strip() or title.strip()


def derive_status(ipo: Ipo, today: date | None = None) -> str:
    """Compute ``upcoming`` / ``open`` / ``listed`` from the issue and listing dates.

    An issue that has closed but not yet listed is reported as ``open`` (allotment pending).
    """
    today = today or date.today()
    if ipo.listing_date and ipo.listing_date <= today:
        return "listed"
    if ipo.issue_open and ipo.issue_open <= today:
        return "open"
    return "upcoming"


def get_or_create_ipo(session: Session, company: str, source: str) -> Ipo:
    """Return the IPO for ``company`` (matched on normalised name), creating it if needed."""
    norm = normalize_issuer(company)
    ipo = session.scalar(select(Ipo).where(Ipo.issuer_norm == norm))
    if ipo is None:
        ipo = Ipo(ipo_id=slugify(norm), company=company.strip(), issuer_norm=norm, source=source)
        session.add(ipo)
        session.flush()
    return ipo


def apply_fields(ipo: Ipo, fields: dict[str, object], overwrite: bool) -> None:
    """Copy known ``Ipo`` attributes from ``fields``; only fill blanks unless ``overwrite``."""
    for key, value in fields.items():
        if value is None or not hasattr(Ipo, key) or key in {"ipo_id", "issuer_norm"}:
            continue
        if key in {"issue_open", "issue_close", "listing_date"} and not isinstance(value, date):
            value = parse_date(str(value))
        if overwrite or getattr(ipo, key) in (None, ""):
            setattr(ipo, key, value)


def record_filing(session: Session, rec: FilingRecord) -> tuple[Filing, bool]:
    """Store a filing unless one with the same (issuer, filed date, doc type) exists.

    Returns ``(filing, created)``. Missing URLs on an existing filing are filled in.
    """
    ipo = get_or_create_ipo(session, rec.company, rec.source)
    apply_fields(ipo, rec.extra, overwrite=False)
    doc_type = rec.doc_type or detect_doc_type(rec.title)
    existing = session.scalar(
        select(Filing).where(
            Filing.issuer_norm == ipo.issuer_norm,
            Filing.filed_date.is_(rec.filed_date) if rec.filed_date is None
            else Filing.filed_date == rec.filed_date,
            Filing.doc_type == doc_type,
        )
    )
    if existing is not None:
        existing.pdf_url = existing.pdf_url or rec.pdf_url
        existing.page_url = existing.page_url or rec.page_url
        return existing, False
    filing = Filing(
        ipo_id=ipo.ipo_id, issuer_norm=ipo.issuer_norm, doc_type=doc_type,
        filed_date=rec.filed_date, title=rec.title or f"{rec.company} - {doc_type}",
        page_url=rec.page_url, pdf_url=rec.pdf_url, source=rec.source,
    )
    session.add(filing)
    session.flush()
    return filing, True


def load_seed(session: Session, path: Path) -> list[str]:
    """Load manually curated IPOs from YAML. Seed values overwrite scraped ones.

    Returns the list of ``ipo_id`` values touched.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    touched: list[str] = []
    for entry in data.get("ipos", []):
        entry = dict(entry)
        filings = entry.pop("filings", []) or []
        ipo = get_or_create_ipo(session, entry["company"], "seed")
        if entry.get("ipo_id") and entry["ipo_id"] != ipo.ipo_id:
            raise ValueError(f"seed ipo_id {entry['ipo_id']!r} != derived {ipo.ipo_id!r}")
        apply_fields(ipo, entry, overwrite=True)
        for f in filings:
            record_filing(session, FilingRecord(
                company=ipo.company, doc_type=f["doc_type"], source="seed",
                title=f.get("title", ""), filed_date=parse_date(str(f.get("filed_date"))),
                page_url=f.get("page_url"), pdf_url=f.get("pdf_url"),
            ))
        touched.append(ipo.ipo_id)
    return touched


def refresh_statuses(session: Session, today: date | None = None) -> None:
    """Recompute ``status`` for every IPO from its dates."""
    for ipo in session.scalars(select(Ipo)):
        ipo.status = derive_status(ipo, today)
