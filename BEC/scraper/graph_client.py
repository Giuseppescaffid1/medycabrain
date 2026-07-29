"""
scraper/graph_client.py
=======================
Instagram Graph API — the official, sanctioned way to read accounts.

Replaces the cookie-based scraping that used to run as Giuseppe's personal
account (removed 2026-07-29). The caller is a Meta app + an Instagram
BUSINESS account we control; competitor accounts are read through
`business_discovery`, which Meta provides exactly for this purpose.

What the official API gives and does not give, honestly:
  - target accounts must be Business or Creator — a personal profile is not
    discoverable at all. `graph_check` measures who qualifies.
  - like/comment counts yes; VIEW counts no (plays are not exposed through
    business_discovery), so competitor weighting leans on likes.
  - `media_url` for competitor videos is often withheld by Meta. When it is,
    the official API yields metadata + caption only, and the video itself
    still needs Apify or nothing. Measured per account by `graph_check`,
    not assumed either way.

Configuration (.env):
  IG_GRAPH_TOKEN        long-lived user access token (60 days; see
                        docs/instagram-graph-api-setup.md for the exchange)
  IG_GRAPH_USER_ID      the CALLER's instagram_business_account id
                        (resolved automatically by graph_check if empty)
  IG_GRAPH_API_VERSION  default v21.0
"""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

import requests
from django.conf import settings

from scraper.types import ProfileMeta, ReelMeta

logger = logging.getLogger(__name__)

_MEDIA_FIELDS = ("id,caption,media_type,media_product_type,media_url,"
                 "thumbnail_url,permalink,timestamp,like_count,comments_count")


class GraphError(RuntimeError):
    def __init__(self, message: str, code: int = 0, subcode: int = 0):
        super().__init__(message)
        self.code = code
        self.subcode = subcode


class NotDiscoverable(GraphError):
    """The target is not a Business/Creator account (or blocks discovery)."""


def _base() -> str:
    v = getattr(settings, "IG_GRAPH_API_VERSION", "v21.0")
    return f"https://graph.facebook.com/{v}"


def configured() -> bool:
    return bool(getattr(settings, "IG_GRAPH_TOKEN", ""))


def _get(path: str, params: dict, timeout: int = 30) -> dict:
    params = {**params, "access_token": settings.IG_GRAPH_TOKEN}
    resp = requests.get(f"{_base()}/{path.lstrip('/')}", params=params,
                        timeout=timeout)
    try:
        data = resp.json()
    except ValueError as exc:
        raise GraphError(f"risposta non JSON ({resp.status_code})") from exc
    err = data.get("error")
    if err:
        msg = err.get("message", "")
        code = int(err.get("code", 0))
        sub = int(err.get("error_subcode", 0))
        # code 110 / "cannot be found": the username is not a Business or
        # Creator account, or has blocked discovery. A verdict, not a fault.
        if code == 110 or "business discovery" in msg.lower():
            raise NotDiscoverable(msg, code, sub)
        raise GraphError(msg, code, sub)
    return data


def whoami() -> dict:
    """The token's identity — {'id', 'name'}. Cheap token validity check."""
    return _get("me", {"fields": "id,name"})


def resolve_caller_ig_id() -> str:
    """The instagram_business_account id behind the token's first Page.

    business_discovery is always called *as* an IG business account; this
    walks token -> pages -> linked IG account so nobody has to hunt the id
    down in Meta's UI.
    """
    pages = _get("me/accounts", {"fields": "name,instagram_business_account"})
    for page in pages.get("data", []):
        ig = page.get("instagram_business_account")
        if ig and ig.get("id"):
            logger.info("[graph] caller IG account via pagina '%s': %s",
                        page.get("name"), ig["id"])
            return ig["id"]
    raise GraphError(
        "Nessuna pagina Facebook con un account Instagram Business collegato. "
        "Serve: pagina FB + account IG Business collegato alla pagina."
    )


_SHORTCODE_RE = re.compile(r"instagram\.com/(?:reel|p|tv)/([A-Za-z0-9_-]+)")


def _to_reel(m: dict) -> Optional[ReelMeta]:
    """A business_discovery media node → the pipeline's ReelMeta, or None
    for media that are not video (the pipeline is a reel pipeline)."""
    if m.get("media_type") != "VIDEO":
        return None
    permalink = m.get("permalink") or ""
    sc = _SHORTCODE_RE.search(permalink)
    if not sc:
        return None
    ts = None
    raw_ts = m.get("timestamp")
    if raw_ts:
        from datetime import datetime
        try:
            ts = int(datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).timestamp())
        except ValueError:
            pass
    return ReelMeta(
        shortcode=sc.group(1),
        ig_media_id=str(m.get("id") or ""),
        caption=m.get("caption") or "",
        video_url=m.get("media_url") or "",
        thumbnail_url=m.get("thumbnail_url") or "",
        # Plays are not exposed through business_discovery: None is the
        # truth, and writing 0 would corrupt the engagement weighting.
        view_count=None,
        like_count=m.get("like_count"),
        comment_count=m.get("comments_count"),
        posted_at_ts=ts,
        raw=m,
    )


def discover(username: str, caller_ig_id: str, after: str = "",
             page_size: int = 25) -> tuple[ProfileMeta, list[ReelMeta], dict]:
    """One page of a target account through business_discovery.

    Returns (profile, reels, paging) where paging is
    {'after': cursor or '', 'has_next_page': bool}.
    Raises NotDiscoverable for personal accounts — the caller records that
    on the TrackedAccount instead of retrying forever.
    """
    cursor = f".after({after})" if after else ""
    fields = (f"business_discovery.username({username})"
              f"{{username,name,profile_picture_url,biography,followers_count,"
              f"media_count,media.limit({page_size}){cursor}"
              f"{{{_MEDIA_FIELDS}}}}}")
    data = _get(caller_ig_id, {"fields": fields})
    bd = data.get("business_discovery") or {}

    profile = ProfileMeta(
        username=bd.get("username") or username,
        ig_user_id=str(bd.get("id") or ""),
        display_name=bd.get("name") or "",
        profile_pic_url=bd.get("profile_picture_url") or "",
        bio=bd.get("biography") or "",
        followers_count=bd.get("followers_count"),
    )
    media = (bd.get("media") or {})
    reels = [r for r in (_to_reel(m) for m in media.get("data", [])) if r]
    nxt = ((media.get("paging") or {}).get("cursors") or {}).get("after", "")
    has_next = bool((media.get("paging") or {}).get("next"))
    return profile, reels, {"after": nxt, "has_next_page": has_next}


def probe(username: str, caller_ig_id: str) -> dict:
    """One cheap request answering the two questions that decide everything:
    is this account discoverable, and do its videos come with a media_url?
    """
    t0 = time.time()
    try:
        profile, reels, _ = discover(username, caller_ig_id, page_size=5)
    except NotDiscoverable as exc:
        return {"username": username, "discoverable": False,
                "reason": str(exc)[:120], "ms": round((time.time() - t0) * 1000)}
    videos = [r for r in reels if r.shortcode]
    with_url = sum(1 for r in videos if r.video_url)
    return {"username": username, "discoverable": True,
            "followers": profile.followers_count,
            "videos_sampled": len(videos), "with_media_url": with_url,
            "ms": round((time.time() - t0) * 1000)}
