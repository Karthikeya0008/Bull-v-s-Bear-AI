"""Bull and Bear agents.

Each agent (1) writes its own retrieval queries for its stance, (2) retrieves evidence with the
hybrid retriever, (3) receives the computed metrics as facts, and (4) returns structured
claims ``{claim_id, text, stance, evidence, strength, quote, rebuts}``. Claims must cite ids
from the evidence book; numbers are only allowed if they appear in the cited evidence.

When no LLM provider is configured (or all are rate-limited), a deterministic rule-based
agent produces claims from the same metrics and retrieved chunks, and the debate records
``rule-based`` as the model so nobody mistakes it for LLM output.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from backend.agents.evidence import EvidenceBook
from backend.config import get_settings
from backend.llm.client import LLMClient, NoProviderAvailable
from backend.retrieval.hybrid import HybridRetriever

log = logging.getLogger(__name__)

TOPICS = {
    "bear": ["debt borrowings and repayment obligations", "equity dilution and offer for sale "
             "by selling shareholders", "outstanding litigation criminal tax proceedings",
             "related party transactions with promoter group", "key risk factors for the business",
             "valuation price band compared with listed peers"],
    "bull": ["revenue growth and customer subscriber growth", "market position and market share "
             "leadership", "profit margins and EBITDA improvement", "objects of the issue use of "
             "proceeds debt repayment", "competitive strengths advantage over peers"],
}
# Legal/procedural boilerplate that never carries an investment argument.
BOILERPLATE_SECTIONS = {"Definitions and Abbreviations", "Offer Procedure", "Offer Structure",
                        "Terms of the Offer", "Articles of Association", "Material Contracts",
                        "Declaration", "Restrictions on Foreign Ownership",
                        "Other Regulatory Disclosures", "Presentation of Financial Information",
                        "Forward-Looking Statements", "Statement of Special Tax Benefits",
                        "General Information", "Cover and General"}
STANCE_WORDS = {
    "bear": ["risk", "default", "litigation", "proceeding", "penalty", "debt", "borrowing",
             "loss", "decline", "adverse", "depend", "competition", "regulat", "related party",
             "dilution", "promoter", "contingent", "pledge", "negative", "fail", "breach"],
    "bull": ["growth", "grew", "increase", "leader", "largest", "market share", "strength",
             "margin", "profit", "customer", "subscriber", "expand", "advantage", "scale",
             "improve", "first", "leading", "innovation", "repay", "reduce"],
}
ROUND_NAMES = {1: "opening", 2: "rebuttal", 3: "closing"}
CLAIMS_PER_ROUND = {1: 4, 2: 3, 3: 2}

SYSTEM = """You are the {STANCE} analyst in a structured debate about the Indian IPO of {company}.
Argue the {stance} case using ONLY the evidence provided.
Rules:
- Every claim must cite one or more evidence ids exactly as written in square brackets.
- Never invent or compute numbers. Any figure you state must appear in a cited chunk or be the
  value of a cited metric. Prefer citing metric ids for financial figures.
