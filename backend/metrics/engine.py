"""Compute traceable metrics for an IPO from its extracted financial rows.

Every metric records its formula, each input figure (value, line item, period, page) and the
source pages, so any number shown to an agent or a user can be traced back to the document.
Metric ids look like ``jio-platforms:debt_to_equity:FY2026``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.knowledge.models import Document, FinancialRow, Ipo, Metric
from backend.metrics import formulas as F

log = logging.getLogger(__name__)


@dataclass
class MetricResult:
    """A computed (or skipped) metric before it is stored."""

    name: str
    label: str
    period: str
    value: float | None
    unit: str
    formula: str
    inputs: dict[str, dict] = field(default_factory=dict)
    status: str = "ok"
    note: str | None = None

    def pages(self) -> list[int]:
        return sorted({i["page"] for i in self.inputs.values() if i.get("page")})


class Financials:
    """Lookup over one document's rows: ``get("revenue_from_operations", "FY2026")``."""

    def __init__(self, rows: list[FinancialRow]) -> None:
        basis = "consolidated" if any(r.basis == "consolidated" for r in rows) else "standalone"
        self.rows = {(r.line_item, r.period): r for r in rows if r.basis == basis}
        self.basis = basis
        self.fy_periods = sorted({r.period for r in self.rows.values()
                                  if r.period.startswith("FY")}, reverse=True)

    def get(self, item: str, period: str) -> float | None:
        r = self.rows.get((item, period))
        return r.value_inr_mn if r else None

    def ref(self, item: str, period: str) -> dict:
        r = self.rows.get((item, period))
        if r is None:
            return {"line_item": item, "period": period, "value": None, "page": None}
        return {"line_item": item, "period": period, "value": r.value_inr_mn,
                "page": r.page, "raw_label": r.raw_label}

    # Derived inputs with documented fallbacks --------------------------------------------
    def total_borrowings(self, p: str) -> float | None:
        nc, c = self.get("non_current_borrowings", p), self.get("current_borrowings", p)
        return None if nc is None and c is None else (nc or 0.0) + (c or 0.0)

    def total_equity(self, p: str) -> float | None:
        te = self.get("total_equity", p) or self.get("equity_attributable_to_owners", p)
        if te is not None:
            return te
        sc, oe = self.get("equity_share_capital", p), self.get("other_equity", p)
        return None if sc is None or oe is None else sc + oe

    def total_liabilities(self, p: str) -> float | None:
        tl = self.get("total_liabilities", p)
        if tl is not None:
            return tl
        ncl, cl = self.get("total_non_current_liabilities", p), self.get("total_current_liabilities", p)
        if ncl is not None and cl is not None:
            return ncl + cl
        ta, te = self.get("total_assets", p), self.total_equity(p)
        return None if ta is None or te is None else ta - te


