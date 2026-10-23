"""Extract restated P&L, balance sheet and cash-flow figures into structured rows.

Pipeline per document:

1. Candidate pages: pages whose top lines carry a statement title ("Restated Consolidated
   Statement of Profit and Loss", "... Assets and Liabilities", "... Cash Flows") and the
   pages right after them (a statement continuing onto the next page keeps its columns).
2. Lines: pdfplumber words grouped into lines by their vertical position. Numbers split by
   stray spaces ("1 26.52") are re-joined when the fragments almost touch.
3. Period columns: dates in the header ("June 30, 2026", "March 31, 2026", "Fiscal 2025")
   -> ``STUB-2026-06``, ``FY2026``, ``FY2025``, ordered by their x position on the page.
4. Rows: trailing numeric tokens are the values, the rest is the label. Values are mapped to
   columns by count (extra leading numbers are note references) or by nearest x position.
5. Labels map to canonical line items (``line_items.py``); values are converted to INR
   million (EPS stays in rupees per share).

The first value found for (statement, item, period, basis) wins. Candidate pages are visited
with the full restated statements first, then the summary tables, so later mentions cannot
overwrite them. A per-IPO override CSV can correct any value; overridden rows are flagged.
"""

from __future__ import annotations

import calendar
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
    "other": re.compile(r"statement of changes in equity|notes? to (the )?restated|"
                        r"significant accounting policies", re.I),
    "balance_sheet": re.compile(r"statement of assets and liabilities|balance sheet", re.I),
    "pnl": re.compile(r"statement of profit (and|&) loss|profit (and|&) loss (statement|account)",
                      re.I),
    "cash_flow": re.compile(r"statement of cash flows?|cash flow statement", re.I),
}
FINANCIAL_SECTIONS = ["Financial Information", "Summary of Financial Information",
                      "Offer Document Summary", "Other Financial Information"]

UNIT_TO_MN = {"million": 1.0, "crore": 10.0, "lakh": 0.1, "thousand": 0.001, "rupees": 1e-6}
_UNIT_RX = re.compile(
    r"(?:₹|rs\.?|inr|`|₹|rupees)\s*(?:in\s*)?(millions?|mn|crores?|lakhs?|lacs?|thousands?)"
    r"|in\s*(?:₹|rs\.?|inr|`|₹|indian rupees)?\s*(millions?|mn|crores?|lakhs?|lacs?|"
    r"thousands?)", re.I)

_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
           "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
_DATE_RXS = [
    re.compile(rf"\b{_MON}\s*(\d{{1,2}})(?:st|nd|rd|th)?,?\s*(\d{{4}})\b", re.I),  # March 31, 2026
    re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s*{_MON},?\s*(\d{{4}})\b", re.I),  # 31 March 2026
]
_FISCAL_RX = re.compile(r"\b(?:fiscal(?:\s+year)?|fy)\s*'?(20\d{2}|\d{2})\b", re.I)
_NUM = r"(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?"
_NUM_TOKEN = re.compile(rf"^(?:\(-?{_NUM}\)|-?{_NUM})$")
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


@dataclass
class TableLine:
    """A text line: label plus positioned numbers ``(x_center, value)``."""

    label: str
    values: list[tuple[float, float]]
    text: str = ""
    token_x: list[float] | None = None  # centre of every token in ``text`` (words mode)


@dataclass
class Column:
    """A period column; ``x`` is its horizontal centre (``None`` = assign by order)."""

    period: str
    end: date
    x: float | None = None


# ------------------------------------------------------------------------------------------
# Token-level parsing
# ------------------------------------------------------------------------------------------
def parse_number(token: str) -> float | None:
    """Parse ``1,46,885.30`` / ``(2,345.10)`` / ``-`` into a float; ``None`` if not numeric."""
    t = token.strip().replace("−", "-")
    if t.lower() in _NIL_TOKENS:
        return 0.0
    if not _NUM_TOKEN.match(t):
        return None
    neg = (t.startswith("(") and t.endswith(")")) or t.startswith("-")
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
    end = date(year, month, calendar.monthrange(year, month)[1])
    return (f"FY{year}" if month == 3 else f"STUB-{year}-{month:02d}"), end


