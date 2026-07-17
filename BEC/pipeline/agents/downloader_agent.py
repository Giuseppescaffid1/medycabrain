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


def _extract_audio(mp4: Path, mp3: Path) -> None:
    mp3.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp4), "-vn", "-acodec", "libmp3lame",
         "-q:a", "5", "-ar", "16000", "-ac", "1", str(mp3)],
        check=True, capture_output=True,
    )


def _refresh_video_url(reel: Reel) -> str:
    """Re-fetch a single reel's fresh CDN url (URLs expire)."""
    from scraper import ig_client
    from scraper.session_store import load_cookies

    cookies = load_cookies()
    session = ig_client.build_session(cookies)
    # Use the public web appwith the shortcode media info endpoint
    data = ig_client._request(
        session, "GET",
        f"https://www.instagram.com/api/v1/media/{reel.ig_media_id}/info/",
        csrftoken=cookies.get("csrftoken", ""),
    )
    items = data.get("items") or []
    if items:
        vvs = items[0].get("video_versions") or []
        if vvs:
            return vvs[0].get("url", "")
    return ""


def _process_one(reel: Reel) -> bool:
    scratch = Path(settings.TMP_DIR)
    scratch.mkdir(parents=True, exist_ok=True)
    mp4 = scratch / f"{reel.shortcode}.mp4"
    rel_audio = f"audio/{reel.account.username}/{reel.shortcode}.mp3"
    rel_thumb = f"thumbs/{reel.account.username}/{reel.shortcode}.jpg"
    mp3 = Path(settings.MEDIA_ROOT) / rel_audio
    thumb = Path(settings.MEDIA_ROOT) / rel_thumb

    video_url = reel.video_url
    if not video_url:
        video_url = _refresh_video_url(reel)

    try:
        _download(video_url, mp4)
    except Exception:  # noqa: BLE001 — likely expired URL
        video_url = _refresh_video_url(reel)
        if not video_url:
            raise
        _download(video_url, mp4)

    _extract_audio(mp4, mp3)
    if reel.thumbnail_url:
        try:
            _download(reel.thumbnail_url, thumb)
            reel.thumbnail_file = rel_thumb
        except Exception as exc:  # noqa: BLE001 — non-fatal
            logger.warning("[downloader] thumb failed %s: %r", reel.shortcode, exc)

    mp4.unlink(missing_ok=True)
    reel.audio_file = rel_audio
    reel.media_status = DONE
    reel.transcribe_status = PENDING
    reel.last_error = ""
    reel.save(update_fields=["audio_file", "thumbnail_file", "media_status",
                             "transcribe_status", "last_error"])
    return True


def run(ctx) -> dict:
    qs = Reel.objects.filter(media_status=PENDING, is_active=True).select_related("account")
    if ctx.limit:
        qs = qs[: ctx.limit]
    done = failed = skipped = 0
    for reel in qs:
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
