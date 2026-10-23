"""LLM client: provider order, judge/debater separation, caching and fallback (no network)."""

import pytest

from backend.config import get_settings
from backend.llm import client as llm_client
from backend.llm.client import LLMClient, NoProviderAvailable, RetryableError, extract_json


@pytest.fixture
def keys(monkeypatch, engine):
    s = get_settings()
    monkeypatch.setattr(s, "gemini_api_key", "g-test")
    monkeypatch.setattr(s, "groq_api_key", "q-test")
    monkeypatch.setattr(s, "openrouter_api_key", "")
    monkeypatch.setattr(s, "cerebras_api_key", "")
    monkeypatch.setattr(s, "debater_provider", "gemini")
    monkeypatch.setattr(s, "judge_provider", "groq")
    monkeypatch.setattr(s, "llm_max_retries", 2)
    monkeypatch.setattr(llm_client, "session_scope", _scope(engine))
    monkeypatch.setattr(llm_client.Cache, "__init__", _cache_init(engine))
    monkeypatch.setattr(llm_client.time, "sleep", lambda _s: None)
    return s


def _scope(engine):
    from backend.db import session_scope
    return lambda: session_scope(engine)


def _cache_init(engine):
    def init(self, namespace, engine_=None):
        self.namespace, self.engine = namespace, engine
    return init


def test_extract_json_tolerates_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! Here it is: {"claims": []} hope this helps') == {"claims": []}


def test_provider_order_and_judge_separation(keys):
    assert LLMClient("debater").providers == ["gemini", "groq"]   # no key -> skipped
    assert LLMClient("judge").providers == ["groq", "gemini"]
    assert LLMClient("judge", exclude={"gemini"}).providers == ["groq"]


def test_cache_hit_and_rate_limit_fallback(keys, monkeypatch):
    calls = []

    def fake_call(self, provider, model, system, user, temperature):
        calls.append(provider)
        if provider == "gemini":
            raise RetryableError("HTTP 429")
        return '{"verdict": "Neutral"}', {"prompt_tokens": 10, "completion_tokens": 3}

    monkeypatch.setattr(LLMClient, "_call", fake_call)
    c = LLMClient("debater")
    r1 = c.complete_json("sys", "user")
    assert r1.provider == "groq" and r1.data == {"verdict": "Neutral"} and not r1.cached
    assert calls == ["gemini", "gemini", "groq"]  # retried, then fell back
    r2 = c.complete_json("sys", "user")
    assert r2.cached and calls == ["gemini", "gemini", "groq"]  # rerun: no network at all


def test_no_keys_raises(monkeypatch, keys):
    monkeypatch.setattr(keys, "gemini_api_key", "")
    monkeypatch.setattr(keys, "groq_api_key", "")
    c = LLMClient("debater")
    assert not c.available
    with pytest.raises(NoProviderAvailable):
        c.complete_json("s", "u")
