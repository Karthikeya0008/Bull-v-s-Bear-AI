"""Metric formulas against hand-computed values."""

import pytest

from backend.metrics import formulas as F
from backend.metrics.engine import Financials, compute
from backend.knowledge.models import FinancialRow, Ipo


def test_basic_ratios():
    assert F.debt_to_equity(500, 1000) == pytest.approx(0.5)
    assert F.debt_to_equity(500, -10) is None  # negative equity: ratio is meaningless
    assert F.interest_coverage(300, 100) == pytest.approx(4.0)  # (300 + 100) / 100
    assert F.interest_coverage(300, 0) is None
    assert F.growth(120, 100) == pytest.approx(0.2)
    assert F.growth(120, 0) is None
    assert F.cagr(121, 100, 2) == pytest.approx(0.1)
    assert F.ebitda(300, 100, 50, 20) == pytest.approx(430)  # 300 + 100 + 50 - 20


def test_altman_z_em_hand_computed():
    # X1 = 200/1000, X2 = 300/1000, X3 = 150/1000, X4 = 600/400
    # Z'' = 3.25 + 6.56*0.2 + 3.26*0.3 + 6.72*0.15 + 1.05*1.5 = 8.123
    z = F.altman_z_em(working_capital=200, retained_earnings=300, ebit=150, book_equity=600,
                      total_assets=1000, total_liabilities=400)
    assert z == pytest.approx(8.123)
    assert F.altman_zone(z) == "safe"
    assert F.altman_zone(5.0) == "grey"
    assert F.altman_zone(4.0) == "distress"


def _year(**kw):
    base = dict(sales=1000, receivables=100, cogs=600, current_assets=400, ppe=300,
                total_assets=1000, depreciation=50, sga=100, current_liabilities=200,
                long_term_debt=100, net_income=80, cfo=80)
    base.update(kw)
    return base


def test_beneish_neutral_company_is_minus_2_48():
    # Identical years and NI == CFO -> every index is 1 and TATA = 0:
    # M = -4.84 + 0.920 + 0.528 + 0.404 + 0.892 + 0.115 - 0.172 - 0.327 = -2.48
    idx = F.beneish_indices(_year(), _year())
    assert all(idx[k] == pytest.approx(1.0) for k in ("DSRI", "GMI", "AQI", "SGI", "DEPI", "SGAI", "LVGI"))
    assert idx["TATA"] == pytest.approx(0.0)
    assert F.beneish_m(idx) == pytest.approx(-2.48)


def test_beneish_receivables_jump_raises_score():
    # Receivables double while sales stay flat: DSRI = 2 -> M rises by 0.920
    idx = F.beneish_indices(_year(receivables=200), _year())
    assert idx["DSRI"] == pytest.approx(2.0)
    assert F.beneish_m(idx) == pytest.approx(-2.48 + 0.920)


def test_price_to_earnings_and_median():
    assert F.price_to_earnings(1119, 33.59) == pytest.approx(33.3135, rel=1e-4)
    assert F.price_to_earnings(100, -2) is None
    assert F.median([10, None, 30, 20]) == 20


def _rows(values: dict[tuple[str, str], float]) -> list[FinancialRow]:
    return [FinancialRow(ipo_id="x", doc_id="d", statement="pnl", line_item=item, raw_label=item,
                         period=p, basis="consolidated", value_raw=v, unit="million",
                         value_inr_mn=v, page=10 + i) for i, ((item, p), v) in enumerate(values.items())]


def test_engine_traceability_and_graceful_skip():
    fin = Financials(_rows({
        ("revenue_from_operations", "FY2026"): 1200, ("revenue_from_operations", "FY2025"): 1000,
        ("profit_after_tax", "FY2026"): 120, ("profit_after_tax", "FY2025"): 100,
        ("profit_before_tax", "FY2026"): 160, ("finance_costs", "FY2026"): 40,
        ("non_current_borrowings", "FY2026"): 300, ("current_borrowings", "FY2026"): 100,
        ("total_equity", "FY2026"): 800, ("basic_eps", "FY2026"): 12.0,
    }))
    ipo = Ipo(ipo_id="x", company="X Ltd", issuer_norm="x", price_band_high=240,
              fresh_issue_cr=750, ofs_cr=250)
    by_name = {m.name: m for m in compute(ipo, fin)}
    assert by_name["debt_to_equity"].value == pytest.approx(0.5)       # 400 / 800
    assert by_name["interest_coverage"].value == pytest.approx(5.0)    # (160 + 40) / 40
    assert by_name["revenue_growth"].value == pytest.approx(20.0)
    assert by_name["pat_margin"].value == pytest.approx(10.0)
    assert by_name["pe_upper_band"].value == pytest.approx(20.0)       # 240 / 12
    assert by_name["ofs_share"].value == pytest.approx(25.0)           # 250 / 1000
    # every input carries its source page
    assert by_name["interest_coverage"].pages() == [14, 15]
    # Beneish needs balance-sheet items that are missing: skipped with a reason, not an error
    assert by_name["beneish_m"].status == "skipped" and "missing" in by_name["beneish_m"].note
