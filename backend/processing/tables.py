"""Extract restated P&L, balance sheet and cash-flow figures into structured rows.

Pipeline per document:

1. Candidate pages: pages in the financial sections whose top lines carry a statement title
   ("Restated Consolidated Statement of Profit and Loss", "... Assets and Liabilities",
   "... Cash Flows"). A statement continuing onto the next page inherits the title.
2. Period columns: dates in the page header ("March 31, 2026", "Fiscal 2025",
   "June 30, 2026") in reading order -> ``FY2026``, ``FY2025``, ``STUB-2026-06``.
3. Rows: pdfplumber text lines; trailing numeric tokens are the values, the rest is the label.
   With N periods the last N numbers are used (a leading note number is ignored).
4. Labels map to canonical line items (``line_items.py``); values are converted to INR million.

The first value found for (statement, item, period, basis) wins, and candidate pages are
visited with the full restated statements before the summary tables, so later mentions
(MD&A, notes) cannot overwrite them. A per-IPO override CSV can correct any value; overridden
rows are flagged.
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import pdfplumber

from backend.processing.line_items import match_context, match_line_item
from backend.processing.pdf_parser import ParsedDoc
from backend.processing.sections import SectionStart, section_for_page

log = logging.getLogger(__name__)

STATEMENT_TITLES = {
    "balance_sheet": re.compile(r"statement of assets and liabilities|balance sheet", re.I),
    "pnl": re.compile(r"statement of profit (and|&) loss|profit (and|&) loss (statement|account)",
                      re.I),
    "cash_flow": re.compile(r"statement of cash flows?|cash flow statement", re.I),
}
FINANCIAL_SECTIONS = ["Financial Information", "Summary of Financial Information",
                      "Offer Document Summary", "Other Financial Information"]

UNIT_TO_MN = {"million": 1.0, "crore": 10.0, "lakh": 0.1, "thousand": 0.001, "rupees": 1e-6}
_UNIT_RX = re.compile(
    r"(?:₹|rs\.?|inr|`|₹)\s*(?:in\s*)?(million|mn|crores?|lakhs?|lacs?|thousands?)"
    r"|in\s*(?:₹|rs\.?|inr|`|₹)?\s*(million|mn|crores?|lakhs?|lacs?|thousands?)", re.I)

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
           "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DATE_RXS = [
    re.compile(rf"\b{_MON}\s*(\d{{1,2}})(?:st|nd|rd|th)?,?\s*(\d{{4}})\b", re.I),  # March 31, 2026
    re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s*{_MON},?\s*(\d{{4}})\b", re.I),  # 31 March 2026
]
_FISCAL_RX = re.compile(r"\b(?:fiscal(?:\s+year)?|fy)\s*'?(20\d{2}|\d{2})\b", re.I)
_NUM_TOKEN = re.compile(r"^(?:\(-?NUM\)|-?NUM)$".replace(
    "NUM", r"(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?"))
_NIL_TOKENS = {"-", "–", "—", "nil", "*"}


@dataclass
class FinRow:
    """One extracted figure, ready to become a ``FinancialRow``."""

    statement: str
    line_item: str
    raw_label: str
    period: str
    period_end: date | None
    basis: str
    value_raw: float
    unit: str
    value_inr_mn: float
    page: int
    section: str | None
    is_override: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def parse_number(token: str) -> float | None:
    """Parse ``1,46,885.30`` / ``(2,345.10)`` / ``-`` into a float; ``None`` if not numeric."""
    t = token.strip().replace("−", "-")
    if t.lower() in _NIL_TOKENS:
        return 0.0
    if not _NUM_TOKEN.match(t):
        return None
    neg = t.startswith("(") and t.endswith(")") or t.startswith("-")
    value = float(t.strip("()").replace(",", "").lstrip("-"))
    return -value if neg else value


def split_row(line: str) -> tuple[str, list[float]]:
    """Split a text line into ``(label, trailing numbers)``."""
    tokens = line.split()
    numbers: list[float] = []
    while tokens:
        value = parse_number(tokens[-1])
        if value is None:
            break
        numbers.append(value)
        tokens.pop()
    return " ".join(tokens), numbers[::-1]


def period_label(month: int, year: int) -> tuple[str, date]:
    """March year-ends are fiscal years (``FY2026``); other dates are stub periods."""
    import calendar

    end = date(year, month, calendar.monthrange(year, month)[1])
    return (f"FY{year}" if month == 3 else f"STUB-{year}-{month:02d}"), end


def detect_periods(header: str) -> list[tuple[str, date]]:
    """Find period columns in header text, in reading order, without duplicates."""
    found: list[tuple[int, str, date]] = []
    for rx in _DATE_RXS:
        for m in rx.finditer(header):
            g = m.groups()
            mon, year = (g[0], g[2]) if rx is _DATE_RXS[0] else (g[1], g[2])
            label, end = period_label(_MONTHS[mon[:3].lower()], int(year))
            found.append((m.start(), label, end))
    for m in _FISCAL_RX.finditer(header):
        yr = int(m.group(1))
        yr = yr + 2000 if yr < 100 else yr
        label, end = period_label(3, yr)
        found.append((m.start(), label, end))
    if len({label for _, label, _ in found}) < 2:
        # "As at March 31," on one line and "2026 2025 2024" on the next.
        years = [(m.start(), m.group(1)) for m in re.finditer(r"\b(20\d{2})\b", header)]
        if len({y for _, y in years}) >= 2 and re.search(r"march\s*31|31\s*march", header, re.I):
            found = [(pos, *period_label(3, int(y))) for pos, y in years]
    out: list[tuple[str, date]] = []
    for _pos, label, end in sorted(found, key=lambda x: x[0]):
        if label not in [p for p, _ in out]:
            out.append((label, end))
    return out


def detect_unit(text: str) -> str | None:
    """Return the unit a page states (``million`` / ``crore`` / ``lakh`` / ``thousand``)."""
    m = _UNIT_RX.search(text)
    if not m:
        return None
    word = (m.group(1) or m.group(2)).lower()
    for unit in ("million", "crore", "lakh", "thousand"):
        if word.startswith(unit[:3]) or (unit == "lakh" and word.startswith("lac")):
            return unit
    return "million" if word == "mn" else None


def statement_of_page(lines: list[str], max_lines: int = 12) -> str | None:
    """Statement type if a title appears in the page's top lines."""
    top = " ".join(lines[:max_lines])
    if "notes to" in top.lower() and "forming part" in top.lower():
        return None
    for statement, rx in STATEMENT_TITLES.items():
        if rx.search(top):
            return statement
    return None


