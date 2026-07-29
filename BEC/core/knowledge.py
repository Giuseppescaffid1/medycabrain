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

import re

import numpy as np

from django.conf import settings

from django.db.models import Count

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


_INDEX_CACHE: dict = {}


def _corpus_stamp() -> tuple:
    """Cheap fingerprint of the indexed corpus.

    Two counts and the newest embedding: enough to notice the pipeline
    adding, re-embedding or deactivating anything, without reading 900 rows
    on every question just to discover nothing changed.
    """
    from django.db.models import Max

    from core.models import ReelEmbedding

    agg = ReelEmbedding.objects.aggregate(n=Count("id"), last=Max("created_at"))
    return (agg["n"], agg["last"],
            KnowledgeDocument.objects.filter(is_active=True).count(),
            Reel.objects.filter(is_active=True, enrich_status=DONE).count())


def _load_index(scope: str = "all") -> list[dict]:
    """Every embedded item the chat can answer from.

    `scope`: "medyca" (own content only), "competitor", or "all". Competitor
    reels carry their account, because "who said this" is half the answer when
    the client compares themselves to the market.
    """
    stamp = _corpus_stamp()
    hit = _INDEX_CACHE.get(scope)
    if hit and hit[0] == stamp:
        return hit[1]

    items = []
    want_owned = scope in ("all", "medyca", "owned")
    want_comp = scope in ("all", "competitor")
    if want_owned:
        for d in KnowledgeDocument.objects.filter(is_active=True).exclude(embedding=[]):
            items.append({
                "kind": "blog", "owner": "owned", "id": d.id, "title": d.title,
                "url": d.source_url, "summary": d.summary_it,
                "text": d.content_text, "topics": d.topics,
                "vec": np.asarray(d.embedding, dtype=np.float32),
                "chunks": d.chunk_vectors or None,
            })
    owners = ([] if not want_owned else ["owned"]) + ([] if not want_comp else ["competitor"])
    reels = (
        Reel.objects.filter(account__owner_type__in=owners, is_active=True,
                            enrich_status=DONE)
        .exclude(embedding__isnull=True)
        .select_related("account", "enrichment", "transcript", "embedding")
    )
    for r in reels:
        emb = getattr(r, "embedding", None)
        if not emb or not emb.vector:
            continue
        enr = getattr(r, "enrichment", None)
        tr = getattr(r, "transcript", None)
        # A reel whose video was never downloaded and that has no caption is
        # marked enriched (evidence='insufficient') and still gets a vector —
        # of the empty string, which sits at a fixed point close to everything.
        # Ten of those scored 0.84 on "Bijuva", taking the top three places
        # ahead of the reel actually called "bijuva pro e contro". A source
        # with nothing in it cannot answer anything: keep it out.
        if not ((tr.text if tr else "") or r.caption or
                (enr.summary_it if enr else "")).strip():
            continue
        items.append({
            "kind": "reel",
            "owner": r.account.owner_type,
            "id": r.id,
            "title": (enr.primary_topic if enr else "") or (enr.summary_it if enr else "") or r.caption[:80],
            "url": f"https://www.instagram.com/reel/{r.shortcode}/",
            "summary": (enr.summary_it if enr else ""),
            "account": r.account.username,
            "text": (tr.text if tr else "") or r.caption,
            "topics": enr.topics if enr else [],
            "vec": np.asarray(emb.vector, dtype=np.float32),
            "chunks": emb.chunk_vectors or None,
        })
    _INDEX_CACHE[scope] = (stamp, items)
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


# Medyca's own material is 70 items against 835 competitor ones. On one global
# ranking those odds decide the outcome: measured, the first Medyca result for
# "Bijuva" landed 27th, for "perimenopausa" 66th, for "cosa manca ai nostri
# contenuti" 99th — so the chat, asked to compare, truthfully reported having no
# Medyca material and looked disconnected from its own knowledge bank.
#
# The two sides are therefore ranked separately and merged. This is a deliberate
# trade: a guaranteed slot sometimes shows a Medyca item less relevant than the
# competitor it displaced. That is the point of a comparison tool — but only up
# to a point, hence the floor below.
# Expressed as a share, not a count, so the balance survives a smaller top_k —
# which is exactly what happens when a pasted page takes some of the slots.
# Trimming a merged list instead would silently undo the quota: the leftovers
# are re-sorted by score, and on score the competitors win again.
OWNED_SHARE = 5 / 12

