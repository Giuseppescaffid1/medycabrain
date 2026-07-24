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
from core.weighting import account_medians, normalized_engagement, raw_engagement

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
    reels = list(_reels(scope).select_related("account", "enrichment")[:400])
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
    out = []
    for c in run.clusters.all().order_by("-size"):
        reels = list(
            Reel.objects.filter(cluster_assignments__cluster=c, is_active=True)
            .select_related("account")
        )
        if not reels:
            continue
        weights = [normalized_engagement(r, medians) for r in reels]
        views = [r.view_count or 0 for r in reels]
        out.append({
            "id": c.id,
            "label": c.label_it,
            "reels": len(reels),
            "avg_weight": round(sum(weights) / len(weights), 2),
            "avg_views": round(sum(views) / len(views)),
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
