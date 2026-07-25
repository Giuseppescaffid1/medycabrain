"""
core/custom_topics.py
=====================
Client-supplied themes ("tiroide", "osteoporosi", "Bijuva"…) mapped onto the
content by embedding similarity. An overlay on top of the auto-discovered
clusters: it never touches ClusterRun/TopicCluster, so a reel can belong to
an auto cluster AND to any number of custom topics.

Matches are recomputed synchronously when a topic is created (instant
feedback in the UI) and refreshed at the end of every cluster pipeline step
so new reels get mapped overnight.
"""

from __future__ import annotations

import logging

import numpy as np
from django.conf import settings
from django.db import transaction

from core.models import (
    CustomTopic, CustomTopicMatch, KnowledgeDocument, Reel, ScraperConfig,
)

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.40


def _threshold() -> float:
    cfg = ScraperConfig.get("custom_topic_threshold", {"value": DEFAULT_THRESHOLD})
    return float(cfg.get("value", DEFAULT_THRESHOLD) if isinstance(cfg, dict) else cfg)


def _topic_query(topic: CustomTopic) -> str:
    parts = [topic.label]
    if topic.keywords:
        parts.append(" ".join(topic.keywords))
    return ". ".join(parts)


def embed_topic(topic: CustomTopic) -> None:
    from core.knowledge import _embed_query

    topic.embedding = _embed_query(_topic_query(topic)).tolist()
    topic.save(update_fields=["embedding"])


def _fold(text: str) -> str:
    """NFKC-fold and lowercase. Instagram captions are full of mathematical
    bold letters (e.g. "𝐀𝐍𝐃𝐑𝐎𝐏𝐀𝐔𝐒𝐀"), which no plain regex would ever match."""
    import unicodedata
    return unicodedata.normalize("NFKC", text or "").lower()


def _reel_haystack(r: Reel) -> str:
    enr = getattr(r, "enrichment", None)
    tr = getattr(r, "transcript", None)
    parts = [r.caption or ""]
    if enr:
        parts.append(enr.summary_it or "")
        parts.append(" ".join(enr.topics or []))
    if tr and tr.text:
        parts.append(tr.text)
    return _fold("\n".join(parts))


def _load_assets() -> list[dict]:
    """All embedded assets: reels (both scopes) + blog docs (owned)."""
    assets = []
    reels = (
        Reel.objects.filter(is_active=True, embedding__isnull=False)
        .filter(embedding__model_name=settings.EMBEDDINGS_MODEL)
        .select_related("embedding", "account", "enrichment", "transcript")
    )
    for r in reels:
        if r.embedding.vector:
            assets.append({
                "kind": "reel", "obj": r,
                "scope": r.account.owner_type,
                "vec": np.asarray(r.embedding.vector, dtype=np.float32),
                "text": _reel_haystack(r),
            })
    for d in KnowledgeDocument.objects.filter(is_active=True).exclude(embedding=[]):
        assets.append({
            "kind": "doc", "obj": d, "scope": "owned",
            "vec": np.asarray(d.embedding, dtype=np.float32),
            "text": _fold(f"{d.title}\n{d.summary_it}\n{' '.join(d.topics or [])}\n{d.content_text}"),
        })
    return assets


def _lexical_terms(topic: CustomTopic) -> list[str]:
    terms = [_fold(t) for t in [topic.label, *topic.keywords] if len(t.strip()) >= 4]
    # Multi-word labels also match on their individual words ("insonnia
    # notturna" should hit a reel that says just "insonnia"). Words < 5 chars
    # are skipped to limit false positives.
    for t in list(terms):
        for w in t.split():
            if len(w) >= 5 and w not in terms:
                terms.append(w)
    return terms


def _lexical_hit(terms: list[str], haystack: str) -> bool:
    import re
    return any(re.search(r"\b" + re.escape(t), haystack) for t in terms)


def recompute_matches(topics: list[CustomTopic] | None = None) -> dict:
    """Recompute CustomTopicMatch rows for the given (default: all active)
    topics. Returns {topic_label: n_matches}."""
    if topics is None:
        topics = list(CustomTopic.objects.filter(is_active=True))
    topics = [t for t in topics if t.embedding]
    if not topics:
        return {}

    assets = _load_assets()
    th = _threshold()
    out: dict[str, int] = {}

    for topic in topics:
        tv = np.asarray(topic.embedding, dtype=np.float32)
        tv /= (np.linalg.norm(tv) or 1.0)
        terms = _lexical_terms(topic)
        rows = []
        for a in assets:
            sim = float(np.dot(tv, a["vec"]))
            semantic = sim >= th
            lexical = _lexical_hit(terms, a["text"]) if terms else False
            if not semantic and not lexical:
                continue
            via = "both" if semantic and lexical else ("keyword" if lexical else "semantic")
            rows.append(CustomTopicMatch(
                topic=topic,
                reel=a["obj"] if a["kind"] == "reel" else None,
                document=a["obj"] if a["kind"] == "doc" else None,
                scope=a["scope"],
                similarity=round(sim, 4),
                via=via,
            ))
        with transaction.atomic():
            CustomTopicMatch.objects.filter(topic=topic).delete()
            CustomTopicMatch.objects.bulk_create(rows)
        out[topic.label] = len(rows)
        logger.info("[custom-topics] %r -> %d matches (th=%.2f)", topic.label, len(rows), th)
    return out
