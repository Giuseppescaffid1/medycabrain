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

import contextlib
import contextvars
import fcntl
import json
import logging
import os
import re
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_hf_client = None
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

# Which model actually served the last call. Callers record this instead of
# guessing from settings — enrichments used to all claim a model that never
# ran, which made quality regressions impossible to attribute.
_last_model: contextvars.ContextVar[str] = contextvars.ContextVar("last_model", default="")


def last_model_used() -> str:
    return _last_model.get()


class LLMError(Exception):
    pass


class LLMRateLimit(LLMError):
    """Provider is rate-limiting us (429). Carries how long to wait."""

    def __init__(self, retry_after: float, daily: bool = False):
        super().__init__(
            "daily token budget exhausted" if daily
            else f"rate limited, retry in {retry_after:.0f}s")
        self.retry_after = retry_after
        self.daily = daily


class LLMCreditError(LLMError):
    """Provider returned 401/402/403 — bad key or no balance. That endpoint is
    skipped for the rest of the process; the next one in the chain answers."""


class LLMModelMissing(LLMError):
    """404: this provider does not serve that model name.

    Distinct from a dead key on purpose — the provider is fine, only the name
    is wrong, so we move to the next endpoint WITHOUT disabling this one.
    Groq retiring llama-3.3-70b-versatile is exactly this case."""


# Once a provider reports a bad key / depleted credits, skip it this process.
# Per ENDPOINT, not global: when one gateway runs out of balance the next one
# in the chain must still answer. A single flag here meant a dead gateway took
# the whole remote layer down with it and everything fell to the local 3B.
_hf_disabled = False
_fast_disabled: set[str] = set()


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


def _ollama_chat(system: str, user: str, max_tokens: int, temperature: float,
                 json_mode: bool = False, timeout: int = 240, on_token=None) -> str:
    """Local generation. Streams so a slow CPU still shows life: `timeout`
    becomes a per-chunk read timeout instead of a whole-answer deadline, so a
    long-but-progressing answer is no longer killed halfway."""
    payload = {
        "model": settings.OLLAMA_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "stream": True,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    if json_mode:  # only for structured-extraction prompts, not free-text answers
        payload["format"] = "json"
    _last_model.set(f"ollama:{settings.OLLAMA_MODEL}")
    chunks: list[str] = []
    deadline = time.time() + timeout
    with requests.post(f"{settings.OLLAMA_URL}/api/chat", json=payload,
                       stream=True, timeout=(10, 120)) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue
            piece = (data.get("message") or {}).get("content", "")
            if piece:
                chunks.append(piece)
                if on_token:
                    with contextlib.suppress(Exception):
                        on_token("".join(chunks))
            if data.get("done"):
                break
            if time.time() > deadline:
                logger.warning("[llm] ollama stream exceeded %ss — returning partial", timeout)
                break
    return "".join(chunks)


@contextlib.contextmanager
def _ollama_slot(wait: int | None = None, priority: bool = False):
    """Serialize local generations across every process on the box.

    The CPU fits exactly one 3B/7B generation at a time. Two concurrent
    callers (nightly pipeline + a client pressing "Analizza") each run at
    half speed and BOTH hit their read timeout — the failure mode that made
    every job fail while burning 700% CPU. An flock turns that collision
    into a queue.
    """
    wait = wait if wait is not None else settings.OLLAMA_LOCK_WAIT
    path = settings.OLLAMA_LOCK_PATH
    prio_path = path + ".priority"
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o666)
    deadline = time.time() + wait
    prio_fd = None
    try:
        if priority:
            # Announce ourselves so batch work stands aside at its next item.
            prio_fd = os.open(prio_path, os.O_CREAT | os.O_RDWR, 0o666)
            fcntl.flock(prio_fd, fcntl.LOCK_EX)
        else:
            # Batch work: never start a new generation while a human waits.
            while os.path.exists(prio_path) and _prio_held(prio_path):
                if time.time() >= deadline:
                    raise LLMError("ollama busy: interactive work has priority")
                time.sleep(2.0)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() >= deadline:
                    raise LLMError(f"ollama busy: no free slot after {wait}s")
                time.sleep(1.0)
        yield
    finally:
        with contextlib.suppress(Exception):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        if prio_fd is not None:
            with contextlib.suppress(Exception):
                fcntl.flock(prio_fd, fcntl.LOCK_UN)
            os.close(prio_fd)


