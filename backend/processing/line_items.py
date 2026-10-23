"""Canonical financial line items and the label variants used in Indian offer documents.

Restated statements follow Schedule III of the Companies Act, but wording varies
("Profit for the year", "Restated profit/(loss) for the period", ...). Labels are normalised
and matched against these patterns; the first match wins, so specific patterns come first.
Some labels ("Borrowings") are ambiguous and are resolved by the current sub-heading
(non-current vs current liabilities).
"""

from __future__ import annotations

import re

# statement -> list of (canonical item, regex on the normalised label)
LINE_ITEMS: dict[str, list[tuple[str, str]]] = {
    "pnl": [
        ("revenue_from_operations",
         r"(restated )?(total )?revenue from operations( net)?|income from operations"),
        ("other_income", r"other income"),
        ("total_income", r"total (revenue|income)"),
        ("cost_of_materials", r"cost of (raw )?materials? consumed"),
        ("purchases_stock_in_trade", r"purchases? of stock in trade"),
        ("employee_benefits_expense", r"employee benefits? expenses?"),
        ("finance_costs", r"finance costs?|interest expenses?"),
        ("depreciation_amortisation",
         r"depreciation (and|&) amorti[sz]ation( and impairment)?( expenses?)?|depreciation"),
        ("other_expenses", r"other expenses"),
        ("total_expenses", r"total expenses"),
        ("ebitda", r"ebitda"),
        ("exceptional_items", r"exceptional items?( net)?"),
        ("profit_before_exceptional_and_tax",
         r"(restated )?profit (loss )?before exceptional items? and tax"),
        ("profit_before_tax", r"(restated )?profit (loss )?before tax(es)?|pbt|"
                              r"(restated )?profit (loss )?before share of .*"),
        ("tax_expense", r"total tax expenses?( credit)?|tax expenses?( credit)?|total tax"),
        # "Profit for the year" is the bottom line (after share of associates/JVs); a plain
        # "Profit after tax" line is only used when the former is absent (see tables.py).
        ("profit_after_tax",
         r"(restated )?(net )?profit (loss )?(after tax )?for the (year|period|year period|period year)"),
        ("profit_after_tax_alt", r"(restated )?(net )?profit (loss )?after tax(es)?|pat"),
        ("total_comprehensive_income",
         r"(restated )?total comprehensive income (loss )?for the (year|period|year period)"),
        ("basic_eps", r"basic( eps)?|basic earnings per (equity )?share.*|earnings per share basic"),
        ("diluted_eps", r"diluted( eps)?|diluted earnings per (equity )?share.*"),
    ],
    "balance_sheet": [
        ("property_plant_equipment", r"property plant (and|&) equipment"),
        ("capital_wip", r"capital work in progress"),
        ("goodwill", r"goodwill"),
        ("intangible_assets", r"other intangible assets|intangible assets"),
        ("total_non_current_assets", r"total non current assets"),
        ("inventories", r"inventories"),
        ("trade_receivables", r"trade receivables"),
        ("cash_and_equivalents", r"cash (and|&) cash equivalents"),
        ("other_bank_balances", r"(other )?bank balances other than.*|other bank balances"),
        ("total_current_assets", r"total current assets"),
        ("total_assets", r"total assets"),
        ("equity_share_capital", r"(equity )?share capital"),
        ("other_equity", r"other equity|reserves (and|&) surplus"),
        ("equity_attributable_to_owners",
         r"equity attributable to (the )?(equity holders|owners|shareholders) of (the )?"
         r"(parent|company|holding company)"),
        ("non_controlling_interest", r"non controlling interests?"),
        ("total_equity", r"total equity|net worth|total shareholders funds"),
        ("lease_liabilities", r"lease liabilities"),
        ("borrowings", r"borrowings|long term borrowings|short term borrowings"),
        ("trade_payables", r"trade payables"),
        ("total_non_current_liabilities", r"total non current liabilities"),
        ("total_current_liabilities", r"total current liabilities"),
        ("total_liabilities", r"total liabilities"),
        ("total_equity_and_liabilities", r"total equity (and|&) liabilities"),
    ],
    "cash_flow": [
        ("cfo", r"net cash (flows? )?(generated )?(from|used in|from used in|generated from used in)"
                r" operating activities.*"),
        ("cfi", r"net cash (flows? )?(generated )?(from|used in|from used in|generated from used in)"
                r" investing activities.*"),
        ("cff", r"net cash (flows? )?(generated )?(from|used in|from used in|generated from used in)"
                r" financing activities.*"),
        ("capex", r"(purchase|acquisition) of property plant (and|&) equipment.*"),
    ],
}

_COMPILED = {st: [(item, re.compile(rf"^(?:{pat})$")) for item, pat in items]
             for st, items in LINE_ITEMS.items()}

# Sub-headings that change how ambiguous labels are read (balance sheet only).
CONTEXT_HEADINGS = [
    ("non_current_liabilities", re.compile(r"^non current liabilities$")),
    ("current_liabilities", re.compile(r"^current liabilities$")),
    ("non_current_assets", re.compile(r"^non current assets$")),
    ("current_assets", re.compile(r"^current assets$")),
    ("equity", re.compile(r"^equity$")),
]


def normalize_label(label: str) -> str:
    """Lowercase, drop note references, roman numerals, brackets and punctuation."""
    t = label.lower().replace("&", " and ").replace("’", "'")
    t = re.sub(r"\(\s*(?:in\s*)?(?:rs\.?|rupees|inr|₹)[^)]*\)", " ", t)  # "(in Rupees)"
    t = re.sub(r"\(\s*[ivx]+(?:\s*[-+=]\s*[ivx]+)*\s*\)", " ", t)  # (iii-iv) (i+ii)
    t = re.sub(r"\(\s*(?:[ivx]+|[a-z]|\d+)\s*\)", " ", t)       # (i) (a) (1)
    t = re.sub(r"\s+[ivx]+(?:\s*[-+=]\s*[ivx]+)+\s*$", " ", t)   # trailing iii-iv
    t = re.sub(r"^\s*(?:[ivx]+|[a-z]|\d+)[.)]\s+", " ", t)      # i. a) 1.
    t = re.sub(r"^\s*[ivx]+\s+(?=[a-z]{3})", " ", t)            # "I Revenue ..." (Sr. No.)
    t = re.sub(r"\bnote\s*\d+(?:\.\d+)?\b", " ", t)
    t = t.replace("/", " ").replace("-", " ")
    t = re.sub(r"[^a-z ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\b(total )?(net )?loss\b", "loss", t)
    return t


def match_context(label: str) -> str | None:
    """Return a balance-sheet context name if ``label`` is a sub-heading such as 'Current liabilities'."""
    norm = normalize_label(label)
    for name, rx in CONTEXT_HEADINGS:
        if rx.match(norm):
            return name
    return None


def match_line_item(statement: str, label: str, context: str | None = None) -> str | None:
    """Map a raw label to a canonical item, using ``context`` to split current/non-current."""
    norm = normalize_label(label)
    if not norm:
        return None
    for item, rx in _COMPILED[statement]:
        if rx.match(norm):
            if item in {"borrowings", "lease_liabilities"} and statement == "balance_sheet":
                if context == "non_current_liabilities":
                    return f"non_current_{item}"
                if context == "current_liabilities":
                    return f"current_{item}"
                if "long term" in norm:
                    return f"non_current_{item}"
                if "short term" in norm:
                    return f"current_{item}"
                return None  # ambiguous without context
            return item
    return None
