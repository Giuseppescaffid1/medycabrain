"""
pipeline/agents/knowledge_agent.py
==================================
Enriches + embeds blog articles — Medyca's own AND the competitors'.

Parity with the reel pipeline, where it makes sense: the same deep-reading
model (`model_for("analysis")`), a primary_topic under the same rule (the
one specific subject, never an umbrella term), an on-topic verdict, and
claim extraction with the same grounding contract — every claim carries a
verbatim quote from the article or it is not stored.

What deliberately differs from reels: no hook and no content_format — those
describe a video's craft, not an article's.

Language: bodies are never translated. Summaries and topics come out Italian
regardless of the source language, because Italian topic strings are what
clustering and custom-topic matching compare across sources. For non-Italian
documents the embedding uses ONLY the Italian material the model produced —
an English body mixed into the vector makes English docs cluster with each
other instead of by subject.

Failures stay FAILED. The old blanket FAILED→PENDING reset at the end of
every run was an infinite retry loop that also hid the failure; retry is now
an explicit act (reprocess --stage knowledge).
"""

from __future__ import annotations

import logging

from django.conf import settings

from core.models import DONE, FAILED, PENDING, DocumentArgument, KnowledgeDocument
from llm import client, prompts

logger = logging.getLogger(__name__)

KB_SYSTEM = (
    "Sei un analista di contenuti medici in lingua italiana, specializzato in "
    "menopausa, terapie ormonali e salute femminile. Analizzi articoli di blog "
    "di diversi autori: alcuni sono di Medyca, altri di concorrenti. "
    "Rispondi SEMPRE ed esclusivamente con un oggetto JSON valido."
)

KB_ENRICH_USER = """\
Analizza questo articolo del blog di {source_name}{ownership}.

TITOLO: {title}

TESTO:
{text}

Il testo può essere in un'altra lingua: analizza comunque IN ITALIANO.

Restituisci un JSON:
{{
  "summary_it": "riassunto in 2-3 frasi, in italiano",
  "topics": ["4-8 argomenti/parole chiave in italiano, minuscolo"],
  "primary_topic": "IL soggetto specifico dell'articolo, 2-5 parole. Mai un termine ombrello come 'menopausa' o 'salute femminile': ciò che distingue QUESTO articolo dagli altri",
  "is_on_topic": true,
  "off_topic_reason": "se is_on_topic è false: perché (es. ricetta di cucina, pagina promozionale)"
}}
"""


def _embedder():
    from pipeline.agents import cluster_agent
    return cluster_agent._get_embedder()


def _enrich_one(doc: KnowledgeDocument) -> None:
    from pipeline.agents.enrich_agent import canonical_topic, pick_primary_topic

    who = doc.source.name if doc.source else "Medyca"
    ownership = (" (un CONCORRENTE di Medyca)" if doc.owner_type == "competitor"
                 else " (il blog di Medyca stessa)")
    user = KB_ENRICH_USER.format(source_name=who, ownership=ownership,
                                 title=doc.title,
                                 text=(doc.content_text or "")[:6000])
    data = client.chat_json(KB_SYSTEM, user, max_tokens=600,
                            # The same deep-reading tier the reels get: what
                            # an article claims and how specific its subject
                            # is decide the whole thematic layer above it.
                            model=client.model_for("analysis"))
    topics = data.get("topics") or []
    if isinstance(topics, str):
        topics = [t.strip() for t in topics.split(",") if t.strip()]
    topics = [canonical_topic(str(t))[:60] for t in topics][:8]
    doc.summary_it = str(data.get("summary_it", ""))[:2000]
    doc.topics = topics
    doc.primary_topic = pick_primary_topic(
        str(data.get("primary_topic", "")), topics)[:80]
    doc.is_on_topic = bool(data.get("is_on_topic", True))
    doc.off_topic_reason = str(data.get("off_topic_reason") or "")[:300] \
        if not doc.is_on_topic else ""
    doc.enrich_status = DONE
    doc.last_error = ""
    doc.save(update_fields=["summary_it", "topics", "primary_topic",
                            "is_on_topic", "off_topic_reason",
                            "enrich_status", "last_error"])


