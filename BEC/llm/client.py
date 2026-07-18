"""
llm/client.py
=============
LLM access with a provider fallback chain (default: HuggingFace Pro →
local Ollama). HF gives the best Italian quality; Ollama is the zero-cost
local backstop used when HF has no token or its credits are depleted
(402 Payment Required).

Modeled on the SPI _HuggingFaceExtractor for the HF side: InferenceClient
.chat_completion + fence-stripping JSON parsing with retries.
"""

from __future__ import annotations

import json
import logging
import re
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_hf_client = None
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class LLMError(Exception):
    pass


class LLMCreditError(LLMError):
    """HF returned 402 / out-of-credits — skip HF for the rest of the run."""


# Once HF reports depleted credits, don't keep retrying it this process.
_hf_disabled = False


def _get_hf_client():
    global _hf_client
    if _hf_client is None:
        from huggingface_hub import InferenceClient

        _hf_client = InferenceClient(model=settings.HF_LLM_MODEL, token=settings.HF_API_TOKEN)
    return _hf_client


def _hf_chat(system: str, user: str, max_tokens: int, temperature: float) -> str:
    client = _get_hf_client()
    try:
        resp = client.chat_completion(
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            max_tokens=max_tokens, temperature=temperature,
        )
        return resp.choices[0].message.content or ""
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "402" in msg or "Payment Required" in msg or "depleted" in msg:
            raise LLMCreditError(msg) from exc
        raise LLMError(msg) from exc


def _ollama_chat(system: str, user: str, max_tokens: int, temperature: float) -> str:
    resp = requests.post(
        f"{settings.OLLAMA_URL}/api/chat",
        json={
            "model": settings.OLLAMA_MODEL,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "stream": False,
            "format": "json",  # nudge valid JSON for our extraction prompts
            "options": {"temperature": temperature, "num_predict": max_tokens},
        },
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json().get("message", {}).get("content", "")


def _providers() -> list[str]:
    order = []
    for p in settings.LLM_PROVIDER_ORDER:
        p = p.strip().lower()
        if p == "hf" and settings.HF_API_TOKEN and not _hf_disabled:
            order.append("hf")
        elif p == "ollama":
            order.append("ollama")
    return order


def chat(system: str, user: str, max_tokens: int = 800, temperature: float = 0.2,
         retries: int = 2) -> str:
    """Return raw assistant text, trying providers in order with retries."""
    global _hf_disabled
    providers = _providers()
    if not providers:
        raise LLMError("no LLM provider available (no HF token, Ollama disabled)")

    last_err = None
    for provider in providers:
        fn = _hf_chat if provider == "hf" else _ollama_chat
        for attempt in range(retries + 1):
            try:
                return fn(system, user, max_tokens, temperature)
            except LLMCreditError as exc:
                logger.warning("[llm] HF credits depleted — disabling HF, falling back")
                _hf_disabled = True
                last_err = exc
                break  # stop retrying HF, move to next provider
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                if attempt < retries:
                    time.sleep(2 ** attempt)
        # provider exhausted → next provider
    raise LLMError(f"all providers failed: {last_err!r}")


def chat_json(system: str, user: str, **kwargs) -> dict | list:
    return parse_json(chat(system, user, **kwargs))


def parse_json(raw: str):
    text = (raw or "").strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    return json.loads(text)


def available() -> bool:
    """True if any provider can serve (HF token, or Ollama reachable)."""
    if settings.HF_API_TOKEN and not _hf_disabled:
        return True
    if "ollama" in [p.strip().lower() for p in settings.LLM_PROVIDER_ORDER]:
        try:
            requests.get(f"{settings.OLLAMA_URL}/api/tags", timeout=3).raise_for_status()
            return True
        except Exception:  # noqa: BLE001
            return False
    return False
