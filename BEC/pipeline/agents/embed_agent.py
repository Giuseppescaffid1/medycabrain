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
    chunks = _embed_passages()
    return {"embedded": len(missing), "already": before, "passages": chunks}


def _embed_passages(batch: int = 64) -> int:
    """One vector per passage, for the chat's passage picker.

    Without these the chat re-encodes every candidate document's passages on
    every question: measured at 15-18s per query, which was its entire
    latency. Computing them here costs one pass and makes the chat's cost a
    dot product.
    """
    from core.knowledge import _chunks, _get_embedder
    from core.models import KnowledgeDocument, ReelEmbedding

    embedder = _get_embedder()
    done = 0

    def _fill(obj, text, save_field):
        nonlocal done
        parts = _chunks(text)
        # A single passage needs no picking, and an empty one nothing to pick.
        if len(parts) < 2:
            if obj_chunks(obj, save_field):
                setattr(obj, save_field, [])
                obj.save(update_fields=[save_field])
            return
        vecs = embedder.encode(parts, normalize_embeddings=True,
                               show_progress_bar=False)
        setattr(obj, save_field, [v.tolist() for v in vecs])
        obj.save(update_fields=[save_field])
        done += 1

    def obj_chunks(obj, field):
        return getattr(obj, field, None)

    qs = (ReelEmbedding.objects
          .select_related("reel", "reel__transcript")
          .iterator(chunk_size=batch))
    for emb in qs:
        text = ""
        tr = getattr(emb.reel, "transcript", None)
        text = (tr.text if tr else "") or emb.reel.caption
        if len(_chunks(text)) == len(emb.chunk_vectors or []) and emb.chunk_vectors:
            continue  # already current
        _fill(emb, text, "chunk_vectors")

    for doc in KnowledgeDocument.objects.filter(is_active=True).iterator():
        if len(_chunks(doc.content_text)) == len(doc.chunk_vectors or []) and doc.chunk_vectors:
            continue
        _fill(doc, doc.content_text, "chunk_vectors")

    logger.info("[embed] passaggi indicizzati per %d documenti", done)
    return done
