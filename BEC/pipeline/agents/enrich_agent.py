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


_MIN_CAPTION_CHARS = 80  # below this a caption is hashtags/greetings, not content


def _norm(text: str) -> str:
    """Fold text for substring checks: unicode-normalised, lowercase, single
    spaces. Instagram captions use mathematical-bold letters that would
    otherwise never match."""
    import re as _re
    import unicodedata
    t = unicodedata.normalize("NFKC", text or "").lower()
    return _re.sub(r"\s+", " ", t).strip()


def _caption_signal(caption: str) -> str:
    """Caption text with hashtags/mentions stripped — what actually says
    something about the content."""
    import re as _re
    return _re.sub(r"[#@]\w+", " ", caption or "").strip()


def classify_evidence(reel: Reel) -> tuple[str, str]:
    """Return (evidence, transcript_text).

    'transcript'   — there is spoken content to analyse
    'caption_only' — no audio, but the caption carries real information
    'insufficient' — neither; the model would have to invent everything
    """
    transcript = getattr(reel, "transcript", None)
    text = (transcript.text if transcript else "") or ""
    if len(text.strip()) >= 40:
        return "transcript", text
    if len(_caption_signal(reel.caption)) >= _MIN_CAPTION_CHARS:
        return "caption_only", ""
    return "insufficient", ""


def canonical_topic(t: str) -> str:
    """Fold synonym variants onto one label so the same idea stops arriving
    under three names ("terapia con ormoni bioidentici" == "ormoni bioidentici")."""
    t = " ".join((t or "").lower().split())
    return prompts.TOPIC_SYNONYMS.get(t, t)


def pick_primary_topic(raw: str, topics: list[str]) -> str:
    """Keep the model's specific answer, or recover one from the topic list.

    An umbrella label ("menopausa") is rejected: it is true of nearly every
    reel here and therefore separates nothing.
    """
    cand = canonical_topic(raw)
    if cand and cand not in prompts.UMBRELLA_TOPICS:
        return cand[:80]
    for t in topics:  # fall back to the first genuinely specific topic
        c = canonical_topic(t)
        if c and c not in prompts.UMBRELLA_TOPICS:
            return c[:80]
    return ""


def _enrich_one(reel: Reel) -> None:
    evidence, transcript_text = classify_evidence(reel)

    if evidence == "insufficient":
        # Nothing to analyse. Asking anyway is exactly how the model ended up
        # inventing medical claims for a reel that only said "grazie a tutti".
        Enrichment.objects.update_or_create(
            reel=reel,
            defaults={"summary_it": "", "topics": [], "primary_topic": "", "hook_text": "",
                      "hook_analysis_it": "", "target_audience_it": "",
                      "content_format": "altro", "llm_model": "",
                      "evidence": evidence, "raw_response": {}},
        )
        logger.info("[enrich] %s: dati insufficienti — nessuna chiamata LLM", reel.shortcode)
        return

    user = prompts.ENRICH_USER_TEMPLATE.format(
        caption=(reel.caption or "")[:1500],
        transcript=transcript_text[:3000] or "(nessuna trascrizione)",
    )
    if evidence == "caption_only":
        user += prompts.ENRICH_CAPTION_ONLY_NOTE

    # Reading a transcript well is the whole point of this step.
    data = client.chat_json(prompts.ENRICH_SYSTEM, user, max_tokens=700,
                            model=client.model_for("analysis"))
    fmt = str(data.get("content_format", "")).strip().lower()
    if fmt not in VALID_FORMATS:
        fmt = "altro"
    topics = data.get("topics") or []
    if isinstance(topics, str):
        topics = [t.strip() for t in topics.split(",") if t.strip()]
    # Canonicalise, drop duplicates, keep order.
    seen, canon = set(), []
    for t in topics:
        c = canonical_topic(str(t))
        if c and c not in seen:
            seen.add(c)
            canon.append(c)
    topics = canon
    primary = pick_primary_topic(str(data.get("primary_topic", "")), topics)

    hook = str(data.get("hook_text", ""))[:500]
    if evidence == "caption_only":
        hook = ""  # there is no spoken opening to quote

    Enrichment.objects.update_or_create(
        reel=reel,
        defaults={
            "summary_it": str(data.get("summary_it", ""))[:2000],
            "topics": [t[:60] for t in topics][:6],
            "primary_topic": primary,
            "hook_text": hook,
            "hook_analysis_it": "" if not hook else str(data.get("hook_analysis_it", ""))[:1000],
            "target_audience_it": str(data.get("target_audience_it", ""))[:1000],
            "content_format": fmt,
            "llm_model": client.last_model_used()[:64],
            "evidence": evidence,
            "is_on_topic": bool(data.get("is_on_topic", True)),
            "off_topic_reason": str(data.get("off_topic_reason", ""))[:300],
            "raw_response": data if isinstance(data, dict) else {},
        },
    )


def _extract_arguments(reel: Reel) -> int:
    evidence, transcript_text = classify_evidence(reel)
    if evidence != "transcript":
        # No spoken content: any "claim" would be produced from thin air.
        reel.arguments.all().delete()
        return 0

    user = prompts.ARGUMENTS_USER_TEMPLATE.format(
        caption=(reel.caption or "")[:1500],
        transcript=transcript_text[:3000],
    )
    data = client.chat_json(prompts.ARGUMENTS_SYSTEM, user, max_tokens=600,
                            model=client.model_for("analysis"))
    args = data.get("argomenti") if isinstance(data, dict) else data
    if not isinstance(args, list):
        args = []

    haystack = _norm(transcript_text + " " + (reel.caption or ""))
    reel.arguments.all().delete()  # re-extraction replaces
    created = dropped = 0
    for a in args:
        if isinstance(a, dict):
            text, quote = str(a.get("testo", "")).strip(), str(a.get("citazione", "")).strip()
        else:
            text, quote = str(a).strip(), ""
        if len(text) < 8:
            continue
        # The claim survives only if its quote really appears in the source.
        # This is what makes fabrication structurally impossible rather than
        # merely discouraged by the prompt.
        needle = _norm(quote)
        if len(needle) < 12 or needle not in haystack:
            dropped += 1
            continue
        ReelArgument.objects.create(reel=reel, text_it=text[:1000], quote=quote[:1000])
        created += 1
    if dropped:
        logger.info("[enrich] %s: %d affermazioni scartate (citazione non trovata)",
                    reel.shortcode, dropped)
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
    # NOTE: failures are deliberately left as FAILED. Resetting them to
    # PENDING (as this used to) hid every error and retried it forever.

    return {"enriched": enriched, "enrich_failed": failed,
            "arg_reels": arg_reels, "arguments": total_args, "arg_failed": arg_failed}
