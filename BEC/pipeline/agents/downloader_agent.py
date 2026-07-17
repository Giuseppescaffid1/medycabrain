"""
pipeline/agents/downloader_agent.py
===================================
DownloaderAgent — for each reel with media_status='pending':
  1. download the reel mp4 to a scratch dir
  2. ffmpeg-extract audio → media/audio/{account}/{shortcode}.mp3
  3. download thumbnail → media/thumbs/{account}/{shortcode}.jpg
  4. delete the mp4, set media_status='done', transcribe_status='pending'

CDN video URLs expire (hours/days). On a 403, re-fetch the single reel's
fresh video_url via the GraphQL client before giving up. 3 attempts then
media_status='skipped'.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import requests
from django.conf import settings

from core.models import DONE, FAILED, PENDING, SKIPPED, Reel

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_MAX_ATTEMPTS = 3


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(url, headers={"User-Agent": _UA}, timeout=60, stream=True)
    resp.raise_for_status()
    with open(dest, "wb") as fh:
        for chunk in resp.iter_content(8192):
            fh.write(chunk)


def _has_audio(mp4: Path) -> bool:
    """True if the file contains at least one audio stream."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(mp4)],
        capture_output=True, text=True,
    )
    return "audio" in out.stdout


def _extract_audio(mp4: Path, mp3: Path) -> None:
    mp3.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp4), "-vn", "-acodec", "libmp3lame",
         "-q:a", "5", "-ar", "16000", "-ac", "1", str(mp3)],
        check=True, capture_output=True,
    )


def _refresh_video_url(reel: Reel) -> str:
    """Re-fetch a single reel's fresh CDN url (URLs expire)."""
    return _fetch_media_details(reel).get("video_url", "")


def _fetch_media_details(reel: Reel) -> dict:
    """Fetch full media details via /api/v1/media/{pk}/info/.

    The clips (reels-tab) connection returns lightweight nodes without
    video_url, caption, taken_at or duration — so we backfill them here
    (this is also where the fresh, non-expired CDN video_url comes from).
    """
    from datetime import datetime, timezone

    from scraper import ig_client
    from scraper.session_store import load_cookies

    cookies = load_cookies()
    session = ig_client.build_session(cookies)
    data = ig_client._request(
        session, "GET",
        f"https://www.instagram.com/api/v1/media/{reel.ig_media_id}/info/",
        csrftoken=cookies.get("csrftoken", ""),
        headers={"Referer": f"https://www.instagram.com/reel/{reel.shortcode}/"},
    )
    items = data.get("items") or []
    if not items:
        return {}
    it = items[0]
    vvs = it.get("video_versions") or []
    iv = (it.get("image_versions2") or {}).get("candidates") or []
    caption_obj = it.get("caption") or {}
    clips = it.get("clips_metadata") or {}
    music = (clips.get("music_info") or {}).get("music_asset_info") or {}
    orig = clips.get("original_sound_info") or {}
    audio = {}
    if music:
        audio = {"title": music.get("title"), "artist": music.get("display_artist")}
    elif orig:
        audio = {"title": orig.get("original_audio_title"), "artist": None}

    details = {
        "video_url": vvs[0].get("url", "") if vvs else "",
        "thumbnail_url": iv[0].get("url", "") if iv else reel.thumbnail_url,
        "caption": caption_obj.get("text", "") if isinstance(caption_obj, dict) else "",
        "duration_s": it.get("video_duration"),
        "taken_at": it.get("taken_at"),
        "audio_info": audio,
        "has_audio": it.get("has_audio", True),
        "view_count": it.get("play_count") or it.get("view_count"),
        "like_count": it.get("like_count"),
        "comment_count": it.get("comment_count"),
    }
    # Backfill the reel row with the richer metadata.
    reel.caption = details["caption"] or reel.caption
    reel.duration_s = details["duration_s"] or reel.duration_s
    reel.thumbnail_url = details["thumbnail_url"] or reel.thumbnail_url
    reel.audio_info = details["audio_info"] or reel.audio_info
    if details["view_count"] is not None:
        reel.view_count = details["view_count"]
    if details["like_count"] is not None:
        reel.like_count = details["like_count"]
    if details["comment_count"] is not None:
        reel.comment_count = details["comment_count"]
    if details["taken_at"]:
        reel.posted_at = datetime.fromtimestamp(details["taken_at"], tz=timezone.utc)
    reel.save(update_fields=[
        "caption", "duration_s", "thumbnail_url", "audio_info",
        "view_count", "like_count", "comment_count", "posted_at",
    ])
    return details


