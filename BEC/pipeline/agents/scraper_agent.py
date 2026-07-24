"""
pipeline/agents/scraper_agent.py
================================
ScraperAgent — mimics Apify's instagram-scraper for the configured
tracked accounts.

Per active account:
  1. resolve profile (GraphQL primary → instaloader fallback)
  2. paginate reels, skipping already-known shortcodes; stop when a full
     page is all-known (incremental)
  3. dump each raw node to data/raw/{account}/{shortcode}.json
  4. upsert Reel rows (media_status='pending')

Rate discipline (all from ScraperConfig, admin-editable):
  min_delay_s jittered between requests, max_pages_per_account,
  global_request_budget across the whole run, provider_order.

IGBlocked aborts the current account but never the pipeline.
"""

from __future__ import annotations

import json
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.utils import timezone as dj_tz

from core.models import PENDING, Reel, ScraperConfig, TrackedAccount
from scraper import ig_client, instaloader_fallback
from scraper.session_store import load_cookies
from scraper.types import IGBlocked, IGSchemaChanged, ProfileMeta, ReelMeta

logger = logging.getLogger(__name__)


def _cfg(key, default):
    val = ScraperConfig.get(key)
    if isinstance(val, dict) and "value" in val:
        return val["value"]
    return val if val is not None else default


def _dump_raw(username: str, reel: ReelMeta):
    d = Path(settings.RAW_DUMP_DIR) / username
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{reel.shortcode}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(reel.raw, fh, ensure_ascii=False)
    return str(path.relative_to(settings.BASE_DIR))


def _upsert_reel(account: TrackedAccount, reel: ReelMeta, raw_path: str) -> bool:
    posted_at = None
    if reel.posted_at_ts:
        posted_at = datetime.fromtimestamp(reel.posted_at_ts, tz=timezone.utc)

    obj, created = Reel.objects.update_or_create(
        shortcode=reel.shortcode,
        defaults={
            "account": account,
            "ig_media_id": reel.ig_media_id,
            "caption": reel.caption,
            "posted_at": posted_at,
            "duration_s": reel.duration_s,
            "view_count": reel.view_count,
            "like_count": reel.like_count,
            "comment_count": reel.comment_count,
            "video_url": reel.video_url,
            "thumbnail_url": reel.thumbnail_url,
            "audio_info": reel.audio_info or {},
            "raw_json_path": raw_path,
            "is_active": True,
        },
    )
    if created:
        # New reel → schedule the media stage.
        obj.media_status = PENDING
        obj.save(update_fields=["media_status"])
    return created


def _scrape_account_graphql(account: TrackedAccount, budget: list[int]) -> tuple[int, bool]:
    """Returns (new_reels, complete). Mutates budget[0] (remaining requests)."""
    cookies = load_cookies()
    csrf = cookies.get("csrftoken", "")
    impersonate = _cfg("impersonate", "chrome124")
    session = ig_client.build_session(cookies, impersonate=impersonate)

    doc_id = _cfg("doc_id_reels_tab", "")
    page_size = int(_cfg("page_size", 12))
    max_pages = int(_cfg("max_pages_per_account", 3))
    min_delay = float(_cfg("min_delay_s", 25))
    # Full backfill: paginate the whole depth even when pages are already known,
    # to pull the OLDER reels an incremental scrape never reaches.
    full_backfill = bool(_cfg("full_backfill", False))

    # Resolve profile
    profile = ig_client.resolve_user(session, account.username, csrftoken=csrf)
    budget[0] -= 1
    _apply_profile(account, profile)

    known = set(
        Reel.objects.filter(account=account).values_list("shortcode", flat=True)
    )
    new_count = 0
    cursor = ""
    for page_idx in range(max_pages):
        if budget[0] <= 0:
            logger.warning("[scraper] global request budget exhausted")
            return new_count, False
        time.sleep(random.uniform(min_delay, min_delay * 2))
        nodes, page_info = ig_client.fetch_reels_page(
            session, profile.ig_user_id, doc_id, after=cursor,
            page_size=page_size, csrftoken=csrf, handle=account.username,
        )
        budget[0] -= 1

        page_new = 0
        for node in nodes:
            reel = ig_client.parse_reel_node(node)
            if not reel:
                continue
            raw_path = _dump_raw(account.username, reel)
            if _upsert_reel(account, reel, raw_path):
                page_new += 1
        new_count += page_new
        logger.info("[scraper] @%s page %s: %s nodes, %s new",
                    account.username, page_idx + 1, len(nodes), page_new)

        # Incremental stop: whole page already known and no new ones.
        # Skipped in full-backfill mode so we reach the older, unseen reels.
        if not full_backfill:
            all_known = all(
                (ig_client.parse_reel_node(n) or ReelMeta(shortcode="")).shortcode in known
                for n in nodes if n
            )
            if nodes and page_new == 0 and all_known:
                logger.info("[scraper] @%s: full page already known, stopping", account.username)
                break
        if not page_info.get("has_next_page"):
            break
        cursor = page_info.get("end_cursor", "")
        account.scrape_state = {**account.scrape_state, "end_cursor": cursor}
        account.save(update_fields=["scrape_state"])

    return new_count, True


