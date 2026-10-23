"""BSE public issues (best effort).

BSE's JSON API sits behind Akamai bot protection and currently answers scripted requests
with "Access Denied". The source is kept so the watcher tries it on every run, but it
degrades to an empty list; NSE and SEBI cover the same mainboard issues.
"""

from __future__ import annotations

import logging

import httpx

from backend.ingestion.sources.base import FilingRecord, http_client, parse_date
from backend.ingestion.sources.nse import parse_price_band

log = logging.getLogger(__name__)

API = "https://api.bseindia.com/BseIndiaAPI/api/PubIssues/w?id=0&Type=IPO&IPOType="


class BseSource:
    """Fetches mainboard IPOs from BSE when the API is reachable."""

    name = "bse"

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def fetch(self) -> list[FilingRecord]:
        """Return BSE IPO listings, or [] when blocked or unreachable."""
        client = self._client or http_client()
        try:
            resp = client.get(API, headers={"Referer": "https://www.bseindia.com/",
                                            "Origin": "https://www.bseindia.com"})
            if resp.status_code == 403 or "Access Denied" in resp.text[:500]:
                log.info("BSE API blocked scripted access (403); skipping")
                return []
            resp.raise_for_status()
            payload = resp.json()
            items = payload.get("Table", payload) if isinstance(payload, dict) else payload
            out = []
            for it in items:
                name = it.get("Scrip_Name") or it.get("CompanyName")
                if not name:
                    continue
                low, high = parse_price_band(it.get("Price_Band") or it.get("PriceBand"))
                out.append(FilingRecord(
                    company=name, doc_type="LISTING", source="bse", title=f"{name} - BSE issue",
                    extra={"price_band_low": low, "price_band_high": high,
                           "issue_open": parse_date(it.get("Start_Dt")),
                           "issue_close": parse_date(it.get("End_Dt"))}))
            return out
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            log.warning("BSE fetch failed: %s", exc)
            return []
        finally:
            if self._client is None:
                client.close()
