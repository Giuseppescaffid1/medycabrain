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
import time
from pathlib import Path

import requests
from django.conf import settings

from django.db.models import Case, IntegerField, Value, When

from core.models import DONE, FAILED, PENDING, SKIPPED, Reel
from scraper.types import IGThrottled

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_MAX_ATTEMPTS = 3
_THROTTLE_STREAK = 3  # consecutive quota errors that end a run

# Hard cap on how many reels the url prefetch may ask Apify for, per account.
# Every result is billed whether or not we needed it — see _prefetch_urls.
# 30 reels = $0.079 per account; the old uncapped depth reached $0.48.
_PREFETCH_MAX_DEPTH = 30


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

    try:
        cookies = load_cookies()
    except FileNotFoundError as exc:
        # Session removed by decision (personal account, 2026-07-29). The
        # reel did nothing wrong: defer it like a quota hit — attempts are
        # not charged and the run moves on with cached/Apify urls — instead
        # of failing it three times into 'skipped'.
        raise IGThrottled("nessuna sessione Instagram (migrazione ad API "
                          "ufficiali)") from exc
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


def _url_expired(url: str, margin_s: int = 900) -> bool:
    """True when a signed CDN url is past (or about to pass) its `oe` expiry.

    Instagram signs media urls with `oe=<hex unix ts>`; using one after that
    returns 403. Without the parameter we cannot tell, so we assume it is
    still good and let the download attempt decide.
    """
    import re as _re
    m = _re.search(r"[?&]oe=([0-9A-Fa-f]+)", url or "")
    if not m:
        return False
    try:
        return time.time() + margin_s >= int(m.group(1), 16)
    except ValueError:
        return False


def _ytdlp_fetch(reel: Reel, mp4: Path) -> None:
    """Fetch a public reel by permalink, anonymously, via yt-dlp.

    Replaces the media/info renewal path, which needed a logged-in session —
    removed 2026-07-29 because it ran as Giuseppe's personal account. This
    path involves no account at all: measured 2026-07-30 from this VPS,
    3/3 reels, 6-8s each, valid MP4s with correct durations.

    Still unofficial: Instagram can block the IP or change the page. A block
    surfaces as a DownloadError mentioning login/rate — mapped to IGThrottled
    so the run defers instead of burning three attempts per reel.
    """
    import yt_dlp

    opts = {
        "outtmpl": str(mp4.with_suffix("")) + ".%(ext)s",
        "merge_output_format": "mp4",
        "quiet": True, "no_warnings": True, "noprogress": True,
        "socket_timeout": 60,
        "retries": 1,
    }
    url = f"https://www.instagram.com/reel/{reel.shortcode}/"
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        msg = str(exc).lower()
        if any(k in msg for k in ("login", "rate", "429", "wait a few minutes")):
            raise IGThrottled(f"yt-dlp bloccato: {str(exc)[:120]}") from exc
        raise
    if not mp4.exists():
        raise RuntimeError("yt-dlp: nessun file prodotto")


def _process_one(reel: Reel) -> bool:
    scratch = Path(settings.TMP_DIR)
    scratch.mkdir(parents=True, exist_ok=True)
    mp4 = scratch / f"{reel.shortcode}.mp4"
    rel_audio = f"audio/{reel.account.username}/{reel.shortcode}.mp3"
    rel_thumb = f"thumbs/{reel.account.username}/{reel.shortcode}.jpg"
    mp3 = Path(settings.MEDIA_ROOT) / rel_audio
    thumb = Path(settings.MEDIA_ROOT) / rel_thumb

    # Cheapest first: a cached, unexpired CDN url is a plain file fetch.
    # Otherwise yt-dlp fetches the public permalink anonymously — the
    # media/info renewal it replaces needed a logged-in session.
    used_api = False
    fetched = False
    if reel.video_url and not _url_expired(reel.video_url):
        try:
            _download(reel.video_url, mp4)
            fetched = True
            logger.debug("[downloader] %s: url in cache", reel.shortcode)
        except Exception as exc:  # noqa: BLE001 — expired early or revoked
            logger.debug("[downloader] %s: url in cache morto (%r), provo yt-dlp",
                         reel.shortcode, exc)
    if not fetched:
        _ytdlp_fetch(reel, mp4)
        used_api = True  # web hit on Instagram: it deserves the pacing delay

    # Defensive: a reel can ship a video-only stream.
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
    return used_api


