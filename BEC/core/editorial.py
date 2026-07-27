"""
core/editorial.py
=================
The editorial plan: a list of contents ready to be filmed, not a prose brief.

Each entry answers the four questions a creator actually has — what do I talk
about, from which angle, how do I open, and why now — and every one of them is
tied to material that exists in the knowledge bank. An idea without a source is
dropped: the same rule that stopped the analysis layer inventing claims.

Grounding comes from the real corpus: Medyca's own reels and blog articles
(what is already covered, and how well it performed) and the competitors'
themes (what is being said that Medyca is not saying).
"""

from __future__ import annotations

import json
import logging
import uuid

from core.models import ContentIdea, Reel
from core.weighting import account_medians, normalized_engagement
from llm import client

logger = logging.getLogger(__name__)

VALID_FORMATS = {"talking_head", "voiceover", "tutorial", "testimonianza",
                 "text_overlay", "intervista", "altro"}

PLAN_SYSTEM = (
    "Sei un content strategist per un profilo Instagram medico italiano "
    "(menopausa, terapie ormonali bioidentiche, salute femminile). Progetti "
    "contenuti che il professionista può girare domani.\n\n"
    "REGOLE:\n"
    "- Ogni contenuto deve nascere dal MATERIALE fornito. Se un'idea non è "
    "sostenuta da almeno una fonte dell'elenco, non proporla.\n"
    "- Il gancio è la prima frase pronunciata nel video: scrivila per intero, "
    "come va detta. Non descriverla.\n"
    "- Niente idee generiche del tipo 'parlare di menopausa': ogni contenuto "
    "ha un taglio specifico e riconoscibile.\n"
    "- Rispondi ESCLUSIVAMENTE con un oggetto JSON valido."
)

PLAN_USER = """\
Costruisci un piano editoriale di {n} contenuti.

COSA MEDYCA HA GIÀ PUBBLICATO (con il rendimento rispetto alla sua media):
{medyca}

TEMI SU CUI I COMPETITOR SONO PRESENTI:
{competitor}

{focus}
Per ogni contenuto indica:
- "titolo": di cosa parla, in modo specifico (max 12 parole)
- "angolo": il taglio con cui affrontarlo, diverso da ciò che è già stato detto
- "gancio": la prima frase da pronunciare, per intero
- "formato": uno tra talking_head, voiceover, tutorial, testimonianza, text_overlay, intervista
- "perche_ora": la ragione, citando i numeri o il gap quando esistono
- "scaletta": da 3 a 6 passaggi del video, in ordine, ognuno con
  {{"passaggio": "cosa dire in questo momento del video",
    "nota": "indicazione pratica di ripresa o tono, se utile"}}
  Il primo passaggio è il gancio, l'ultimo porta alla chiusura.
- "chiusura": la call to action finale, la frase con cui chiudere
- "fonti": i titoli dell'elenco sopra che sostengono il contenuto (almeno uno)
- "e_gap": true se il tema è coperto dai competitor e non da Medyca

Restituisci un JSON: {{"contenuti": [ ... ]}}"""


def _medyca_material(limit: int = 25) -> tuple[str, dict]:
    """Medyca's published content, strongest first, with its real weight."""
    from core.knowledge import _load_index

    medians = account_medians()
    reels = {r.id: r for r in Reel.objects.filter(account__owner_type="owned",
                                                  is_active=True)}
    rows, by_title = [], {}
    for item in _load_index():
        weight = ""
        if item["kind"] == "reel" and item["id"] in reels:
            w = normalized_engagement(reels[item["id"]], medians)
            weight = f" — rendimento {w:.1f}× la media"
        title = item["title"][:90]
        by_title[title.lower()] = {"kind": item["kind"], "title": title,
                                   "url": item.get("url", "")}
        rows.append(f"- {title}{weight}")
    return "\n".join(rows[:limit]) or "(nessun contenuto)", by_title


def _competitor_material(limit: int = 20) -> tuple[str, dict]:
    from core.models import ClusterRun

    run = ClusterRun.objects.filter(scope="competitor", is_current=True).first()
    rows, by_title = [], {}
    if run:
        for c in run.clusters.all().order_by("-size")[:limit]:
            title = c.label_it[:90]
            by_title[title.lower()] = {"kind": "competitor", "title": title, "url": ""}
            rows.append(f"- {title} ({c.reel_assignments.count()} reel)")
    return "\n".join(rows) or "(nessun tema competitor)", by_title


def generate_plan(n: int = 6, theme: str = "", job=None) -> list[ContentIdea]:
    """Produce n grounded content ideas and store them as one batch."""
    def progress(p, m):
        if job is not None:
            job.set_progress(p, m)

    progress(15, "Leggo cosa Medyca ha già pubblicato…")
    medyca, med_sources = _medyca_material()

    progress(35, "Guardo i temi dei competitor…")
    competitor, comp_sources = _competitor_material()
    known = {**med_sources, **comp_sources}

    focus = f'TEMA SU CUI CONCENTRARSI: "{theme}"\n\n' if theme else ""
    progress(55, "Costruisco il piano… di solito 30-60 secondi")
    data = client.chat_json(
        PLAN_SYSTEM,
        PLAN_USER.format(n=n, medyca=medyca, competitor=competitor, focus=focus),
        max_tokens=3600, timeout=900, model=client.model_for("reasoning"),
    )
    items = data.get("contenuti") if isinstance(data, dict) else data
    if not isinstance(items, list):
        items = []

    progress(85, "Salvo il piano…")
    batch = uuid.uuid4().hex[:12]
    model_used = client.last_model_used()[:64]
    created, dropped = [], 0
    for it in items:
        if not isinstance(it, dict):
            continue
        title = str(it.get("titolo", "")).strip()
        if len(title) < 5:
            continue
        # Resolve the cited sources against what actually exists. An idea whose
        # sources are all invented is an idea about nothing.
        refs = []
        for name in (it.get("fonti") or []):
            match = known.get(str(name).strip().lower())
            if match:
                refs.append(match)
        if not refs:
            dropped += 1
            continue
        fmt = str(it.get("formato", "")).strip().lower()
        outline = []
        for step in (it.get("scaletta") or [])[:8]:
            if isinstance(step, dict) and str(step.get("passaggio", "")).strip():
                outline.append({"step": str(step["passaggio"])[:400],
                                "note": str(step.get("nota", ""))[:220]})
            elif isinstance(step, str) and step.strip():
                outline.append({"step": step[:400], "note": ""})

        created.append(ContentIdea.objects.create(
            outline=outline,
            cta_it=str(it.get("chiusura", ""))[:300],
            argument_it=title[:300],
            angle_it=str(it.get("angolo", ""))[:2000],
            hook_it=str(it.get("gancio", ""))[:400],
            content_format=fmt if fmt in VALID_FORMATS else "altro",
            rationale_it=str(it.get("perche_ora", ""))[:2000],
            is_gap=bool(it.get("e_gap", False)),
            source_refs=refs,
            scope="owned",
            batch=batch,
        ))
    if dropped:
        logger.info("[editorial] %d contenuti scartati (nessuna fonte reale)", dropped)
    progress(100, f"Piano pronto: {len(created)} contenuti.")
    logger.info("[editorial] batch %s: %d contenuti con %s", batch, len(created), model_used)
    return created