def _load_peers() -> dict:
    s = get_settings()
    path: Path = s.resolve(s.config_dir) / "peers.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def compute(ipo: Ipo, fin: Financials) -> list[MetricResult]:
    """All metrics for the latest fiscal year (and growth vs the previous one)."""
    out: list[MetricResult] = []
    if not fin.fy_periods:
        return [MetricResult("financials", "Financial statements", "-", None, "-", "-",
                             status="skipped", note="No restated financial rows were extracted.")]
    p = fin.fy_periods[0]
    prev = fin.fy_periods[1] if len(fin.fy_periods) > 1 else None
    first = fin.fy_periods[-1]

    # Base facts: agents cite these instead of quoting numbers themselves.
    for item, label in [("revenue_from_operations", "Revenue from operations"),
                        ("profit_after_tax", "Profit after tax"),
                        ("total_assets", "Total assets"), ("finance_costs", "Finance costs")]:
        for period in fin.fy_periods:
            v = fin.get(item, period)
            if v is not None:
                out.append(MetricResult(f"fact_{item}", label, period, v, "INR mn",
                                        f"{item} as reported", {item: fin.ref(item, period)}))
    tb = fin.total_borrowings(p)
    if tb is not None:
        out.append(MetricResult("fact_total_borrowings", "Total borrowings", p, tb, "INR mn",
                                "non_current_borrowings + current_borrowings",
                                {"non_current_borrowings": fin.ref("non_current_borrowings", p),
                                 "current_borrowings": fin.ref("current_borrowings", p)}))

    def add(name, label, value, unit, formula, inputs, period=p, skip_note=None):
        missing = [k for k, v in inputs.items() if v.get("value") is None]
        if value is None:
            out.append(MetricResult(name, label, period, None, unit, formula, inputs, "skipped",
                                    skip_note or f"Missing inputs: {', '.join(missing) or 'n/a'}"))
        else:
            out.append(MetricResult(name, label, period, round(value, 4), unit, formula, inputs))

    eq = fin.total_equity(p)
    add("debt_to_equity", "Debt-to-equity", F.debt_to_equity(tb, eq), "x",
        "(non_current_borrowings + current_borrowings) / total_equity",
        {"total_borrowings": {"value": tb, "page": fin.ref("non_current_borrowings", p)["page"]
                              or fin.ref("current_borrowings", p)["page"]},
         "total_equity": {"value": eq, "page": fin.ref("total_equity", p)["page"]
                          or fin.ref("other_equity", p)["page"]}})
    pbt, fc = fin.get("profit_before_tax", p), fin.get("finance_costs", p)
    add("interest_coverage", "Interest coverage", F.interest_coverage(pbt, fc), "x",
        "(profit_before_tax + finance_costs) / finance_costs",
        {"profit_before_tax": fin.ref("profit_before_tax", p),
         "finance_costs": fin.ref("finance_costs", p)})

    rev, pat = fin.get("revenue_from_operations", p), fin.get("profit_after_tax", p)
    if prev:
        add("revenue_growth", "Revenue growth (YoY)",
            _pct(F.growth(rev, fin.get("revenue_from_operations", prev))), "%",
            f"revenue_from_operations[{p}] / revenue_from_operations[{prev}] - 1",
            {f"revenue_{p}": fin.ref("revenue_from_operations", p),
             f"revenue_{prev}": fin.ref("revenue_from_operations", prev)})
        add("pat_growth", "PAT growth (YoY)",
            _pct(F.growth(pat, fin.get("profit_after_tax", prev))), "%",
            f"profit_after_tax[{p}] / profit_after_tax[{prev}] - 1",
            {f"pat_{p}": fin.ref("profit_after_tax", p),
             f"pat_{prev}": fin.ref("profit_after_tax", prev)})
    years = len(fin.fy_periods) - 1
    if years >= 2:
        add("revenue_cagr", f"Revenue CAGR ({first}-{p})",
            _pct(F.cagr(rev, fin.get("revenue_from_operations", first), years)), "%",
            f"(revenue[{p}] / revenue[{first}])^(1/{years}) - 1",
            {f"revenue_{p}": fin.ref("revenue_from_operations", p),
             f"revenue_{first}": fin.ref("revenue_from_operations", first)})

    dep, oi = fin.get("depreciation_amortisation", p), fin.get("other_income", p)
    eb = F.ebitda(pbt, fc, dep, oi)
    add("ebitda_margin", "EBITDA margin", _pct(F.safe_div(eb, rev)), "%",
        "(profit_before_tax + finance_costs + depreciation_amortisation - other_income) / revenue",
        {"profit_before_tax": fin.ref("profit_before_tax", p),
         "finance_costs": fin.ref("finance_costs", p),
         "depreciation_amortisation": fin.ref("depreciation_amortisation", p),
         "other_income": fin.ref("other_income", p),
         "revenue_from_operations": fin.ref("revenue_from_operations", p)})
    add("pat_margin", "PAT margin", _pct(F.safe_div(pat, rev)), "%",
        "profit_after_tax / revenue_from_operations",
        {"profit_after_tax": fin.ref("profit_after_tax", p),
         "revenue_from_operations": fin.ref("revenue_from_operations", p)})
    add("roe", "Return on equity", _pct(F.safe_div(pat, eq) if eq and eq > 0 else None), "%",
        "profit_after_tax / total_equity",
        {"profit_after_tax": fin.ref("profit_after_tax", p),
         "total_equity": {"value": eq, "page": fin.ref("total_equity", p)["page"]}})

    out.append(_altman(fin, p))
    out.append(_beneish(fin, p, prev))
    out.extend(_valuation(ipo, fin, p))
    out.append(_issue_structure(ipo, p))
    return out


def _issue_structure(ipo: Ipo, p: str) -> MetricResult:
    """Share of the issue that is an offer for sale (money to sellers, not the company)."""
    fresh, ofs = ipo.fresh_issue_cr, ipo.ofs_cr
    inputs = {"fresh_issue_cr": {"value": fresh, "page": None, "source": "IPO registry"},
              "ofs_cr": {"value": ofs, "page": None, "source": "IPO registry"}}
    total = (fresh or 0) + (ofs or 0)
    value = None if fresh is None or ofs is None or total == 0 else ofs / total * 100
    return MetricResult("ofs_share", "Offer-for-sale share of issue", "issue",
                        None if value is None else round(value, 2), "%",
                        "ofs_cr / (fresh_issue_cr + ofs_cr)", inputs,
                        "ok" if value is not None else "skipped",
                        None if value is not None else "Issue size split not in registry")


