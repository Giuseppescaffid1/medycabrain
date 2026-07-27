"""
Re-run transcription and/or enrichment over existing content.

Needed after a prompt or model change: the corpus carries the output of the
old prompts, and free-tier providers cap tokens per model per day, so a full
re-run has to be resumable rather than one long shot.

    python manage.py reprocess --stage transcribe --scope medyca
    python manage.py reprocess --stage enrich --limit 20
    python manage.py reprocess --stage transcribe,enrich        # everything
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from core.models import DONE, PENDING, Reel

STAGES = ("transcribe", "enrich")


class Command(BaseCommand):
    help = "Re-transcribe / re-enrich existing reels, resumable across days."

    def add_arguments(self, parser):
        parser.add_argument("--stage", default="enrich",
                            help="Comma list: " + ",".join(STAGES))
        parser.add_argument("--scope", default="",
                            help="medyca | competitor (default: both)")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--only-stale", action="store_true",
                            help="Skip reels already produced by the current prompts.")
        parser.add_argument("--with-transcript", action="store_true",
                            help="Only reels that actually have spoken content.")
        parser.add_argument("--not-model", default="",
                            help="Only reels whose analysis came from a model NOT "
                                 "starting with this prefix (e.g. 'claude').")

    def handle(self, *args, **opts):
        from django.conf import settings

        stages = [s.strip() for s in opts["stage"].split(",") if s.strip()]
        qs = Reel.objects.filter(is_active=True).select_related(
            "account", "enrichment", "transcript")
        if opts["scope"]:
            owner = "owned" if opts["scope"].lower() in ("medyca", "owned") else "competitor"
            qs = qs.filter(account__owner_type=owner)
        qs = qs.order_by("-view_count")  # highest-value content first

        if "transcribe" in stages:
            self._transcribe(qs, opts, settings)
        if "enrich" in stages:
            self._enrich(qs, opts, settings)

    # ── transcription ──────────────────────────────────────────────────
    def _transcribe(self, qs, opts, settings):
        from pathlib import Path

        from pipeline.agents.transcriber_agent import _transcribe
        from core.models import Transcript

        todo = qs.exclude(audio_file="")
        if opts["only_stale"]:
            todo = todo.exclude(transcript__model_name=settings.FAST_STT_MODEL)
        todo = list(todo[: opts["limit"]] if opts["limit"] else todo)
        self.stdout.write(f"[transcribe] {len(todo)} reel")

        ok = fail = 0
        for i, reel in enumerate(todo, 1):
            mp3 = Path(settings.MEDIA_ROOT) / reel.audio_file
            if not mp3.exists():
                fail += 1
                continue
            try:
                res = _transcribe(mp3)
                Transcript.objects.update_or_create(
                    reel=reel,
                    defaults={"text": res["text"], "segments": res["segments"],
                              "language": res.get("language", "it"),
                              "model_name": res.get("model_name", ""),
                              "audio_duration_s": res.get("duration", 0) or 0},
                )
                # A new transcript invalidates the analysis built on the old one.
                reel.enrich_status = PENDING
                reel.argument_status = PENDING
                reel.save(update_fields=["enrich_status", "argument_status"])
                ok += 1
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(f"  {reel.shortcode}: {exc!r}")
                fail += 1
            if i % 20 == 0:
                self.stdout.write(f"  {i}/{len(todo)} (ok={ok} ko={fail})")
        self.stdout.write(self.style.SUCCESS(f"[transcribe] ok={ok} falliti={fail}"))

    # ── enrichment ─────────────────────────────────────────────────────
    def _enrich(self, qs, opts, settings):
        from llm.client import LLMRateLimit
        from pipeline.agents import enrich_agent as ea

        if opts["with_transcript"]:
            # A reel with no audio yet produces no LLM call at all — including
            # it would only rewrite hundreds of "insufficient" rows.
            qs = qs.filter(transcribe_status=DONE).exclude(transcript__text="")
        if opts["not_model"]:
            # Redo only what a weaker model produced: re-running an analysis
            # that is already good costs time and changes nothing.
            qs = qs.exclude(enrichment__llm_model__startswith=opts["not_model"])
            # ...but a reel that never got an analysis at all still needs one.
            self.stdout.write(
                f"[enrich] filtro: analisi non prodotte da '{opts['not_model']}*'")

        todo = list(qs[: opts["limit"]] if opts["limit"] else qs)
        self.stdout.write(f"[enrich] {len(todo)} reel")

        ok = fail = skipped = 0
        for i, reel in enumerate(todo, 1):
            try:
                ea._enrich_one(reel)
                n = ea._extract_arguments(reel)
                reel.enrich_status = DONE
                reel.argument_status = DONE
                reel.save(update_fields=["enrich_status", "argument_status"])
                ok += 1
                if n == 0:
                    skipped += 1
            except LLMRateLimit as exc:
                if exc.daily:
                    # Every model's daily budget is gone. Stop cleanly: the
                    # next run picks up where this one left off.
                    self.stdout.write(self.style.WARNING(
                        f"budget giornaliero esaurito dopo {ok} reel — riprendi domani"))
                    break
                time.sleep(min(exc.retry_after, 60))
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(f"  {reel.shortcode}: {exc!r}")
                fail += 1
            if i % 20 == 0:
                self.stdout.write(f"  {i}/{len(todo)} (ok={ok} ko={fail})")
        self.stdout.write(self.style.SUCCESS(
            f"[enrich] ok={ok} falliti={fail} senza affermazioni={skipped}"))
