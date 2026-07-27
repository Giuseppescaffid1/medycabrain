"""
scraper/types.py
================
Shared dataclasses + exceptions for the Instagram scraping layer.

Both the primary GraphQL client (ig_client.py) and the instaloader
fallback (instaloader_fallback.py) emit the same ReelMeta / ProfileMeta
so the ScraperAgent is provider-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class IGBlocked(Exception):
    """Instagram actively blocked us (401/403/429/checkpoint/login redirect).

    The scrape aborts for this account, but the pipeline continues — never
    fatal. Downstream agents keep processing whatever is already pending.
    """


class IGThrottled(Exception):
    """Instagram answered the HTML app-shell with a 200 instead of JSON.

    Soft rate-limiting on the private API: the account/IP has spent its quota
    for the window. Not a schema change, and not the fault of the reel being
    fetched — retrying inside the same run only deepens the block.
    """


class IGSchemaChanged(Exception):
    """HTTP 200 but the expected JSON keys are missing.

    Almost always means the GraphQL doc_id rotated. Distinct from IGBlocked
    so logs say exactly what happened and the provider falls back.
    """


@dataclass
class ProfileMeta:
    username: str
    ig_user_id: str
    display_name: str = ""
    profile_pic_url: str = ""
    bio: str = ""
    followers_count: Optional[int] = None


@dataclass
class ReelMeta:
    shortcode: str
    ig_media_id: str = ""
    caption: str = ""
    video_url: str = ""
    thumbnail_url: str = ""
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    duration_s: Optional[float] = None
    posted_at_ts: Optional[int] = None  # unix seconds
    audio_info: dict = field(default_factory=dict)  # {title, artist}
    raw: dict = field(default_factory=dict)  # original node, dumped to disk
