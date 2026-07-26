"""
core/strategy.py
================
The input-driven content-strategy engine — the genuinely useful core.

Given an input (free-text topic/brief, or a clicked theme), it:
  1. finds what Medyca ALREADY covers on it (owned reels + blog), weighted
     by engagement (media ponderata);
  2. finds what COMPETITORS say on it that Medyca doesn't (the gap);
  3. asks the local LLM for a STRATEGIC BRIEF grounded in that evidence
     (angolo, perché ora con i numeri, cosa esiste già, il gap, scaletta);
  4. can generate a full DRAFT on-demand from the same sources.

Everything is grounded in real content + real engagement numbers — not
invented. Runs async via Job.
"""

from __future__ import annotations

import logging

import numpy as np

from core.knowledge import _embed_query, _load_index
from core.models import Reel, StrategyBrief
from core.weighting import account_medians, normalized_engagement
from llm import client

logger = logging.getLogger(__name__)

COVERED = 0.55
PARTIAL = 0.42


def _competitor_index():
    """Competitor reels with embeddings, for topic matching."""
    from core.models import DONE, ReelEmbedding

    items = []
    for e in ReelEmbedding.objects.filter(
        reel__account__owner_type="competitor", reel__is_active=True,
        reel__enrich_status=DONE,
    ).select_related("reel", "reel__enrichment", "reel__account"):
        r = e.reel
        if not e.vector:
            continue
        enr = getattr(r, "enrichment", None)
        items.append({
            "title": (enr.summary_it if enr and enr.summary_it else r.caption[:80]) or r.shortcode,
            "url": f"https://www.instagram.com/reel/{r.shortcode}/",
            "account": r.account.username,
            "vec": np.asarray(e.vector, dtype=np.float32),
        })
    return items


def _rank(query_vec, index, top_k):
    if not index:
        return []
    mat = np.vstack([it["vec"] for it in index])
    scores = mat @ query_vec
    order = np.argsort(-scores)[:top_k]
    return [(index[int(i)], float(scores[int(i)])) for i in order]


STRATEGY_SYSTEM = (
    "Sei uno stratega di contenuti per Medyca (terapie ormonali bioidentiche, "
    "menopausa, salute femminile). Rispondi in italiano. Fondati ESCLUSIVAMENTE "
    "sulle evidenze fornite (contenuti Medyca, contenuti competitor, numeri di "
    "engagement) — non inventare fatti."
)
STRATEGY_USER = """\
RICHIESTA / TEMA: {topic}

COSA MEDYCA HA GIÀ PUBBLICATO SU QUESTO TEMA (con performance):
{medyca}

COSA PUBBLICANO I COMPETITOR SU QUESTO TEMA:
{competitor}

Produci un BRIEF STRATEGICO in Markdown con queste sezioni:
## Angolo
(l'angolo di contenuto consigliato, 1-2 frasi)
## Perché ora
(motivazione fondata sui numeri di engagement forniti)
## Cosa Medyca ha già
(sintesi di ciò che è già coperto, con riferimento alle fonti)
## Il gap
(cosa i competitor trattano e Medyca no, o come differenziarsi)
## Scaletta
(4-6 punti per il nuovo contenuto, fondati sulle fonti)
Sii concreto e operativo. Niente dati non presenti nelle evidenze."""

DRAFT_SYSTEM = (
    "Sei un copywriter medico per Medyca. Scrivi in italiano, tono professionale "
    "ma accessibile. Fonda il testo SOLO sulle evidenze fornite; non inventare."
)
DRAFT_USER = """\
TEMA: {topic}

BRIEF STRATEGICO:
{brief}

FONTI MEDYCA:
{medyca}

Scrivi una bozza di contenuto completa in italiano (articolo o script per reel)
fondata sul brief e sulle fonti. Formato Markdown: titolo, introduzione,
sezioni, conclusione."""


def _material(hits, with_weight=False) -> str:
    lines = []
    for h, score in hits:
        w = f" [performance {h.get('weight')}×]" if with_weight and h.get("weight") is not None else ""
        lines.append(f"- {h['title']}{w}")
    return "\n".join(lines) or "(nessuno)"


