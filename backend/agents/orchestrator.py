"""Runs a full debate: planning -> retrieval -> 3 rounds -> verification -> verdict.

Every step emits an event dict (``{"type": ..., ...}``). Events are streamed to the client
(SSE) and saved with the debate so it can be replayed offline, event by event.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select

from backend.agents.debaters import ROUND_NAMES, Agent
from backend.agents.evidence import EvidenceBook
from backend.agents.judge import judge
from backend.db import session_scope
from backend.knowledge.models import Debate, Ipo, Metric
from backend.llm.client import LLMClient
from backend.metrics.engine import compute_and_store, metric_dict
from backend.retrieval.hybrid import HybridRetriever

log = logging.getLogger(__name__)

Emit = Callable[[dict], None]


def _load_metrics(ipo_id: str) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(Metric).where(Metric.ipo_id == ipo_id)).all()
        if not rows:
            rows = compute_and_store(s, ipo_id)
        return [metric_dict(m) for m in rows]


def run_debate(ipo_id: str, emit: Emit | None = None, debate_id: str | None = None) -> str:
    """Run a debate for ``ipo_id``; returns the debate id. Never raises (errors are saved)."""
    debate_id = debate_id or uuid.uuid4().hex[:12]
    events: list[dict] = []

    def send(event: dict) -> None:
        event = {"debate_id": debate_id, "ts": datetime.now().isoformat(timespec="seconds"),
                 **event}
        events.append(event)
        if emit:
            emit(event)

    with session_scope() as s:
        ipo = s.get(Ipo, ipo_id)
        if ipo is None:
            raise KeyError(ipo_id)
        company = ipo.company
        s.add(Debate(debate_id=debate_id, ipo_id=ipo_id, status="running"))

    try:
        retriever = HybridRetriever()
        book = EvidenceBook()
        book.add_metrics(_load_metrics(ipo_id))
        debater_llm = LLMClient("debater", debate_id=debate_id)
        bull = Agent("bull", ipo_id, company, book, retriever, debater_llm)
        bear = Agent("bear", ipo_id, company, book, retriever, debater_llm)
        send({"type": "start", "ipo_id": ipo_id, "company": company,
              "debater_model": debater_llm.describe() if debater_llm.available else "rule-based",
              "metrics": len(book.metrics)})

        evidence: dict[str, list[str]] = {}
        for agent in (bull, bear):
            queries = agent.plan_queries()
            send({"type": "queries", "side": agent.stance, "queries": queries})
            evidence[agent.stance] = agent.gather(queries)
            send({"type": "evidence", "side": agent.stance, "chunk_ids": evidence[agent.stance]})

        for round_no in (1, 2, 3):
            send({"type": "round", "round": round_no, "name": ROUND_NAMES[round_no]})
            bull_prev = [c for c in bull.claims if c["round"] == round_no - 1]
            bear_prev = [c for c in bear.claims if c["round"] == round_no - 1]
            for agent, opp_prev, opponent in ((bull, bear_prev, bear), (bear, bull_prev, bull)):
                ids = evidence[agent.stance]
                if round_no == 2 and opp_prev:  # fresh evidence aimed at the opponent's claims
                    extra = agent.gather([c["text"][:200] for c in opp_prev[:2]])
                    ids = list(dict.fromkeys(ids + extra))
                    evidence[agent.stance] = ids
                target = opp_prev if round_no == 2 else opponent.claims
                for claim in agent.argue(round_no, ids, target):
                    send({"type": "claim", "side": agent.stance, "round": round_no,
                          "claim": claim})

        claims = bull.claims + bear.claims
        exclude = {debater_llm.providers[0]} if debater_llm.available else set()
        for agent in (bull, bear):
            if "/" in agent.model_used:
                exclude.add(agent.model_used.split("/")[0])
        judge_llm = LLMClient("judge", exclude=exclude, debate_id=debate_id)
        send({"type": "judging", "judge_model": judge_llm.describe()
              if judge_llm.available else "rule-based"})
        verifications, verdict = judge(claims, book, company, judge_llm)
        for v in verifications:
            send({"type": "verification", "claim_id": v.claim_id, "result": v.as_dict()})
        send({"type": "verdict", "verdict": verdict})

        models = {"bull": bull.model_used, "bear": bear.model_used,
                  "judge": verdict.get("model"), "embedding": "BAAI/bge-small-en-v1.5"}
        cited = {e for c in claims for e in c["evidence"]}
        with session_scope() as s:
            d = s.get(Debate, debate_id)
            d.status = "done"
            d.models_json = json.dumps(models)
            d.claims_json = json.dumps(claims)
            d.verification_json = json.dumps([v.as_dict() for v in verifications])
            d.verdict_json = json.dumps(verdict)
            d.finished_at = datetime.now()
            send({"type": "done", "models": models,
                  "citations": {cid: c for cid, c in book.chunks.items() if cid in cited}})
            d.events_json = json.dumps(events)
    except Exception as exc:  # persist the failure, report it, keep the server alive
        log.exception("Debate %s failed", debate_id)
        send({"type": "error", "message": str(exc)})
        with session_scope() as s:
            d = s.get(Debate, debate_id)
            d.status, d.error, d.events_json = "failed", str(exc), json.dumps(events)
            d.finished_at = datetime.now()
    return debate_id


def debate_payload(d: Debate) -> dict:
    """API representation of a stored debate."""
    return {"debate_id": d.debate_id, "ipo_id": d.ipo_id, "status": d.status,
            "models": json.loads(d.models_json or "{}"), "claims": json.loads(d.claims_json),
            "verification": json.loads(d.verification_json),
            "verdict": json.loads(d.verdict_json or "{}"), "error": d.error,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "finished_at": d.finished_at.isoformat() if d.finished_at else None}
