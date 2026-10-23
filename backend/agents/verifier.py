"""Code-level citation verification (runs before the LLM judge sees anything).

For each claim:

1. **References**: every evidence id must resolve to a retrieved chunk or a computed metric.
   A claim with no valid reference is struck.
2. **Figures**: every number in the claim (₹ amounts, %, ratios) must appear in a cited chunk
   or equal a cited metric value, allowing rounding and unit changes (crore <-> million,
   ratio <-> percent). One unsupported figure strikes the claim.
3. **Quote**: if the agent supplied a verbatim quote, fuzzy-match it against the cited chunks
   (rapidfuzz ``partial_ratio`` >= 85).
4. **Entailment**: NLI cross-encoder (nli-deberta-v3-small) between each cited chunk
   (premise) and the claim (hypothesis); the best chunk counts. If the model is unavailable,
   a lexical overlap score is used instead and the verification records that.

Outcome: ``supported`` / ``partially_supported`` / ``struck`` with a human-readable reason.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache

from rapidfuzz import fuzz

from backend.config import get_settings

log = logging.getLogger(__name__)

_NUM_RX = re.compile(r"(?<![\w.])[-−]?\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|(?<![\w.])[-−]?\d+(?:\.\d+)?")
_YEAR_RX = re.compile(r"^(19|20)\d{2}$")
_STOP = set("the a an of to in and or for on by with from as at is are was were be been this "
            "that it its our we their which has have had will would can could than into".split())


@dataclass
class Evidence:
    """A resolved reference: chunk text or a metric rendered as text, plus numeric values."""

    ref_id: str
    kind: str  # chunk / metric
    text: str
    values: list[float] = field(default_factory=list)
    page: int | None = None


@dataclass
class Verification:
    """Verification outcome for one claim."""

    claim_id: str
    status: str  # supported / partially_supported / struck
    reason: str
    entailment: float | None = None
    method: str = "nli"
    valid_refs: list[str] = field(default_factory=list)
    invalid_refs: list[str] = field(default_factory=list)
    unmatched_figures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


_ATTRIBUTION_RX = re.compile(
    r"^(?:in closing:\s*)?(?:the|our|its)?\s*[\w'’ ,&-]{0,80}?\s*(?:section|document|drhp|rhp|"
    r"prospectus|filing)\s*(?:\(p\.?\s*\d+\))?\s*(?:states|says|notes|discloses|shows|reports)"
    r"(?:\s+that)?\s*:?\s*", re.IGNORECASE)
_PAGE_REF_RX = re.compile(r"\b(?:p|pp|page|pages)\.?\s*\d+(?:\s*[-–]\s*\d+)?", re.IGNORECASE)


def hypothesis_text(claim_text: str) -> str:
    """The factual content of a claim for NLI: drops 'The Risk Factors section (p.54) states:'
    wrappers and surrounding quotes, which the source chunk itself never says."""
    t = _ATTRIBUTION_RX.sub("", claim_text.strip())
    return t.strip().strip('"“”').strip() or claim_text


def extract_figures(text: str) -> list[tuple[str, float]]:
    """Numbers that matter in a claim: skips years, page references, single digits, list markers."""
    text = _PAGE_REF_RX.sub(" ", text)
    out = []
    for m in _NUM_RX.finditer(text):
        raw = m.group(0)
        clean = raw.replace(",", "").replace("−", "-")
        try:
            val = float(clean)
        except ValueError:
            continue
        if _YEAR_RX.match(clean) or (abs(val) < 10 and "." not in clean
                                      and not text[m.end():m.end() + 1] == "%"):
            continue
        out.append((raw, val))
    return out


_APPROX_RX = re.compile(r"(?:over|nearly|about|around|roughly|almost|approximately|more than|"
                        r"less than|under|~|close to)\s*(?:₹|rs\.?\s*)?$", re.IGNORECASE)


def is_approximate(text: str, raw: str) -> bool:
    """True when a figure is hedged ("over 20%", "nearly ₹50,000"): allow 10% tolerance."""
    idx = text.find(raw)
    return idx > 0 and bool(_APPROX_RX.search(text[max(0, idx - 20):idx]))


def _numbers_in(text: str) -> list[float]:
    vals = []
    for m in _NUM_RX.finditer(text):
        try:
            vals.append(float(m.group(0).replace(",", "").replace("−", "-")))
        except ValueError:
            pass
    return vals


def figure_supported(value: float, candidates: list[float], rel_tol: float = 0.015) -> bool:
    """True if ``value`` matches a candidate after rounding or a unit change."""
    scales = (1, 10, 0.1, 100, 0.01, 1000, 0.001, 1e5, 1e-5, 1e7, 1e-7)
    for c in candidates:
        for s in scales:
            target = abs(c * s)
            if target == 0:
                continue
            if abs(abs(value) - target) <= max(rel_tol * target, 0.051):
                return True
    return False


@lru_cache
def _nli_model():
    s = get_settings()
    if not s.verify_use_nli:
        return None
    try:
        from sentence_transformers import CrossEncoder
        return CrossEncoder(s.nli_model, device="cpu")
    except Exception as exc:  # model not downloaded / offline
        log.warning("NLI model unavailable (%s); using lexical overlap", exc)
        return None


def entailment_scores(pairs: list[tuple[str, str]]) -> tuple[list[tuple[float, float]], str]:
    """(entailment, contradiction) probability per (premise, hypothesis) pair, and the method."""
    model = _nli_model()
    if model is None:
        return [(lexical_support(p, h), 0.0) for p, h in pairs], "lexical"
    import numpy as np

    logits = model.predict([(p[:2000], h) for p, h in pairs], convert_to_numpy=True)
    probs = np.exp(logits) / np.exp(logits).sum(axis=1, keepdims=True)
    # nli-deberta-v3 label order: contradiction, entailment, neutral
    return [(float(p[1]), float(p[0])) for p in probs], "nli"


def lexical_support(premise: str, hypothesis: str) -> float:
    """Share of the claim's content words found in the premise (0..1)."""
    words = [w for w in re.findall(r"[a-z]{3,}", hypothesis.lower()) if w not in _STOP]
    if not words:
        return 0.0
    prem = premise.lower()
    return sum(1 for w in set(words) if w in prem) / len(set(words))


