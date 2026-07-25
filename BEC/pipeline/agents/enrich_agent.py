"""
pipeline/agents/enrich_agent.py
===============================
EnrichAgent — one HF LLM call per reel with enrich_status='pending':
extracts summary_it, topics, hook, target audience, content_format.

Then extracts standalone arguments/claims (layer-2) for reels with
argument_status='pending'. Both stages are idempotent and skip gracefully
when HF_API_TOKEN is absent (pipeline continues, like SPI enrichment).
"""

from __future__ import annotations

import logging
import time

from django.db.models import Q

from core.models import DONE, FAILED, PENDING, SKIPPED, Enrichment, Reel, ReelArgument
from llm import client, prompts

logger = logging.getLogger(__name__)

VALID_FORMATS = {
    "talking_head", "voiceover", "tutorial", "testimonianza",
    "text_overlay", "intervista", "altro",
}
_DELAY = 0.3


def _enrich_one(reel: Reel) -> None:
    transcript = getattr(reel, "transcript", None)
    transcript_text = transcript.text if transcript else ""
    user = prompts.ENRICH_USER_TEMPLATE.format(
        caption=(reel.caption or "")[:1500],
        transcript=(transcript_text or "")[:3000] or "(nessuna trascrizione)",
    )
    data = client.chat_json(prompts.ENRICH_SYSTEM, user, max_tokens=700,
                            model=client.settings.FAST_LLM_MODEL_BULK)
    fmt = str(data.get("content_format", "")).strip().lower()
    if fmt not in VALID_FORMATS:
        fmt = "altro"
    topics = data.get("topics") or []
    if isinstance(topics, str):
        topics = [t.strip() for t in topics.split(",") if t.strip()]

    Enrichment.objects.update_or_create(
        reel=reel,
        defaults={
            "summary_it": str(data.get("summary_it", ""))[:2000],
            "topics": [str(t).lower()[:60] for t in topics][:6],
            "hook_text": str(data.get("hook_text", ""))[:500],
            "hook_analysis_it": str(data.get("hook_analysis_it", ""))[:1000],
            "target_audience_it": str(data.get("target_audience_it", ""))[:1000],
            "content_format": fmt,
            "llm_model": client.settings.HF_LLM_MODEL,
            "raw_response": data if isinstance(data, dict) else {},
        },
    )


def _extract_arguments(reel: Reel) -> int:
    transcript = getattr(reel, "transcript", None)
    transcript_text = transcript.text if transcript else ""
    user = prompts.ARGUMENTS_USER_TEMPLATE.format(
        caption=(reel.caption or "")[:1500],
        transcript=(transcript_text or "")[:3000] or "(nessuna trascrizione)",
    )
    data = client.chat_json(prompts.ARGUMENTS_SYSTEM, user, max_tokens=600,
                            model=client.settings.FAST_LLM_MODEL_BULK)
    args = data.get("argomenti") if isinstance(data, dict) else data
    if not isinstance(args, list):
        args = []
    reel.arguments.all().delete()  # re-extraction replaces
    created = 0
    for a in args:
        text = str(a).strip()
        if len(text) >= 8:
            ReelArgument.objects.create(reel=reel, text_it=text[:1000])
            created += 1
    return created


def run(ctx) -> dict:
    if not client.available():
        return {"skipped": True, "note": "HF_API_TOKEN not set"}

    # Stage A: enrichment. Include silent reels (transcription SKIPPED) —
    # they still have captions worth enriching.
    qs = Reel.objects.filter(
        Q(transcribe_status=DONE) | Q(transcribe_status=SKIPPED),
        enrich_status=PENDING, is_active=True,
    )
    if ctx.limit:
        qs = qs[: ctx.limit]
    enriched = failed = 0
    for reel in qs:
        try:
            _enrich_one(reel)
            reel.enrich_status = DONE
            reel.last_error = ""
            reel.save(update_fields=["enrich_status", "last_error"])
            enriched += 1
        except Exception as exc:  # noqa: BLE001
            reel.enrich_status = FAILED
            reel.last_error = repr(exc)[:500]
            reel.save(update_fields=["enrich_status", "last_error"])
            failed += 1
            logger.warning("[enrich] %s failed: %r", reel.shortcode, exc)
        time.sleep(_DELAY)

    # Stage B: argument extraction
    qs2 = Reel.objects.filter(argument_status=PENDING, enrich_status=DONE, is_active=True)
    if ctx.limit:
        qs2 = qs2[: ctx.limit]
    arg_reels = total_args = arg_failed = 0
    for reel in qs2:
        try:
            n = _extract_arguments(reel)
            reel.argument_status = DONE
            reel.save(update_fields=["argument_status"])
            arg_reels += 1
            total_args += n
        except Exception as exc:  # noqa: BLE001
            reel.argument_status = FAILED
            reel.last_error = repr(exc)[:500]
            reel.save(update_fields=["argument_status", "last_error"])
            arg_failed += 1
            logger.warning("[arguments] %s failed: %r", reel.shortcode, exc)
        time.sleep(_DELAY)

    # Retry transient failures next run
    Reel.objects.filter(enrich_status=FAILED).update(enrich_status=PENDING)
    Reel.objects.filter(argument_status=FAILED).update(argument_status=PENDING)

    return {"enriched": enriched, "enrich_failed": failed,
            "arg_reels": arg_reels, "arguments": total_args, "arg_failed": arg_failed}