def _prefetch_urls(batch: list[Reel]) -> dict:
    """Fill in video_url for a whole batch from Apify, one call per account.

    This is what keeps the run off Instagram's throttled media/info endpoint:
    _process_one already prefers a cached, unexpired url and only calls the
    API when one is missing, so a batch that arrives with fresh urls makes
    zero throttled calls.

    Depth is measured against the account's whole known history, not against
    the reels in this batch. The actor returns the N most recent reels of the
    account, and our pending rows are scattered through that timeline rather
    than sitting at the top of it: a first attempt sized from the batch asked
    for 7 and matched 0 of them.

    **The depth is capped, and the cap is a money decision.** The original
    `known + 60` was written when Apify was a cheap insurance policy against
    Instagram's quota. On the $5/cycle plan it is the single most expensive
    thing the pipeline can do: `menopausa_insieme` alone has 124 known reels,
    so `known + 60` asks for 184 results — $0.48 for one account, one night —
    and across twelve accounts one run would ask for roughly $3.70. The whole
    cycle, in a night, to fetch urls that yt-dlp does not need.

    It is also mostly redundant now. The scrape stage fetches through Apify
    too, so a freshly collected reel already arrives carrying its `videoUrl`
    from that same call, and `_process_one` prefers a cached url anyway. What
    is left is the narrow case of a reel whose url expired before the download
    stage reached it — and for that, yt-dlp is the free answer.
    """
    from scraper import apify_provider

    by_account: dict[str, list[Reel]] = {}
    for reel in batch:
        if reel.video_url and not _url_expired(reel.video_url):
            continue  # already usable, costs nothing
        by_account.setdefault(reel.account.username, []).append(reel)
    if not by_account:
        return {"apify_accounts": 0, "apify_urls": 0}

    filled = accounts = 0
    for username, reels in by_account.items():
        # A flat margin, not a ratio: our rows can sit deeper in the account's
        # real timeline than their own count suggests, and a run that comes
        # back short is wasted entirely rather than partially.
        known = Reel.objects.filter(account__username=username).count()
        depth = min(max(known, len(reels)) + 20, _PREFETCH_MAX_DEPTH)
        try:
            items = apify_provider.fetch_reels(username, limit=depth)
        except apify_provider.ApifyUnavailable as exc:
            # Includes the budget ceiling refusing to spend. Not an incident:
            # yt-dlp fetches these reels without Apify, just more slowly.
            logger.warning("[downloader] apify non disponibile per @%s: %s", username, exc)
            continue
        accounts += 1

        found = {i["shortcode"]: i for i in items}
        for reel in reels:
            item = found.get(reel.shortcode)
            if not item or not item["video_url"]:
                continue
            reel.video_url = item["video_url"]
            fields = ["video_url"]
            # Backfill only what is missing or newer — never overwrite a real
            # value with a blank one the actor happened not to return.
            for attr, key in (("thumbnail_url", "thumbnail_url"),
                              ("caption", "caption"),
                              ("duration_s", "duration_s")):
                if item[key] and not getattr(reel, attr):
                    setattr(reel, attr, item[key])
                    fields.append(attr)
            for attr in ("view_count", "like_count", "comment_count"):
                if item[attr] is not None:
                    setattr(reel, attr, item[attr])
                    fields.append(attr)
            if item["posted_at"] and not reel.posted_at:
                reel.posted_at = item["posted_at"]
                fields.append("posted_at")
            reel.save(update_fields=fields)
            filled += 1

    if accounts:
        logger.info("[downloader] apify: %s url pronti su %s account",
                    filled, accounts)
    return {"apify_accounts": accounts, "apify_urls": filled}