- "quote" must be a short verbatim excerpt (<= 25 words) copied from one cited chunk, or "".
- strength is 1 (weak) to 5 (decisive).
Respond with JSON only."""

CLAIM_SCHEMA = ('{"claims": [{"text": "...", "evidence": ["<id>", "..."], "strength": 3, '
                '"quote": "...", "rebuts": "<opponent claim_id or null>"}]}')


@dataclass
class Agent:
    """One side of the debate."""

    stance: str  # bull / bear
    ipo_id: str
    company: str
    book: EvidenceBook
    retriever: HybridRetriever
    llm: LLMClient | None
    claims: list[dict] = field(default_factory=list)
    model_used: str = "rule-based"

    # ----------------------------------------------------------------------------------------
    def plan_queries(self) -> list[str]:
        """Stance-specific retrieval queries (LLM-written, falling back to the topic list)."""
        topics = TOPICS[self.stance]
        if self.llm and self.llm.available:
            try:
                r = self.llm.complete_json(
                    SYSTEM.format(STANCE=self.stance.upper(), stance=self.stance,
                                  company=self.company),
                    f"Write 6 short search queries to find {self.stance} evidence in the "
                    f"offer document of {self.company}. Cover: {'; '.join(topics)}. "
                    'Return {"queries": ["..."]}.', temperature=0.2)
                qs = [str(q) for q in r.data.get("queries", []) if str(q).strip()][:6]
                if qs:
                    self.model_used = f"{r.provider}/{r.model}"
                    return qs
            except NoProviderAvailable as exc:
                log.warning("%s query planning fell back to topics: %s", self.stance, exc)
        return topics

    def gather(self, queries: list[str]) -> list[str]:
        """Retrieve evidence for each query; returns the new chunk ids in rank order."""
        per = get_settings().debate_evidence_per_query
        ids: list[str] = []
        for q in queries:
            hits = self.retriever.search(self.ipo_id, q, k=per,
                                         exclude_sections=BOILERPLATE_SECTIONS)
            for cid in self.book.add_hits(hits):
                if cid not in ids:
                    ids.append(cid)
        return ids

    # ----------------------------------------------------------------------------------------
    def argue(self, round_no: int, chunk_ids: list[str], opponent: list[dict]) -> list[dict]:
        """Produce this round's claims (LLM first, rule-based fallback)."""
        raw: list[dict] | None = None
        if self.llm and self.llm.available:
            try:
                raw = self._llm_claims(round_no, chunk_ids, opponent)
            except (NoProviderAvailable, ValueError) as exc:
                log.warning("%s round %d fell back to rule-based: %s", self.stance, round_no, exc)
        if raw is None:
            raw = rule_based_claims(self.stance, round_no, self.book, chunk_ids, opponent,
                                    self.claims)
        claims = []
        for i, c in enumerate(raw[:CLAIMS_PER_ROUND[round_no]], start=1):
            claims.append({
                "claim_id": f"{self.stance.upper()}-R{round_no}-{i}",
                "round": round_no, "stance": self.stance,
                "text": str(c.get("text", "")).strip(),
                "evidence": [str(e).strip("[] ") for e in (c.get("evidence") or [])],
                "strength": max(1, min(5, int(c.get("strength") or 3))),
                "quote": str(c.get("quote") or "")[:400],
                "rebuts": c.get("rebuts") if c.get("rebuts") in {o["claim_id"] for o in opponent}
                else None,
            })
        self.claims.extend(claims)
        return claims

    def _llm_claims(self, round_no: int, chunk_ids: list[str], opponent: list[dict]) -> list[dict]:
        n = CLAIMS_PER_ROUND[round_no]
        task = {
            1: f"OPENING: make your {n} strongest {self.stance} claims.",
            2: f"REBUTTAL: attack the opponent's claims below. Make {n} claims; each should set "
               f"\"rebuts\" to the opponent claim_id it answers and cite evidence that "
               f"undermines it.",
            3: f"CLOSING: make your {n} most decisive final claims, restating your best evidence.",
        }[round_no]
        opp = "\n".join(f"- {o['claim_id']}: {o['text']}" for o in opponent) or "(none yet)"
        own = "\n".join(f"- {o['claim_id']}: {o['text']}" for o in self.claims) or "(none yet)"
        user = (f"{task}\n\nCOMPUTED METRICS (cite by id):\n{self.book.metrics_prompt()}\n\n"
                f"DOCUMENT EVIDENCE (cite by id):\n{self.book.chunks_prompt(chunk_ids)}\n\n"
                f"YOUR EARLIER CLAIMS:\n{own}\n\nOPPONENT CLAIMS:\n{opp}\n\n"
                f"Return JSON exactly like: {CLAIM_SCHEMA}")
        r = self.llm.complete_json(
            SYSTEM.format(STANCE=self.stance.upper(), stance=self.stance, company=self.company),
            user, temperature=0.4)
        self.model_used = f"{r.provider}/{r.model}"
        claims = r.data.get("claims")
        if not isinstance(claims, list) or not claims:
            raise ValueError("model returned no claims")
        return claims


