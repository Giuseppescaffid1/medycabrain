"""
scraper/apify_budget.py
=======================
Il tetto di spesa su Apify — the one thing that actually protects the budget.

The account is on Apify's FREE plan: **$5.00 per usage cycle**, and the cycle
renews monthly (verified 2026-09-11: cycle 27 Aug → 26 Sep, $0.03 spent). It is
not a one-off allowance, but it is a hard ceiling: past it, the actor stops
answering and the nightly collection dies silently.

So nothing here trusts intentions. Before a run spends anything, it asks Apify
what the cycle has already cost, adds what it is about to cost, and refuses if
that crosses the ceiling — leaving the last dollar untouched on purpose, so a
mis-estimate cannot reach zero.

Prices, read from the actor's own pricing on 2026-09-11 (`apify/instagram-reel-
scraper`, PAY_PER_EVENT, FREE tier). They are per *result*, not per request:

    reel                $0.0026   every reel returned, new or already known
    actor-start         $0.0010   flat, once per account queried

    shares-count        $0.0070   ⛔ never enabled
    video-download      $0.0200   ⛔ never enabled — yt-dlp does it for free
    transcript          $0.0480   ⛔ never enabled — the pipeline transcribes itself

The three add-ons are one JSON field away and cost 2.7×, 7.7× and **18×** the
base price. `apify_provider` sends an explicit, closed input payload for that
reason: a stray flag would burn a month of budget in a single night.

A verified cost check: 5 reels from one account cost exactly
$0.001 + 5 × $0.0026 = $0.014, which is what Apify billed.
"""

from __future__ import annotations

import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

PRICE_PER_REEL = 0.0026
PRICE_PER_START = 0.0010

# What the run refuses to cross. Below the plan's $5 on purpose: the estimate is
# an estimate (an account can return fewer reels than asked, never more), and
# the remaining dollar is the margin that keeps a bad guess from reaching zero.
DEFAULT_CEILING_USD = 4.00

_USER_URL = "https://api.apify.com/v2/users/me"
_USAGE_URL = "https://api.apify.com/v2/users/me/usage/monthly"

# `/ops/status/` is polled every five seconds per open tab and shows the spend.
# Without a cache that would be a request to Apify every five seconds, per tab.
_CACHE_TTL_S = 300
_cache: dict = {"at": 0.0, "value": None}


class ApifyBudgetExceeded(RuntimeError):
    """The cycle's ceiling would be crossed. The caller must not spend."""


def ceiling_usd() -> float:
    """The configured ceiling, editable in the admin without a redeploy."""
    from core.models import ScraperConfig

    val = ScraperConfig.get("apify_ceiling_usd", {"value": DEFAULT_CEILING_USD})
    if isinstance(val, dict):
        val = val.get("value", DEFAULT_CEILING_USD)
    try:
        return max(0.0, float(val))
    except (TypeError, ValueError):
        return DEFAULT_CEILING_USD


def estimate_usd(accounts: int, depth: int) -> float:
    """What querying `accounts` accounts at `depth` reels each would cost.

    Deliberately pessimistic: it assumes every account returns the full depth.
    An account that posts rarely returns fewer, so the real bill comes in under
    the estimate — the right direction to be wrong in when the budget is $5.
    """
    return accounts * (PRICE_PER_START + depth * PRICE_PER_REEL)


def spend(force: bool = False) -> dict | None:
    """What this cycle has cost so far, straight from Apify.

    Returns None when there is no token or Apify cannot be reached — the
    caller then treats the budget as unknown, which blocks spending rather
    than assuming there is room.
    """
    token = getattr(settings, "APIFY_TOKEN", "")
    if not token:
        return None
    if not force and _cache["value"] and time.time() - _cache["at"] < _CACHE_TTL_S:
        return _cache["value"]

    try:
        user = requests.get(_USER_URL, params={"token": token}, timeout=20).json()
        usage = requests.get(_USAGE_URL, params={"token": token}, timeout=20).json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("[apify] impossibile leggere la spesa del ciclo: %r", exc)
        return None

    plan = (user.get("data") or {}).get("plan") or {}
    u = usage.get("data") or {}
    limit = plan.get("maxMonthlyUsageUsd") or plan.get("monthlyUsageCreditsUsd") or 0.0
    spent = u.get("totalUsageCreditsUsdAfterVolumeDiscount") or 0.0
    cycle = u.get("usageCycle") or {}
    ceiling = ceiling_usd()

    value = {
        "plan": plan.get("id", ""),
        "spent_usd": round(float(spent), 4),
        "limit_usd": round(float(limit), 2),
        "ceiling_usd": round(ceiling, 2),
        # What a run is still allowed to spend — against our ceiling, not the
        # plan's limit. This is the number every decision is made on.
        "available_usd": round(max(0.0, ceiling - float(spent)), 4),
        "cycle_start": cycle.get("startAt"),
        "cycle_end": cycle.get("endAt"),
    }
    _cache["at"], _cache["value"] = time.time(), value
    return value


def check(cost_usd: float) -> dict:
    """Refuse `cost_usd` if it would cross the ceiling. Returns the budget.

    Raises `ApifyBudgetExceeded` — which every caller treats as "stop spending",
    never as "the account is broken".
    """
    b = spend()
    if b is None:
        raise ApifyBudgetExceeded(
            "budget Apify sconosciuto (token mancante o API irraggiungibile): "
            "non spendo al buio")
    if cost_usd > b["available_usd"]:
        raise ApifyBudgetExceeded(
            f"tetto raggiunto: spesi ${b['spent_usd']:.2f} di ${b['ceiling_usd']:.2f} "
            f"nel ciclo, questa operazione ne costerebbe ${cost_usd:.2f}")
    return b


def note_spent(cost_usd: float) -> None:
    """Add a just-incurred cost to the cached figure.

    The cache lives five minutes, and a run queries many accounts inside that
    window. Without this, every account in a run would be checked against the
    same stale number and the ceiling could be crossed several times over
    before Apify's own figure caught up.
    """
    if _cache["value"]:
        v = _cache["value"]
        v["spent_usd"] = round(v["spent_usd"] + cost_usd, 4)
        v["available_usd"] = round(max(0.0, v["ceiling_usd"] - v["spent_usd"]), 4)