def run(ctx) -> dict:
    import random
    import time

    from core.models import ScraperConfig

    dl_delay = ScraperConfig.get("download_delay_s", {"value": 4})
    dl_delay = dl_delay.get("value", 4) if isinstance(dl_delay, dict) else dl_delay

    # Priority: Medyca's own content first, then each competitor's best
    # performing reels. A 122-reel account must not starve the other twelve.
    qs = (
        Reel.objects.filter(media_status=PENDING, is_active=True)
        .select_related("account")
        .annotate(is_owned=Case(When(account__owner_type="owned", then=Value(0)),
                                default=Value(1), output_field=IntegerField()))
        .order_by("is_owned", "-view_count", "-posted_at")
    )
    # Instagram throttles media/info after a few hundred rapid calls: it starts
    # answering HTML with a 200, which is what turned a 394-reel batch into 379
    # failures. Cap each run and let the backlog drain across scheduled runs.
    cap = ScraperConfig.get("download_max_per_run", {"value": 0})
    cap = cap.get("value", 0) if isinstance(cap, dict) else cap
    if ctx.limit:
        qs = qs[: ctx.limit]
    elif cap:
        qs = qs[:cap]
    # Materialise before prefetching: the batch is iterated twice, and a
    # sliced queryset would run the whole query again.
    batch = list(qs)
    from scraper import apify_provider
    stats = _prefetch_urls(batch) if apify_provider.enabled() else {}

    done = failed = skipped = 0
    throttled_streak = 0
    throttled_total = 0
    stopped_early = False
    spent_api = False
    deferred = 0
    for reel in batch:
        # Once Instagram's quota is gone, only the reels that would call it are
        # blocked. A reel holding a fresh CDN url needs no API at all, and
        # stopping the whole run on its account's behalf is what kept 691 reels
        # at zero attempts: the run aborted on the first few urls it lacked and
        # never reached the hundreds it could already have fetched.
        needs_api = not (reel.video_url and not _url_expired(reel.video_url))
        if stopped_early and needs_api:
            deferred += 1
            continue

        # Pace only the throttled endpoint. A cached url goes straight to the
        # CDN, which has no quota — sleeping there would waste hours.
        if spent_api:
            time.sleep(random.uniform(dl_delay, dl_delay * 2))
        try:
            spent_api = _process_one(reel)
            done += 1
            throttled_streak = 0
        except IGThrottled as exc:
            # The quota for this window is gone: every further call in this run
            # would fail too (measured: once it starts, 45/45 failed). Stop, and
            # do NOT charge the reel an attempt — it did nothing wrong.
            throttled_streak += 1
            throttled_total += 1
            reel.media_status = PENDING
            reel.last_error = f"quota Instagram esaurita: {exc}"[:500]
            reel.save(update_fields=["media_status", "last_error"])
            logger.warning("[downloader] quota esaurita (%s consecutivi) su %s",
                           throttled_streak, reel.shortcode)
            # Total, not consecutive. A run alternates between reels holding a
            # cached url (which succeed) and reels needing the API (which do
            # not), and every success reset the streak — so it never reached
            # three, never stopped trying, and paid the 20-40s pacing sleep on
            # every doomed call. Measured: 2 reels/min instead of ~12.
            # The quota belongs to the window, not to a run of bad luck: once
            # it has gone three times, it is gone.
            if throttled_streak >= _THROTTLE_STREAK or throttled_total >= _THROTTLE_STREAK:
                stopped_early = True
                logger.warning("[downloader] quota Instagram esaurita: proseguo solo "
                               "con i reel che hanno gia un url utilizzabile")
        except Exception as exc:  # noqa: BLE001
            throttled_streak = 0
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
    return {"downloaded": done, "failed": failed, "skipped": skipped,
            "stopped_early": stopped_early, "deferred": deferred, **stats}
