"""Content-hash cache stored in SQLite.

Keys are SHA-256 digests of (namespace, payload parts), so identical inputs always hit the
same row. Phase 1 caches embeddings; Phase 3 reuses this for LLM responses.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from sqlalchemy import Engine, select
from sqlalchemy.dialects.sqlite import insert

from backend.db import get_engine, session_scope
from backend.knowledge.models import CacheEntry


def content_hash(*parts: str) -> str:
    """Return a SHA-256 hex digest over the given string parts (order matters)."""
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x1f")  # unit separator so ("ab","c") != ("a","bc")
    return h.hexdigest()


class Cache:
    """Namespaced key/value cache over the ``cache`` table."""

    def __init__(self, namespace: str, engine: Engine | None = None) -> None:
        self.namespace = namespace
        self.engine = engine or get_engine()

    def key(self, *parts: str) -> str:
        """Build the cache key for ``parts`` within this namespace."""
        return content_hash(self.namespace, *parts)

    def get_many(self, keys: Iterable[str]) -> dict[str, bytes]:
        """Return ``{key: value}`` for every key present in the cache."""
        keys = list(keys)
        found: dict[str, bytes] = {}
        with session_scope(self.engine) as s:
            for start in range(0, len(keys), 500):  # stay under SQLite's variable limit
                batch = keys[start : start + 500]
                rows = s.execute(select(CacheEntry.key, CacheEntry.value).where(
                    CacheEntry.key.in_(batch)
                ))
                found.update({k: v for k, v in rows})
        return found

    def get(self, key: str) -> bytes | None:
        """Return the cached bytes for ``key`` or ``None``."""
        return self.get_many([key]).get(key)

    def set_many(self, items: dict[str, bytes]) -> None:
        """Insert or replace many entries."""
        if not items:
            return
        rows = [{"key": k, "namespace": self.namespace, "value": v} for k, v in items.items()]
        with session_scope(self.engine) as s:
            stmt = insert(CacheEntry).values(rows)
            s.execute(stmt.on_conflict_do_update(
                index_elements=["key"], set_={"value": stmt.excluded.value}
            ))

    def set(self, key: str, value: bytes) -> None:
        """Insert or replace one entry."""
        self.set_many({key: value})

    def get_json(self, key: str) -> object | None:
        """Return a cached JSON value, or ``None`` on a miss."""
        raw = self.get(key)
        return None if raw is None else json.loads(raw.decode("utf-8"))

    def set_json(self, key: str, value: object) -> None:
        """Store a JSON-serialisable value."""
        self.set(key, json.dumps(value, ensure_ascii=False).encode("utf-8"))
