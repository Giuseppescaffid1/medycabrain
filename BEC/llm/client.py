"""
llm/client.py
=============
Thin wrapper over the HuggingFace Pro Inference API, modeled on the SPI
_HuggingFaceExtractor: InferenceClient(model, token=HF_API_TOKEN)
.chat_completion(...) plus fence-stripping JSON parsing with retries.
"""

from __future__ import annotations

import json
import logging
import re
import time

from django.conf import settings

logger = logging.getLogger(__name__)

_client = None
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class LLMError(Exception):
    pass


def _get_client():
    global _client
    if _client is None:
        if not settings.HF_API_TOKEN:
            raise LLMError("HF_API_TOKEN not set")
        from huggingface_hub import InferenceClient

        _client = InferenceClient(model=settings.HF_LLM_MODEL, token=settings.HF_API_TOKEN)
    return _client


def chat(system: str, user: str, max_tokens: int = 800, temperature: float = 0.2,
         retries: int = 2) -> str:
    """Return the raw assistant text for a system+user prompt."""
    client = _get_client()
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = client.chat_completion(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return resp.choices[0].message.content or ""
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise LLMError(f"chat_completion failed after {retries + 1} tries: {last_err!r}")


def chat_json(system: str, user: str, **kwargs) -> dict | list:
    """chat() + robust JSON parse (strips ```json fences, finds the object)."""
    raw = chat(system, user, **kwargs)
    return parse_json(raw)


def parse_json(raw: str):
    text = raw.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    # Trim to the outermost JSON object/array if there's leading/trailing prose.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    return json.loads(text)  # let it raise if truly unparseable


def available() -> bool:
    return bool(settings.HF_API_TOKEN)
