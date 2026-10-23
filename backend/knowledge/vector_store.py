"""Persistent ChromaDB store with one collection per IPO (``ipo_<ipo_id>``)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from backend.config import get_settings


@dataclass
class Hit:
    """One dense-retrieval result."""

    chunk_id: str
    score: float  # cosine similarity
    text: str
    metadata: dict


def collection_name(ipo_id: str) -> str:
    """Chroma names allow [A-Za-z0-9._-], 3-63 chars, alphanumeric at both ends."""
    name = "ipo_" + re.sub(r"[^A-Za-z0-9._-]", "-", ipo_id)
    return name[:63].rstrip("-_.")


@lru_cache
def _client():
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    s = get_settings()
    path = s.resolve(s.chroma_dir)
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path),
                                     settings=ChromaSettings(anonymized_telemetry=False))


class VectorStore:
    """Thin wrapper over Chroma; embeddings are always supplied by our own ``Embedder``."""

    def __init__(self, client=None) -> None:
        self.client = client or _client()

    def collection(self, ipo_id: str):
        """Get or create the cosine-space collection for an IPO."""
        return self.client.get_or_create_collection(
            collection_name(ipo_id), metadata={"hnsw:space": "cosine"})

    def upsert(self, ipo_id: str, ids: list[str], vectors: np.ndarray, texts: list[str],
               metadatas: list[dict]) -> None:
        """Insert or update chunks (batched; Chroma caps a single call's size)."""
        col = self.collection(ipo_id)
        step = 2000
        for i in range(0, len(ids), step):
            col.upsert(ids=ids[i:i + step], embeddings=vectors[i:i + step].tolist(),
                       documents=texts[i:i + step], metadatas=metadatas[i:i + step])

    def delete_doc(self, ipo_id: str, doc_id: str) -> None:
        """Remove every chunk of one document (used on re-ingest)."""
        self.collection(ipo_id).delete(where={"doc_id": doc_id})

    def query(self, ipo_id: str, vector: np.ndarray, k: int = 10,
              where: dict | None = None) -> list[Hit]:
        """Return the ``k`` nearest chunks to ``vector`` within one IPO."""
        col = self.collection(ipo_id)
        if col.count() == 0:
            return []
        res = col.query(query_embeddings=[vector.tolist()], n_results=min(k, col.count()),
                        where=where)
        return [Hit(cid, 1.0 - dist, doc, meta) for cid, dist, doc, meta in zip(
            res["ids"][0], res["distances"][0], res["documents"][0], res["metadatas"][0])]

    def count(self, ipo_id: str) -> int:
        """Number of chunks stored for an IPO."""
        return self.collection(ipo_id).count()