def _scrape_account_instaloader(account: TrackedAccount) -> tuple[int, bool]:
    known = set(Reel.objects.filter(account=account).values_list("shortcode", flat=True))
    max_pages = int(_cfg("max_pages_per_account", 3))
    page_size = int(_cfg("page_size", 12))
    profile, reels = instaloader_fallback.resolve_and_fetch(
        account.username, max_reels=max_pages * page_size, known_shortcodes=known,
    )
    _apply_profile(account, profile)
    new_count = 0
    for reel in reels:
        raw_path = _dump_raw(account.username, reel)
        if _upsert_reel(account, reel, raw_path):
            new_count += 1
    return new_count, True


def _apply_profile(account: TrackedAccount, profile: ProfileMeta):
    account.ig_user_id = profile.ig_user_id or account.ig_user_id
    account.display_name = profile.display_name or account.display_name
    account.profile_pic_url = profile.profile_pic_url or account.profile_pic_url
    account.bio = profile.bio or account.bio
    if profile.followers_count is not None:
        account.followers_count = profile.followers_count
    account.save(update_fields=[
        "ig_user_id", "display_name", "profile_pic_url", "bio", "followers_count",
    ])


def run(ctx) -> dict:
    provider_order = _cfg("provider_order", ["graphql", "instaloader"])
    budget = [int(_cfg("global_request_budget", 40))]
    accounts = TrackedAccount.objects.filter(is_active=True)
    if not accounts:
        return {"accounts": 0, "new_reels": 0, "note": "no active accounts"}

    total_new = 0
    per_account = {}
    for account in accounts:
        if budget[0] <= 0:
            per_account[account.username] = "skipped (budget)"
            continue
        new_count, err = _scrape_one(account, provider_order, budget)
        per_account[account.username] = new_count if err is None else f"error: {err}"
        if err is None:
            total_new += new_count
            account.last_scraped_at = dj_tz.now()
            account.scrape_state = {**account.scrape_state, "consecutive_failures": 0,
                                    "last_error": ""}
            account.save(update_fields=["last_scraped_at", "scrape_state"])
        else:
            fails = int(account.scrape_state.get("consecutive_failures", 0)) + 1
            account.scrape_state = {**account.scrape_state,
                                    "consecutive_failures": fails, "last_error": err}
            account.save(update_fields=["scrape_state"])

    return {"accounts": len(per_account), "new_reels": total_new, "detail": per_account}


def _scrape_one(account, provider_order, budget):
    """Try providers in order. Returns (new_count, error_str|None)."""
    last_err = None
    for provider in provider_order:
        try:
            if provider == "graphql":
                n, _ = _scrape_account_graphql(account, budget)
            elif provider == "instaloader":
                n, _ = _scrape_account_instaloader(account)
            else:
                continue
            account.scrape_state = {**account.scrape_state, "provider": provider}
            return n, None
        except IGSchemaChanged as exc:
            logger.error("[scraper] @%s doc_id rotated on %s: %s — trying fallback",
                         account.username, provider, exc)
            last_err = f"schema_changed: {exc}"
            continue
        except IGBlocked as exc:
            logger.error("[scraper] @%s blocked on %s: %s", account.username, provider, exc)
            last_err = f"blocked: {exc}"
            continue
        except FileNotFoundError as exc:
            return 0, f"no_session: {exc}"
        except Exception as exc:  # noqa: BLE001
            logger.exception("[scraper] @%s unexpected error on %s", account.username, provider)
            last_err = f"error: {exc!r}"
            continue
    return 0, last_err
