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


def _chunks(text: str, size: int = 700, overlap: int = 120) -> list[str]:
    """Split a document into overlapping passages.

    Sending a summary to the model is not retrieval: the answer usually lives
    in one paragraph in the middle of a transcript. Chunking lets us send the
    passage that actually contains it.
    """
    text = " ".join((text or "").split())
    if len(text) <= size:
        return [text] if text else []
    out, start = [], 0
    while start < len(text):
        out.append(text[start:start + size])
        start += size - overlap
    return out


def _lexical_score(query: str, text: str) -> float:
    """Fraction of the query's distinctive words that appear verbatim.

    Embeddings miss rare tokens — drug and brand names like "Bijuva" are
    exactly what a client asks about, so keyword evidence is blended in.
    """
    import re
    import unicodedata
    norm = lambda t: unicodedata.normalize("NFKC", t or "").lower()
    words = [w for w in re.findall(r"\w+", norm(query)) if len(w) >= 5]
    if not words:
        return 0.0
    hay = norm(text)
    return sum(1 for w in words if w in hay) / len(words)


def semantic_search(query: str, top_k: int = 6) -> list[dict]:
    """Hybrid retrieval over the knowledge bank.

    Documents are ranked by embedding similarity blended with verbatim
    keyword evidence; the winning passage inside each document is then
    selected so the generator receives the text that answers the question,
    not the opening lines of the article.
    """
    index = _load_index()
    if not index:
        return []
    q = _embed_query(query)
    mat = np.vstack([it["vec"] for it in index])
    dense = mat @ q  # normalized vectors → cosine

    scored = []
    for i, it in enumerate(index):
        lex = _lexical_score(query, f"{it['title']} {it['summary']} {it['text']}")
        scored.append((0.75 * float(dense[i]) + 0.25 * lex, i, lex))
    scored.sort(reverse=True)

    out = []
    for score, i, lex in scored[:top_k]:
        it = index[i]
        passage = _best_passage(it["text"] or it["summary"], q) or _snippet(it["text"])
        out.append({
            "kind": it["kind"], "id": it["id"], "title": it["title"],
            "url": it["url"], "summary": it["summary"], "topics": it["topics"],
            "snippet": passage,
            "score": round(float(score), 3),
            "keyword_match": round(lex, 2),
        })
    return out


def _best_passage(text: str, qvec) -> str:
    """The chunk of `text` closest to the query vector."""
    parts = _chunks(text)
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    vecs = _get_embedder().encode(parts, normalize_embeddings=True, show_progress_bar=False)
    sims = np.asarray(vecs, dtype=np.float32) @ qvec
    return parts[int(np.argmax(sims))]


ANSWER_SYSTEM = (
    "Sei l'assistente della knowledge bank di Medyca (terapie ormonali "
    "bioidentiche, menopausa, salute femminile). Parli a una professionista "
    "del settore: rispondi in italiano, in modo chiaro e concreto.\n\n"
    "REGOLE NON NEGOZIABILI:\n"
    "- Usa ESCLUSIVAMENTE le fonti fornite. Non aggiungere conoscenza medica "
    "esterna, nemmeno se corretta: questa knowledge bank serve a sapere cosa "
    "Medyca ha detto, non cosa è vero in generale.\n"
    "- Cita ogni affermazione con [n]. Un'affermazione senza citazione è un "
    "errore.\n"
    "- Se le fonti non rispondono, dillo apertamente e indica cosa manca. "
    "Una risposta mancante è preferibile a una inventata.\n"
    "- Se le fonti si contraddicono, segnalalo invece di sceglierne una."
)
ANSWER_USER = """\
DOMANDA:
{query}

FONTI (estratti selezionati dai contenuti di Medyca):
{sources}

Rispondi alla domanda basandoti SOLO sulle fonti, citando con [n].
Chiudi con una riga "Copertura:" che dice se le fonti coprono la domanda
in modo completo, parziale o nullo.
Scrivi ESCLUSIVAMENTE in lingua italiana."""


def answer(query: str, top_k: int = 8) -> dict:
    """RAG over the knowledge bank.

    Retrieval is hybrid (embeddings + verbatim keywords) and sends the
    passage that matches, not the head of the document. Generation runs on
    the reasoning model — the same one that analyses transcripts — because
    reading several sources and refusing to over-claim is judgement work.
    """
    hits = semantic_search(query, top_k=top_k)
    if not hits:
        return {"answer": "La knowledge bank è ancora vuota o non indicizzata.",
                "sources": [], "model": ""}
    sources_txt = "\n\n".join(
        f"[{i+1}] {h['title']} ({'articolo blog' if h['kind'] == 'blog' else 'reel'})\n"
        f"{h['snippet']}"
        for i, h in enumerate(hits)
    )
    if not client.available():
        return {"answer": "(LLM non disponibile — mostro solo le fonti recuperate.)",
                "sources": hits, "model": ""}
    try:
        text = client.chat(
            ANSWER_SYSTEM,
            ANSWER_USER.format(query=query, sources=sources_txt),
            max_tokens=900, temperature=0.2, priority=True, timeout=600,
            model=client.model_for("analysis"),
        )
        used = client.last_model_used()
    except Exception as exc:  # noqa: BLE001
        text, used = f"(Errore nella generazione: {exc!r})", ""
    # Surface which sources the answer actually leaned on.
    import re
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", text or "")}
    for i, h in enumerate(hits, start=1):
        h["cited"] = i in cited
    return {"answer": (text or "").strip(), "sources": hits, "model": used}
