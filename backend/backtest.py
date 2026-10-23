"""Back-test: compare each listed IPO's latest verdict with its listing-day and current return.

Prices come from Yahoo Finance via yfinance (``<NSE symbol>.NS``) and are cached in SQLite
for the day; ``data/backtest_prices.csv`` (columns ``ipo_id,date,close``) is the offline
fallback and is also written whenever prices are fetched, so the demo works without internet.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.knowledge.cache import Cache
from backend.knowledge.models import Debate, Ipo

log = logging.getLogger(__name__)

VERDICT_SCORE = {"Strong Bull": 2, "Lean Bull": 1, "Neutral": 0, "Lean Bear": -1, "Strong Bear": -2}


def _csv_path():
    return get_settings().resolve(get_settings().data_dir) / "backtest_prices.csv"


def _read_csv(ipo_id: str) -> list[tuple[date, float]]:
    path = _csv_path()
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        rows = [(date.fromisoformat(r["date"]), float(r["close"]))
                for r in csv.DictReader(fh) if r["ipo_id"] == ipo_id]
    return sorted(rows)


def _write_csv(ipo_id: str, prices: list[tuple[date, float]]) -> None:
    path = _csv_path()
    existing = []
    if path.exists():
        with path.open(encoding="utf-8", newline="") as fh:
            existing = [r for r in csv.DictReader(fh) if r["ipo_id"] != ipo_id]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["ipo_id", "date", "close"])
        w.writeheader()
        w.writerows(existing)
        w.writerows({"ipo_id": ipo_id, "date": d.isoformat(), "close": round(c, 2)}
                    for d, c in prices)


def fetch_prices(ipo: Ipo) -> tuple[list[tuple[date, float]], str]:
    """Daily closes from the listing date to today, and where they came from."""
    cache = Cache("prices")
    key = cache.key(ipo.ipo_id, date.today().isoformat())
    hit = cache.get_json(key)
    if hit:
        return [(date.fromisoformat(d), c) for d, c in hit], "yfinance (cached)"
    if ipo.nse_symbol and ipo.listing_date:
        try:
            import yfinance as yf

            hist = yf.Ticker(f"{ipo.nse_symbol}.NS").history(
                start=ipo.listing_date.isoformat(),
                end=(date.today() + timedelta(days=1)).isoformat(), auto_adjust=False)
            prices = [(idx.date(), float(row["Close"])) for idx, row in hist.iterrows()]
            if prices:
                cache.set_json(key, [(d.isoformat(), c) for d, c in prices])
                _write_csv(ipo.ipo_id, prices)
                return prices, "yfinance"
        except Exception as exc:  # network, delisted symbol, API change
            log.warning("yfinance failed for %s: %s", ipo.nse_symbol, exc)
    return _read_csv(ipo.ipo_id), "csv"


def backtest(session: Session) -> list[dict]:
    """One row per listed IPO with a completed debate."""
    out = []
    for ipo in session.scalars(select(Ipo).where(Ipo.status == "listed")):
        debate = session.scalars(select(Debate).where(Debate.ipo_id == ipo.ipo_id,
                                                      Debate.status == "done")
                                 .order_by(Debate.created_at.desc())).first()
        if debate is None:
            continue  # only IPOs the system has actually judged
        row = {"ipo_id": ipo.ipo_id, "company": ipo.company, "listing_date":
               ipo.listing_date.isoformat() if ipo.listing_date else None,
               "issue_price": ipo.price_band_high, "symbol": ipo.nse_symbol,
               "verdict": None, "confidence": None, "debate_id": None,
               "listing_close": None, "last_close": None, "last_date": None,
               "listing_gain_pct": None, "current_return_pct": None, "hit": None,
               "price_source": None}
        v = json.loads(debate.verdict_json or "{}")
        row.update(verdict=v.get("verdict"), confidence=v.get("confidence"),
                   debate_id=debate.debate_id)
        prices, source = fetch_prices(ipo)
        row["price_source"] = source if prices else "unavailable"
        if prices and ipo.price_band_high:
            issue = ipo.price_band_high
            listing_close, (last_d, last_close) = prices[0][1], prices[-1]
            row.update(listing_close=round(listing_close, 2), last_close=round(last_close, 2),
                       last_date=last_d.isoformat(),
                       listing_gain_pct=round((listing_close / issue - 1) * 100, 2),
                       current_return_pct=round((last_close / issue - 1) * 100, 2))
            if row["verdict"] is not None:
                score = VERDICT_SCORE[row["verdict"]]
                row["hit"] = None if score == 0 else (score > 0) == (row["listing_gain_pct"] > 0)
        out.append(row)
    return out