def _prio_held(prio_path: str) -> bool:
    """True while some interactive caller actually holds the priority flag
    (a stale file left by a crashed process must not block batch work)."""
    try:
        fd = os.open(prio_path, os.O_RDWR)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)


def _anthropic_chat(system: str, user: str, max_tokens: int, temperature: float,
                    json_mode: bool = False, timeout: int = 300, model: str = "",
                    endpoint: dict | None = None) -> str:
    """Anthropic's own Messages API — NOT OpenAI-compatible.

    Different path (/v1/messages), different auth header (x-api-key, not
    Bearer), the system prompt as its own top-level field, and the answer in
    content[].text. That is why it cannot ride on _fast_chat.

    Only the synchronous path lives here. The bulk nightly work goes through
    llm/batch.py instead: same models, half the price, answers within 24h.
    """
    import anthropic

    endpoint = endpoint or {}
    model = model or endpoint.get("models", {}).get("reasoning") or settings.BATCH_MODEL
    client = anthropic.Anthropic(api_key=endpoint.get("api_key", ""),
                                 timeout=float(timeout), max_retries=0)
    if json_mode:
        # No response_format on this API: the documented way to pin the shape
        # is to ask for it. The callers' prompts already demand JSON; this
        # only reinforces it.
        system = system + "\n\nRispondi esclusivamente con un oggetto JSON valido."
    _last_model.set(model)
    try:
        # No temperature/top_p: the sampling parameters were REMOVED on the
        # current Claude models (Sonnet 5, Opus 5, 4.7+) and the SDK rejects
        # the keyword outright. Determinism comes from the prompt instead.
        msg = client.messages.create(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.AuthenticationError as exc:
        raise LLMCreditError(f"anthropic: chiave rifiutata — {exc}") from exc
    except anthropic.PermissionDeniedError as exc:
        raise LLMCreditError(f"anthropic: accesso negato — {exc}") from exc
    except anthropic.NotFoundError as exc:
        raise LLMModelMissing(f"anthropic non serve il modello {model!r}") from exc
    except anthropic.RateLimitError as exc:
        wait = 0.0
        resp = getattr(exc, "response", None)
        if resp is not None:
            try:
                wait = float(resp.headers.get("retry-after", "") or 0)
            except ValueError:
                wait = 0.0
        raise LLMRateLimit(wait or 20.0) from exc
    except anthropic.APIStatusError as exc:
        # "credit balance is too low" is a spend problem, not a bug: treat it
        # like a dead key so the chain moves on instead of retrying.
        if "credit balance" in str(exc).lower():
            raise LLMCreditError(f"anthropic: credito esaurito — {exc}") from exc
        raise LLMError(str(exc)[:300]) from exc
    if getattr(msg, "stop_reason", "") == "refusal":
        raise LLMError("anthropic: richiesta rifiutata dai filtri di sicurezza")
    if getattr(msg, "stop_reason", "") == "max_tokens":
        # A truncated answer is not a shorter answer: JSON callers would fail
        # with a parse error that hides the real cause.
        raise LLMError(
            f"anthropic: risposta troncata al tetto di {max_tokens} token")
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _fast_chat(system: str, user: str, max_tokens: int, temperature: float,
               json_mode: bool = False, timeout: int = 120, model: str = "",
               endpoint: dict | None = None) -> str:
    """One OpenAI-compatible remote provider (Groq, OpenRouter, a gateway, …).

    Two orders of magnitude faster than local CPU inference, which is what
    makes the Second Brain feel instant instead of frozen. `endpoint` is one
    entry of settings.FAST_ENDPOINTS — url, key and model names travel
    together, so two providers are never mixed up.
    """
    endpoint = endpoint or (settings.FAST_ENDPOINTS[0] if settings.FAST_ENDPOINTS else {})
    base_url = endpoint.get("base_url") or settings.FAST_LLM_BASE_URL
    api_key = endpoint.get("api_key") or settings.FAST_LLM_API_KEY
    payload = {
        "model": model or endpoint.get("models", {}).get("reasoning") or settings.FAST_LLM_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    # gpt-oss models emit REASONING tokens before the answer, billed against
    # max_tokens. Measured 2026-09-13 on one enrichment prompt: 406 completion
    # tokens at the default effort, 263 at "low", same JSON quality. At
    # max_tokens=20 the answer came back EMPTY — the whole budget went to
    # reasoning, with finish_reason still "stop". Silent failure; hence this.
    if "gpt-oss" in payload["model"]:
        payload.setdefault("reasoning_effort", "low")
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
        # OpenAI-compatible endpoints reject json mode outright (400) unless
        # the word "json" appears in the messages. Without this the whole
        # enrichment path silently fell back to local CPU inference.
        if "json" not in f"{system}{user}".lower():
            payload["messages"][0]["content"] = (
                system + "\n\nRispondi esclusivamente con un oggetto JSON valido.")
    _last_model.set(payload["model"])
    resp = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        json=payload, timeout=timeout,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
    )
    if resp.status_code in (401, 402, 403):
        raise LLMCreditError(
            f"{endpoint.get('name', 'fast')} rejected the key "
            f"({resp.status_code}): {resp.text[:120]}")
    if resp.status_code == 404:
        # The model name is not on this account (a provider retired it, or a
        # gateway's catalogue differs). Retrying it is pointless.
        raise LLMModelMissing(
            f"{endpoint.get('name', 'fast')} has no model {payload['model']!r}")
    if resp.status_code == 429:
        # Free tiers cap tokens-per-minute. Waiting for the bucket to refill
        # is far cheaper than falling back to a ~136s local generation.
        try:
            wait = float(resp.headers.get("retry-after", "") or 0)
        except ValueError:
            wait = 0.0
        # A per-day cap will not refill within any sane wait: escalate at once.
        daily = "per day" in resp.text.lower() or "tpd" in resp.text.lower()
        raise LLMRateLimit(wait or 20.0, daily=daily)
    if resp.status_code == 400:
        # A malformed request will fail identically on every retry: surface it
        # loudly instead of burning the local fallback on it.
        logger.error("[llm] fast provider rejected the request: %s", resp.text[:200])
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def transcribe_audio(path: str, prompt: str = "", language: str = "it") -> dict:
    """Speech-to-text on the fast provider (whisper-large-v3).

    Returns {"text", "segments", "model"}. `prompt` carries the domain
    glossary: whisper conditions on it, which is what fixes recurring medical
    terms the local `small` model mangles ("ormoni bioidentici").
    Raises LLMError so the caller can fall back to the local model.
    """
    if not settings.STT_API_KEY:
        raise LLMError("no STT provider key")
    url = f"{settings.STT_BASE_URL.rstrip('/')}/audio/transcriptions"
    data = {"model": settings.FAST_STT_MODEL, "language": language,
            "response_format": "verbose_json", "temperature": "0"}
    if prompt:
        data["prompt"] = prompt[:800]
    with open(path, "rb") as fh:
        resp = requests.post(
            url, headers={"Authorization": f"Bearer {settings.STT_API_KEY}"},
            files={"file": (os.path.basename(path), fh, "audio/mpeg")},
            data=data, timeout=300,
        )
    if resp.status_code == 429:
        try:
            wait = float(resp.headers.get("retry-after", "") or 0)
        except ValueError:
            wait = 0.0
        daily = "per day" in resp.text.lower() or "tpd" in resp.text.lower()
        raise LLMRateLimit(wait or 20.0, daily=daily)
    if resp.status_code >= 400:
        raise LLMError(f"STT failed ({resp.status_code}): {resp.text[:200]}")
    payload = resp.json()
    segments = [
        {"start": round(float(s.get("start", 0)), 2),
         "end": round(float(s.get("end", 0)), 2),
         "text": (s.get("text") or "").strip()}
        for s in payload.get("segments", [])
    ]
    return {"text": (payload.get("text") or "").strip(),
            "segments": segments,
            "model": settings.FAST_STT_MODEL}


TASKS = ("analysis", "reasoning", "bulk")


def _endpoints() -> list[dict]:
    """The remote providers still worth trying, in priority order."""
    return [e for e in settings.FAST_ENDPOINTS
            if e.get("api_key") and e["name"] not in _fast_disabled]


def model_for(task: str) -> str:
    """The model name for a kind of work, on the FIRST live provider.

    'analysis'  reading a transcript, extracting claims, naming themes —
                the deep layer, where a weak model costs meaning
    'reasoning' strategy briefs and drafts
    'bulk'      mechanical, high-volume extraction

    Callers pass the result back as chat(model=...); chat() re-resolves it per
    provider as it walks the chain, so a caller never needs to know who will
    end up answering.
    """
    order = {"analysis": ("analysis", "reasoning", "bulk"),
             "reasoning": ("reasoning", "analysis", "bulk")}.get(
                 task, ("bulk", "reasoning", "analysis"))
    for ep in _endpoints() or settings.FAST_ENDPOINTS:
        for tier in order:
            if ep.get("models", {}).get(tier):
                return ep["models"][tier]
    return settings.OLLAMA_MODEL


def _task_of(model: str) -> str:
    """Which tier a model name belongs to, across every configured provider.

    This is what lets the chain keep its meaning: a caller asked for the
    'analysis' model of provider #1, so when provider #2 answers instead it
    must answer with ITS analysis model, not with provider #1's name — which
    it would 404 on.
    """
    for ep in settings.FAST_ENDPOINTS:
        for tier, name in (ep.get("models") or {}).items():
            if name and name == model:
                return tier
    return ""


def _providers() -> list[tuple[str, dict | None]]:
    """(kind, endpoint) in the order they will be tried."""
    order: list[tuple[str, dict | None]] = []
    for p in settings.LLM_PROVIDER_ORDER:
        p = p.strip().lower()
        if p == "fast":
            order += [("fast", ep) for ep in _endpoints()]
        elif p == "hf" and settings.HF_API_TOKEN and not _hf_disabled:
            order.append(("hf", None))
        elif p == "ollama":
            order.append(("ollama", None))
    return order


def chat(system: str, user: str, max_tokens: int = 800, temperature: float = 0.2,
         retries: int = 2, json_mode: bool = False, timeout: int = 240,
         on_token=None, priority: bool = False, model: str = "") -> str:
    """Return raw assistant text, trying providers in order with retries.

    json_mode nudges Ollama to emit valid JSON — set only for extraction
    prompts, never for free-text answers (it degrades prose quality).
    timeout applies to the Ollama call (long jobs pass a bigger value).
    """
    global _hf_disabled, _fast_disabled
    providers = _providers()
    if not providers:
        raise LLMError("no LLM provider available (no key, Ollama disabled)")

    # The tier the caller asked for, so every provider in the chain answers
    # with ITS model of that tier instead of a name it does not serve.
    task = _task_of(model) if model else ""

    def _model_on(endpoint) -> str:
        if not model:
            return ""
        if endpoint.get("models", {}).get(task):
            return endpoint["models"][task]
        return model if endpoint is (settings.FAST_ENDPOINTS or [None])[0] else ""

    def _call_alt(endpoint, alt_model: str) -> str:
        """Same endpoint, a sibling model — used when a daily cap is hit."""
        fn = _anthropic_chat if endpoint.get("dialect") == "anthropic" else _fast_chat
        return fn(system, user, max_tokens, temperature, json_mode=json_mode,
                  timeout=min(timeout, 300), model=alt_model, endpoint=endpoint)

    def _call(provider, endpoint=None):
        if provider == "fast":
            if (endpoint or {}).get("dialect") == "anthropic":
                return _anthropic_chat(system, user, max_tokens, temperature,
                                       json_mode=json_mode, timeout=min(timeout, 300),
                                       model=_model_on(endpoint), endpoint=endpoint)
            return _fast_chat(system, user, max_tokens, temperature,
                              json_mode=json_mode, timeout=min(timeout, 120),
                              model=_model_on(endpoint), endpoint=endpoint)
        if provider == "hf":
            return _hf_chat(system, user, max_tokens, temperature)
        # Local generation: take the single CPU slot, never run two at once.
        with _ollama_slot(priority=priority):
            return _ollama_chat(system, user, max_tokens, temperature,
                                json_mode=json_mode, timeout=timeout,
                                on_token=on_token)

    last_err = None
    for provider, endpoint in providers:
        label = endpoint["name"] if endpoint else provider
        for attempt in range(retries + 1):
            try:
                return _call(provider, endpoint)
            except LLMModelMissing as exc:
                # The provider works, the model name does not exist on it.
                # Next provider, and keep this one available for other tiers.
                logger.warning("[llm] %s: %s", label, exc)
                last_err = exc
                break
            except LLMCreditError as exc:
                logger.warning("[llm] %s key rejected/depleted — disabling it: %s",
                               label, exc)
                if provider == "fast":
                    _fast_disabled.add(endpoint["name"])
                else:
                    _hf_disabled = True
                last_err = exc
                break
            except LLMRateLimit as exc:
                last_err = exc
                if exc.daily:
                    # Today's budget for THIS model is gone; each model has its
                    # own. Walk the chain before ever dropping to local CPU.
                    if provider == "fast":
                        tried = {_model_on(endpoint)
                                 or endpoint.get("models", {}).get("reasoning")}
                        for alt in endpoint.get("chain", []):
                            if alt in tried:
                                continue
                            tried.add(alt)
                            logger.warning("[llm] daily budget exhausted — switching to %s", alt)
                            try:
                                return _call_alt(endpoint, alt)
                            except LLMRateLimit as exc2:
                                last_err = exc2
                                if not exc2.daily:
                                    break
                            except Exception as exc2:  # noqa: BLE001
                                last_err = exc2
                                break
                    break
                wait = min(exc.retry_after, 60.0)
                logger.info("[llm] %s rate-limited — waiting %.0fs", label, wait)
                if attempt < retries:
                    time.sleep(wait)
                    continue
                break
            except requests.exceptions.Timeout as exc:
                # Retrying a timeout means asking a machine that is already
                # too slow to redo the same work — it only deepens the jam.
                logger.warning("[llm] %s timed out after %ss — not retrying", label, timeout)
                last_err = exc
                break
            except Exception as exc:  # noqa: BLE001
                # Log it: an unexpected failure here used to be invisible, and
                # the chain moving on quietly is exactly how a misconfigured
                # provider goes unnoticed for weeks.
                logger.warning("[llm] %s failed (attempt %s/%s): %r",
                               label, attempt + 1, retries + 1, exc)
                last_err = exc
                if attempt < retries:
                    time.sleep(2 ** attempt)
    raise LLMError(f"all providers failed: {last_err!r}")


def chat_json(system: str, user: str, **kwargs) -> dict | list:
    kwargs.setdefault("json_mode", True)
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
    """True if ANY provider can serve — remote endpoint, HF, or local Ollama.

    The remote chain has to be checked first: without it this returned False
    whenever Ollama was unreachable, and the analysis stage skipped itself
    even though a paid, working provider was configured and answering.
    """
    if _endpoints():
        return True
    if settings.HF_API_TOKEN and not _hf_disabled:
        return True
    if "ollama" in [p.strip().lower() for p in settings.LLM_PROVIDER_ORDER]:
        try:
            requests.get(f"{settings.OLLAMA_URL}/api/tags", timeout=3).raise_for_status()
            return True
        except Exception:  # noqa: BLE001
            return False
    return False
