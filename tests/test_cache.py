from backend.knowledge.cache import Cache, content_hash


def test_content_hash_is_order_and_boundary_sensitive():
    assert content_hash("a", "b") == content_hash("a", "b")
    assert content_hash("a", "b") != content_hash("b", "a")
    assert content_hash("ab", "c") != content_hash("a", "bc")


def test_cache_roundtrip_and_namespaces(engine):
    emb = Cache("embedding", engine)
    llm = Cache("llm", engine)
    k = emb.key("model", "text")
    assert emb.get(k) is None
    emb.set(k, b"\x00\x01")
    assert emb.get(k) == b"\x00\x01"
    assert llm.key("model", "text") != k  # same payload, different namespace
    emb.set(k, b"\x02")  # overwrite
    assert emb.get(k) == b"\x02"


def test_cache_many_and_json(engine):
    c = Cache("t", engine)
    items = {c.key(str(i)): str(i).encode() for i in range(1200)}  # crosses the 500-key batch
    c.set_many(items)
    assert c.get_many(items) == items
    c.set_json(c.key("j"), {"claim": "₹ 25,000 million"})
    assert c.get_json(c.key("j")) == {"claim": "₹ 25,000 million"}
