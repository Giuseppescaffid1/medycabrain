"""
core/knowledge.py
=================
Retrieval over the Medyca knowledge bank — the "second brain" (MEDYC-10)
and the interface downstream agents use (MEDYC-13).

The knowledge bank has two content types:
  - KnowledgeDocument  (blog articles from medyca.it)
  - OWNED Reels        (owner_type='owned', e.g. @medyca.menopausa) — their
                        transcripts + captions

`semantic_search` embeds a query and cosine-ranks it against both sources,
returning unified hits with a snippet + score. `answer` layers an LLM on
top (RAG) to produce a grounded Italian answer with citations — the call
an agent makes to "write copy / an article / find content gaps" from
Medyca's own material.
"""

from __future__ import annotations

import numpy as np

from django.conf import settings

from core.models import DONE, KnowledgeDocument, Reel
from llm import client

_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(settings.EMBEDDINGS_MODEL)
    return _embedder


def _embed_query(text: str) -> np.ndarray:
    v = _get_embedder().encode([text], normalize_embeddings=True, show_progress_bar=False)[0]
    return np.asarray(v, dtype=np.float32)


def _load_index() -> list[dict]:
    """Gather all embedded knowledge-bank items into a flat list."""
    items = []
    for d in KnowledgeDocument.objects.filter(is_active=True).exclude(embedding=[]):
        items.append({
            "kind": "blog",
            "id": d.id,
            "title": d.title,
            "url": d.source_url,
            "summary": d.summary_it,
            "text": d.content_text,
            "topics": d.topics,
            "vec": np.asarray(d.embedding, dtype=np.float32),
        })
    # Owned reels (their own content), if scraped + embedded
    owned = (
        Reel.objects.filter(account__owner_type="owned", is_active=True,
                            enrich_status=DONE)
        .exclude(embedding__isnull=True)
        .select_related("account", "enrichment", "transcript", "embedding")
    )
    for r in owned:
        emb = getattr(r, "embedding", None)
        if not emb or not emb.vector:
            continue
        enr = getattr(r, "enrichment", None)
        tr = getattr(r, "transcript", None)
        items.append({
            "kind": "reel",
            "id": r.id,
            "title": (enr.summary_it if enr else "") or r.caption[:80],
            "url": f"https://www.instagram.com/reel/{r.shortcode}/",
            "summary": enr.summary_it if enr else "",
            "text": (tr.text if tr else "") or r.caption,
            "topics": enr.topics if enr else [],
            "vec": np.asarray(emb.vector, dtype=np.float32),
        })
    return items


def _snippet(text: str, n: int = 320) -> str:
    text = " ".join((text or "").split())
    return text[:n] + ("…" if len(text) > n else "")


def semantic_search(query: str, top_k: int = 6) -> list[dict]:
    """Return the top_k knowledge-bank items most relevant to the query."""
    index = _load_index()
    if not index:
        return []
    q = _embed_query(query)
    mat = np.vstack([it["vec"] for it in index])
    scores = mat @ q  # vectors are normalized → cosine similarity
    order = np.argsort(-scores)[:top_k]
    out = []
    for i in order:
        it = index[int(i)]
        out.append({
            "kind": it["kind"], "id": it["id"], "title": it["title"],
            "url": it["url"], "summary": it["summary"], "topics": it["topics"],
            "snippet": _snippet(it["text"]),
            "score": round(float(scores[int(i)]), 3),
        })
    return out


ANSWER_SYSTEM = (
    "Sei l'assistente della knowledge bank di Medyca (terapie ormonali "
    "bioidentiche, menopausa, salute femminile). Rispondi in italiano, in modo "
    "chiaro e professionale, usando ESCLUSIVAMENTE le fonti fornite. Se le fonti "
    "non contengono la risposta, dillo. Cita le fonti pertinenti con [n]."
)
ANSWER_USER = """\
DOMANDA:
{query}

FONTI:
{sources}

Istruzioni: rispondi alla domanda basandoti SOLO sulle fonti, citando con [n].
Scrivi la risposta ESCLUSIVAMENTE in lingua italiana."""


def answer(query: str, top_k: int = 6) -> dict:
    """RAG: retrieve from the knowledge bank + generate a grounded answer."""
    hits = semantic_search(query, top_k=top_k)
    if not hits:
        return {"answer": "La knowledge bank è ancora vuota o non indicizzata.",
                "sources": []}
    sources_txt = "\n\n".join(
        f"[{i+1}] {h['title']}\n{h['summary'] or h['snippet']}"
        for i, h in enumerate(hits)
    )
    if not client.available():
        return {"answer": "(LLM non disponibile — mostro solo le fonti recuperate.)",
                "sources": hits}
    try:
        text = client.chat(
            ANSWER_SYSTEM,
            ANSWER_USER.format(query=query, sources=sources_txt),
            max_tokens=500, temperature=0.2,
        )
    except Exception as exc:  # noqa: BLE001
        text = f"(Errore nella generazione: {exc!r})"
    return {"answer": text.strip(), "sources": hits}
