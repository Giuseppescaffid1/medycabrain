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

# Apify is billed per result, so depth is money. The floor is what it takes to
# notice a new post at all; the ceiling stops one prolific account from eating
# a run's budget. Both are editable in the admin (scraper_config).
_APIFY_MIN_DEPTH = 3


def _apify_max_depth() -> int:
    return int(_cfg("apify_max_depth", 30))

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

    obj, created = Reel.objects.get_or_create(
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
        obj.media_status = PENDING
        obj.save(update_fields=["media_status"])
        return True

    # Re-scrape: refresh volatile fields (engagement counts + fresh URLs) but
    # NEVER clobber the richer media/info-backfilled fields (posted_at, caption,
    # duration) — the clips node lacks them, so writing them would null out data.
    obj.account = account
    if reel.view_count is not None:
        obj.view_count = reel.view_count
    if reel.like_count is not None:
        obj.like_count = reel.like_count
    if reel.comment_count is not None:
        obj.comment_count = reel.comment_count
    if reel.video_url:
        obj.video_url = reel.video_url
    if reel.thumbnail_url:
        obj.thumbnail_url = reel.thumbnail_url
    if posted_at and not obj.posted_at:
        obj.posted_at = posted_at
    if reel.caption and not obj.caption:
        obj.caption = reel.caption
    if reel.duration_s and not obj.duration_s:
        obj.duration_s = reel.duration_s
    # Deliberately NOT touching is_active here: a reel the client excluded
    # (greetings, off-topic guest) must stay excluded across re-scrapes.
    obj.save()
    return False


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


def _scrape_account_graph(account: TrackedAccount, budget: list[int]) -> tuple[int, bool]:
    """The official path: business_discovery via the Graph API.

    Same contract as the GraphQL scraper — (new_reels, complete), budget
    mutated — but no cookies, no impersonation, no quota guessing: the rate
    limits are documented and the caller is an app we registered.

    A personal target account raises NotDiscoverable; that is a property of
    the account, not a transient failure, so it is recorded on the row and
    the account is skipped in future runs until it changes.
    """
    from django.conf import settings

    from scraper import graph_client

    caller = settings.IG_GRAPH_USER_ID or graph_client.resolve_caller_ig_id()
    max_pages = int(_cfg("max_pages_per_account", 3))
    page_size = min(int(_cfg("page_size", 12)) * 2, 25)  # API pages are cheap
    full_backfill = bool(_cfg("full_backfill", False))

    state = account.scrape_state or {}
    if state.get("graph_not_discoverable"):
        logger.info("[scraper] @%s: non-Business, salto (business_discovery)",
                    account.username)
        return 0, True

    known = set(
        Reel.objects.filter(account=account).values_list("shortcode", flat=True)
    )
    new_count, cursor = 0, ""
    for page_idx in range(max_pages):
        if budget[0] <= 0:
            logger.warning("[scraper] global request budget exhausted")
            return new_count, False
        try:
            profile, reels, paging = graph_client.discover(
                account.username, caller, after=cursor, page_size=page_size)
        except graph_client.NotDiscoverable as exc:
            # Permanent property of the target, surfaced once, not retried
            # nightly into noise. Flipping the account to Business clears it
            # by hand (scrape_state) or via a fresh graph_check.
            account.scrape_state = {**state, "graph_not_discoverable": str(exc)[:200]}
            account.save(update_fields=["scrape_state"])
            logger.warning("[scraper] @%s non è Business/Creator: %s",
                           account.username, exc)
            return 0, True
        budget[0] -= 1
        if page_idx == 0:
            _apply_profile(account, profile)

        page_new = 0
        for reel in reels:
            raw_path = _dump_raw(account.username, reel)
            if _upsert_reel(account, reel, raw_path):
                page_new += 1
        new_count += page_new
        logger.info("[scraper] @%s (graph) page %s: %s video, %s new",
                    account.username, page_idx + 1, len(reels), page_new)

        if not full_backfill and reels and page_new == 0 \
                and all(r.shortcode in known for r in reels):
            break
        if not paging.get("has_next_page"):
            break
        cursor = paging.get("after", "")
        # Documented, generous limits — a short fixed pause is courtesy, not
        # the elaborate jitter the unofficial endpoint needed.
        time.sleep(2)

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


def _apify_depth(account: TrackedAccount) -> int:
    """How many reels to ask Apify for, for this account.

    Every result is billed ($0.0026), whether it is new or something we
    already have. Asking a fixed depth of everyone is therefore a way of
    paying the prolific accounts' price for the quiet ones: measured on
    2026-09-11, this project's accounts post anywhere between every 0.1 days
    and every 34 days.

    So the depth is the gap since their last known post, divided by how often
    they actually post, plus a margin of three. An account that posts monthly
    is asked for a handful of reels; one that posts daily is asked for more,
    because it genuinely has more.
    """
    import math

    qs = Reel.objects.filter(account=account).exclude(posted_at=None)
    n = qs.count()
    if n < 2:
        # Nothing to reason from — a new account, or one that has never
        # returned anything. Start shallow and let the next run learn.
        return _APIFY_MIN_DEPTH
    first = qs.order_by("posted_at").first().posted_at
    last = qs.order_by("-posted_at").first().posted_at
    days_per_post = max((last - first).days, 1) / n
    gap_days = max((dj_tz.now() - last).days, 0)
    depth = math.ceil(gap_days / days_per_post) + 3
    return max(_APIFY_MIN_DEPTH, min(depth, _apify_max_depth()))


def _scrape_account_apify(account: TrackedAccount) -> tuple[int, bool]:
    """List an account's recent reels through Apify, and upsert them.

    This is the collection path since 2026-09-11. Instagram closed the two
    that came before it: listing a public profile anonymously now answers
    `401 {"require_login": true}`, and the logged-in path was removed because
    it ran as a personal account that Instagram had begun checkpointing.
    yt-dlp — which does still fetch a reel anonymously — has no working way to
    *list* an account: its own profile extractor is marked `_WORKING = False`.

    Apify queries from its own infrastructure, so no Instagram account of ours
    is involved at all. What it costs, and what stops it costing too much, is
    in `scraper/apify_budget.py`.
    """
    from scraper import apify_provider

    depth = _apify_depth(account)
    items = apify_provider.fetch_reels(account.username, limit=depth)

    new_count = 0
    for it in items:
        posted = it.get("posted_at")
        reel = ReelMeta(
            shortcode=it["shortcode"],
            caption=it.get("caption") or "",
            video_url=it.get("video_url") or "",
            thumbnail_url=it.get("thumbnail_url") or "",
            view_count=it.get("view_count"),
            like_count=it.get("like_count"),
            comment_count=it.get("comment_count"),
            duration_s=it.get("duration_s"),
            posted_at_ts=int(posted.timestamp()) if posted else None,
            raw={k: v for k, v in it.items() if k != "posted_at"},
        )
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
    """Collect new reels for every active account.

    **Apify is the collection path** (since 2026-09-11). The two that came
    before it are closed: Instagram answers `401 require_login` to an
    anonymous profile listing, and the logged-in path was removed on
    2026-07-29 because it ran as a personal account Instagram had started
    checkpointing (23 blocks on 26 July, 15 more on the 29th). Meta's official
    Graph API remains supported and takes precedence when a token is set, but
    it is not configured here.

    Apify costs real money on a $5/cycle plan, so this stage stops on the
    budget ceiling exactly as it stops on the request budget — and says so,
    rather than failing each account into what would read as an incident.
    """
    from scraper import apify_budget, apify_provider, graph_client

    if graph_client.configured():
        provider_order = _cfg("provider_order", ["graph"])
        if "graph" not in provider_order:
            provider_order = ["graph"] + list(provider_order)
    elif apify_provider.enabled():
        provider_order = ["apify"]
    else:
        logger.warning("[scraper] nessuna fonte configurata (né APIFY_TOKEN né "
                       "IG_GRAPH_TOKEN): raccolta sospesa")
        return {"accounts": 0, "new_reels": 0,
                "note": "sospeso: nessuna fonte configurata "
                        "(serve APIFY_TOKEN oppure IG_GRAPH_TOKEN)"}
    budget = [int(_cfg("global_request_budget", 40))]
    accounts = TrackedAccount.objects.filter(is_active=True)
    if not accounts:
        return {"accounts": 0, "new_reels": 0, "note": "no active accounts"}

    total_new = 0
    per_account = {}
    money_stopped = False
    spent_before = (apify_budget.spend(force=True) or {}).get("spent_usd")
    for account in accounts:
        if budget[0] <= 0:
            per_account[account.username] = "skipped (budget)"
            continue
        # Once the money ceiling is reached, every remaining account would be
        # refused anyway. Say it once and stop asking — a dozen identical
        # "budget exceeded" lines read as a dozen failures.
        if money_stopped:
            per_account[account.username] = "skipped (tetto di spesa)"
            continue
        new_count, err = _scrape_one(account, provider_order, budget)
        if err and "tetto" in err:
            money_stopped = True
            per_account[account.username] = "skipped (tetto di spesa)"
            logger.warning("[scraper] fermato dal tetto di spesa Apify: %s", err)
            continue
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

    after = apify_budget.spend(force=True) or {}
    cost = None
    if spent_before is not None and after.get("spent_usd") is not None:
        cost = round(after["spent_usd"] - spent_before, 4)
    return {"accounts": len(per_account), "new_reels": total_new,
            "cost_usd": cost, "budget_stopped": money_stopped,
            "detail": per_account}


def _scrape_one(account, provider_order, budget):
    """Try providers in order. Returns (new_count, error_str|None)."""
    last_err = None
    for provider in provider_order:
        try:
            if provider == "apify":
                n, _ = _scrape_account_apify(account)
            elif provider == "graph":
                n, complete = _scrape_account_graph(account, budget)
            elif provider == "graphql":
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
