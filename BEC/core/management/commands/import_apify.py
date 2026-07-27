"""
Import an Apify Instagram-reel export to fill in what our own scraper cannot get.

The reels-tab GraphQL connection returns lightweight nodes: no video url, no
caption, no timestamp, no duration. Today each of those costs one call to
`/api/v1/media/{pk}/info/`, which Instagram throttles at roughly 35 calls per
run from a datacenter IP — the reason 590 reels are stuck without audio.

The Apify actor returns exactly those fields in bulk. This command matches its
output onto reels we already scraped and caches the video url, so the download
step can go straight to the CDN (which is not throttled).

    python manage.py import_apify dataset.json
    python manage.py import_apify dataset.json --dry-run

Signed CDN urls expire in ~4-5 days, so import and download the same day.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.models import PENDING, Reel


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class Command(BaseCommand):
    help = "Fill video_url/caption/posted_at/duration from an Apify reel export."

    def add_arguments(self, parser):
        parser.add_argument("path", help="JSON file exported from the Apify actor")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        path = Path(opts["path"])
        if not path.exists():
            raise CommandError(f"file non trovato: {path}")
        try:
            records = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise CommandError(f"JSON non valido: {exc}") from exc
        if isinstance(records, dict):
            records = records.get("items") or records.get("results") or [records]

        by_code = {}
        for r in records:
            code = r.get("shortCode") or r.get("shortcode") or r.get("code")
            if code:
                by_code[code] = r
        self.stdout.write(f"record Apify: {len(records)} ({len(by_code)} con shortcode)")

        reels = {r.shortcode: r for r in Reel.objects.filter(shortcode__in=by_code.keys())}
        matched = updated = unknown = 0

        for code, rec in by_code.items():
            reel = reels.get(code)
            if not reel:
                unknown += 1
                continue
            matched += 1

            fields = []
            video_url = rec.get("videoUrl") or rec.get("video_url") or ""
            # Only ever fill in — never overwrite a good value with an empty
            # one. A previous re-scrape wiped posted_at across the corpus
            # exactly this way.
            if video_url and video_url != reel.video_url:
                reel.video_url = video_url
                fields.append("video_url")
            caption = rec.get("caption") or ""
            if caption and not reel.caption:
                reel.caption = caption
                fields.append("caption")
            ts = _parse_ts(rec.get("timestamp") or rec.get("takenAt"))
            if ts and not reel.posted_at:
                reel.posted_at = ts
                fields.append("posted_at")
            dur = rec.get("videoDuration") or rec.get("duration")
            if dur and not reel.duration_s:
                reel.duration_s = int(float(dur))
                fields.append("duration_s")
            for src, dst in (("videoPlayCount", "view_count"), ("likesCount", "like_count"),
                             ("commentsCount", "comment_count")):
                val = rec.get(src)
                if val and val > (getattr(reel, dst) or 0):
                    setattr(reel, dst, val)
                    fields.append(dst)

            if not fields:
                continue
            # A reel that was given up on deserves another go now that we have
            # a url that needs no throttled call.
            if reel.media_status != "done" and "video_url" in fields:
                reel.media_status = PENDING
                reel.media_attempts = 0
                fields += ["media_status", "media_attempts"]

            if not opts["dry_run"]:
                reel.save(update_fields=list(set(fields)))
            updated += 1

        verb = "sarebbero aggiornati" if opts["dry_run"] else "aggiornati"
        self.stdout.write(self.style.SUCCESS(
            f"abbinati {matched} · {verb} {updated} · non presenti in DB {unknown}"))
        pending_with_url = Reel.objects.filter(media_status=PENDING).exclude(video_url="").count()
        self.stdout.write(f"reel in coda con url in cache: {pending_with_url}")
