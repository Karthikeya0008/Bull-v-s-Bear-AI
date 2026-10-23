"""Provider-agnostic LLM client (free tiers): Gemini, Groq, OpenRouter, Cerebras.

* One ``complete_json`` call: tries the role's preferred provider, then the ordered
  fallback list from ``LLM_PROVIDER_ORDER``, skipping providers without an API key.
* Retries with exponential backoff on HTTP 429 / 5xx / timeouts before falling back.
* Responses are cached by content hash (provider, model, prompts, temperature), so a rerun
  costs nothing and survives rate limits.
* Every call (cached or not) is logged to ``llm_calls`` with token counts and latency.
* The judge never uses the debaters' provider (enforced by ``exclude``).
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

import httpx

from backend.config import get_settings
from backend.db import session_scope
from backend.knowledge.cache import Cache
from backend.knowledge.models import LlmCall

log = logging.getLogger(__name__)

OPENAI_COMPAT = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "cerebras": "https://api.cerebras.ai/v1/chat/completions",
}
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class NoProviderAvailable(RuntimeError):
    """Raised when no configured provider could answer."""


class RetryableError(RuntimeError):
    """Rate limit, server error or timeout: worth retrying."""


@dataclass
class LlmResponse:
    """Parsed model output plus bookkeeping."""

    data: dict
    provider: str
    model: str
    cached: bool
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


def extract_json(text: str) -> dict:
    """Parse a JSON object from model output, tolerating ``` fences and leading prose."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start >= 0 and end > start:
            return json.loads(t[start:end + 1])
        raise


class LLMClient:
    """JSON-mode chat completion with provider fallback, retries and caching."""

    def __init__(self, role: str, exclude: set[str] | None = None,
                 debate_id: str | None = None) -> None:
        self.s = get_settings()
        self.role = role
        self.debate_id = debate_id
        self.cache = Cache("llm")
        preferred = self.s.judge_provider if role == "judge" else self.s.debater_provider
        order = [preferred] + [p.strip() for p in self.s.llm_provider_order.split(",")]
        seen: list[str] = []
        for p in order:
            if p and p not in seen and p not in (exclude or set()):
                seen.append(p)
        self.providers = [p for p in seen if self._key(p)]

    def _key(self, provider: str) -> str:
        return getattr(self.s, f"{provider}_api_key", "") or ""

    def _model(self, provider: str) -> str:
        return getattr(self.s, f"{provider}_model")

    @property
    def available(self) -> bool:
        return bool(self.providers)

    def describe(self) -> str:
        """``provider/model`` of the first provider that would be tried."""
        return f"{self.providers[0]}/{self._model(self.providers[0])}" if self.providers else "none"

    # ----------------------------------------------------------------------------------------
    def complete_json(self, system: str, user: str, temperature: float = 0.3) -> LlmResponse:
        """Return the first successful JSON response across the provider chain."""
        errors = []
        keys = {p: self.cache.key(p, self._model(p), system, user, f"{temperature:.2f}")
                for p in self.providers}
        for provider in self.providers:  # any cached answer wins: reruns cost nothing
            hit = self.cache.get_json(keys[provider])
            if hit is not None:
                model = self._model(provider)
                self._log(provider, model, hit.get("usage", {}), cached=True, latency=0)
                return LlmResponse(hit["data"], provider, model, True,
                                   *self._tokens(hit.get("usage", {})))
        for provider in self.providers:
            model, key = self._model(provider), keys[provider]
            for attempt in range(self.s.llm_max_retries):
                t0 = time.perf_counter()
                try:
                    text, usage = self._call(provider, model, system, user, temperature)
                    data = extract_json(text)
                    latency = int((time.perf_counter() - t0) * 1000)
                    self.cache.set_json(key, {"data": data, "usage": usage})
                    self._log(provider, model, usage, cached=False, latency=latency)
                    return LlmResponse(data, provider, model, False, *self._tokens(usage))
                except RetryableError as exc:
                    wait = min(30, 2 ** attempt * 3)
                    log.warning("%s %s attempt %d failed (%s); retrying in %ds", self.role,
                                provider, attempt + 1, exc, wait)
                    errors.append(f"{provider}: {exc}")
                    time.sleep(wait)
                except (httpx.HTTPError, ValueError, KeyError, json.JSONDecodeError) as exc:
                    log.warning("%s %s failed: %s", self.role, provider, exc)
                    errors.append(f"{provider}: {exc}")
                    self._log(provider, model, {}, cached=False, latency=None, error=str(exc))
                    break
        raise NoProviderAvailable("; ".join(errors) or "no LLM API keys configured")

    @staticmethod
    def _tokens(usage: dict) -> tuple[int | None, int | None]:
        return usage.get("prompt_tokens"), usage.get("completion_tokens")

    def _call(self, provider: str, model: str, system: str, user: str,
              temperature: float) -> tuple[str, dict]:
        timeout = self.s.llm_timeout_seconds
        if provider == "gemini":
            body = {"systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": user}]}],
                    "generationConfig": {"temperature": temperature,
                                         "responseMimeType": "application/json"}}
            resp = self._post(GEMINI_URL.format(model=model), body, timeout,
                              params={"key": self._key("gemini")})
            payload = resp.json()
            text = "".join(p.get("text", "") for p in
                           payload["candidates"][0]["content"]["parts"])
            meta = payload.get("usageMetadata", {})
            return text, {"prompt_tokens": meta.get("promptTokenCount"),
                          "completion_tokens": meta.get("candidatesTokenCount")}
        url = OPENAI_COMPAT[provider]
        body = {"model": model, "temperature": temperature,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "response_format": {"type": "json_object"}}
        resp = self._post(url, body, timeout,
                          headers={"Authorization": f"Bearer {self._key(provider)}"})
        payload = resp.json()
        return payload["choices"][0]["message"]["content"], payload.get("usage", {}) or {}

    @staticmethod
    def _post(url: str, body: dict, timeout: int, params: dict | None = None,
              headers: dict | None = None) -> httpx.Response:
        try:
            resp = httpx.post(url, json=body, params=params, headers=headers, timeout=timeout)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise RetryableError(type(exc).__name__) from exc
        if resp.status_code == 429 or resp.status_code >= 500:
            raise RetryableError(f"HTTP {resp.status_code}")
        resp.raise_for_status()
        return resp

    def _log(self, provider: str, model: str, usage: dict, cached: bool, latency: int | None,
             error: str | None = None) -> None:
        with session_scope() as s:
            s.add(LlmCall(debate_id=self.debate_id, role=self.role, provider=provider,
                          model=model, prompt_tokens=usage.get("prompt_tokens"),
                          completion_tokens=usage.get("completion_tokens"), cached=int(cached),
                          latency_ms=latency, error=error))
