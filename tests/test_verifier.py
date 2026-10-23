"""Citation verification: unsupported claims must be struck."""

import pytest

from backend.agents import verifier
from backend.agents.judge import score_verdict
from backend.agents.verifier import (
    chunk_evidence,
    extract_figures,
    figure_supported,
    metric_evidence,
    verify_claim,
    verify_claims,
)

CHUNK = ("The Company proposes to utilise ₹25,000 million of the Net Proceeds towards repayment "
         "or prepayment of all or a portion of certain outstanding borrowings availed by Reliance "
         "Jio Infocomm Limited.")
METRIC = {"metric_id": "jio:debt_to_equity:FY2026", "label": "Debt-to-equity", "period": "FY2026",
          "value": 0.2147, "unit": "x", "formula": "borrowings / equity", "source_pages": [287],
          "inputs": {"total_borrowings": {"value": 707810.0, "page": 287},
                     "total_equity": {"value": 3359769.0, "page": 287}}}


@pytest.fixture
def evidence():
    return {"c1": chunk_evidence("c1", CHUNK, 106), METRIC["metric_id"]: metric_evidence(METRIC)}


def test_extract_figures_skips_years_and_small_integers():
    figs = [raw for raw, _ in extract_figures("In FY2026 (2026) revenue grew 14.6% to ₹1,46,885 "
                                              "million across 3 segments")]
    assert figs == ["14.6", "1,46,885"]


def test_figure_supported_handles_units_and_rounding():
    assert figure_supported(2500, [25000])           # ₹2,500 crore == ₹25,000 million
    assert figure_supported(0.21, [0.2147])          # rounding
    assert figure_supported(21.5, [0.2147])          # ratio stated as a percentage
    assert not figure_supported(90000, [25000, 0.2147])


def test_supported_claim(evidence):
    claim = {"claim_id": "BULL-1", "text": "₹25,000 million of proceeds go to repaying borrowings.",
             "evidence": ["c1"], "quote": "repayment or prepayment of all or a portion"}
    v = verify_claim(claim, evidence, nli=(0.91, 0.02), method="nli")
    assert v.status == "supported"


def test_deliberately_unsupported_figure_is_struck(evidence):
    claim = {"claim_id": "BEAR-1", "text": "The company will spend ₹90,000 million on acquisitions.",
             "evidence": ["c1"]}
    v = verify_claim(claim, evidence, nli=(0.4, 0.1), method="nli")
    assert v.status == "struck"
    assert v.unmatched_figures == ["90,000"]
    assert "not found" in v.reason


def test_claim_without_reference_is_struck(evidence):
    assert verify_claim({"claim_id": "X", "text": "Great company.", "evidence": []},
                        evidence).status == "struck"
    v = verify_claim({"claim_id": "Y", "text": "Debt is falling.", "evidence": ["made-up-id"]},
                     evidence)
    assert v.status == "struck" and v.invalid_refs == ["made-up-id"]


def test_contradicted_claim_is_struck(evidence):
    claim = {"claim_id": "Z", "text": "None of the proceeds will be used to repay borrowings.",
             "evidence": ["c1"]}
    assert verify_claim(claim, evidence, nli=(0.03, 0.95), method="nli").status == "struck"


def test_metric_claim_supported_by_value(evidence):
    claim = {"claim_id": "M", "text": "Debt-to-equity for FY2026 is a low 0.21x.",
             "evidence": [METRIC["metric_id"]]}
    assert verify_claim(claim, evidence).status == "supported"


def test_verify_claims_lexical_fallback(evidence, monkeypatch):
    monkeypatch.setattr(verifier, "_nli_model", lambda: None)
    claims = [
        {"claim_id": "A", "text": "Net proceeds will repay outstanding borrowings of Reliance Jio "
                                  "Infocomm.", "evidence": ["c1"]},
        {"claim_id": "B", "text": "Satellite broadband launches in Europe next quarter.",
         "evidence": ["c1"]},
    ]
    a, b = verify_claims(claims, evidence)
    assert a.method == "lexical" and a.status == "supported"
    assert b.status == "struck"


def test_score_verdict_ignores_struck_claims(evidence):
    claims = [{"claim_id": "B1", "stance": "bull", "strength": 5},
              {"claim_id": "R1", "stance": "bear", "strength": 5}]
    results = {"B1": verifier.Verification("B1", "supported", ""),
               "R1": verifier.Verification("R1", "struck", "")}
    v = score_verdict(claims, results)
    assert v["verdict"] == "Strong Bull"
    assert v["decisive_bear"] == []


def test_hypothesis_strips_attribution_and_page_refs_are_not_figures():
    text = 'The Risk Factors section (p.54) states: "We have incurred significant indebtedness."'
    assert verifier.hypothesis_text(text) == "We have incurred significant indebtedness."
    assert extract_figures("See pages 54-56 and p.112 for the ₹25,000 million") == \
        [("25,000", 25000.0)]


def test_hedged_figures_get_wider_tolerance(evidence):
    ev = {"m": metric_evidence({**METRIC, "metric_id": "m", "value": 20.46, "unit": "%",
                                "inputs": {}})}
    hedged = {"claim_id": "H", "text": "PAT margin is over 20%.", "evidence": ["m"]}
    exact = {"claim_id": "E", "text": "PAT margin is 20%.", "evidence": ["m"]}
    assert verify_claim(hedged, ev).status == "supported"
    assert verify_claim(exact, ev).status == "struck"
