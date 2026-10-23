"""Pure financial formulas. Every function takes plain numbers and returns a number (or None).

These are unit-tested against hand-computed values in ``tests/test_metrics.py``.
"""

from __future__ import annotations

import statistics


def safe_div(a: float | None, b: float | None) -> float | None:
    """``a / b``, or ``None`` when either is missing or ``b`` is zero."""
    if a is None or b is None or b == 0:
        return None
    return a / b


def growth(current: float | None, previous: float | None) -> float | None:
    """Year-on-year growth as a fraction; ``None`` if the base is missing or not positive."""
    if current is None or previous is None or previous <= 0:
        return None
    return current / previous - 1.0


def cagr(last: float | None, first: float | None, years: int) -> float | None:
    """Compound annual growth rate between two positive values ``years`` apart."""
    if last is None or first is None or first <= 0 or last <= 0 or years <= 0:
        return None
    return (last / first) ** (1.0 / years) - 1.0


def debt_to_equity(total_borrowings: float | None, total_equity: float | None) -> float | None:
    """Total borrowings / total equity. Negative equity makes the ratio meaningless -> None."""
    if total_equity is not None and total_equity <= 0:
        return None
    return safe_div(total_borrowings, total_equity)


def interest_coverage(profit_before_tax: float | None, finance_costs: float | None) -> float | None:
    """EBIT / finance costs, with EBIT = profit before tax + finance costs."""
    if profit_before_tax is None or finance_costs is None:
        return None
    return safe_div(profit_before_tax + finance_costs, finance_costs)


def ebitda(profit_before_tax: float | None, finance_costs: float | None,
           depreciation: float | None, other_income: float | None = 0.0) -> float | None:
    """EBITDA as defined in most DRHPs: PBT + finance costs + D&A - other income."""
    if None in (profit_before_tax, finance_costs, depreciation):
        return None
    return profit_before_tax + finance_costs + depreciation - (other_income or 0.0)


def altman_z_em(working_capital: float, retained_earnings: float, ebit: float,
                book_equity: float, total_assets: float, total_liabilities: float) -> float | None:
    """Altman Z''-Score, emerging-markets variant (Altman, 2005).

    Z'' = 3.25 + 6.56*X1 + 3.26*X2 + 6.72*X3 + 1.05*X4 with
    X1 = working capital / TA, X2 = retained earnings / TA, X3 = EBIT / TA,
    X4 = book equity / total liabilities. Zones: > 5.85 safe, 4.35-5.85 grey, < 4.35 distress.
    """
    if not total_assets or not total_liabilities:
        return None
    x1 = working_capital / total_assets
    x2 = retained_earnings / total_assets
    x3 = ebit / total_assets
    x4 = book_equity / total_liabilities
    return 3.25 + 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4


def altman_zone(z: float | None) -> str | None:
    """Classify an EM Z''-Score."""
    if z is None:
        return None
    return "safe" if z > 5.85 else "grey" if z >= 4.35 else "distress"


BENEISH_COEFFS = {"const": -4.84, "DSRI": 0.920, "GMI": 0.528, "AQI": 0.404, "SGI": 0.892,
                  "DEPI": 0.115, "SGAI": -0.172, "TATA": 4.679, "LVGI": -0.327}
BENEISH_THRESHOLD = -1.78


def beneish_indices(cur: dict[str, float], prev: dict[str, float]) -> dict[str, float]:
    """The eight Beneish (1999) indices from two consecutive years.

    Keys required in ``cur``/``prev``: sales, receivables, cogs, current_assets, ppe,
    total_assets, depreciation, sga, current_liabilities, long_term_debt; and in ``cur``
    also net_income and cfo.
    """
    def gm(d):
        return (d["sales"] - d["cogs"]) / d["sales"]

    def aq(d):
        return 1 - (d["current_assets"] + d["ppe"]) / d["total_assets"]

    def dep_rate(d):
        return d["depreciation"] / (d["depreciation"] + d["ppe"])

    def lev(d):
        return (d["current_liabilities"] + d["long_term_debt"]) / d["total_assets"]

    return {
        "DSRI": (cur["receivables"] / cur["sales"]) / (prev["receivables"] / prev["sales"]),
        "GMI": gm(prev) / gm(cur),
        "AQI": aq(cur) / aq(prev),
        "SGI": cur["sales"] / prev["sales"],
        "DEPI": dep_rate(prev) / dep_rate(cur),
        "SGAI": (cur["sga"] / cur["sales"]) / (prev["sga"] / prev["sales"]),
        "LVGI": lev(cur) / lev(prev),
        "TATA": (cur["net_income"] - cur["cfo"]) / cur["total_assets"],
    }


def beneish_m(indices: dict[str, float]) -> float:
    """Beneish 8-variable M-Score; above -1.78 flags likely earnings manipulation."""
    return BENEISH_COEFFS["const"] + sum(BENEISH_COEFFS[k] * v for k, v in indices.items())


def price_to_earnings(price: float | None, eps: float | None) -> float | None:
    """Price / EPS; ``None`` for loss-making companies (EPS <= 0)."""
    if eps is None or eps <= 0:
        return None
    return safe_div(price, eps)


def median(values: list[float]) -> float | None:
    """Median of the non-missing values."""
    vals = [v for v in values if v is not None]
    return statistics.median(vals) if vals else None
