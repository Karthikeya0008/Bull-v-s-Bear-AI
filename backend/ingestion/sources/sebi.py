"""SEBI public issues filings (https://www.sebi.gov.in) - DRHPs and RHPs.

The listing page is rendered by a POST to ``getnewslistinfo.jsp``, which needs the session
cookie set by the listing page. Each filing page embeds the full offer document in an
``<iframe src=".../web/?file=<pdf url>">``; the separate ``_p.pdf`` link is only the abridged
prospectus.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta

import httpx
from bs4 import BeautifulSoup

from backend.ingestion.registry import detect_doc_type, issuer_from_title
from backend.ingestion.sources.base import FilingRecord, http_client, parse_date

log = logging.getLogger(__name__)

BASE = "https://www.sebi.gov.in"
LISTING_URL = BASE + "/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15&smid={smid}"
AJAX_URL = BASE + "/sebiweb/ajax/home/getnewslistinfo.jsp"

# Sub-sub-sections of "Public Issues" on the SEBI site.
SECTIONS = {
    10: "Draft Offer Documents filed with SEBI",
    11: "Red Herring Documents filed with ROC",
}


def parse_listing(html: str, section_name: str) -> list[FilingRecord]:
    """Parse the rows of a SEBI listing (full page or AJAX fragment) into filing records."""
    soup = BeautifulSoup(html, "lxml")
    records: list[FilingRecord] = []
    for row in soup.select("tr[role=row]"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        link = cells[1].find("a", href=True)
        if link is None or "/filings/" not in link["href"]:
            continue
        # The anchor's text contains a nested abridged-prospectus link; keep only the title.
        title = link.get("title", "") or link.get_text(" ", strip=True)
        title = re.split(r"<br|\n", title)[0]
        title = re.sub(r"\s+", " ", title.replace("�", "-")).strip()
        records.append(FilingRecord(
            company=issuer_from_title(title),
            doc_type=detect_doc_type(title),
            source="sebi",
            title=title,
            filed_date=parse_date(cells[0].get_text(strip=True)),
            page_url=link["href"],
            extra={"_section": section_name},
        ))
    return records


def extract_pdf_url(filing_html: str) -> str | None:
    """Return the full offer-document PDF URL embedded in a SEBI filing page."""
    m = re.search(r"""<iframe[^>]+src=['"][^'"]*?file=(https?://[^'"&]+\.pdf)""", filing_html,
                  re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"""href=['"](https?://[^'"]+/attachdocs/[^'"]+\.pdf)['"]""", filing_html,
                  re.IGNORECASE)
    return m.group(1) if m else None


class SebiSource:
    """Fetches recent DRHP and RHP filings from SEBI."""

    name = "sebi"

    def __init__(self, lookback_days: int = 45, max_pages: int = 3,
                 search: str = "", client: httpx.Client | None = None) -> None:
        self.lookback_days = lookback_days
        self.max_pages = max_pages
        self.search = search
        self._client = client

    def _list_section(self, client: httpx.Client, smid: int, name: str) -> list[FilingRecord]:
        listing = LISTING_URL.format(smid=smid)
        client.get(listing)  # sets JSESSIONID, required by the AJAX endpoint
        cutoff = date.today() - timedelta(days=self.lookback_days)
        out: list[FilingRecord] = []
        for page in range(1, self.max_pages + 1):
            form = {
                "nextValue": str(page), "next": "n" if page > 1 else "s",
                "search": self.search, "fromDate": "", "toDate": "", "fromYear": "",
                "toYear": "", "deptId": "-1", "sid": "3", "ssid": "15", "smid": str(smid),
                "ssidhidden": "15", "intmid": "-1", "sText": "Public Issues", "ssText": name,
                "smText": "", "doDirect": "-1" if page == 1 else str(page),
            }
            resp = client.post(AJAX_URL, data=form, headers={
                "X-Requested-With": "XMLHttpRequest", "Referer": listing})
            resp.raise_for_status()
            rows = parse_listing(resp.text, name)
            if not rows:
                break
            out.extend(r for r in rows if r.filed_date is None or r.filed_date >= cutoff)
            if all(r.filed_date and r.filed_date < cutoff for r in rows):
                break
        return out

    def fetch(self) -> list[FilingRecord]:
        """Return recent DRHP/RHP filings; logs and returns what it has on failure."""
        records: list[FilingRecord] = []
        client = self._client or http_client()
        try:
            for smid, name in SECTIONS.items():
                try:
                    records.extend(self._list_section(client, smid, name))
                except (httpx.HTTPError, ValueError) as exc:
                    log.warning("SEBI section %s failed: %s", name, exc)
        finally:
            if self._client is None:
                client.close()
        log.info("SEBI: %d filings", len(records))
        return records


def resolve_pdf_url(page_url: str, client: httpx.Client | None = None) -> str | None:
    """Fetch a SEBI filing page and return the offer-document PDF URL inside it."""
    own = client is None
    client = client or http_client()
    try:
        resp = client.get(page_url)
        resp.raise_for_status()
        return extract_pdf_url(resp.text)
    except httpx.HTTPError as exc:
        log.warning("Could not resolve PDF for %s: %s", page_url, exc)
        return None
    finally:
        if own:
            client.close()
