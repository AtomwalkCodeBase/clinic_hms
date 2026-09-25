"""
core/llm_client.py
------------------
One door to "the LLM", whichever one this server uses. Toggle in .env:

    LLM_MODE=local        your machine's Ollama (OpenAI-compatible
                          DOC_CLASSIFIER_LLM_BASE / _MODEL) — development
    LLM_MODE=production   the GPU server's gateway (LLM_GATEWAY_URL):
                            POST {url}/ask/     {system_prompt, user_prompt, temperature, max_tokens}
                                             -> {content, prompt_tokens, completion_tokens, generation_time}
                            GET  {url}/status/  reachable?

    complete(system, user, …) -> {"content", "prompt_tokens", "completion_tokens", "generation_time"}
    status()                  -> {"mode", "url", "model", "online", "detail"}
    max_chars()               -> how much page text a prompt may carry in this mode

Raises LLMUnavailable when the server can't be reached / is busy / errors —
callers running as Celery tasks on the "llm" queue retry on it, so work
waits for the GPU server instead of failing (core/pipeline/llm_queue.py).
"""

import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """The LLM server is down, unreachable or overloaded — try again later."""


def mode() -> str:
    m = (getattr(settings, "LLM_MODE", "local") or "local").strip().lower()
    return "production" if m in ("production", "prod", "gpu") else "local"


def _gateway() -> str:
    return (getattr(settings, "LLM_GATEWAY_URL", "") or "").rstrip("/")


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    token = getattr(settings, "LLM_GATEWAY_TOKEN", "")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def configured() -> bool:
    if mode() == "production":
        return bool(_gateway())
    from core import doc_classifier_llm as dcl
    return dcl._enabled()


def label() -> str:
    if mode() == "production":
        return "GPU server"
    return f"local · {getattr(settings, 'DOC_CLASSIFIER_LLM_MODEL', '')}"


def max_chars() -> int:
    if mode() == "production":
        return int(getattr(settings, "LLM_GATEWAY_MAX_CHARS", 12000) or 12000)
    return int(getattr(settings, "DOC_CLASSIFIER_LLM_MAX_CHARS", 0) or 6000)


# ── calls ────────────────────────────────────────────────────────────────
def complete(system: str, user: str, *, temperature: float = 0.0, max_tokens: int = 1024,
             json_mode: bool = False) -> dict:
    if mode() == "production":
        return _complete_gateway(system, user, temperature, max_tokens)
    return _complete_local(system, user, temperature, max_tokens, json_mode)


def _complete_gateway(system, user, temperature, max_tokens):
    url = _gateway()
    if not url:
        raise LLMUnavailable("LLM_GATEWAY_URL is not set")
    t0 = time.monotonic()
    try:
        r = requests.post(f"{url}/ask/", headers=_headers(), timeout=int(getattr(settings, "LLM_GATEWAY_TIMEOUT", 300)),
                          json={"system_prompt": system, "user_prompt": user,
                                "temperature": temperature, "max_tokens": max_tokens})
    except requests.RequestException as exc:
        raise LLMUnavailable(f"GPU server unreachable: {exc.__class__.__name__}") from exc
    if r.status_code in (429, 502, 503, 504) or r.status_code >= 500:
        raise LLMUnavailable(f"GPU server busy/unavailable (HTTP {r.status_code})")
    r.raise_for_status()
    d = r.json()
    return {
        "content": d.get("content") or "",
        "prompt_tokens": d.get("prompt_tokens"),
        "completion_tokens": d.get("completion_tokens"),
        "generation_time": d.get("generation_time") or round(time.monotonic() - t0, 2),
    }


def _complete_local(system, user, temperature, max_tokens, json_mode):
    base = (getattr(settings, "DOC_CLASSIFIER_LLM_BASE", "") or "").rstrip("/")
    if not base:
        raise LLMUnavailable("DOC_CLASSIFIER_LLM_BASE is not set")
    key = getattr(settings, "DOC_CLASSIFIER_LLM_KEY", "") or "local"
    payload = {
        "model": settings.DOC_CLASSIFIER_LLM_MODEL, "temperature": temperature, "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    t0 = time.monotonic()
    try:
        r = requests.post(f"{base}/chat/completions", json=payload, timeout=int(getattr(settings, "DOC_CLASSIFIER_LLM_TIMEOUT", 45) or 45),
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    except requests.RequestException as exc:
        raise LLMUnavailable(f"local LLM unreachable: {exc.__class__.__name__}") from exc
    if r.status_code == 400 and json_mode and "response_format" in r.text:
        return _complete_local(system, user, temperature, max_tokens, False)
    if r.status_code in (429, 502, 503, 504) or r.status_code >= 500:
        raise LLMUnavailable(f"local LLM busy/unavailable (HTTP {r.status_code})")
    r.raise_for_status()
    d = r.json()
    usage = d.get("usage") or {}
    return {
        "content": d["choices"][0]["message"]["content"],
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "generation_time": round(time.monotonic() - t0, 2),
    }


def status() -> dict:
    """Is the configured LLM reachable right now? Never raises."""
    out = {"mode": mode(), "label": label(), "configured": configured(), "online": False, "detail": ""}
    try:
        if mode() == "production":
            url = _gateway()
            out["url"] = url
            if not url:
                out["detail"] = "LLM_GATEWAY_URL is not set"
                return out
            r = requests.get(f"{url}/status/", headers=_headers(), timeout=5)
            out["online"] = r.ok
            try:
                out["detail"] = r.json()
            except ValueError:
                out["detail"] = r.text[:200]
        else:
            base = (getattr(settings, "DOC_CLASSIFIER_LLM_BASE", "") or "").rstrip("/")
            out["url"] = base
            if not base:
                out["detail"] = "DOC_CLASSIFIER_LLM_BASE is not set"
                return out
            r = requests.get(f"{base}/models", timeout=5,
                             headers={"Authorization": f"Bearer {getattr(settings, 'DOC_CLASSIFIER_LLM_KEY', '') or 'local'}"})
            out["online"] = r.ok
            out["detail"] = {"model": getattr(settings, "DOC_CLASSIFIER_LLM_MODEL", "")}
    except requests.RequestException as exc:
        out["detail"] = f"unreachable ({exc.__class__.__name__})"
    return out
