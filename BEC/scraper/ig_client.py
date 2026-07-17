"""
scraper/ig_client.py
====================
Primary Instagram scraper: reverse-engineered web/GraphQL API via
curl_cffi (Chrome TLS impersonation), authenticated with burner-account
session cookies.

Modeled on the SPI immobiliare_api.py client: a Session with
impersonate=chrome*, per-request retry/backoff, a dedicated Blocked
exception, and a (results, complete) partial-run contract so an
interrupted paginate never looks like a full snapshot.

Two calls:
  resolve_user(username)          -> ProfileMeta   (web_profile_info)
  fetch_reels_page(uid, cursor)   -> (list[node], page_info)  (graphql/query)

doc_id lives in ScraperConfig (Django admin editable) so a rotation is a
one-row edit, not a deploy. A 200 response whose expected keys are
missing raises IGSchemaChanged (== doc_id likely rotated).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

from curl_cffi import requests as curl_requests

from .types import IGBlocked, IGSchemaChanged, ProfileMeta, ReelMeta

logger = logging.getLogger(__name__)

IG_APP_ID = "936619743392459"
GRAPHQL_URL = "https://www.instagram.com/graphql/query"
WEB_PROFILE_URL = "https://www.instagram.com/api/v1/users/web_profile_info/"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

IG_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "*/*",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "X-IG-App-ID": IG_APP_ID,
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.instagram.com/",
    "Origin": "https://www.instagram.com",
}

_MAX_ATTEMPTS = 3
_BACKOFF_BASE = 3  # 3, 9, 27 s
_BLOCK_STATUSES = (401, 403, 429)


def build_session(cookies: dict, impersonate: str = "chrome124"):
    session = curl_requests.Session(impersonate=impersonate)
    for name, value in cookies.items():
        session.cookies.set(name, value, domain=".instagram.com")
    return session


def _looks_blocked(resp) -> bool:
    if resp.status_code in _BLOCK_STATUSES:
        return True
    # Login-wall / checkpoint pages answer 200 with these markers
    text_head = (resp.text or "")[:2000].lower()
    return "checkpoint_required" in text_head or "login_required" in text_head


def _request(session, method: str, url: str, csrftoken: str = "", **kwargs) -> dict:
    """Do one request with retry/backoff. Raises IGBlocked / RuntimeError."""
    headers = {**IG_HEADERS, **kwargs.pop("headers", {})}
    if csrftoken:
        headers["x-csrftoken"] = csrftoken
    last_err: Optional[str] = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = session.request(method, url, headers=headers, timeout=40, **kwargs)
            if _looks_blocked(resp):
                raise IGBlocked(f"HTTP {resp.status_code} (blocked/checkpoint) on {url}")
            if resp.status_code == 200:
                try:
                    return resp.json()
                except json.JSONDecodeError as exc:
                    raise IGSchemaChanged(f"non-JSON 200 on {url}: {exc}") from exc
            last_err = f"HTTP {resp.status_code}"
        except IGBlocked:
            raise
        except IGSchemaChanged:
            raise
        except Exception as exc:  # noqa: BLE001 — network/JSON
            last_err = repr(exc)

        if attempt < _MAX_ATTEMPTS:
            wait = _BACKOFF_BASE ** attempt
            logger.warning(
                "[ig] %s attempt %s/%s failed (%s), retry in %ss",
                url, attempt, _MAX_ATTEMPTS, last_err, wait,
            )
            time.sleep(wait)

    raise RuntimeError(f"{url} failed after {_MAX_ATTEMPTS} attempts: {last_err}")


# ── Profile resolution ─────────────────────────────────────────────────────────

def resolve_user(session, username: str, csrftoken: str = "") -> ProfileMeta:
    data = _request(
        session, "GET", WEB_PROFILE_URL,
        csrftoken=csrftoken, params={"username": username},
    )
    user = (data.get("data") or {}).get("user")
    if not user:
        raise IGSchemaChanged(f"web_profile_info missing data.user for @{username}")
    return ProfileMeta(
        username=username,
        ig_user_id=str(user.get("id") or ""),
        display_name=user.get("full_name") or "",
        profile_pic_url=user.get("profile_pic_url_hd") or user.get("profile_pic_url") or "",
        bio=user.get("biography") or "",
        followers_count=(user.get("edge_followed_by") or {}).get("count"),
    )


# ── Reels pagination ───────────────────────────────────────────────────────────

def fetch_reels_page(
    session, ig_user_id: str, doc_id: str, after: str = "",
    page_size: int = 12, csrftoken: str = "",
) -> tuple[list[dict], dict]:
    """Fetch one page of the clips (reels) connection.

    Returns (raw_nodes, page_info). page_info = {has_next_page, end_cursor}.
    Raises IGSchemaChanged if the expected connection keys are absent.
    """
    variables = {
        "data": {
            "count": page_size,
            "include_relationship_info": True,
            "latest_besties_reel_media": True,
            "latest_reel_media": True,
        },
        "target_user_id": str(ig_user_id),
        "__relay_internal__pv__PolarisIsLoggedInrelayprovider": True,
    }
    if after:
        variables["after"] = after
        variables["data"]["page_size"] = page_size

    payload = {
        "doc_id": str(doc_id),
        "variables": json.dumps(variables),
    }
    data = _request(
        session, "POST", GRAPHQL_URL, csrftoken=csrftoken,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    # The clips connection key has varied across doc_ids; probe a few.
    conn = _extract_connection(data)
    if conn is None:
        raise IGSchemaChanged(
            "clips connection not found in GraphQL response — doc_id likely rotated"
        )
    edges = conn.get("edges") or []
    nodes = [e.get("node") for e in edges if e.get("node")]
    page_info = conn.get("page_info") or {}
    return nodes, {
        "has_next_page": bool(page_info.get("has_next_page")),
        "end_cursor": page_info.get("end_cursor") or "",
    }


def _extract_connection(data: dict) -> Optional[dict]:
    xdt = data.get("data") or {}
    for key in (
        "xdt_api__v1__clips__user__connection_v2",
        "xdt_api__v1__clips__user__connection",
    ):
        if key in xdt and isinstance(xdt[key], dict):
            return xdt[key]
    # Fallback: any nested dict that has both 'edges' and 'page_info'
    for v in xdt.values():
        if isinstance(v, dict) and "edges" in v and "page_info" in v:
            return v
    return None


# ── Node parsing ───────────────────────────────────────────────────────────────

def parse_reel_node(node: dict) -> Optional[ReelMeta]:
    """Flatten a clips-connection node into ReelMeta. None if unusable."""
    media = node.get("media") or node
    shortcode = media.get("code") or media.get("shortcode")
    if not shortcode:
        return None

    caption_obj = media.get("caption") or {}
    caption = caption_obj.get("text", "") if isinstance(caption_obj, dict) else ""

    # video url: prefer video_versions[0].url
    video_url = ""
    vvs = media.get("video_versions") or []
    if vvs:
        video_url = vvs[0].get("url", "")

    # thumbnail: image_versions2.candidates[0]
    thumb = ""
    iv = (media.get("image_versions2") or {}).get("candidates") or []
    if iv:
        thumb = iv[0].get("url", "")

    clips = media.get("clips_metadata") or {}
    audio = {}
    music = (clips.get("music_info") or {}).get("music_asset_info") or {}
    orig = clips.get("original_sound_info") or {}
    if music:
        audio = {"title": music.get("title"), "artist": music.get("display_artist")}
    elif orig:
        audio = {"title": orig.get("original_audio_title"), "artist": None}

    return ReelMeta(
        shortcode=shortcode,
        ig_media_id=str(media.get("pk") or media.get("id") or ""),
        caption=caption,
        video_url=video_url,
        thumbnail_url=thumb,
        view_count=media.get("play_count") or media.get("view_count"),
        like_count=media.get("like_count"),
        comment_count=media.get("comment_count"),
        duration_s=(vvs[0].get("duration") if vvs and "duration" in vvs[0] else None)
        or media.get("video_duration"),
        posted_at_ts=media.get("taken_at"),
        audio_info=audio,
        raw=node,
    )
