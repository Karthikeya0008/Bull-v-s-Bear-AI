"""The evidence an agent may cite: retrieved chunks plus computed metrics, keyed by id."""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.agents.verifier import Evidence, chunk_evidence, metric_evidence
from backend.retrieval.hybrid import SearchHit


@dataclass
class EvidenceBook:
    """Everything citeable in a debate. Ids are chunk ids (``ipo/DRHP/p0123/ab12cd34``) or
    metric ids (``ipo:debt_to_equity:FY2026``)."""

    chunks: dict[str, dict] = field(default_factory=dict)
    metrics: dict[str, dict] = field(default_factory=dict)

    def add_hits(self, hits: list[SearchHit]) -> list[str]:
        """Add search hits; returns their ids."""
        for h in hits:
            self.chunks.setdefault(h.chunk_id, {"chunk_id": h.chunk_id, "text": h.text,
                                                "section": h.section, "page": h.page,
                                                "page_end": h.page_end, "doc_id": h.doc_id,
                                                "doc_type": h.doc_type,
                                                "source_url": h.source_url})
        return [h.chunk_id for h in hits]

    def add_metrics(self, metrics: list[dict]) -> None:
        for m in metrics:
            if m["status"] == "ok":
                self.metrics[m["metric_id"]] = m

    def ids(self) -> set[str]:
        return set(self.chunks) | set(self.metrics)

    def resolved(self) -> dict[str, Evidence]:
        """Evidence objects for the verifier."""
        out = {cid: chunk_evidence(cid, c["text"], c["page"]) for cid, c in self.chunks.items()}
        out.update({mid: metric_evidence(m) for mid, m in self.metrics.items()})
        return out

    def metrics_prompt(self) -> str:
        """Metric facts as prompt lines; agents must cite these ids, never compute numbers."""
        lines = []
        for mid, m in self.metrics.items():
            pages = ", ".join(map(str, m.get("source_pages") or [])) or "registry"
            note = f" ({m['note']})" if m.get("note") else ""
            lines.append(f"[{mid}] {m['label']} {m['period']} = {_fmt(m['value'])} {m['unit']}"
                         f"{note} [pages {pages}]")
        return "\n".join(lines)

    def chunks_prompt(self, ids: list[str], max_chars: int = 900) -> str:
        """Chunk excerpts as prompt blocks."""
        blocks = []
        for cid in ids:
            c = self.chunks[cid]
            text = " ".join(c["text"].split())[:max_chars]
            blocks.append(f"[{cid}] ({c['doc_type']}, {c['section']}, p.{c['page']})\n{text}")
        return "\n\n".join(blocks)


def _fmt(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v:,.2f}" if abs(v) < 1000 else f"{v:,.0f}"
