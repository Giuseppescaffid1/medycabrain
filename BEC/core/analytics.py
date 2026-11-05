"""
core/analytics.py
=================
Engagement / performance statistics — the visible "numbers" layer.

Mirrors the SPI analytics pattern (messtudent/spi-backend/analytics/views.py:
one computation per metric → a plain dict/list), but uses the Django ORM
(TruncMonth time-buckets, aggregates, top-N) since medycabrain's models are
Django-managed. All metrics are per scope (owned = Medyca, competitor).
Performance uses the normalized engagement from core/weighting.py.
"""

from __future__ import annotations

from django.db.models import Avg, Count, Sum
from django.db.models.functions import TruncMonth

from core.models import ClusterRun, Reel, ReelClusterAssignment, TopicCluster
from core.weighting import LIKE_BLEND, account_medians, normalized_engagement, raw_engagement

SCOPE_MAP = {"medyca": "owned", "owned": "owned", "competitor": "competitor"}


def _reels(scope: str):
    owner = SCOPE_MAP.get(scope, "competitor")
    return Reel.objects.filter(is_active=True, account__owner_type=owner)


def overview(scope: str) -> dict:
    qs = _reels(scope)
    agg = qs.aggregate(
        total=Count("id"),
        avg_views=Avg("view_count"),
        avg_likes=Avg("like_count"),
        total_views=Sum("view_count"),
        total_likes=Sum("like_count"),
    )
    # top-performing theme (cluster) by normalized engagement
    top = cluster_performance(scope)
    return {
        "scope": scope,
        "reels": agg["total"] or 0,
        "avg_views": round(agg["avg_views"] or 0),
        "avg_likes": round(agg["avg_likes"] or 0),
        "total_views": agg["total_views"] or 0,
        "total_likes": agg["total_likes"] or 0,
        "top_theme": top[0]["label"] if top else None,
    }


def engagement_over_time(scope: str) -> list[dict]:
    qs = (
        _reels(scope)
        .exclude(posted_at__isnull=True)
        .annotate(m=TruncMonth("posted_at"))
        .values("m")
        .annotate(reels=Count("id"), views=Sum("view_count"), likes=Sum("like_count"))
        .order_by("m")
    )
    return [
        {
            "month": r["m"].strftime("%Y-%m"),
            "reels": r["reels"],
            "views": r["views"] or 0,
            "likes": r["likes"] or 0,
        }
        for r in qs
    ]


def top_content(scope: str, limit: int = 8) -> list[dict]:
    medians = account_medians()
    reels = list(_reels(scope).select_related("account", "enrichment"))
    scored = sorted(reels, key=lambda r: normalized_engagement(r, medians), reverse=True)
    out = []
    for r in scored[:limit]:
        enr = getattr(r, "enrichment", None)
        out.append({
            "id": r.id,
            "shortcode": r.shortcode,
            "account": r.account.username,
            "title": (enr.summary_it if enr and enr.summary_it else r.caption or r.shortcode)[:80],
            "views": r.view_count or 0,
            "likes": r.like_count or 0,
            "weight": normalized_engagement(r, medians),
            "url": f"https://www.instagram.com/reel/{r.shortcode}/",
            "thumbnail_file": r.thumbnail_file,
        })
    return out


def cluster_performance(scope: str) -> list[dict]:
    owner = SCOPE_MAP.get(scope, "competitor")
    run = ClusterRun.objects.filter(scope=owner, is_current=True).first()
    if not run:
        return []
    medians = account_medians()
    # One query for the whole run, grouped here. It used to ask for the reels
    # of each cluster in turn: 310 queries, 2.6 s, for 233 clusters.
    rows = (
        ReelClusterAssignment.objects
        .filter(run=run, cluster__isnull=False, reel__is_active=True)
        .values_list("cluster_id", "reel__account_id", "reel__view_count", "reel__like_count")
    )
    by_cluster: dict[int, list[tuple]] = {}
    for cid, account_id, views, likes in rows:
        by_cluster.setdefault(cid, []).append((account_id, views or 0, likes or 0))
    out = []
    for c in run.clusters.all().order_by("-size"):
        members = by_cluster.get(c.id)
        if not members:
            continue
        weights = []
        for account_id, views, likes in members:
            med = medians.get(account_id, 0.0)
            raw = float(views) + LIKE_BLEND * float(likes)
            # same rule as weighting.normalized_engagement
            weights.append(round(raw / med, 3) if med > 0 else 1.0)
        out.append({
            "id": c.id,
            "label": c.label_it,
            "reels": len(members),
            "avg_weight": round(sum(weights) / len(weights), 2),
            "avg_views": round(sum(m[1] for m in members) / len(members)),
        })
    out.sort(key=lambda x: x["avg_weight"], reverse=True)
    return out


def benchmark() -> dict:
    """Medyca vs competitor headline comparison (raw + per-reel averages)."""
    def block(owner):
        qs = Reel.objects.filter(is_active=True, account__owner_type=owner)
        agg = qs.aggregate(reels=Count("id"), avg_views=Avg("view_count"), avg_likes=Avg("like_count"))
        return {
            "reels": agg["reels"] or 0,
            "avg_views": round(agg["avg_views"] or 0),
            "avg_likes": round(agg["avg_likes"] or 0),
        }
    return {"medyca": block("owned"), "competitor": block("competitor")}
