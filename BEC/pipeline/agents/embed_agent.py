"""
pipeline/agents/embed_agent.py
==============================
EmbedAgent — gives every enriched reel a vector.

Embeddings used to be produced only as a side effect of the clustering step.
Anything enriched after the last cluster run therefore had no vector, and
`core/custom_topics.py` filters on `embedding__isnull=False` — which is how a
reel with 1.2M views stayed invisible under its own theme. Making this its own
stage means "analysed" and "searchable" can no longer drift apart.
"""

from __future__ import annotations

import logging

from core.models import DONE, Reel

logger = logging.getLogger(__name__)


def run(ctx) -> dict:
    from pipeline.agents.cluster_agent import _ensure_reel_embeddings

    qs = (
        Reel.objects.filter(enrich_status=DONE, is_active=True)
        .select_related("enrichment", "transcript", "embedding")
    )
    if ctx.limit:
        qs = qs[: ctx.limit]
    reels = list(qs)
    missing = [r for r in reels if getattr(r, "embedding", None) is None]

    if not reels:
        return {"embedded": 0, "already": 0}

    before = len(reels) - len(missing)
    _ensure_reel_embeddings(reels)  # caches; only computes what is missing
    logger.info("[embed] %d reel senza vettore su %d", len(missing), len(reels))
    return {"embedded": len(missing), "already": before}
