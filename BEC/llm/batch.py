"""
llm/batch.py
============
The Batch API: the same models as `llm/client.py`, at half the price, with
answers within 24 hours instead of within seconds.

Why this exists as a separate module rather than a provider in the chain:
`client.chat()` is synchronous — it hands back a string. A batch cannot do
that. Work is DELIVERED now and COLLECTED later, which means the pipeline
splits into two stages that may run on different nights. Everything that
needs an answer immediately (the chat, an "Analizza" button) keeps using
`client.chat()` and the provider chain.

The trade, measured on this corpus (1.113 reels, ~1.500 token in / ~400 out
per call, Sonnet 5):

    live calls   ~8 $     answer in ~2s
    batch        ~4 $     answer within 24h, usually inside an hour

Two rules that the code enforces rather than trusts:

1. **Results are matched by `custom_id`, never by position.** The API returns
   them in any order. Matching by position would file one reel's analysis
   under a different reel — a silent, permanent corruption of the corpus.
2. **What is in flight is marked `batched`.** Otherwise the next nightly run
   resubmits the same items and we pay twice for the same answers.

Failures stay failed, per the project rule: an `errored` or `expired` result
sets the row to `failed` with the reason, and is never silently requeued.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger(__name__)

# Anthropic's own limits: 100.000 requests or 256 MB per batch. We stay far
# below on purpose — a smaller batch fails smaller, and BATCH_MAX_REQUESTS
# caps one delivery.
PROVIDER_MAX_REQUESTS = 100_000


class BatchError(RuntimeError):
    pass


@dataclass
class BatchItem:
    """One request in a delivery. `custom_id` is how the answer finds its way
    home, so it must encode the row it belongs to (e.g. "reel-1251")."""

    custom_id: str
    system: str
    user: str
    max_tokens: int = 700


def _endpoint() -> dict:
    """The configured Anthropic endpoint, or an explanation of its absence.

    The batch runs only on Anthropic: it is the provider we pay directly, and
    the 50% discount is the whole point. Groq has no batch equivalent.
    """
    for ep in settings.FAST_ENDPOINTS:
        if ep.get("dialect") == "anthropic" and ep.get("api_key"):
            return ep
    raise BatchError(
        "nessun endpoint Anthropic configurato: serve LLM_ANTHROPIC_API_KEY nel .env")


def _client():
    import anthropic

    return anthropic.Anthropic(api_key=_endpoint()["api_key"], max_retries=2)


def available() -> bool:
    if not settings.BATCH_ENABLED:
        return False
    try:
        _endpoint()
    except BatchError:
        return False
    return True


def submit(items: list[BatchItem], *, model: str = "") -> tuple[str, list[str]]:
    """Hand a batch over. Returns (batch_id, custom_ids actually sent).

    Raises BatchError when nothing can be delivered — the caller decides
    whether that is fatal. Never silently truncates: the cap is applied by
    the caller so it knows what was left behind.
    """
    import anthropic
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    if not items:
        raise BatchError("niente da consegnare")
    if len(items) > PROVIDER_MAX_REQUESTS:
        raise BatchError(f"{len(items)} richieste: oltre il limite del fornitore")

    model = model or settings.BATCH_MODEL
    # Duplicate custom_ids would make the answers ambiguous — refuse up front
    # rather than discover it while writing results.
    seen = {i.custom_id for i in items}
    if len(seen) != len(items):
        raise BatchError("custom_id duplicati nella stessa consegna")

    requests = [
        Request(
            custom_id=it.custom_id,
            params=MessageCreateParamsNonStreaming(
                model=model,
                max_tokens=it.max_tokens,
                system=it.system + "\n\nRispondi esclusivamente con un oggetto JSON valido.",
                messages=[{"role": "user", "content": it.user}],
            ),
        )
        for it in items
    ]
    try:
        batch = _client().messages.batches.create(requests=requests)
    except anthropic.AuthenticationError as exc:
        raise BatchError(f"chiave rifiutata: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise BatchError(f"consegna rifiutata ({exc.status_code}): {str(exc)[:200]}") from exc
    logger.info("[batch] consegnate %s richieste a %s — batch %s",
                len(requests), model, batch.id)
    return batch.id, [it.custom_id for it in items]


def status(batch_id: str) -> dict:
    """Where the delivery is: {'ended': bool, 'processing_status', counts…}."""
    b = _client().messages.batches.retrieve(batch_id)
    c = b.request_counts
    return {
        "processing_status": b.processing_status,
        "ended": b.processing_status == "ended",
        "processing": c.processing,
        "succeeded": c.succeeded,
        "errored": c.errored,
        "canceled": c.canceled,
        "expired": c.expired,
    }


def collect(batch_id: str) -> dict[str, dict]:
    """Pick the answers up, keyed by custom_id.

    Each value is either {"ok": True, "data": <parsed json>, "model": str} or
    {"ok": False, "error": "<reason>"}. Parsing happens here so a malformed
    answer is an error for ONE item instead of an exception that loses the
    whole batch — which is 24 hours and real money.
    """
    from llm.client import parse_json

    # Keep the client alive for the whole iteration. `results()` is a streamed
    # JSONL response: building the client inline inside the for-statement let
    # it be garbage-collected as soon as the expression finished, which closed
    # the socket under the stream — "ReadError: [Errno 9] Bad file descriptor"
    # on every collect.
    client = _client()
    out: dict[str, dict] = {}
    for res in client.messages.batches.results(batch_id):
        kind = res.result.type
        if kind != "succeeded":
            # errored / canceled / expired all stay failures. An "errored"
            # with type invalid_request will fail identically on retry; a
            # server error would be safe to retry, but retrying is a human
            # decision here, not an automatic loop.
            reason = kind
            err = getattr(res.result, "error", None)
            if err is not None:
                reason = f"{kind}: {getattr(err, 'type', '')} {str(err)[:150]}"
            out[res.custom_id] = {"ok": False, "error": reason}
            continue
        msg = res.result.message
        if getattr(msg, "stop_reason", "") == "max_tokens":
            # Say what actually happened. Letting this fall through to the JSON
            # parser reported "json illeggibile" for a truncation, which sent
            # the reader looking for a prompt bug instead of a token ceiling.
            out[res.custom_id] = {
                "ok": False,
                "error": f"risposta troncata al tetto di {msg.usage.output_tokens} token"}
            continue
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        try:
            data = parse_json(text)
        except Exception as exc:  # noqa: BLE001 — one bad answer, not the batch
            out[res.custom_id] = {"ok": False, "error": f"json illeggibile: {exc!r}"}
            continue
        out[res.custom_id] = {"ok": True, "data": data, "model": msg.model}
    return out


def cancel(batch_id: str) -> str:
    return _client().messages.batches.cancel(batch_id).processing_status
