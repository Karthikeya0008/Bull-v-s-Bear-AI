from datetime import date

import pytest

from backend.processing.line_items import match_line_item, normalize_label
from backend.processing.pdf_parser import parse_pdf
from backend.processing.sections import detect_sections
from backend.processing.tables import (
    detect_periods,
    detect_unit,
    extract_financials,
    extract_page_rows,
    parse_number,
    split_row,
)


@pytest.mark.parametrize("token,expected", [
    ("1,46,885.30", 146885.30), ("12,345", 12345.0), ("(2,345.10)", -2345.10),
    ("-12.5", -12.5), ("-", 0.0), ("–", 0.0), ("Nil", 0.0), ("0.75", 0.75),
    ("Revenue", None), ("2026)", None), ("1,2", None),
])
def test_parse_number(token, expected):
    assert parse_number(token) == expected


def test_split_row_separates_label_and_trailing_numbers():
    assert split_row("Finance costs 27 4,500.00 (5,200.00) -") == ("Finance costs", [27, 4500.0, -5200.0, 0.0])
    assert split_row("Current liabilities") == ("Current liabilities", [])


def test_detect_periods_full_dates_and_stub():
    header = "Particulars June 30, 2026 March 31, 2026 31 March 2025 March 31, 2024"
    assert [p for p, _ in detect_periods(header)] == ["STUB-2026-06", "FY2026", "FY2025", "FY2024"]
    assert detect_periods(header)[0][1] == date(2026, 6, 30)


def test_detect_periods_fiscal_labels_dedup_and_split_header():
    assert [p for p, _ in detect_periods("Fiscal 2026 Fiscal 2025 FY 2024 Fiscal 2026")] == \
        ["FY2026", "FY2025", "FY2024"]
    assert [p for p, _ in detect_periods("As at March 31,\n2026 2025 2024")] == \
        ["FY2026", "FY2025", "FY2024"]


def test_detect_unit():
    assert detect_unit("(₹ in million, unless otherwise stated)") == "million"
    assert detect_unit("(Rs. in crores)") == "crore"
    assert detect_unit("(in ₹ lakhs)") == "lakh"
    assert detect_unit("no unit here") is None


def test_line_item_matching_and_context():
    assert normalize_label("Restated profit/(loss) for the year") == "restated profit loss for the year"
    assert match_line_item("pnl", "Restated profit/(loss) for the year") == "profit_after_tax"
    assert match_line_item("pnl", "Profit before exceptional items and tax") == \
        "profit_before_exceptional_and_tax"
    assert match_line_item("pnl", "Profit before tax") == "profit_before_tax"
    assert match_line_item("balance_sheet", "(i) Borrowings", "non_current_liabilities") == \
        "non_current_borrowings"
    assert match_line_item("balance_sheet", "Borrowings", "current_liabilities") == "current_borrowings"
    assert match_line_item("balance_sheet", "Borrowings") is None  # ambiguous without context


def test_extract_page_rows_uses_last_n_numbers_and_converts_units():
    periods = detect_periods("March 31, 2026 March 31, 2025")
    lines = ["Non-current liabilities", "Borrowings 18 1,000.00 2,000.00",
             "Current liabilities", "Borrowings 19 300.00 (400.00)", "Some unknown line 1 2"]
    rows = extract_page_rows(lines, "balance_sheet", "consolidated", "crore", 10, "FI", periods)
    got = {(r.line_item, r.period): r.value_inr_mn for r in rows}
    assert got == {("non_current_borrowings", "FY2026"): 10000.0,
                   ("non_current_borrowings", "FY2025"): 20000.0,
                   ("current_borrowings", "FY2026"): 3000.0,
                   ("current_borrowings", "FY2025"): -4000.0}


def test_extract_financials_from_pdf(drhp_pdf):
    parsed = parse_pdf(drhp_pdf)
    rows = extract_financials(drhp_pdf, detect_sections(parsed), parsed)
    got = {(r.line_item, r.period): r for r in rows}
    assert got[("revenue_from_operations", "FY2026")].value_inr_mn == pytest.approx(146885.30)
    assert got[("other_income", "FY2024")].value_inr_mn == pytest.approx(-150.25)
    assert got[("profit_after_tax", "FY2025")].value_inr_mn == pytest.approx(23500.0)
    assert got[("finance_costs", "FY2024")].page == 6
    assert all(r.statement == "pnl" and r.basis == "consolidated" for r in rows)
