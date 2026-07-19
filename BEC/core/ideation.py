"""
core/ideation.py
================
The content-ideation Second Brain (MEDYC-10, reframed).

Understands "what argument can be proposed for a content pipeline" by
contrasting two signals:

  - COMPETITOR coverage — the current competitor topic clusters + the
    arguments competitors actually make (ReelArgument on competitor reels).
  - MEDYCA coverage — topics Medyca already covers (owned-reel enrichment
    topics + blog KnowledgeDocument topics).

An LLM then proposes concrete content arguments for Medyca, flagging the
GAPS (competitors push it, Medyca hasn't), each with a rationale and a
concrete angle. Supporting sources are attached via the knowledge bank
(knowledge.semantic_search). Results persist as ContentIdea rows.
"""

from __future__ import annotations

import logging

from core.models import (
    ArgumentAssignment, ClusterRun, ContentIdea, KnowledgeDocument, Reel,
    ReelArgument, TopicCluster,
)
from llm import client

logger = logging.getLogger(__name__)


def _competitor_signal(max_clusters: int = 12, max_args: int = 25) -> dict:
    run = ClusterRun.objects.filter(scope="competitor", is_current=True).first()
    clusters, arguments = [], []
    if run:
        clusters = list(
            TopicCluster.objects.filter(run=run).order_by("-size")
            .values_list("label_it", flat=True)[:max_clusters]
        )
        seen = set()
        for a in (ReelArgument.objects
                  .filter(reel__account__owner_type="competitor")
                  .order_by("-id")[: max_args * 3]):
            key = a.text_it.strip().lower()[:80]
            if key not in seen:
                seen.add(key)
                arguments.append(a.text_it)
            if len(arguments) >= max_args:
                break
    return {"clusters": clusters, "arguments": arguments}


def _medyca_coverage(max_topics: int = 40) -> list[str]:
    topics = set()
    for r in (Reel.objects.filter(account__owner_type="owned")
              .select_related("enrichment")):
        enr = getattr(r, "enrichment", None)
        if enr:
            topics.update(enr.topics or [])
    for d in KnowledgeDocument.objects.filter(is_active=True):
        topics.update(d.topics or [])
    return sorted(topics)[:max_topics]


IDEATION_SYSTEM = (
    "Sei uno stratega di contenuti per Medyca (terapie ormonali bioidentiche, "
    "menopausa, salute femminile). Il tuo compito è proporre argomenti di "
    "contenuto per i canali di Medyca. Rispondi SEMPRE ed esclusivamente con "
    "un oggetto JSON valido, in lingua italiana."
)

IDEATION_USER = """\
ARGOMENTI TRATTATI DAI COMPETITOR (cluster tematici):
{comp_clusters}

AFFERMAZIONI FATTE DAI COMPETITOR:
{comp_args}

ARGOMENTI GIÀ COPERTI DA MEDYCA (Instagram + blog):
{medyca_topics}

Proponi {n} argomenti di contenuto che Medyca dovrebbe produrre.
Dai PRIORITÀ ai GAP: argomenti che i competitor trattano ma Medyca no.
Per ciascuno indica se è un gap (true/false).

Restituisci un JSON:
{{
  "idee": [
    {{
      "argument": "l'argomento/tema in italiano (max 12 parole)",
      "rationale": "perché è rilevante per Medyca, 1-2 frasi",
      "angle": "un taglio/angolo concreto per il contenuto, 1 frase",
      "is_gap": true
    }}
  ]
}}
"""


def generate_ideas(n: int = 8) -> list[ContentIdea]:
    """Generate + persist n content ideas. Returns the created rows."""
    comp = _competitor_signal()
    medyca = _medyca_coverage()

    if not comp["clusters"] and not comp["arguments"]:
        raise RuntimeError("Nessun dato competitor: esegui prima il clustering competitor.")

    user = IDEATION_USER.format(
        comp_clusters="\n".join(f"- {c}" for c in comp["clusters"]) or "(nessuno)",
        comp_args="\n".join(f"- {a}" for a in comp["arguments"]) or "(nessuna)",
        medyca_topics=", ".join(medyca) or "(nessuno)",
        n=n,
    )
    data = client.chat_json(IDEATION_SYSTEM, user, max_tokens=1200, retries=3)
    ideas = data.get("idee") if isinstance(data, dict) else data
    if not isinstance(ideas, list):
        ideas = []

    # A batch id groups this generation (no Date.now available; use max pk + count).
    last = ContentIdea.objects.order_by("-id").values_list("id", flat=True).first() or 0
    batch = f"batch-{last + 1}"

    created = []
    from core.knowledge import semantic_search
    for item in ideas[:n]:
        if not isinstance(item, dict):
            continue
        arg = str(item.get("argument", "")).strip()
        if len(arg) < 4:
            continue
        # Attach supporting sources from the knowledge bank.
        try:
            hits = semantic_search(arg, top_k=3)
        except Exception:  # noqa: BLE001
            hits = []
        refs = [{"kind": h["kind"], "title": h["title"], "url": h["url"]} for h in hits]
        created.append(ContentIdea.objects.create(
            argument_it=arg[:300],
            rationale_it=str(item.get("rationale", ""))[:1000],
            angle_it=str(item.get("angle", ""))[:1000],
            is_gap=bool(item.get("is_gap", False)),
            source_refs=refs,
            status="proposed",
            batch=batch,
        ))
    logger.info("[ideation] generated %d ideas (batch %s)", len(created), batch)
    return created
