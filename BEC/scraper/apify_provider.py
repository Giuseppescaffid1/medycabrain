"""
scraper/apify_provider.py
=========================
Reel metadata — including a working video url — from the Apify actor
`apify/instagram-reel-scraper`.

Why this exists
---------------
Instagram's own media/info endpoint throttles after roughly 35 calls: it then
answers HTML with a 200, which turned a 394-reel batch into 379 failures on
2026-07-26. The backlog stopped draining entirely — 691 competitor reels sat
at media_status='pending' with zero attempts, because every run hit the quota
within seconds of the scrape stage finishing and gave up.

Apify runs the request from its own proxied infrastructure, so the quota is
theirs to manage rather than ours to trip over. Measured on 2026-07-27: the
actor returned `videoUrl` for every reel, and that url downloaded 12.7 MB in
0.4s straight from the CDN.

Cost is per result (from $2.60/1000 reels), so calls are batched per account —
one actor run returns many reels — and never issued per reel.

Note on expiry
--------------
`videoUrl` is a signed CDN url with an `oe` expiry a few hours out. Fetch and
download in the same pass; a url cached for a day is worthless.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_ENDPOINT = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
# The actor spends real money per result. A run that somehow asked for
# everything would be an expensive mistake, so the ceiling is explicit.
_MAX_RESULTS = 1000


class ApifyUnavailable(RuntimeError):
    """No token configured, or the actor run failed."""


def enabled() -> bool:
    return bool(getattr(settings, "APIFY_TOKEN", ""))


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def fetch_reels(username: str, limit: int, timeout: int = 600) -> list[dict]:
    """The account's most recent `limit` reels, normalised.

    Returns [] rather than raising when the actor simply found nothing: an
    account with no reels is a fact, not a failure.
    """
    if not enabled():
        raise ApifyUnavailable("APIFY_TOKEN not configured")

    limit = max(1, min(int(limit), _MAX_RESULTS))
    url = _ENDPOINT.format(actor=settings.APIFY_REEL_ACTOR)
    try:
        resp = requests.post(
            url,
            params={"token": settings.APIFY_TOKEN},
            json={"username": [username], "resultsLimit": limit},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise ApifyUnavailable(f"apify request failed: {exc!r}") from exc

    if resp.status_code >= 400:
        raise ApifyUnavailable(f"apify {resp.status_code}: {resp.text[:200]}")

    try:
        items = resp.json()
    except ValueError as exc:
        raise ApifyUnavailable("apify returned non-JSON") from exc
    if not isinstance(items, list):
        raise ApifyUnavailable(f"unexpected apify payload: {type(items).__name__}")

    out = []
    for it in items:
        shortcode = it.get("shortCode")
        if not shortcode:
            continue
        out.append({
            "shortcode": shortcode,
            "video_url": it.get("videoUrl") or "",
            "thumbnail_url": it.get("displayUrl") or "",
            "caption": it.get("caption") or "",
            "duration_s": it.get("videoDuration") or None,
            # The actor reports -1 when a count is hidden; that is "unknown",
            # not zero, and writing zero would quietly corrupt the ranking the
            # download order depends on.
            "view_count": _count(it.get("videoPlayCount")),
            "like_count": _count(it.get("likesCount")),
            "comment_count": _count(it.get("commentsCount")),
            "posted_at": _parse_ts(it.get("timestamp")),
        })
    logger.info("[apify] @%s: %s reel, %s con video",
                username, len(out), sum(1 for r in out if r["video_url"]))
    return out


def _count(v) -> int | None:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return None if n < 0 else n
