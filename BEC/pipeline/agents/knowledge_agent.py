"""
pipeline/agents/knowledge_agent.py
==================================
Enriches + embeds the Medyca knowledge bank (MEDYC-10).

The knowledge bank = OWNED reels (owner_type='owned', already enriched by
the reel pipeline) + KnowledgeDocuments (blog articles). This agent brings
the blog docs to parity: an Italian summary + topics via the LLM, and a
local embedding for semantic search / the second-brain retrieval.
"""

from __future__ import annotations

import logging

from django.conf import settings

from core.models import DONE, FAILED, PENDING, KnowledgeDocument
from llm import client

logger = logging.getLogger(__name__)

KB_SUMMARY_SYSTEM = (
    "Sei un analista di contenuti medici in lingua italiana per Medyca "
    "(terapie ormonali bioidentiche, menopausa, salute femminile). "
    "Rispondi SEMPRE ed esclusivamente con un oggetto JSON valido."
)
KB_SUMMARY_USER = """\
Analizza questo articolo del blog Medyca.

TITOLO: {title}

TESTO:
{text}

Restituisci un JSON:
{{
  "summary_it": "riassunto in 2-3 frasi, in italiano",
  "topics": ["4-8 argomenti/parole chiave in italiano, minuscolo"]
}}
"""


def _embedder():
    from pipeline.agents import cluster_agent
    return cluster_agent._get_embedder()


def _enrich_one(doc: KnowledgeDocument) -> None:
    user = KB_SUMMARY_USER.format(title=doc.title, text=(doc.content_text or "")[:6000])
    data = client.chat_json(KB_SUMMARY_SYSTEM, user, max_tokens=500)
    topics = data.get("topics") or []
    if isinstance(topics, str):
        topics = [t.strip() for t in topics.split(",") if t.strip()]
    doc.summary_it = str(data.get("summary_it", ""))[:2000]
    doc.topics = [str(t).lower()[:60] for t in topics][:8]
    doc.enrich_status = DONE
    doc.last_error = ""
    doc.save(update_fields=["summary_it", "topics", "enrich_status", "last_error"])


def _embed_one(doc: KnowledgeDocument) -> None:
    text = f"{doc.title}\n{doc.summary_it}\n{' '.join(doc.topics)}\n{doc.content_text[:1500]}"
    vec = _embedder().encode([text], normalize_embeddings=True, show_progress_bar=False)[0]
    doc.embedding = vec.tolist()
    doc.embedding_model = settings.EMBEDDINGS_MODEL
    doc.embed_status = DONE
    doc.save(update_fields=["embedding", "embedding_model", "embed_status"])


def run(ctx) -> dict:
    enriched = enrich_failed = embedded = embed_failed = 0

    if client.available():
        qs = KnowledgeDocument.objects.filter(enrich_status=PENDING, is_active=True)
        if ctx.limit:
            qs = qs[: ctx.limit]
        for doc in qs:
            try:
                _enrich_one(doc)
                enriched += 1
            except Exception as exc:  # noqa: BLE001
                doc.enrich_status = FAILED
                doc.last_error = repr(exc)[:500]
                doc.save(update_fields=["enrich_status", "last_error"])
                enrich_failed += 1
                logger.warning("[knowledge] enrich failed %s: %r", doc.source_url, exc)

    # Embedding needs no LLM; embed anything enriched (or at least fetched).
    qs2 = KnowledgeDocument.objects.filter(embed_status=PENDING, is_active=True).exclude(content_text="")
    if ctx.limit:
        qs2 = qs2[: ctx.limit]
    for doc in qs2:
        try:
            _embed_one(doc)
            embedded += 1
        except Exception as exc:  # noqa: BLE001
            doc.embed_status = FAILED
            doc.last_error = repr(exc)[:500]
            doc.save(update_fields=["embed_status", "last_error"])
            embed_failed += 1
            logger.warning("[knowledge] embed failed %s: %r", doc.source_url, exc)

    KnowledgeDocument.objects.filter(enrich_status=FAILED).update(enrich_status=PENDING)
    KnowledgeDocument.objects.filter(embed_status=FAILED).update(embed_status=PENDING)
    return {"enriched": enriched, "enrich_failed": enrich_failed,
            "embedded": embedded, "embed_failed": embed_failed}
