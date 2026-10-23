"""NSE IPO listings: current, upcoming and recently listed issues (JSON API).

NSE's API rejects requests without the cookies set by a normal page visit, so the client
first loads the public IPO page, then calls the API with that cookie jar.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta

import httpx

from backend.ingestion.sources.base import FilingRecord, http_client, parse_date

log = logging.getLogger(__name__)

BASE = "https://www.nseindia.com"
WARMUP = BASE + "/market-data/all-upcoming-issues-ipo"
ENDPOINTS = {
    "upcoming": "/api/all-upcoming-issues?category=ipo",
    "past": "/api/public-past-issues",
}


def parse_price_band(text: str | None) -> tuple[float | None, float | None]:
    """Parse ``"Rs.1065 to Rs.1119"`` (or a single price) into ``(low, high)``."""
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", (text or "").replace(",", ""))]
    if not nums:
        return None, None
    return min(nums), max(nums)


def parse_upcoming(items: list[dict]) -> list[FilingRecord]:
    """Map NSE current/upcoming issue JSON to filing records (registry fields only)."""
    out = []
    for it in items:
        if (it.get("series") or "EQ") not in {"EQ", ""}:
            continue  # skip SME (``SME``) and debt series
        low, high = parse_price_band(it.get("issuePrice"))
        out.append(FilingRecord(
            company=it["companyName"], doc_type="LISTING", source="nse",
            title=f"{it['companyName']} - NSE issue", extra={
                "price_band_low": low, "price_band_high": high,
                "issue_open": parse_date(it.get("issueStartDate")),
                "issue_close": parse_date(it.get("issueEndDate")),
                "nse_symbol": it.get("symbol"),
            }))
    return out


def parse_past(items: list[dict], since: date) -> list[FilingRecord]:
    """Map NSE past-issue JSON (listed IPOs) to records, keeping listings on/after ``since``."""
    out = []
    for it in items:
        if (it.get("securityType") or "EQ") != "EQ":
            continue
        listing = parse_date(it.get("listingDate"))
        if listing is None or listing < since:
            continue
        low, high = parse_price_band(it.get("priceRange"))
        out.append(FilingRecord(
            company=it["company"], doc_type="LISTING", source="nse",
            title=f"{it['company']} - NSE listing", extra={
                "price_band_low": low, "price_band_high": high,
                "issue_open": parse_date(it.get("ipoStartDate")),
                "issue_close": parse_date(it.get("ipoEndDate")),
                "listing_date": listing, "nse_symbol": it.get("symbol"),
            }))
    return out


class NseSource:
    """Fetches mainboard IPOs from NSE."""

    name = "nse"

    def __init__(self, lookback_days: int = 45, client: httpx.Client | None = None) -> None:
        self.lookback_days = lookback_days
        self._client = client

    def fetch(self) -> list[FilingRecord]:
        """Return current, upcoming and recently listed NSE IPOs; [] on failure."""
        client = self._client or http_client()
        records: list[FilingRecord] = []
        try:
            client.get(WARMUP)
            headers = {"Accept": "application/json", "Referer": WARMUP}
            up = client.get(BASE + ENDPOINTS["upcoming"], headers=headers)
            up.raise_for_status()
            records.extend(parse_upcoming(up.json()))
            past = client.get(BASE + ENDPOINTS["past"], headers=headers)
            past.raise_for_status()
            since = date.today() - timedelta(days=self.lookback_days)
            records.extend(parse_past(past.json(), since))
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            log.warning("NSE fetch failed: %s", exc)
        finally:
            if self._client is None:
                client.close()
        log.info("NSE: %d issues", len(records))
        return records
