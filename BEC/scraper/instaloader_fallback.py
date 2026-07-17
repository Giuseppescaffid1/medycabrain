"""
scraper/instaloader_fallback.py
===============================
Fallback provider using instaloader (v4.15.x). Kicks in when the GraphQL
client raises IGSchemaChanged (doc_id rotated) or otherwise fails.

Uses the same burner-account cookies via context._session, and emits the
same ProfileMeta / ReelMeta so the ScraperAgent doesn't care which
provider produced a reel.
"""

from __future__ import annotations

import logging
from typing import Iterator

from .session_store import load_cookies
from .types import IGBlocked, ProfileMeta, ReelMeta

logger = logging.getLogger(__name__)


def _make_loader(cookies: dict):
    import instaloader

    L = instaloader.Instaloader(
        quiet=True,
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_comments=False,
        save_metadata=False,
        request_timeout=40,
    )
    # Inject burner-account cookies into instaloader's requests session.
    for name, value in cookies.items():
        L.context._session.cookies.set(name, value, domain=".instagram.com")
    ds_user = cookies.get("ds_user_id")
    if ds_user:
        L.context.user_id = ds_user
    return L, instaloader


def resolve_and_fetch(
    username: str, max_reels: int = 36, known_shortcodes: set[str] | None = None
) -> tuple[ProfileMeta, list[ReelMeta]]:
    """Resolve the profile and pull up to max_reels reels via instaloader."""
    known_shortcodes = known_shortcodes or set()
    cookies = load_cookies()
    L, instaloader = _make_loader(cookies)

    try:
        profile = instaloader.Profile.from_username(L.context, username)
    except Exception as exc:  # noqa: BLE001
        raise IGBlocked(f"instaloader profile load failed for @{username}: {exc!r}") from exc

    meta = ProfileMeta(
        username=username,
        ig_user_id=str(profile.userid),
        display_name=profile.full_name or "",
        profile_pic_url=profile.profile_pic_url or "",
        bio=profile.biography or "",
        followers_count=profile.followers,
    )

    reels: list[ReelMeta] = []
    try:
        for post in profile.get_posts():
            if not post.is_video:
                continue
            if post.shortcode in known_shortcodes:
                continue
            reels.append(_post_to_reel(post))
            if len(reels) >= max_reels:
                break
    except Exception as exc:  # noqa: BLE001
        logger.warning("[instaloader] iteration stopped early for @%s: %r", username, exc)
        if not reels:
            raise IGBlocked(f"instaloader posts iteration failed: {exc!r}") from exc

    return meta, reels


def _post_to_reel(post) -> ReelMeta:
    return ReelMeta(
        shortcode=post.shortcode,
        ig_media_id=str(post.mediaid),
        caption=post.caption or "",
        video_url=post.video_url or "",
        thumbnail_url=post.url or "",
        view_count=getattr(post, "video_view_count", None),
        like_count=post.likes,
        comment_count=post.comments,
        duration_s=getattr(post, "video_duration", None),
        posted_at_ts=int(post.date_utc.timestamp()) if post.date_utc else None,
        audio_info={},
        raw={"provider": "instaloader", "shortcode": post.shortcode},
    )
