"""
backfill_meta
=============
Re-fetch media/info for reels missing metadata (posted_at, duration, audio
info). Fixes reels that were downloaded before the media/info backfill was
added to the downloader, so they appear on the publication timeline.

    python manage.py backfill_meta            # all reels missing posted_at
    python manage.py backfill_meta --scope owned
"""

import time

from django.core.management.base import BaseCommand

from core.models import Reel
from pipeline.agents.downloader_agent import _fetch_media_details


class Command(BaseCommand):
    help = "Backfill posted_at / metadata for reels missing it (via media/info)."

    def add_arguments(self, parser):
        parser.add_argument("--scope", choices=["owned", "competitor"], default=None)
        parser.add_argument("--limit", type=int, default=None)
        parser.add_argument("--delay", type=float, default=6.0)

    def handle(self, *args, **opts):
        qs = Reel.objects.filter(posted_at__isnull=True, is_active=True).select_related("account")
        if opts["scope"]:
            qs = qs.filter(account__owner_type=opts["scope"])
        if opts["limit"]:
            qs = qs[: opts["limit"]]

        total = qs.count()
        self.stdout.write(f"backfilling metadata for {total} reels…")
        ok = fail = 0
        for i, reel in enumerate(qs):
            try:
                _fetch_media_details(reel)  # backfills posted_at, caption, duration, audio
                reel.refresh_from_db()
                if reel.posted_at:
                    ok += 1
                    self.stdout.write(f"  [{i+1}/{total}] {reel.shortcode} → {reel.posted_at.date()}")
                else:
                    fail += 1
                    self.stdout.write(f"  [{i+1}/{total}] {reel.shortcode} → still no date")
            except Exception as exc:  # noqa: BLE001
                fail += 1
                self.stdout.write(self.style.WARNING(f"  [{i+1}/{total}] {reel.shortcode} failed: {exc!r}"))
            time.sleep(opts["delay"])
        self.stdout.write(self.style.SUCCESS(f"done — {ok} dated, {fail} unresolved"))