def _pct(x: float | None) -> float | None:
    return None if x is None else x * 100.0


def _altman(fin: Financials, p: str) -> MetricResult:
    ta = fin.get("total_assets", p)
    tca, tcl = fin.get("total_current_assets", p), fin.get("total_current_liabilities", p)
    re_ = fin.get("other_equity", p)  # retained-earnings proxy (Ind AS has no separate line)
    pbt, fc = fin.get("profit_before_tax", p), fin.get("finance_costs", p)
    eq, tl = fin.total_equity(p), fin.total_liabilities(p)
    inputs = {"total_current_assets": fin.ref("total_current_assets", p),
              "total_current_liabilities": fin.ref("total_current_liabilities", p),
              "other_equity (retained earnings proxy)": fin.ref("other_equity", p),
              "profit_before_tax": fin.ref("profit_before_tax", p),
              "finance_costs": fin.ref("finance_costs", p),
              "total_assets": fin.ref("total_assets", p),
              "total_equity": {"value": eq, "page": fin.ref("total_equity", p)["page"]},
              "total_liabilities": {"value": tl, "page": fin.ref("total_liabilities", p)["page"]}}
    formula = ("3.25 + 6.56*(TCA-TCL)/TA + 3.26*RE/TA + 6.72*EBIT/TA + 1.05*Equity/TL; "
               "EBIT = PBT + finance costs; RE proxied by other equity")
    if None in (ta, tca, tcl, re_, pbt, fc, eq, tl):
        missing = [k for k, v in inputs.items() if v.get("value") is None]
        return MetricResult("altman_z_em", "Altman Z''-Score (EM)", p, None, "score", formula,
                            inputs, "skipped", f"Missing inputs: {', '.join(missing)}")
    z = F.altman_z_em(tca - tcl, re_, pbt + fc, eq, ta, tl)
    return MetricResult("altman_z_em", "Altman Z''-Score (EM)", p, round(z, 3), "score", formula,
                        inputs, note=f"Zone: {F.altman_zone(z)} (safe > 5.85, distress < 4.35)")


_BENEISH_MAP = {
    "sales": "revenue_from_operations", "receivables": "trade_receivables",
    "current_assets": "total_current_assets", "ppe": "property_plant_equipment",
    "total_assets": "total_assets", "depreciation": "depreciation_amortisation",
    "current_liabilities": "total_current_liabilities", "long_term_debt": "non_current_borrowings",
    "sga": "other_expenses", "net_income": "profit_after_tax", "cfo": "cfo",
}


def _beneish(fin: Financials, p: str, prev: str | None) -> MetricResult:
    formula = ("-4.84 + 0.920*DSRI + 0.528*GMI + 0.404*AQI + 0.892*SGI + 0.115*DEPI "
               "- 0.172*SGAI + 4.679*TATA - 0.327*LVGI")
    if prev is None:
        return MetricResult("beneish_m", "Beneish M-Score", p, None, "score", formula,
                            status="skipped", note="Needs two consecutive fiscal years; only one found.")
    inputs, cur, old, missing = {}, {}, {}, []
    for key, item in _BENEISH_MAP.items():
        for period, bucket in ((p, cur), (prev, old)):
            if key in ("net_income", "cfo") and period == prev:
                continue
            v = fin.get(item, period)
            inputs[f"{key}_{period}"] = fin.ref(item, period)
            if v is None:
                missing.append(f"{item}[{period}]")
            bucket[key] = v
    assumed = []
    cogs_items = ("cost_of_materials", "purchases_stock_in_trade")
    for period, bucket in ((p, cur), (prev, old)):
        parts = [fin.get(i, period) for i in cogs_items]
        bucket["cogs"] = sum(x for x in parts if x is not None) if any(
            x is not None for x in parts) else None
    if cur["cogs"] is None or old["cogs"] is None:
        cur["cogs"] = old["cogs"] = 0.0  # service company: GMI = 1 (neutral)
        assumed.append("GMI=1 (no cost of goods line)")
    if cur.get("long_term_debt") is None and old.get("long_term_debt") is None:
        cur["long_term_debt"] = old["long_term_debt"] = 0.0
        missing = [m for m in missing if not m.startswith("non_current_borrowings")]
        assumed.append("long-term debt = 0 (none reported)")
    if missing:
        return MetricResult("beneish_m", "Beneish M-Score", p, None, "score", formula, inputs,
                            "skipped", "Skipped: missing " + ", ".join(missing))
    try:
        idx = F.beneish_indices(cur, old)
    except ZeroDivisionError:
        return MetricResult("beneish_m", "Beneish M-Score", p, None, "score", formula, inputs,
                            "skipped", "Skipped: a denominator is zero")
    m = F.beneish_m(idx)
    flag = "above" if m > F.BENEISH_THRESHOLD else "below"
    note = (f"{flag} the -1.78 threshold; indices "
            + ", ".join(f"{k}={v:.3f}" for k, v in idx.items())
            + ("; assumptions: " + "; ".join(assumed) if assumed else "")
            + "; SG&A proxied by other expenses")
    return MetricResult("beneish_m", "Beneish M-Score", p, round(m, 3), "score", formula,
                        inputs, note=note)