def _extract_arguments(doc: KnowledgeDocument) -> int:
    """Grounded claims from the article, same contract as reels: the quote
    must appear verbatim in the text or the claim is dropped."""
    from pipeline.agents.enrich_agent import _norm

    text = (doc.content_text or "")[:8000]
    if len(text.strip()) < 200:
        return 0
    user = prompts.ARGUMENTS_USER_TEMPLATE.format(transcript=text, caption="")
    data = client.chat_json(prompts.ARGUMENTS_SYSTEM, user, max_tokens=600,
                            model=client.model_for("analysis"))
    rows = data.get("argomenti") or []
    doc.arguments.all().delete()  # idempotent re-extraction
    haystack = _norm(text)
    created = dropped = 0
    for row in rows[:6]:
        claim = str(row.get("testo") or "").strip()
        quote = str(row.get("citazione") or "").strip()
        if not claim or not quote:
            continue
        needle = _norm(quote)
        if len(needle) < 12 or needle not in haystack:
            dropped += 1
            continue
        DocumentArgument.objects.create(document=doc, text_it=claim[:1000],
                                        quote=quote[:1000])
        created += 1
    if dropped:
        logger.info("[knowledge] %s: %d affermazioni scartate (citazione non trovata)",
                    doc.source_url, dropped)
    return created


def _embed_one(doc: KnowledgeDocument) -> None:
    base = f"{doc.title}\n{doc.summary_it}\n{' '.join(doc.topics)}"
    if doc.language and doc.language != "it":
        # Only the Italian material the model produced: mixing an English
        # body into a multilingual vector makes English docs cluster with
        # each other rather than by subject.
        text = base
    else:
        text = f"{base}\n{doc.content_text[:1500]}"
    vec = _embedder().encode([text], normalize_embeddings=True,
                             show_progress_bar=False)[0]
    doc.embedding = vec.tolist()
    doc.embedding_model = settings.EMBEDDINGS_MODEL
    doc.embed_status = DONE
    doc.save(update_fields=["embedding", "embedding_model", "embed_status"])


def run(ctx) -> dict:
    from pipeline.agents.enrich_agent import _parallel

    enriched = enrich_failed = embedded = embed_failed = 0
    arg_docs = total_args = arg_failed = 0

    if client.available():
        qs = KnowledgeDocument.objects.filter(
            enrich_status=PENDING, is_active=True).select_related("source")
        if ctx.limit:
            qs = qs[: ctx.limit]
        # The cost of a document is the model's reading time, not CPU:
        # the reel stage's thread pool applies unchanged.
        for doc, _res, exc in _parallel(list(qs), _enrich_one):
            if exc is None:
                enriched += 1
            else:
                doc.enrich_status = FAILED
                doc.last_error = repr(exc)[:500]
                doc.save(update_fields=["enrich_status", "last_error"])
                enrich_failed += 1
                logger.warning("[knowledge] enrich failed %s: %r", doc.source_url, exc)

        qs_a = KnowledgeDocument.objects.filter(
            argument_status=PENDING, enrich_status=DONE, is_active=True)
        if ctx.limit:
            qs_a = qs_a[: ctx.limit]
        for doc, n, exc in _parallel(list(qs_a), _extract_arguments):
            if exc is None:
                doc.argument_status = DONE
                doc.save(update_fields=["argument_status"])
                arg_docs += 1
                total_args += n or 0
            else:
                doc.argument_status = FAILED
                doc.last_error = repr(exc)[:500]
                doc.save(update_fields=["argument_status", "last_error"])
                arg_failed += 1
                logger.warning("[knowledge] arguments failed %s: %r",
                               doc.source_url, exc)

    # Embedding needs no LLM; embed anything enriched (or at least fetched).
    qs2 = KnowledgeDocument.objects.filter(
        embed_status=PENDING, is_active=True).exclude(content_text="")
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

    # NOTE: failures stay FAILED, per project rule. The blanket reset that
    # used to live here re-queued every permanently broken doc on every run —
    # an infinite retry that also hid the failure from every status page.
    return {"enriched": enriched, "enrich_failed": enrich_failed,
            "arg_docs": arg_docs, "arguments": total_args,
            "arg_failed": arg_failed,
            "embedded": embedded, "embed_failed": embed_failed}