# Each side is filtered against its OWN best, not against the global best.
#
# Two reasons. An absolute cutoff does not work: on the nonsense query "ricetta
# della pasta al forno" the best competitor still scored 0.50, because
# similarity values in this space are compressed. And a global reference is
# quietly unfair — the maximum of 835 samples runs higher than the maximum of
# 70 by sample size alone, so measuring Medyca against the competitors' best
# penalises it for being the smaller corpus, which is the very bias this whole
# change exists to remove. It showed up immediately: "cosa manca ai nostri
# contenuti" returned zero Medyca sources, on the one question that is entirely
# about Medyca's own material.
#
# Within a side, 60% of that side's best keeps the real match for "Bijuva"
# (0.40 of 0.40) and drops the padding ("donna", 0.21).
RELEVANCE_FLOOR = 0.60


def _rank(index: list[dict], query: str, qvec) -> list[tuple[float, dict, float]]:
    if not index:
        return []
    mat = np.vstack([it["vec"] for it in index])
    dense = mat @ qvec  # normalized vectors → cosine
    out = []
    for i, it in enumerate(index):
        lex = _lexical_score(query, f"{it['title']} {it['summary']} {it['text']}")
        out.append((0.75 * float(dense[i]) + 0.25 * lex, it, lex))
    out.sort(key=lambda r: -r[0])
    return out


def semantic_search(query: str, top_k: int = 6, scope: str = "all") -> list[dict]:
    """Hybrid retrieval over the knowledge bank.

    Documents are ranked by embedding similarity blended with verbatim
    keyword evidence; the winning passage inside each document is then
    selected so the generator receives the text that answers the question,
    not the opening lines of the article.

    Under scope "all" the two sides are ranked separately and merged, so
    Medyca's own material is present whenever it has something to say.
    """
    index = _load_index(scope)
    if not index:
        return []
    q = _embed_query(query)

    if scope in ("all",):
        owned = _rank([i for i in index if i.get("owner") != "competitor"], query, q)
        comp = _rank([i for i in index if i.get("owner") == "competitor"], query, q)

        def _keep(ranked, slots):
            # Padding a quota with weak matches is another way of answering
            # badly, so a slot the side cannot fill well is left to the other.
            if not ranked:
                return []
            floor = ranked[0][0] * RELEVANCE_FLOOR
            return [r for r in ranked[:slots] if r[0] >= floor]

        owned_slots = max(1, round(top_k * OWNED_SHARE))
        take_owned = _keep(owned, owned_slots)
        take_comp = _keep(comp, top_k - owned_slots)
        spare = top_k - len(take_owned) - len(take_comp)
        if spare > 0:
            seen = {id(r[1]) for r in take_owned + take_comp}
            rest = sorted((r for r in owned + comp if id(r[1]) not in seen),
                          key=lambda r: -r[0])
            take_comp += rest[:spare]
        scored = sorted(take_owned + take_comp, key=lambda r: -r[0])
    else:
        scored = _rank(index, query, q)

    out = []
    for score, it, lex in scored[:top_k]:
        passage = (_best_passage(it["text"] or it["summary"], q, it.get("chunks"))
                   or _snippet(it["text"]))
        out.append({
            "kind": it["kind"], "owner": it.get("owner", "owned"),
            "account": it.get("account", ""),
            "id": it["id"], "title": it["title"],
            "url": it["url"], "summary": it["summary"], "topics": it["topics"],
            "snippet": passage,
            "score": round(float(score), 3),
            "keyword_match": round(lex, 2),
        })
    return out


