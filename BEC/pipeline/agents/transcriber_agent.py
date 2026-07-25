"""
pipeline/agents/transcriber_agent.py
====================================
TranscriberAgent — faster-whisper (local CPU, Italian) over each reel's
mp3. For every reel with transcribe_status='pending' and a downloaded
audio file: transcribe → store Transcript(text, segments) → mark done,
enrich_status='pending'.

Model is loaded once per run (deferred import), int8 on CPU threads from
settings. Empty/near-silent audio still marks done (with empty text) so
it doesn't loop forever.
"""

from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings

from core.models import DONE, FAILED, PENDING, Reel, Transcript

logger = logging.getLogger(__name__)

_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        logger.info("[transcriber] loading faster-whisper '%s' (%s)",
                    settings.WHISPER_MODEL, settings.WHISPER_COMPUTE_TYPE)
        _model = WhisperModel(
            settings.WHISPER_MODEL,
            device="cpu",
            compute_type=settings.WHISPER_COMPUTE_TYPE,
            cpu_threads=settings.WHISPER_CPU_THREADS,
        )
    return _model


def _transcribe(mp3_path: Path) -> dict:
    """Remote whisper-large-v3 first, local faster-whisper as the backstop.

    The local `small` model mangles the domain vocabulary ("umonibirentici"
    for "ormoni bioidentici"); large-v3 conditioned on the glossary gets it
    right, in about a second, without loading the VPS.
    """
    if settings.USE_REMOTE_STT and settings.FAST_LLM_API_KEY:
        import time as _time

        from llm import client, prompts
        from llm.client import LLMRateLimit

        for attempt in range(4):
            try:
                out = client.transcribe_audio(str(mp3_path), prompt=prompts.MEDICAL_GLOSSARY)
                if out.get("text"):
                    segs = out["segments"]
                    return {"text": out["text"], "segments": segs, "language": "it",
                            "duration": segs[-1]["end"] if segs else 0.0,
                            "model_name": out["model"]}
                logger.warning("[transcriber] remote STT returned empty text — using local")
                break
            except LLMRateLimit as exc:
                if exc.daily:
                    logger.warning("[transcriber] STT daily budget spent — using local")
                    break
                # Per-minute cap: waiting costs seconds, whereas falling back to
                # the local `small` model costs both minutes AND the accuracy
                # this whole change exists to fix.
                wait = min(max(exc.retry_after, 2.0), 30.0)
                logger.info("[transcriber] STT rate-limited — attendo %.0fs", wait)
                _time.sleep(wait)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[transcriber] remote STT failed (%r) — using local", exc)
                break

    model = _get_model()
    segments_iter, info = model.transcribe(
        str(mp3_path), language="it", vad_filter=True, beam_size=5,
        initial_prompt=_local_prompt(),
    )
    segments = []
    parts = []
    for seg in segments_iter:
        segments.append({"start": round(seg.start, 2), "end": round(seg.end, 2),
                         "text": seg.text.strip()})
        parts.append(seg.text.strip())
    return {
        "text": " ".join(parts).strip(),
        "segments": segments,
        "language": info.language,
        "duration": info.duration,
        "model_name": settings.WHISPER_MODEL,
    }


def _local_prompt() -> str:
    from llm import prompts
    return prompts.MEDICAL_GLOSSARY


def run(ctx) -> dict:
    qs = (
        Reel.objects.filter(transcribe_status=PENDING, media_status=DONE, is_active=True)
        .exclude(audio_file="")
        .select_related("account")
    )
    if ctx.limit:
        qs = qs[: ctx.limit]
    done = failed = 0
    for reel in qs:
        mp3 = Path(settings.MEDIA_ROOT) / reel.audio_file
        if not mp3.exists():
            reel.transcribe_status = FAILED
            reel.last_error = "audio file missing"
            reel.save(update_fields=["transcribe_status", "last_error"])
            failed += 1
            continue
        try:
            result = _transcribe(mp3)
            Transcript.objects.update_or_create(
                reel=reel,
                defaults={
                    "text": result["text"],
                    "segments": result["segments"],
                    "language": result["language"],
                    "model_name": result.get("model_name", settings.WHISPER_MODEL),
                    "audio_duration_s": result["duration"],
                },
            )
            reel.transcribe_status = DONE
            reel.enrich_status = PENDING
            reel.last_error = ""
            reel.save(update_fields=["transcribe_status", "enrich_status", "last_error"])
            done += 1
        except Exception as exc:  # noqa: BLE001
            reel.transcribe_status = FAILED
            reel.last_error = repr(exc)[:500]
            reel.save(update_fields=["transcribe_status", "last_error"])
            failed += 1
            logger.warning("[transcriber] %s failed: %r", reel.shortcode, exc)
    return {"transcribed": done, "failed": failed}
