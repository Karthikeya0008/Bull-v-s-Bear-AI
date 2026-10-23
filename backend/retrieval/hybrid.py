"""Hybrid retrieval: BM25 (lexical) + bge-small dense search, fused with Reciprocal Rank Fusion.

RRF (Cormack et al., 2009): score(d) = sum over rankers of 1 / (k + rank_r(d)), k = 60.
It only uses ranks, so BM25 scores and cosine similarities never need to be calibrated.
Results are always restricted to one IPO and, by default, to its latest offer document
(an RHP supersedes the DRHP, and searching both would return near-duplicate passages).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from rank_bm25 import BM25Okapi
from sqlalchemy import select

from backend.db import session_scope
from backend.knowledge.models import Chunk, Document

RRF_K = 60
_STOP = set("""a an the of to in and or for on by with from as at is are was were be been this that
these those it its our we us their they which such any all other than into upto up per""".split())


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens without stop-words (numbers are kept)."""
    return [t for t in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower()) if t not in _STOP]


def rrf_fuse(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Fuse ranked id lists with Reciprocal Rank Fusion; ties keep first-seen order."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


@dataclass
class SearchHit:
    """One fused search result with its provenance."""

    chunk_id: str
    text: str
    section: str
    page: int
    page_end: int
    doc_id: str
    doc_type: str
    source_url: str | None
    score: float
    ranks: dict[str, int | None] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class _Corpus:
    ids: list[str]
    bm25: BM25Okapi
    chunks: dict[str, dict]


def select_doc_ids(ipo_id: str, policy: str = "latest") -> list[str]:
    """Doc ids to search: the latest parsed offer document, or all of them."""
    with session_scope() as s:
        docs = s.scalars(select(Document).where(Document.ipo_id == ipo_id,
                                                Document.status == "parsed")
                         .order_by(Document.filed_date.desc())).all()
        ids = [d.doc_id for d in docs]
    return ids[:1] if policy == "latest" else ids


@lru_cache(maxsize=16)
def _corpus(doc_ids: tuple[str, ...]) -> _Corpus:
    with session_scope() as s:
        rows = s.execute(select(Chunk, Document.doc_type, Document.source_url)
                         .join(Document, Document.doc_id == Chunk.doc_id)
                         .where(Chunk.doc_id.in_(doc_ids)).order_by(Chunk.ordinal)).all()
    chunks = {c.chunk_id: {"text": c.text, "section": c.section, "page": c.page,
                           "page_end": c.page_end, "doc_id": c.doc_id, "doc_type": dt,
                           "source_url": url} for c, dt, url in rows}
    ids = list(chunks)
    corpus = [tokenize(chunks[i]["section"] + " " + chunks[i]["text"]) for i in ids]
    return _Corpus(ids, BM25Okapi(corpus or [[""]]), chunks)


def clear_cache() -> None:
    """Forget cached BM25 indexes (call after re-ingesting)."""
    _corpus.cache_clear()


class HybridRetriever:
    """BM25 + dense retrieval for one IPO."""

    def __init__(self, embedder=None, store=None) -> None:
        self._embedder = embedder
        self._store = store

    @property
    def embedder(self):
        if self._embedder is None:
            from backend.knowledge.embeddings import Embedder
            self._embedder = Embedder()
        return self._embedder

    @property
    def store(self):
        if self._store is None:
            from backend.knowledge.vector_store import VectorStore
            self._store = VectorStore()
        return self._store

    def search(self, ipo_id: str, query: str, k: int = 8, pool: int = 40,
               policy: str = "latest", sections: list[str] | None = None) -> list[SearchHit]:
        """Top ``k`` chunks for ``query`` within ``ipo_id`` (optionally within ``sections``)."""
        doc_ids = select_doc_ids(ipo_id, policy)
        if not doc_ids:
            return []
        corpus = _corpus(tuple(doc_ids))
        allowed = [i for i in corpus.ids
                   if sections is None or corpus.chunks[i]["section"] in sections]
        allowed_set = set(allowed)

        scores = corpus.bm25.get_scores(tokenize(query))
        bm25_rank = [i for i, sc in sorted(zip(corpus.ids, scores), key=lambda x: -x[1])
                     if sc > 0 and i in allowed_set][:pool]

        where: dict = {"doc_id": doc_ids[0]} if len(doc_ids) == 1 else {"doc_id": {"$in": doc_ids}}
        if sections:
            where = {"$and": [where, {"section": {"$in": sections}}]}
        dense = self.store.query(ipo_id, self.embedder.embed_query(query), pool, where)
        dense_rank = [h.chunk_id for h in dense if h.chunk_id in allowed_set]

        fused = rrf_fuse([bm25_rank, dense_rank])[:k]
        b_pos = {cid: r for r, cid in enumerate(bm25_rank, 1)}
        d_pos = {cid: r for r, cid in enumerate(dense_rank, 1)}
        hits = []
        for cid, score in fused:
            c = corpus.chunks[cid]
            hits.append(SearchHit(cid, c["text"], c["section"], c["page"], c["page_end"],
                                  c["doc_id"], c["doc_type"], c["source_url"], round(score, 5),
                                  {"bm25": b_pos.get(cid), "dense": d_pos.get(cid)}))
        return hits
