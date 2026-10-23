"""Shared fixtures: a small synthetic DRHP-style PDF and a throwaway SQLite database."""

from __future__ import annotations

from pathlib import Path

import pymupdf as fitz
import pytest

from backend.db import init_db, make_engine

RISK_PARA = ("Our business depends on continued growth in mobile data consumption. Any slowdown "
             "in subscriber additions or a decline in average revenue per user could adversely "
             "affect our results of operations and financial condition. ")


def _page(doc: fitz.Document, items: list[tuple[float, str, float, bool]]) -> None:
    """Add an A4 page; each item is (y, text, font size, bold)."""
    page = doc.new_page(width=595, height=842)
    for y, text, size, bold in items:
        page.insert_text((50, y), text, fontsize=size, fontname="hebo" if bold else "helv")


def _body(start_y: float, n_lines: int, text: str = RISK_PARA) -> list[tuple[float, str, float, bool]]:
    words, lines, cur = text.split() * 4, [], ""
    for w in words:
        if len(cur) + len(w) > 85:
            lines.append(cur)
            cur = ""
        cur += w + " "
    lines.append(cur)
    return [(start_y + 14 * i, lines[i % len(lines)].strip(), 10, False) for i in range(n_lines)]


@pytest.fixture(scope="session")
def drhp_pdf(tmp_path_factory) -> Path:
    """Seven-page fake offer document with a TOC, four sections and a restated P&L."""
    path = tmp_path_factory.mktemp("pdf") / "DRHP_2026-01-01.pdf"
    doc = fitz.open()
    _page(doc, [(100, "DRAFT RED HERRING PROSPECTUS", 18, True), (140, "ACME LIMITED", 16, True)]
          + _body(200, 5))
    _page(doc, [(60, "TABLE OF CONTENTS", 14, True),
                (100, "RISK FACTORS ........ 3", 11, True),
                (120, "OBJECTS OF THE OFFER ........ 5", 11, True),
                (140, "FINANCIAL INFORMATION ........ 6", 11, True),
                (160, "OUTSTANDING LITIGATION AND MATERIAL DEVELOPMENTS ........ 7", 11, True)])
    _page(doc, [(60, "SECTION II: RISK FACTORS", 14, True)] + _body(100, 40))
    _page(doc, _body(60, 40))
    _page(doc, [(60, "Tail of the last risk factor about spectrum renewal costs.", 10, False),
                (150, "OBJECTS OF THE OFFER", 14, True),
                (190, "The net proceeds will be used for repayment or prepayment of borrowings", 10,
                 False),
                (204, "availed by our Company of up to Rs 25,000 million and general corporate", 10,
                 False),
                (218, "purposes, subject to applicable law.", 10, False)])
    _page(doc, [(60, "FINANCIAL INFORMATION", 14, True),
                (90, "Restated Consolidated Statement of Profit and Loss", 12, True),
                (110, "(Rs in million)", 9, False),
                (130, "Particulars Note March 31, 2026 March 31, 2025 March 31, 2024", 9, True),
                (150, "Revenue from operations 25 1,46,885.30 1,19,117.00 98,700.50", 9, False),
                (165, "Other income 26 2,100.00 1,800.00 (150.25)", 9, False),
                (180, "Total income 1,48,985.30 1,20,917.00 98,550.25", 9, False),
                (195, "Finance costs 27 4,500.00 5,200.00 6,100.00", 9, False),
                (210, "Profit before tax 40,100.00 31,000.00 22,000.00", 9, False),
                (225, "Restated profit/(loss) for the year 30,049.10 23,500.00 16,000.00", 9,
                 False)])
    _page(doc, [(60, "OUTSTANDING LITIGATION AND MATERIAL DEVELOPMENTS", 14, True)]
          + _body(100, 10, "There are 14 outstanding criminal proceedings against our Company. "))
    doc.save(path)
    doc.close()
    return path


@pytest.fixture
def engine(tmp_path):
    """A fresh SQLite database with the full schema."""
    eng = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    init_db(eng)
    yield eng
    eng.dispose()