def _best_passage(text: str, qvec, cached=None) -> str:
    """The chunk of `text` closest to the query vector.

    `cached` are the passage vectors computed once by the embed stage, in the
    order _chunks produces them. Encoding them per question instead cost
    15-18s — the whole of the chat's latency — so they are only computed here
    when a document predates the change or its text moved on since.
    """
    parts = _chunks(text)
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if cached is not None and len(cached) == len(parts):
        vecs = np.asarray(cached, dtype=np.float32)
    else:
        vecs = np.asarray(
            _get_embedder().encode(parts, normalize_embeddings=True,
                                   show_progress_bar=False),
            dtype=np.float32,
        )
    sims = vecs @ qvec
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
    "- Se le fonti si contraddicono, segnalalo invece di sceglierne una.\n"
    "- Ogni fonte indica se \u00e8 di Medyca o di un COMPETITOR: distinguilo "
    "sempre nella risposta. Confondere ci\u00f2 che dice Medyca con ci\u00f2 che dicono "
    "gli altri \u00e8 l'errore peggiore che puoi fare qui.\n"
    "- Una fonte marcata RIFERIMENTO ESTERNO \u00e8 una pagina che l'utente ti ha "
    "indicato in questa conversazione: non fa parte della knowledge bank e non "
    "\u00e8 materiale di Medyca. Serve per il confronto. Quando \u00e8 presente, dì "
    "esplicitamente cosa il riferimento tratta e il materiale di Medyca no: "
    "\u00e8 questa la risposta utile, non il riassunto della pagina.\n"
    "- Le fonti sono una SELEZIONE per questa domanda, non l'inventario della "
    "knowledge bank. Se fra le fonti non c'\u00e8 materiale di Medyca, scrivi che "
    "non \u00e8 emerso nulla di Medyca su questo punto \u2014 NON che Medyca non ha "
    "pubblicato nulla in merito. Sono due affermazioni diverse e la seconda "
    "non la puoi sapere.\n\n"
    "FORMATO: usa markdown \u2014 grassetto per i punti chiave, elenchi puntati, "
    "tabelle dove servono. Niente titoli di primo livello (#): la risposta vive "
    "gi\u00e0 dentro una scheda. Vai al punto: chi legge \u00e8 una professionista."
)
ANSWER_USER = """\
DOMANDA:
{query}

{inventory}
FONTI SELEZIONATE per questa domanda, raggruppate per origine:
{sources}

Rispondi alla domanda basandoti SOLO sulle fonti, citando con [n].
Chiudi con una riga "Copertura:" che dice se le fonti coprono la domanda
in modo completo, parziale o nullo.
Scrivi ESCLUSIVAMENTE in lingua italiana."""


MAX_REFERENCES = 3


def _reference_hits(urls: list[str], qvec, per_ref: int = 3) -> tuple[list[dict], list[dict]]:
    """Read the pages the user pasted, and pull the passages that match.

    Returns (hits, problems). A page that cannot be read is reported rather
    than dropped: silently answering from Medyca's material alone, when the
    user asked for a comparison, looks like an answer and is not one.
    """
    from core.external_ref import RefusedURL, fetch_reference

    hits, problems = [], []
    for url in urls[:MAX_REFERENCES]:
        try:
            ref = fetch_reference(url)
        except RefusedURL as exc:
            problems.append({"url": url, "error": str(exc)})
            continue
        except Exception as exc:  # noqa: BLE001 — a bad page must not break the chat
            problems.append({"url": url, "error": f"Non raggiungibile ({type(exc).__name__})."})
            continue
        parts = _chunks(ref["text"])
        if not parts:
            continue
        vecs = np.asarray(
            _get_embedder().encode(parts, normalize_embeddings=True,
                                   show_progress_bar=False),
            dtype=np.float32,
        )
        sims = vecs @ qvec
        for i in np.argsort(-sims)[:per_ref]:
            hits.append({
                "kind": "reference", "owner": "external", "account": "",
                "id": f"{url}#{int(i)}", "title": ref["title"], "url": url,
                "summary": "", "topics": [], "snippet": parts[int(i)],
                "score": round(float(sims[int(i)]), 3), "keyword_match": 0.0,
            })
    return hits, problems


def _inventory_line() -> str:
    """What the knowledge bank actually holds, told to the model.

    Without it the model can only see the handful of sources it was handed,
    and when none of them are Medyca's it concludes Medyca has published
    nothing — which is what the client read, and what made the chat look
    disconnected from its own data.
    """
    index = _load_index("all")
    reels = sum(1 for i in index if i["kind"] == "reel" and i.get("owner") != "competitor")
    blog = sum(1 for i in index if i["kind"] == "blog")
    comp = sum(1 for i in index if i.get("owner") == "competitor")
    return (f"LA KNOWLEDGE BANK CONTIENE: {reels} reel di Medyca, {blog} articoli "
            f"del blog Medyca, {comp} reel dei competitor.\n")


