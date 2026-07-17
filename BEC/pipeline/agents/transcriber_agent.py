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
    model = _get_model()
    segments_iter, info = model.transcribe(
        str(mp3_path), language="it", vad_filter=True, beam_size=1,
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
    }


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
                    "model_name": settings.WHISPER_MODEL,
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