def _period_matches(text: str) -> list[tuple[int, int, str, date]]:
    """``(start, end, label, period_end)`` for every period phrase in ``text``."""
    found = []
    for i, rx in enumerate(_DATE_RXS):
        for m in rx.finditer(text):
            g = m.groups()
            mon, year = (g[0], g[2]) if i == 0 else (g[1], g[2])
            label, end = period_label(_MONTHS[mon[:3].lower()], int(year))
            found.append((m.start(), m.end(), label, end))
    for m in _FISCAL_RX.finditer(text):
        yr = int(m.group(1))
        label, end = period_label(3, yr + 2000 if yr < 100 else yr)
        found.append((m.start(), m.end(), label, end))
    return sorted(found)


def detect_periods(header: str) -> list[tuple[str, date]]:
    """Find period columns in header text, in reading order, without duplicates."""
    found = [(s, label, end) for s, _e, label, end in _period_matches(header)]
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
    if word.startswith(("mil", "mn")):
        return "million"
    if word.startswith("cr"):
        return "crore"
    if word.startswith(("lak", "lac")):
        return "lakh"
    return "thousand"


def statement_of_page(lines: list[str], max_lines: int = 12) -> str | None:
    """Statement type if a title appears in the page's top lines (``other`` = not a statement)."""
    top = " ".join(lines[:max_lines])
    hits = [(m.start(), statement) for statement, rx in STATEMENT_TITLES.items()
            if (m := rx.search(top))]
    return min(hits)[1] if hits else None  # the earliest title on the page wins


# ------------------------------------------------------------------------------------------
# Lines and columns
# ------------------------------------------------------------------------------------------
def lines_from_text(lines: list[str]) -> list[TableLine]:
    """Text-only lines: numbers keep their order but carry no real position."""
    out = []
    for line in lines:
        label, nums = split_row(line)
        out.append(TableLine(label, [(float(j), v) for j, v in enumerate(nums)], line))
    return out


def _is_numeric_fragment(text: str) -> bool:
    return bool(re.fullmatch(r"[\d,().\-−]+", text))


def _should_join(left: str, right: str, gap: float, merge_gap: float) -> bool:
    """Join "1" + "26.52" or "(" + "2.32)" or "1" + ",743.96"; never two whole numbers."""
    if gap >= merge_gap or not (_is_numeric_fragment(left) and _is_numeric_fragment(right)):
        return False
    partial = len(left) == 1 or right[:1] in {",", "."} or left.endswith(("(", ","))
    return partial and parse_number(left + right) is not None