def _process_one(reel: Reel) -> bool:
    scratch = Path(settings.TMP_DIR)
    scratch.mkdir(parents=True, exist_ok=True)
    mp4 = scratch / f"{reel.shortcode}.mp4"
    rel_audio = f"audio/{reel.account.username}/{reel.shortcode}.mp3"
    rel_thumb = f"thumbs/{reel.account.username}/{reel.shortcode}.jpg"
    mp3 = Path(settings.MEDIA_ROOT) / rel_audio
    thumb = Path(settings.MEDIA_ROOT) / rel_thumb

    # Clips nodes lack a usable video_url, so always fetch media details
    # (this also backfills caption/timestamp/duration/audio).
    details = _fetch_media_details(reel)

    # media/info reports has_audio authoritatively; skip the video download
    # entirely for silent reels (no audio to extract).
    has_audio = details.get("has_audio", True)
    if has_audio:
        video_url = details.get("video_url") or reel.video_url
        try:
            _download(video_url, mp4)
        except Exception:  # noqa: BLE001 — likely expired URL
            video_url = _fetch_media_details(reel).get("video_url", "")
            if not video_url:
                raise
            _download(video_url, mp4)
        # Defensive: a reel can claim audio but ship a video-only stream.
        has_audio = _has_audio(mp4)
        if has_audio:
            _extract_audio(mp4, mp3)

    if reel.thumbnail_url:
        try:
            _download(reel.thumbnail_url, thumb)
            reel.thumbnail_file = rel_thumb
        except Exception as exc:  # noqa: BLE001 — non-fatal
            logger.warning("[downloader] thumb failed %s: %r", reel.shortcode, exc)

    mp4.unlink(missing_ok=True)
    reel.media_status = DONE
    reel.last_error = ""
    if has_audio:
        reel.audio_file = rel_audio
        reel.transcribe_status = PENDING
    else:
        # Silent reel — nothing to transcribe; skip straight to enrichment
        # so the caption/metadata still get processed.
        reel.audio_file = ""
        reel.transcribe_status = SKIPPED
        reel.enrich_status = PENDING
        logger.info("[downloader] %s has no audio stream — skipping transcription",
                    reel.shortcode)
    reel.save(update_fields=["audio_file", "thumbnail_file", "media_status",
                             "transcribe_status", "enrich_status", "last_error"])
    return True


def run(ctx) -> dict:
    import random
    import time

    from core.models import ScraperConfig

    dl_delay = ScraperConfig.get("download_delay_s", {"value": 4})
    dl_delay = dl_delay.get("value", 4) if isinstance(dl_delay, dict) else dl_delay

    qs = Reel.objects.filter(media_status=PENDING, is_active=True).select_related("account")
    if ctx.limit:
        qs = qs[: ctx.limit]
    done = failed = skipped = 0
    for i, reel in enumerate(qs):
        if i > 0:
            time.sleep(random.uniform(dl_delay, dl_delay * 2))  # media/info is an API call
        try:
            _process_one(reel)
            done += 1
        except Exception as exc:  # noqa: BLE001
            reel.media_attempts += 1
            reel.last_error = repr(exc)[:500]
            if reel.media_attempts >= _MAX_ATTEMPTS:
                reel.media_status = SKIPPED
                skipped += 1
            else:
                reel.media_status = FAILED
                failed += 1
            reel.save(update_fields=["media_attempts", "last_error", "media_status"])
            logger.warning("[downloader] %s failed (attempt %s): %r",
                           reel.shortcode, reel.media_attempts, exc)
    # Retry previously-failed rows next run by flipping FAILED back to PENDING
    Reel.objects.filter(media_status=FAILED, media_attempts__lt=_MAX_ATTEMPTS).update(
        media_status=PENDING
    )
    return {"downloaded": done, "failed": failed, "skipped": skipped}
