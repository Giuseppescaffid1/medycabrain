"""
core/blog_workflow.py
=====================
Cluster-driven blog workflow (Alberto's headline feedback).

For a Medyca theme cluster (which now spans reels + blog articles):
  - if the cluster ALREADY has a blog article → 'expand': list what the
    reels in the cluster cover that the existing article doesn't yet, and
    suggest concrete additions.
  - if the cluster has NO blog article → 'draft': write a new article draft
    grounded ONLY in the cluster's reel transcripts (not invented).

Output is stored as a BlogDraft. Runs as a background Job (LLM, slow on CPU).
"""

from __future__ import annotations

import logging

from core.models import (
    BlogDraft, DocClusterAssignment, KnowledgeDocument, ReelClusterAssignment,
    TopicCluster,
)
from llm import client

logger = logging.getLogger(__name__)


def _cluster_reels(cluster: TopicCluster):
    return [
        a.reel for a in ReelClusterAssignment.objects
        .filter(cluster=cluster).select_related("reel__transcript", "reel__enrichment")
    ]


def _cluster_docs(cluster: TopicCluster) -> list[KnowledgeDocument]:
    return [
        a.document for a in DocClusterAssignment.objects
        .filter(cluster=cluster).select_related("document")
    ]


def _reel_material(reels) -> str:
    parts = []
    for r in reels[:12]:
        tr = getattr(r, "transcript", None)
        enr = getattr(r, "enrichment", None)
        txt = (tr.text if tr and tr.text else r.caption or "")[:700]
        summ = enr.summary_it if enr else ""
        parts.append(f"- {summ}\n  «{txt}»")
    return "\n".join(parts)


EXPAND_SYSTEM = (
    "Sei un editor di contenuti medici per Medyca (terapie ormonali bioidentiche, "
    "menopausa). Rispondi in italiano. Usa SOLO le informazioni fornite, non inventare."
)
EXPAND_USER = """\
TEMA: {label}

ARTICOLO BLOG ESISTENTE (estratto):
{article}

CONTENUTI DEI REEL SULLO STESSO TEMA:
{reels}

Elenca in modo concreto quali informazioni presenti nei reel NON sono ancora
coperte dall'articolo, e proponi come integrarle. Struttura la risposta in
Markdown con: una breve premessa, poi "## Cosa manca" (elenco puntato di
integrazioni concrete) e "## Bozze di paragrafo" (1-3 paragrafi pronti da
inserire, fondati sui reel)."""

DRAFT_SYSTEM = (
    "Sei un copywriter medico per Medyca (terapie ormonali bioidentiche, menopausa, "
    "salute femminile). Scrivi in italiano, con tono professionale ma accessibile. "
    "Fonda l'articolo ESCLUSIVAMENTE sui contenuti dei reel forniti — non inventare "
    "fatti o dati non presenti."
)
DRAFT_USER = """\
TEMA: {label}

CONTENUTI DEI REEL SU QUESTO TEMA (usa solo questi):
{reels}

Scrivi una bozza di articolo blog in italiano su questo tema, fondata solo sui
reel. Formato Markdown: un titolo (# ...), un'introduzione, 2-4 sezioni (## ...)
e una breve conclusione. Non inserire dati o affermazioni non presenti nei reel."""


def run_cluster_blog(cluster_id: int, job=None) -> dict:
    def progress(p, m):
        if job is not None:
            job.set_progress(p, m)

    cluster = TopicCluster.objects.filter(id=cluster_id).first()
    if not cluster:
        raise RuntimeError("Cluster non trovato.")

    progress(15, "Raccolgo reel e articoli del cluster…")
    reels = _cluster_reels(cluster)
    docs = _cluster_docs(cluster)
    if not reels and not docs:
        raise RuntimeError("Il cluster non ha contenuti utilizzabili.")

    reel_txt = _reel_material(reels) or "(nessun reel)"
    refs = [{"kind": "reel", "title": (r.caption or r.shortcode)[:60],
             "url": f"https://www.instagram.com/reel/{r.shortcode}/"} for r in reels[:12]]

    if docs:
        # Expand the existing article.
        doc = docs[0]
        refs.insert(0, {"kind": "blog", "title": doc.title, "url": doc.source_url})
        progress(35, "Confronto l'articolo esistente con i reel…")
        user = EXPAND_USER.format(
            label=cluster.label_it,
            article=(doc.content_text or doc.summary_it or "")[:4000],
            reels=reel_txt,
        )
        content = client.chat(EXPAND_SYSTEM, user, max_tokens=1200, timeout=600)
        mode, title = "expand", f"Espansione: {doc.title.replace(' — Medyca','')}"
    else:
        progress(35, "Scrivo una bozza fondata sui reel…")
        user = DRAFT_USER.format(label=cluster.label_it, reels=reel_txt)
        content = client.chat(DRAFT_SYSTEM, user, max_tokens=1400, timeout=700)
        mode, title = "draft", f"Bozza: {cluster.label_it}"

    progress(90, "Salvo il risultato…")
    draft = BlogDraft.objects.create(
        mode=mode, cluster_label=cluster.label_it, title=title[:300],
        content_md=(content or "").strip(), source_refs=refs, status="proposed",
    )
    progress(100, "Fatto.")
    logger.info("[blog_workflow] %s draft for cluster %s -> BlogDraft %s",
                mode, cluster.label_it, draft.id)
    return {"blog_draft_id": draft.id, "mode": mode}