def lines_from_words(words: list[dict], y_tol: float = 2.5,
                     merge_gap: float = 3.5) -> list[TableLine]:
    """Group pdfplumber words into lines and re-join numbers split by stray spaces."""
    rows: list[list[dict]] = []
    cleaned = []
    for w in words:  # drop footnote markers: "8.69*" (not annualised), "^", "#"
        text = re.sub(r"(?<=\d)[*#^†]+$", "", w["text"])
        if text and not re.fullmatch(r"[*#^†]+", text):
            cleaned.append({**w, "text": text})
    for w in sorted(cleaned, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(rows[-1][0]["top"] - w["top"]) <= y_tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    out: list[TableLine] = []
    for row in rows:
        merged: list[dict] = []
        for w in sorted(row, key=lambda w: w["x0"]):
            if merged and _should_join(merged[-1]["text"], w["text"],
                                       w["x0"] - merged[-1]["x1"], merge_gap):
                merged[-1] = {**merged[-1], "text": merged[-1]["text"] + w["text"], "x1": w["x1"]}
            else:
                merged.append(dict(w))
        centers = [(w["x0"] + w["x1"]) / 2 for w in merged]
        values: list[tuple[float, float]] = []
        k = len(merged)
        while k > 0 and (v := parse_number(merged[k - 1]["text"])) is not None:
            values.append((centers[k - 1], v))
            k -= 1
        out.append(TableLine(" ".join(w["text"] for w in merged[:k]), values[::-1],
                             " ".join(w["text"] for w in merged), centers))
    return out


def detect_columns(header: list[TableLine]) -> list[Column]:
    """Period columns from header lines, ordered left to right when positions are known.

    A period phrase's position is the centre of its year token. If a period appears on
    several header lines, the lowest (closest to the data) wins.
    """
    found: dict[str, Column] = {}
    month_marks: list[tuple[float, int]] = []  # (x, month) of every month name in the header
    loose_years: list[tuple[float, int]] = []  # year tokens not part of a full date phrase
    for line in header:
        if not line.token_x:
            continue
        tokens = line.text.split(" ")
        starts, pos = [], 0  # character offset of each token
        for tok in tokens:
            starts.append(pos)
            pos += len(tok) + 1
        used: set[int] = set()
        for s, e, label, end in _period_matches(line.text):
            idx = max(i for i, st in enumerate(starts) if st < e)
            used.update(i for i, st in enumerate(starts) if s <= st < e)
            if idx < len(line.token_x):
                found[label] = Column(label, end, line.token_x[idx])
        for i, tok in enumerate(tokens[:len(line.token_x)]):
            if (m := re.match(_MON + "$", tok.rstrip(","), re.I)):
                month_marks.append((line.token_x[i], _MONTHS[m.group(1).lower()]))
            elif i not in used and re.fullmatch(r"(20\d{2})[,.]?", tok):
                loose_years.append((line.token_x[i], int(tok[:4])))
    # "31st March," on one line and "2026 2025 2024" below it: pair each loose year with the
    # nearest month name above it (or March when the header only speaks of March year-ends).
    march_only = not month_marks and re.search(r"march", " ".join(l.text for l in header), re.I)
    for x, year in loose_years:
        near = min(month_marks, key=lambda mm: abs(mm[0] - x), default=None)
        month = near[1] if near and abs(near[0] - x) <= 60 else 3 if march_only else None
        if month:
            label, end = period_label(month, year)
            found.setdefault(label, Column(label, end, x))
    cols = sorted(found.values(), key=lambda c: c.x)
    if len(cols) >= 2:
        return cols
    return [Column(p, e) for p, e in detect_periods("\n".join(l.text for l in header))]


def assign_columns(values: list[tuple[float, float]], columns: list[Column]) -> dict[str, float]:
    """Map a row's numbers to period columns.

    As many numbers as columns (or more: leading extras are note numbers) -> by order.
    Fewer -> nearest column by x within 60% of the column spacing; blank cells are skipped.
    """
    n = len(columns)
    positioned = all(c.x is not None for c in columns)
    if len(values) == n or (len(values) > n and not positioned):
        return {c.period: v for c, (_x, v) in zip(columns, values[-n:])}
    if not values or not positioned:
        return {}
    spacing = min(b.x - a.x for a, b in zip(columns, columns[1:])) or 1.0
    if len(values) > n:  # note numbers sit left of the first period column
        inside = [(x, v) for x, v in values if x >= columns[0].x - 0.6 * spacing]
        if len(inside) == n:
            return {c.period: v for c, (_x, v) in zip(columns, inside)}
    out: dict[str, float] = {}
    for x, v in values:
        col = min(columns, key=lambda c: abs(c.x - x))
        if abs(col.x - x) <= 0.6 * spacing and col.period not in out:
            out[col.period] = v
    return out


def header_lines(lines: list[TableLine], statement: str, limit: int = 20) -> list[TableLine]:
    """Lines above the first recognised line item or sub-heading."""
    out = []
    for line in lines[:limit]:
        label = line.label.strip().lower()
        if (match_line_item(statement, line.label, "current_liabilities")
                or match_context(line.label)
                or label in {"assets", "income", "equity and liabilities", "expenses"}):
            break
        out.append(line)
    return out


def extract_page_rows(lines: list[TableLine], statement: str, basis: str, unit: str,
                      page_no: int, section: str | None, columns: list[Column]) -> list[FinRow]:
    """Turn the lines of one statement page into rows."""
    rows: list[FinRow] = []
    context: str | None = None
    factor = UNIT_TO_MN[unit]
    ends = {c.period: c.end for c in columns}
    for line in lines:
        if not line.values:
            context = match_context(line.label) or context
            continue
        if not line.label:
            continue
        item = match_line_item(statement, line.label, context)
        if item is None:
            continue
        per_share = item.endswith("_eps")  # EPS is in rupees per share, never scaled
        for period, value in assign_columns(line.values, columns).items():
            rows.append(FinRow(statement, item, line.label[:500], period, ends[period], basis,
                               value, "inr_per_share" if per_share else unit,
                               value if per_share else round(value * factor, 4),
                               page_no, section))
    return rows


# ------------------------------------------------------------------------------------------
# Document level
# ------------------------------------------------------------------------------------------
def _candidate_pages(parsed: ParsedDoc, starts: list[SectionStart],
                     continuation: int = 2) -> list[int]:
    """Pages whose top lines carry a statement title, plus the pages right after them.

    Uses the cheap PyMuPDF text so pdfplumber only opens a few dozen pages. Ordered with the
    full restated statements first, then the summary tables, then anything else.
    """
    titled = {p.number for p in parsed.pages
              if statement_of_page([p.text[:3000]]) not in (None, "other")}
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


def _page_lines(page) -> list[TableLine]:
    return lines_from_words(page.extract_words(x_tolerance=1.5, keep_blank_chars=False))


def extract_financials(path: Path, starts: list[SectionStart], parsed: ParsedDoc) -> list[FinRow]:
    """Extract restated statement rows from a PDF (see module docstring)."""
    candidates = _candidate_pages(parsed, starts)
    seen: set[tuple[str, str, str, str]] = set()
    rows: list[FinRow] = []
    doc_unit = detect_unit(" ".join(p.text[:3000] for p in parsed.pages[:60])) or "million"
    with pdfplumber.open(path) as pdf:
        prev: tuple[int, str, list[Column], str] | None = None  # continuation state
        for page_no in candidates:
            lines = _page_lines(pdf.pages[page_no - 1])
            texts = [ln.text for ln in lines]
            statement = statement_of_page(texts)
            if statement == "other":
                prev = None
                continue
            continued = statement is None and prev is not None and prev[0] == page_no - 1
            if continued:
                statement = prev[1]
            if statement is None:
                prev = None
                continue
            columns = detect_columns(header_lines(lines, statement))
            if len(columns) < 2 and continued:
                columns = prev[2]
            if len(columns) < 2:
                prev = None
                continue
            top = " ".join(texts[:15])
            unit = detect_unit(" ".join(texts[:20])) or doc_unit
            basis = ("consolidated" if re.search(r"consolidated", top, re.I) else
                     "standalone" if re.search(r"standalone", top, re.I) else
                     prev[3] if continued else "consolidated")
            section = section_for_page(starts, page_no)
            page_rows = extract_page_rows(lines, statement, basis, unit, page_no, section, columns)
            prev = (page_no, statement, columns, basis) if page_rows else None
            for r in page_rows:
                key = (r.statement, r.line_item, r.period, r.basis)
                if key not in seen:
                    seen.add(key)
                    rows.append(r)
    # Fall back to a plain "Profit after tax" line where no "Profit for the year" was found.
    for r in [r for r in rows if r.line_item == "profit_after_tax_alt"]:
        if ("pnl", "profit_after_tax", r.period, r.basis) not in seen:
            seen.add(("pnl", "profit_after_tax", r.period, r.basis))
            rows.append(FinRow(**{**r.as_dict(), "line_item": "profit_after_tax"}))
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