def analyze(input_text: str, source_kind: str = "input", job=None,
            query_vec=None) -> StrategyBrief:
    def progress(p, m):
        if job is not None:
            job.set_progress(p, m)

    progress(15, "Cerco cosa Medyca ha già pubblicato…")
    # The web process hands us the query vector it already computed with a
    # warm model: loading sentence-transformers here would cost ~14s in this
    # short-lived job process, more than the whole rest of the analysis.
    if query_vec is not None:
        import numpy as _np
        qv = _np.asarray(query_vec, dtype=_np.float32)
    else:
        qv = _embed_query(input_text)

    # Medyca coverage (owned reels + blog), attach engagement weight to reels.
    medyca_hits = _rank(qv, _load_index(), top_k=6)
    medians = account_medians()
    reel_by_id = {r.id: r for r in Reel.objects.filter(account__owner_type="owned")}
    for h, _ in medyca_hits:
        if h["kind"] == "reel" and h["id"] in reel_by_id:
            h["weight"] = normalized_engagement(reel_by_id[h["id"]], medians)

    progress(35, "Cerco cosa fanno i competitor…")
    comp_hits = _rank(qv, _competitor_index(), top_k=6)

    top_medyca_score = medyca_hits[0][1] if medyca_hits else 0.0
    coverage = "covered" if top_medyca_score >= COVERED else "partial" if top_medyca_score >= PARTIAL else "gap"

    progress(55, "Genero il brief strategico…")
    user = STRATEGY_USER.format(
        topic=input_text,
        medyca=_material(medyca_hits, with_weight=True),
        competitor=_material(comp_hits),
    )
    # Stream: the progress bar advances with the text instead of sitting at a
    # frozen 55% for minutes, and a slow-but-working generation is not killed.
    def _tick(partial: str):
        if job:
            pct = min(90, 55 + len(partial) // 60)
            job.set_progress(pct, f"Scrivo il brief… ({len(partial)} caratteri)")

    brief_md = client.chat(STRATEGY_SYSTEM, user, max_tokens=900, timeout=900,
                           on_token=_tick, priority=True)

    progress(90, "Salvo il brief…")
    brief = StrategyBrief.objects.create(
        input_text=input_text[:400],
        source_kind=source_kind,
        coverage=coverage,
        brief_md=(brief_md or "").strip(),
        brief_model=client.last_model_used()[:64],
        medyca_sources=[
            {"title": h["title"], "url": h["url"], "kind": h["kind"], "weight": h.get("weight")}
            for h, _ in medyca_hits
        ],
        competitor_sources=[{"title": h["title"], "url": h["url"]} for h, _ in comp_hits],
        metrics={"top_medyca_score": round(top_medyca_score, 3),
                 "medyca_hits": len(medyca_hits), "competitor_hits": len(comp_hits)},
        status="proposed",
    )
    progress(100, "Fatto.")
    logger.info("[strategy] brief %s for %r (coverage=%s)", brief.id, input_text[:40], coverage)
    return brief


def generate_draft(brief_id: int, job=None) -> dict:
    def progress(p, m):
        if job is not None:
            job.set_progress(p, m)

    brief = StrategyBrief.objects.filter(id=brief_id).first()
    if not brief:
        raise RuntimeError("Brief non trovato.")
    progress(30, "Scrivo la bozza completa…")
    medyca = "\n".join(f"- {s['title']}" for s in brief.medyca_sources) or "(nessuna)"
    user = DRAFT_USER.format(topic=brief.input_text, brief=brief.brief_md[:3000], medyca=medyca)
    def _tick_draft(partial: str):
        if job:
            pct = min(92, 40 + len(partial) // 60)
            job.set_progress(pct, f"Scrivo la bozza… ({len(partial)} caratteri)")

    draft = client.chat(DRAFT_SYSTEM, user, max_tokens=1200, timeout=900,
                        on_token=_tick_draft, priority=True)
    brief.draft_md = (draft or "").strip()
    brief.draft_model = client.last_model_used()[:64]
    brief.save(update_fields=["draft_md", "draft_model"])
    progress(100, "Bozza pronta.")
    return {"brief_id": brief.id}
