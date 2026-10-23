"""Common types for filing sources (SEBI, NSE, BSE, local drop folder)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

import httpx

from backend.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class FilingRecord:
    """One offer document or issue listing as reported by a source.

    ``extra`` carries optional registry fields a source happens to know
    (price band, issue dates, symbol, ...). Keys match ``Ipo`` column names.
    """

    company: str
    doc_type: str
    source: str
    title: str = ""
    filed_date: date | None = None
    page_url: str | None = None
    pdf_url: str | None = None
    extra: dict[str, object] = field(default_factory=dict)


class Source(Protocol):
    """Anything that can list recent filings."""

    name: str

    def fetch(self) -> list[FilingRecord]:
        """Return recent filings. Must not raise on network or parse errors; log and return []."""
        ...


def http_client() -> httpx.Client:
    """Return an HTTP client with browser-like headers (exchange sites reject bare clients)."""
    s = get_settings()
    return httpx.Client(
        headers={
            "User-Agent": s.http_user_agent,
            "Accept": "text/html,application/json,application/pdf;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        },
        timeout=s.http_timeout_seconds,
        follow_redirects=True,
    )


_DATE_FORMATS = ("%b %d, %Y", "%d-%b-%Y", "%d %b %Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y",
                 "%B %d, %Y", "%d %B %Y", "%d-%b-%y")


def parse_date(text: str | None) -> date | None:
    """Parse the date formats used by SEBI, NSE and BSE. Returns ``None`` if unparseable."""
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", str(text)).strip().rstrip(".")
    cleaned = re.sub(r"T\d{2}:\d{2}.*$", "", cleaned)  # ISO timestamps
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None
