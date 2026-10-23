"""Sentence embeddings with BAAI/bge-small-en-v1.5 on CPU, cached by content hash."""

from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np

from backend.config import get_settings
from backend.knowledge.cache import Cache

log = logging.getLogger(__name__)

# bge models expect this instruction on queries (not on passages).
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


@lru_cache
def _model():
    from sentence_transformers import SentenceTransformer

    s = get_settings()
    log.info("Loading embedding model %s on %s", s.embedding_model, s.embedding_device)
    return SentenceTransformer(s.embedding_model, device=s.embedding_device)


class Embedder:
    """Embeds passages and queries; vectors are L2-normalised so dot product = cosine."""

    def __init__(self, cache: Cache | None = None) -> None:
        self.settings = get_settings()
        self.cache = cache or Cache("embedding")

    def _encode(self, texts: list[str]) -> np.ndarray:
        return _model().encode(texts, batch_size=self.settings.embedding_batch_size,
                               normalize_embeddings=True, show_progress_bar=len(texts) > 256,
                               convert_to_numpy=True).astype(np.float32)

    def embed(self, texts: list[str]) -> np.ndarray:
        """Embed passages, reusing cached vectors. Returns an ``(n, dim)`` float32 array."""
        model_name = self.settings.embedding_model
        keys = [self.cache.key(model_name, t) for t in texts]
        cached = self.cache.get_many(keys)
        missing = [i for i, k in enumerate(keys) if k not in cached]
        log.info("Embeddings: %d cached, %d to compute", len(texts) - len(missing), len(missing))
        vectors: dict[int, np.ndarray] = {
            i: np.frombuffer(cached[k], dtype=np.float32) for i, k in enumerate(keys) if k in cached
        }
        step = 512
        for start in range(0, len(missing), step):
            idx = missing[start : start + step]
            new = self._encode([texts[i] for i in idx])
            self.cache.set_many({keys[i]: vec.tobytes() for i, vec in zip(idx, new)})
            vectors.update(dict(zip(idx, new)))
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        return np.vstack([vectors[i] for i in range(len(texts))])

    def embed_query(self, query: str) -> np.ndarray:
        """Embed one search query (with the bge query instruction)."""
        return self.embed([BGE_QUERY_PREFIX + query])[0]