def _candidate_pages(parsed: ParsedDoc, starts: list[SectionStart],
                     continuation: int = 2) -> list[int]:
    """Pages whose top lines carry a statement title, plus the pages right after them.

    Uses the cheap PyMuPDF text so pdfplumber only opens a few dozen pages. Ordered with the
    full restated statements first, then the summary tables, then anything else.
    """
    titled = {p.number for p in parsed.pages
              if statement_of_page([ln.text for ln in p.lines]) is not None}
    wanted = sorted({n + k for n in titled for k in range(continuation + 1)
                     if n + k <= parsed.n_pages})
    by_section: dict[str, list[int]] = {}
    for number in wanted:
        by_section.setdefault(section_for_page(starts, number), []).append(number)
    ordered: list[int] = []
    for sec in FINANCIAL_SECTIONS:
        ordered.extend(by_section.pop(sec, []))
    for pages in by_section.values():
        ordered.extend(pages)
    return ordered


def extract_page_rows(lines: list[str], statement: str, basis: str, unit: str,
                      page_no: int, section: str | None,
                      periods: list[tuple[str, date]]) -> list[FinRow]:
    """Turn the text lines of one statement page into rows."""
    rows: list[FinRow] = []
    context: str | None = None
    n = len(periods)
    factor = UNIT_TO_MN[unit]
    for line in lines:
        label, numbers = split_row(line)
        if not numbers:
            context = match_context(label) or context
            continue
        if len(numbers) < n or not label:
            continue
        item = match_line_item(statement, label, context)
        if item is None:
            continue
        per_share = item.endswith("_eps")  # EPS is in rupees per share, never scaled
        for (period, end), value in zip(periods, numbers[-n:]):
            rows.append(FinRow(statement, item, label[:500], period, end, basis, value,
                               "inr_per_share" if per_share else unit,
                               value if per_share else round(value * factor, 4),
                               page_no, section))
    return rows


def extract_financials(path: Path, starts: list[SectionStart], parsed: ParsedDoc) -> list[FinRow]:
    """Extract restated statement rows from a PDF (see module docstring)."""
    candidates = _candidate_pages(parsed, starts)
    seen: set[tuple[str, str, str, str]] = set()
    rows: list[FinRow] = []
    doc_unit = detect_unit(" ".join(p.text[:3000] for p in parsed.pages[:60])) or "million"
    with pdfplumber.open(path) as pdf:
        prev: tuple[int, str, list] | None = None  # (page, statement, periods) for continuations
        for page_no in candidates:
            text_lines = [ln["text"] for ln in pdf.pages[page_no - 1].extract_text_lines()]
            statement = statement_of_page(text_lines)
            header = "\n".join(text_lines[:15])
            periods = detect_periods(header)
            if statement is None and prev and prev[0] == page_no - 1:
                statement = prev[1]
                periods = periods or prev[2]
            if statement is None or len(periods) < 2:
                prev = None
                continue
            page_text = "\n".join(text_lines)
            unit = detect_unit(page_text) or doc_unit
            basis = "standalone" if re.search(r"standalone", header, re.I) else "consolidated"
            section = section_for_page(starts, page_no)
            page_rows = extract_page_rows(text_lines, statement, basis, unit, page_no, section,
                                          periods)
            prev = (page_no, statement, periods) if page_rows else None
            for r in page_rows:
                key = (r.statement, r.line_item, r.period, r.basis)
                if key not in seen:
                    seen.add(key)
                    rows.append(r)
    log.info("Extracted %d financial rows from %s", len(rows), path.name)
    return rows


def apply_overrides(rows: list[FinRow], csv_path: Path) -> list[FinRow]:
    """Apply manual corrections from ``financials_override.csv`` (if present).

    Columns: statement, line_item, period, value_inr_mn, page, basis (optional), note.
    """
    if not csv_path.exists():
        return rows
    index = {(r.statement, r.line_item, r.period, r.basis): i for i, r in enumerate(rows)}
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        for rec in csv.DictReader(fh):
            basis = rec.get("basis") or "consolidated"
            key = (rec["statement"], rec["line_item"], rec["period"], basis)
            value = float(rec["value_inr_mn"])
            year = int(rec["period"][2:6]) if rec["period"].startswith("FY") else None
            row = FinRow(key[0], key[1], f"override: {rec.get('note', '')}"[:500], key[2],
                         date(year, 3, 31) if year else None, basis, value, "million", value,
                         int(rec.get("page") or 0), None, is_override=1)
            if key in index:
                rows[index[key]] = row
            else:
                rows.append(row)
    return rows
