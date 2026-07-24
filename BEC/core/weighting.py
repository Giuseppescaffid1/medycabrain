"""
core/weighting.py
=================
Engagement weighting — the "media ponderata".

Each reel is scored by engagement (views, with a like blend), then
NORMALIZED against its own account's median so a huge competitor account
doesn't dominate: a reel is judged relative to what that account usually
gets. weight ≈ reel_engagement / account_median_engagement.

Used by analytics (performance metrics) and the strategy engine (weight
what to propose toward what actually performs).
"""

from __future__ import annotations

import statistics

from core.models import Reel

LIKE_BLEND = 5.0  # 1 like ≈ 5 views of signal


def raw_engagement(reel: Reel) -> float:
    v = reel.view_count or 0
    l = reel.like_count or 0
    return float(v) + LIKE_BLEND * float(l)


def account_medians() -> dict[int, float]:
    """account_id -> median raw engagement (for normalization)."""
    by_acct: dict[int, list[float]] = {}
    for r in Reel.objects.filter(is_active=True).select_related("account"):
        by_acct.setdefault(r.account_id, []).append(raw_engagement(r))
    return {
        aid: (statistics.median(vals) if vals else 0.0)
        for aid, vals in by_acct.items()
    }


def normalized_engagement(reel: Reel, medians: dict[int, float] | None = None) -> float:
    """Reel engagement relative to its account's median (1.0 = typical)."""
    medians = medians if medians is not None else account_medians()
    med = medians.get(reel.account_id, 0.0)
    if med <= 0:
        return 1.0
    return round(raw_engagement(reel) / med, 3)


def weight_map(reels) -> dict[int, float]:
    """reel_id -> normalized engagement, computed with one median pass."""
    medians = account_medians()
    return {r.id: normalized_engagement(r, medians) for r in reels}
