"""Judge: code verification first, then an LLM (on a different provider) weighs the survivors.

The LLM judge only sees claims that survived verification, with their verification status,
and must return one of five verdicts, a confidence, and the most decisive claims per side.
If no judge provider is available, a transparent scoring rule is used instead.
"""

from __future__ import annotations

import logging

from backend.agents.verifier import Verification, verify_claims
from backend.llm.client import LLMClient, NoProviderAvailable

log = logging.getLogger(__name__)

VERDICTS = ["Strong Bull", "Lean Bull", "Neutral", "Lean Bear", "Strong Bear"]
DISCLAIMER = ("Not investment advice. This is an automated analysis of public offer documents "
              "for educational purposes; it may be incomplete or wrong. Consult a SEBI-registered "
              "investment adviser before investing.")
STATUS_WEIGHT = {"supported": 1.0, "partially_supported": 0.5, "struck": 0.0}

JUDGE_SYSTEM = """You are an impartial judge of a Bull vs Bear debate about an Indian IPO.
You receive only claims that survived automated citation checks, each with its verification
status. Weigh them on materiality and evidence quality. Ignore rhetoric.
Return JSON only:
{"verdict": "Strong Bull|Lean Bull|Neutral|Lean Bear|Strong Bear",
 "confidence": "High|Medium|Low", "confidence_score": 0-100,
 "rationale": "3-5 sentences",
 "decisive_bull": ["claim_id", ...up to 3], "decisive_bear": ["claim_id", ...up to 3]}"""


def score_verdict(claims: list[dict], results: dict[str, Verification]) -> dict:
    """Rule-based verdict: strength x verification weight per side, net score -> verdict."""
    side_score = {"bull": 0.0, "bear": 0.0}
    for c in claims:
        w = STATUS_WEIGHT[results[c["claim_id"]].status]
        side_score[c["stance"]] += c["strength"] * w
    total = side_score["bull"] + side_score["bear"]
    net = 0.0 if total == 0 else (side_score["bull"] - side_score["bear"]) / total
    verdict = ("Strong Bull" if net > 0.35 else "Lean Bull" if net > 0.1 else
               "Strong Bear" if net < -0.35 else "Lean Bear" if net < -0.1 else "Neutral")
    survived = [c for c in claims if results[c["claim_id"]].status != "struck"]
    support_ratio = len(survived) / len(claims) if claims else 0.0
    conf_score = int(round(100 * min(1.0, abs(net) * 1.5) * (0.5 + 0.5 * support_ratio)))

    def top(side):
        ranked = sorted((c for c in survived if c["stance"] == side),
                        key=lambda c: -c["strength"] * STATUS_WEIGHT[results[c["claim_id"]].status])
        return [c["claim_id"] for c in ranked[:3]]

    return {"verdict": verdict, "confidence_score": conf_score,
            "confidence": "High" if conf_score >= 65 else "Medium" if conf_score >= 35 else "Low",
            "rationale": (f"Weighted evidence score: bull {side_score['bull']:.1f} vs bear "
                          f"{side_score['bear']:.1f} (strength x verification weight; struck "
                          f"claims count zero). Net {net:+.2f}."),
            "decisive_bull": top("bull"), "decisive_bear": top("bear"),
            "scores": side_score}


def judge(claims: list[dict], book, company: str, llm: LLMClient | None) -> tuple[list[Verification], dict]:
    """Verify every claim, then produce the verdict payload (always with the disclaimer)."""
    verifications = verify_claims(claims, book.resolved())
    results = {v.claim_id: v for v in verifications}
    baseline = score_verdict(claims, results)
    verdict = dict(baseline, method="rule-based", model="rule-based")
    survivors = [c for c in claims if results[c["claim_id"]].status != "struck"]
    if llm and llm.available and survivors:
        listing = "\n".join(
            f"- {c['claim_id']} [{c['stance']}, strength {c['strength']}, "
            f"{results[c['claim_id']].status}]: {c['text']}" for c in survivors)
        try:
            r = llm.complete_json(JUDGE_SYSTEM, f"IPO: {company}\n\nSURVIVING CLAIMS:\n{listing}",
                                  temperature=0.1)
            d = r.data
            ids = {c["claim_id"] for c in survivors}
            if d.get("verdict") in VERDICTS:
                verdict = {
                    "verdict": d["verdict"],
                    "confidence": d.get("confidence") if d.get("confidence") in
                    {"High", "Medium", "Low"} else baseline["confidence"],
                    "confidence_score": int(d.get("confidence_score") or
                                            baseline["confidence_score"]),
                    "rationale": str(d.get("rationale", ""))[:2000],
                    "decisive_bull": [i for i in d.get("decisive_bull", []) if i in ids][:3],
                    "decisive_bear": [i for i in d.get("decisive_bear", []) if i in ids][:3],
                    "scores": baseline["scores"], "baseline_verdict": baseline["verdict"],
                    "method": "llm", "model": f"{r.provider}/{r.model}",
                }
        except NoProviderAvailable as exc:
            log.warning("LLM judge unavailable, using rule-based verdict: %s", exc)
    verdict["struck"] = sum(1 for v in verifications if v.status == "struck")
    verdict["total_claims"] = len(claims)
    verdict["disclaimer"] = DISCLAIMER
    return verifications, verdict