def _valuation(ipo: Ipo, fin: Financials, p: str) -> list[MetricResult]:
    eps = fin.get("diluted_eps", p) or fin.get("basic_eps", p)
    eps_ref = fin.ref("diluted_eps" if fin.get("diluted_eps", p) else "basic_eps", p)
    price = ipo.price_band_high
    inputs = {"price_band_high": {"value": price, "page": None, "source": "IPO registry"},
              "eps": eps_ref}
    pe = F.price_to_earnings(price, eps)
    out = [MetricResult("pe_upper_band", "P/E at upper price band", p,
                        None if pe is None else round(pe, 2), "x", "price_band_high / EPS",
                        inputs, "ok" if pe is not None else "skipped",
                        None if pe is not None else "Needs price band and positive EPS")]
    peers = (_load_peers().get(ipo.ipo_id) or {}).get("peers") or []
    peer_pes = [x.get("pe") for x in peers if x.get("pe") is not None and not x.get("exclude")]
    med = F.median(peer_pes)
    rel = F.safe_div(pe, med) if pe is not None else None
    out.append(MetricResult(
        "pe_vs_peers", "P/E vs listed-peer median", p, None if rel is None else round(rel, 3),
        "x", "pe_upper_band / median(peer P/E)",
        {"pe_upper_band": {"value": pe, "page": eps_ref.get("page")},
         "peer_median_pe": {"value": med, "page": None, "source": "config/peers.yaml",
                            "peers": peers}},
        "ok" if rel is not None else "skipped",
        (f"Peer median P/E {med:.1f} from {len(peer_pes)} peers" if rel is not None
         else "Add peer P/E values to config/peers.yaml")))
    return out


def latest_doc_with_rows(session: Session, ipo_id: str) -> Document | None:
    """The most recently filed document that produced financial rows."""
    docs = session.scalars(select(Document).where(Document.ipo_id == ipo_id)
                           .order_by(Document.filed_date.desc())).all()
    for d in docs:
        if session.scalar(select(FinancialRow.id).where(FinancialRow.doc_id == d.doc_id).limit(1)):
            return d
    return None


def compute_and_store(session: Session, ipo_id: str) -> list[Metric]:
    """Recompute all metrics for an IPO from its latest document and persist them."""
    ipo = session.get(Ipo, ipo_id)
    doc = latest_doc_with_rows(session, ipo_id)
    rows = list(session.scalars(select(FinancialRow).where(FinancialRow.doc_id == doc.doc_id))
                ) if doc else []
    results = compute(ipo, Financials(rows))
    session.execute(delete(Metric).where(Metric.ipo_id == ipo_id))
    stored = []
    for r in results:
        m = Metric(metric_id=f"{ipo_id}:{r.name}:{r.period}", ipo_id=ipo_id, name=r.name,
                   label=r.label, period=r.period, value=r.value, unit=r.unit, formula=r.formula,
                   inputs_json=json.dumps(r.inputs, default=str), status=r.status, note=r.note,
                   source_pages=",".join(map(str, r.pages())),
                   doc_id=doc.doc_id if doc else None)
        session.merge(m)
        stored.append(m)
    session.flush()
    log.info("[%s] %d metrics (%d ok)", ipo_id, len(stored),
             sum(1 for m in stored if m.status == "ok"))
    return stored


def metric_dict(m: Metric) -> dict:
    """API / agent representation of a metric."""
    return {"metric_id": m.metric_id, "name": m.name, "label": m.label, "period": m.period,
            "value": m.value, "unit": m.unit, "formula": m.formula,
            "inputs": json.loads(m.inputs_json), "source_pages": [
                int(x) for x in m.source_pages.split(",") if x],
            "status": m.status, "note": m.note, "doc_id": m.doc_id}