def verify_claim(claim: dict, evidence: dict[str, Evidence],
                 nli: tuple[float, float] | None = None, method: str = "nli") -> Verification:
    """Verify one claim against already-resolved evidence (see module docstring).

    ``nli`` is the best (entailment, contradiction) pair over the cited chunks; metric-only
    claims do not need it.
    """
    cid = claim.get("claim_id", "?")
    refs = [str(r) for r in claim.get("evidence") or []]
    valid = [r for r in refs if r in evidence]
    invalid = [r for r in refs if r not in evidence]
    if not valid:
        return Verification(cid, "struck", "No valid reference: claim cites no retrieved chunk "
                            "or computed metric." + (f" Unknown ids: {invalid}" if invalid else ""),
                            None, method, valid, invalid)

    cited = [evidence[r] for r in valid]
    candidates = [v for e in cited for v in e.values]
    text = claim.get("text", "")
    unmatched = [raw for raw, val in extract_figures(text)
                 if not figure_supported(val, candidates,
                                         0.1 if is_approximate(text, raw) else 0.015)]
    if unmatched:
        return Verification(cid, "struck", f"Figure(s) {', '.join(unmatched)} not found in the "
                            "cited sources.", None, method, valid, invalid, unmatched)

    chunk_texts = [e.text for e in cited if e.kind == "chunk"]
    quote = (claim.get("quote") or "").strip()
    quote_ok = bool(quote) and any(fuzz.partial_ratio(quote.lower(), t.lower()) >= 85
                                   for t in chunk_texts)
    metric_only = not chunk_texts
    has_figures = bool(extract_figures(claim.get("text", "")))

    if metric_only:
        status = "supported" if has_figures else "partially_supported"
        reason = ("All figures match the cited computed metrics." if has_figures else
                  "Cites computed metrics but states no figure to check; interpretation only.")
        return Verification(cid, status, reason, None, "metric", valid, invalid)

    ent, contra = nli if nli else (0.0, 0.0)
    strong, weak = (0.5, 0.15) if method == "nli" else (0.6, 0.35)
    if method == "nli" and contra >= 0.7 and not quote_ok:
        return Verification(cid, "struck", f"Cited text contradicts the claim (p={contra:.2f}).",
                            ent, method, valid, invalid)
    if ent >= strong or (quote_ok and ent >= weak):
        reason = f"Cited text supports the claim ({method} {ent:.2f}"
        reason += ", quote verified)." if quote_ok else ")."
        return Verification(cid, "supported", reason, ent, method, valid, invalid)
    if ent >= weak or quote_ok or has_figures:
        why = "quote found but inference is weak" if quote_ok else \
              "figures match but the cited text only partly supports the wording" if has_figures \
              else "cited text is related but does not fully support the claim"
        return Verification(cid, "partially_supported", f"Partial: {why} ({method} {ent:.2f}).",
                            ent, method, valid, invalid)
    return Verification(cid, "struck", f"Cited text does not support the claim ({method} "
                        f"{ent:.2f}).", ent, method, valid, invalid)


def verify_claims(claims: list[dict], evidence: dict[str, Evidence]) -> list[Verification]:
    """Verify many claims, batching all NLI pairs into one model call."""
    pairs, owners = [], []
    for i, c in enumerate(claims):
        for r in c.get("evidence") or []:
            e = evidence.get(str(r))
            if e is not None and e.kind == "chunk":
                pairs.append((e.text, hypothesis_text(c.get("text", ""))))
                owners.append(i)
    scores, method = entailment_scores(pairs) if pairs else ([], "nli")
    best: dict[int, tuple[float, float]] = {}
    for i, (ent, contra) in zip(owners, scores):
        cur = best.get(i)
        if cur is None or ent > cur[0]:
            best[i] = (ent, max(contra, cur[1]) if cur else contra)
    return [verify_claim(c, evidence, best.get(i), method) for i, c in enumerate(claims)]


def metric_evidence(m: dict) -> Evidence:
    """Render a metric as evidence (its value plus every input figure)."""
    values = [m["value"]] if m.get("value") is not None else []
    for inp in (m.get("inputs") or {}).values():
        if isinstance(inp, dict) and isinstance(inp.get("value"), (int, float)):
            values.append(float(inp["value"]))
    values.extend(_numbers_in(m.get("note") or ""))  # thresholds and indices, set in code
    text = f"{m['label']} ({m['period']}) = {m.get('value')} {m.get('unit')}; {m.get('formula')}"
    pages = m.get("source_pages") or []
    return Evidence(m["metric_id"], "metric", text, values, pages[0] if pages else None)


def chunk_evidence(chunk_id: str, text: str, page: int | None) -> Evidence:
    """Wrap a chunk as evidence with the numbers it contains."""
    return Evidence(chunk_id, "chunk", text, _numbers_in(text), page)