# --------------------------------------------------------------------------------------------
# Rule-based fallback (no LLM): deterministic claims from metrics and retrieved chunks
# --------------------------------------------------------------------------------------------
# metric name -> (bull test, bear test, bull phrasing, bear phrasing)
_RULES = {
    "revenue_growth": (lambda v: v >= 10, lambda v: v < 5,
                       "shows strong top-line momentum", "signals slowing top-line growth"),
    "pat_growth": (lambda v: v >= 10, lambda v: v < 0,
                   "shows profits compounding", "shows profits shrinking"),
    "revenue_cagr": (lambda v: v >= 12, lambda v: v < 6,
                     "reflects sustained multi-year growth", "is modest for a growth IPO"),
    "ebitda_margin": (lambda v: v >= 20, lambda v: v < 10,
                      "indicates strong operating profitability", "leaves thin operating headroom"),
    "pat_margin": (lambda v: v >= 10, lambda v: v < 5,
                   "is a healthy net margin", "is a thin net margin"),
    "roe": (lambda v: v >= 15, lambda v: v < 10,
            "indicates efficient use of equity", "is a weak return on shareholders' equity"),
    "interest_coverage": (lambda v: v >= 4, lambda v: v < 2.5,
                          "means interest is comfortably covered",
                          "means earnings cover interest only narrowly"),
    "debt_to_equity": (lambda v: v <= 0.5, lambda v: v >= 1.0,
                       "is conservative leverage", "is high leverage"),
    "altman_z_em": (lambda v: v > 5.85, lambda v: v < 4.35,
                    "is in the Altman safe zone", "is in the Altman distress zone"),
    "beneish_m": (lambda v: v < -2.22, lambda v: v > -1.78,
                  "is well below the manipulation threshold",
                  "is above the -1.78 earnings-manipulation threshold"),
    "pe_upper_band": (lambda v: v <= 20, lambda v: v >= 40,
                      "is an undemanding valuation", "is a rich valuation"),
    "pe_vs_peers": (lambda v: v < 0.9, lambda v: v > 1.1,
                    "is a discount to listed peers", "is a premium to listed peers"),
    "ofs_share": (lambda v: v <= 10, lambda v: v >= 40,
                  "means most money raised goes into the company",
                  "means much of the issue is existing holders selling out"),
}


def _metric_claims(stance: str, book: EvidenceBook) -> list[dict]:
    out = []
    for mid, m in book.metrics.items():
        rule = _RULES.get(m["name"])
        if rule is None or m["value"] is None:
            continue
        bull_ok, bear_ok, bull_txt, bear_txt = rule
        v = m["value"]
        if (stance == "bull" and bull_ok(v)) or (stance == "bear" and bear_ok(v)):
            phr = bull_txt if stance == "bull" else bear_txt
            unit = "%" if m["unit"] == "%" else "x" if m["unit"] == "x" else ""
            out.append({"text": f"{m['label']} for {m['period']} is {v:,.2f}{unit}, which {phr}.",
                        "evidence": [mid], "strength": 4, "quote": ""})
    return out


def best_sentence(text: str, stance: str, limit: int = 240) -> tuple[str, int]:
    """The sentence with the most stance keywords (ties -> earlier), and its keyword count.

    Table-like sentences (mostly numbers) are skipped: they read badly as claims.
    """
    flat = " ".join(text.split())
    best, best_score = "", -1
    for sent in re.split(r"(?<=[.;])\s+", flat):
        digits = sum(ch.isdigit() for ch in sent)
        if len(sent) < 60 or digits > len(sent) * 0.15:
            continue
        low = sent.lower()
        score = sum(low.count(w) for w in STANCE_WORDS[stance])
        if score > best_score:
            best, best_score = sent, score
    return best[:limit].rstrip(" ,;"), best_score


def _chunk_claims(stance: str, book: EvidenceBook, chunk_ids: list[str]) -> list[dict]:
    scored = []
    for cid in chunk_ids:
        c = book.chunks[cid]
        sentence, score = best_sentence(c["text"], stance)
        if not sentence or score <= 0:
            continue
        scored.append((score, {"text": f"The {c['section']} section (p.{c['page']}) states: "
                                       f"\"{sentence}\"", "evidence": [cid],
                               "strength": 3 if score >= 3 else 2, "quote": sentence[:160]}))
    return [claim for _s, claim in sorted(scored, key=lambda x: -x[0])]


def rule_based_claims(stance: str, round_no: int, book: EvidenceBook, chunk_ids: list[str],
                      opponent: list[dict], earlier: list[dict]) -> list[dict]:
    """Deterministic claims: metric rules first, then quoted evidence from retrieved chunks."""
    used = {tuple(c["evidence"]) for c in earlier}
    metric_claims = _metric_claims(stance, book)
    chunk_claims = _chunk_claims(stance, book, chunk_ids)
    # interleave so each round mixes computed facts with document evidence
    mixed = [c for pair in zip(metric_claims, chunk_claims) for c in pair]
    longer = metric_claims if len(metric_claims) > len(chunk_claims) else chunk_claims
    mixed += longer[min(len(metric_claims), len(chunk_claims)):]
    pool = [c for c in mixed if tuple(c["evidence"]) not in used]
    if round_no == 2:
        targets = sorted(opponent, key=lambda o: -o["strength"])
        for c, target in zip(pool, targets):
            c["rebuts"] = target["claim_id"]
    if round_no == 3:
        best = sorted(earlier, key=lambda c: -c["strength"])[:2]
        return [{"text": f"In closing: {c['text']}", "evidence": c["evidence"],
                 "strength": c["strength"], "quote": c.get("quote", "")} for c in best] or pool
    return pool