_GROUPS = (
    ("external", "RIFERIMENTI ESTERNI indicati dall'utente (non sono materiale Medyca)"),
    ("owned", "MATERIALE DI MEDYCA"),
    ("competitor", "MATERIALE DEI COMPETITOR"),
)


def _sources_block(hits: list[dict]) -> str:
    """The sources, grouped by whose they are.

    A flat list let the model lose track of which side a passage came from —
    the one confusion this screen must never make.
    """
    numbered = {id(h): i + 1 for i, h in enumerate(hits)}
    blocks = []
    for key, heading in _GROUPS:
        group = [h for h in hits
                 if (h.get("owner") if h.get("owner") in ("external", "competitor")
                     else "owned") == key]
        if not group:
            continue
        lines = []
        for h in group:
            what = "articolo blog" if h["kind"] == "blog" else "reel"
            who = f" @{h['account']}" if h.get("account") else ""
            lines.append(f"[{numbered[id(h)]}] {h['title']} ({what}{who})\n{h['snippet']}")
        blocks.append(f"### {heading}\n" + "\n\n".join(lines))
    if not any(h.get("owner") not in ("external", "competitor") for h in hits):
        blocks.append("### MATERIALE DI MEDYCA\n(nessuna fonte di Medyca è emersa "
                      "per questa domanda)")
    return "\n\n".join(blocks)


def _prepare(query: str, top_k: int, scope: str,
             history: list | None, references: list[str] | None) -> dict:
    """Everything that happens before the model speaks.

    Shared by `answer` and `answer_stream` so the prompt cannot drift between
    the blocking and the streaming path and produce two different styles of
    answer depending on which endpoint was called.
    """
    ref_hits, ref_problems = [], []
    if references:
        ref_hits, ref_problems = _reference_hits(references, _embed_query(query))
    # The pasted page leads — it is the thing being asked about — but it must
    # not push the internal material out of the context in exactly the
    # comparison it was needed for. So the retrieval budget is reduced FIRST
    # and the quota applied to what remains, rather than trimming afterwards.
    budget = max(top_k - len(ref_hits), top_k // 2) if ref_hits else top_k
    hits = ref_hits + semantic_search(query, top_k=budget, scope=scope)

    convo = ""
    for turn in (history or [])[-6:]:
        role = "UTENTE" if turn.get("role") == "user" else "ASSISTENTE"
        convo += f"{role}: {str(turn.get('content', ''))[:500]}\n"
    if convo:
        convo = f"CONVERSAZIONE FINORA:\n{convo}\n"

    return {
        "hits": hits,
        "ref_problems": ref_problems,
        "system": ANSWER_SYSTEM,
        "user": convo + ANSWER_USER.format(
            query=query, inventory=_inventory_line(),
            sources=_sources_block(hits)),
    }


def _mark_cited(text: str, hits: list[dict]) -> None:
    """Flag the sources the answer actually leaned on."""
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", text or "")}
    for i, h in enumerate(hits, start=1):
        h["cited"] = i in cited


def answer(query: str, top_k: int = 8, scope: str = "all",
           history: list | None = None,
           references: list[str] | None = None) -> dict:
    """RAG over the knowledge bank.

    Retrieval is hybrid (embeddings + verbatim keywords) and sends the
    passage that matches, not the head of the document. Generation runs on
    the reasoning model — the same one that analyses transcripts — because
    reading several sources and refusing to over-claim is judgement work.
    """
    p = _prepare(query, top_k, scope, history, references)
    hits = p["hits"]
    if not hits:
        return {"answer": "La knowledge bank è ancora vuota o non indicizzata.",
                "sources": [], "model": "", "reference_problems": p["ref_problems"]}
    if not client.available():
        return {"answer": "(LLM non disponibile — mostro solo le fonti recuperate.)",
                "sources": hits, "model": "",
                "reference_problems": p["ref_problems"]}
    try:
        text = client.chat(
            p["system"], p["user"],
            max_tokens=900, temperature=0.2, priority=True, timeout=600,
            # Deliberately the reasoning tier, not the analysis one: the chat
            # answers many questions a day and does not need the deepest model.
            model=client.model_for("reasoning"),
        )
        used = client.last_model_used()
    except Exception as exc:  # noqa: BLE001
        text, used = f"(Errore nella generazione: {exc!r})", ""
    _mark_cited(text, hits)
    return {"answer": (text or "").strip(), "sources": hits, "model": used,
            "reference_problems": p["ref_problems"]}
