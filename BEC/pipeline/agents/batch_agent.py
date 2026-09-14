"""
pipeline/agents/batch_agent.py
==============================
The two halves of batch analysis: **consegna** (submit) and **ritiro**
(collect), for every kind of bulk LLM work in the platform.

The Batch API answers within 24 hours, not within seconds, so one nightly run
hands the work over and a later one picks the answers up. The pipeline never
waits: a batch that takes twenty hours costs nothing but time, and the other
stages carry on around it.

    notte 1  collect()  -> writes down whatever last night's delivery produced
             submit()   -> hands over everything still pending
    notte 2  collect()  -> those answers land, and so on

Collect runs BEFORE submit on purpose: answers that are ready should be in the
database before we decide what is still missing, or we pay twice.

**Three kinds of work**, declared once in KINDS rather than written out three
times:

    reel_enrich    the analysis of a reel      (Reel.enrich_status)
    doc_enrich     the analysis of an article  (KnowledgeDocument.enrich_status)
    doc_arguments  its claims, each quoted     (KnowledgeDocument.argument_status)

Adding a fourth is one entry in that table: which rows are owed, how to build
the prompt, how to write the answer. Nothing else here changes.

Work in flight carries the `batched` status, which is why a resubmission
cannot happen: the pending query does not see those rows.

Costs measured on this corpus with Sonnet 5: ~4 $ for all 1.113 reels through
the batch against ~8 $ live, and the article backlog in the same proportion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from core.models import (BATCHED, DONE, FAILED, PENDING, SKIPPED, BatchRun,
                         KnowledgeDocument, Reel)
from llm import batch as batch_api

logger = logging.getLogger(__name__)


# -- the three kinds of work -------------------------------------------------

@dataclass(frozen=True)
class Kind:
    """One kind of batchable work.

    pending()        rows still owed, newest first
    build(row)       (system, user) for that row, or None when there is
                     nothing worth asking — the row is then handled locally
    write(row, data) store one answer; raising means "this answer is unusable"
    status_field     the column carrying pending / batched / done / failed
    prefix           how the custom_id is spelled ("reel-1251")
    """

    name: str
    prefix: str
    status_field: str
    pending: Callable[[], list]
    build: Callable[[object], tuple[str, str] | None]
    write: Callable[[object, object], None]
    model_cls: type


def _reels_pending() -> list:
    return list(Reel.objects.filter(
        Q(transcribe_status=DONE) | Q(transcribe_status=SKIPPED),
        enrich_status=PENDING, is_active=True).order_by("-id"))


def _reel_build(reel):
    from pipeline.agents import enrich_agent

    built = enrich_agent.build_enrich_prompt(reel)
    if built is None:
        return None
    system, user, _evidence = built
    return system, user


def _reel_write(reel, data):
    from pipeline.agents import enrich_agent

    # The evidence class is re-derived from the row rather than carried
    # through the batch: derived from the row it cannot drift, while a stale
    # copy inside a day-old JSON payload could.
    built = enrich_agent.build_enrich_prompt(reel)
    evidence = built[2] if built else "transcript"
    enrich_agent.write_enrichment(reel, data, evidence, settings.BATCH_MODEL)


def _reel_local(reel):
    """A reel with nothing to analyse: finished here, never sent to a model."""
    from pipeline.agents import enrich_agent

    enrich_agent._enrich_one(reel)


def _docs_pending() -> list:
    return list(KnowledgeDocument.objects.filter(
        enrich_status=PENDING, is_active=True)
        .select_related("source").order_by("-id"))


def _doc_build(doc):
    from pipeline.agents import knowledge_agent

    return knowledge_agent.build_doc_enrich_prompt(doc)


def _doc_write(doc, data):
    from pipeline.agents import knowledge_agent

    knowledge_agent.write_doc_enrich(doc, data)


def _docargs_pending() -> list:
    # Claims are extracted from an article that was already understood:
    # asking for quotes before the analysis exists reverses the dependency.
    return list(KnowledgeDocument.objects.filter(
        argument_status=PENDING, enrich_status=DONE, is_active=True)
        .order_by("-id"))


def _docargs_build(doc):
    from pipeline.agents import knowledge_agent

    return knowledge_agent.build_doc_arguments_prompt(doc)


def _docargs_write(doc, data):
    from pipeline.agents import knowledge_agent

    knowledge_agent.write_doc_arguments(doc, data)


KINDS: dict[str, Kind] = {
    "reel_enrich": Kind(
        name="reel_enrich", prefix="reel", status_field="enrich_status",
        pending=_reels_pending, build=_reel_build, write=_reel_write,
        model_cls=Reel),
    "doc_enrich": Kind(
        name="doc_enrich", prefix="doc", status_field="enrich_status",
        pending=_docs_pending, build=_doc_build, write=_doc_write,
        model_cls=KnowledgeDocument),
    "doc_arguments": Kind(
        name="doc_arguments", prefix="docarg", status_field="argument_status",
        pending=_docargs_pending, build=_docargs_build, write=_docargs_write,
        model_cls=KnowledgeDocument),
}

# Rows with nothing worth asking about are finished locally instead of being
# sent to a model. Only reels have such a case (no speech and no caption);
# an article always has a body.
LOCAL_FALLBACK = {"reel_enrich": _reel_local}


def _max_tokens(kind_name: str) -> int:
    from pipeline.agents import enrich_agent, knowledge_agent

    return (enrich_agent.ENRICH_MAX_TOKENS if kind_name == "reel_enrich"
            else knowledge_agent.DOC_MAX_TOKENS)


# -- submit ------------------------------------------------------------------

def submit_kind(kind_name: str, limit: int | None = None) -> dict:
    """Hand one kind of pending work to the Batch API.

    Never raises for a normal failure: if the delivery is refused the rows
    stay `pending` and the live stage does them tonight — degraded, not lost.
    """
    if not batch_api.available():
        return {"skipped": "batch non configurato"}

    kind = KINDS[kind_name]
    cap = min(limit or settings.BATCH_MAX_REQUESTS, settings.BATCH_MAX_REQUESTS)
    rows = kind.pending()[:cap]
    if not rows:
        return {"submitted": 0}

    items, by_id, local = [], {}, []
    for row in rows:
        built = kind.build(row)
        if built is None:
            local.append(row)
            continue
        system, user = built
        cid = f"{kind.prefix}-{row.id}"
        items.append(batch_api.BatchItem(custom_id=cid, system=system, user=user,
                                         max_tokens=_max_tokens(kind_name)))
        by_id[cid] = row.id

    for row in local:
        handler = LOCAL_FALLBACK.get(kind_name)
        if handler:
            handler(row)
        setattr(row, kind.status_field, DONE)
        row.save(update_fields=[kind.status_field])

    if not items:
        return {"submitted": 0, "locali": len(local)}

    try:
        batch_id, sent = batch_api.submit(items)
    except batch_api.BatchError as exc:
        logger.warning("[batch] %s: consegna fallita: %s — le righe restano pending",
                       kind_name, exc)
        return {"submitted": 0, "failed": str(exc)[:200], "locali": len(local)}

    run = BatchRun.objects.create(
        kind=kind_name, batch_id=batch_id, model=settings.BATCH_MODEL,
        items=[{"custom_id": cid, "row_id": by_id[cid]} for cid in sent],
    )
    # Mark them in flight only AFTER the provider accepted the batch: had the
    # call failed we would have parked them in a state nothing collects.
    kind.model_cls.objects.filter(id__in=[by_id[c] for c in sent]).update(
        **{kind.status_field: BATCHED})
    logger.info("[batch] %s: consegnate %s richieste (%s)",
                kind_name, len(sent), batch_id)
    return {"submitted": len(sent), "batch_id": batch_id, "run": run.id,
            "locali": len(local)}


def submit(limit: int | None = None) -> dict:
    """Hand over every kind of pending work."""
    return {k: submit_kind(k, limit) for k in KINDS}


# -- collect -----------------------------------------------------------------

def collect() -> dict:
    """Pick up every delivery that has finished and write the answers down.

    A batch still working is left alone — no waiting, no polling loop. An
    errored, expired or unusable result sets the row to `failed` with the
    reason, per the project rule that failures stay failed.
    """
    if not batch_api.available():
        return {"skipped": "batch non configurato"}

    out = {"batches": 0, "written": 0, "failed": 0, "still_working": 0,
           "per_tipo": {}}
    for run in BatchRun.objects.filter(status__in=("submitted", "ended")):
        kind = KINDS.get(run.kind)
        if kind is None:
            logger.warning("[batch] %s: tipo sconosciuto %r", run.batch_id, run.kind)
            continue
        try:
            st = batch_api.status(run.batch_id)
        except Exception as exc:  # noqa: BLE001 — one bad batch never stops the others
            logger.warning("[batch] %s: stato illeggibile: %r", run.batch_id, exc)
            run.last_error = repr(exc)[:500]
            run.save(update_fields=["last_error"])
            continue

        run.counts = st
        if not st["ended"]:
            run.save(update_fields=["counts"])
            out["still_working"] += 1
            continue

        run.status = "ended"
        run.save(update_fields=["counts", "status"])
        try:
            results = batch_api.collect(run.batch_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[batch] %s: ritiro fallito: %r", run.batch_id, exc)
            run.last_error = repr(exc)[:500]
            run.save(update_fields=["last_error"])
            continue

        written = failed = 0
        # The mapping travels with the run, so an answer is matched by its
        # custom_id — never by the order it arrived in.
        for entry in run.items:
            row = kind.model_cls.objects.filter(id=entry["row_id"]).first()
            if row is None:
                continue
            res = results.get(entry["custom_id"])
            reason = None
            if res is None:
                # Ended, yet no answer for this id: a failure, rather than
                # leaving the row stuck in "batched" forever.
                reason = "nessuna risposta nel batch"
            elif not res["ok"]:
                reason = f"batch: {res['error']}"
            else:
                try:
                    kind.write(row, res["data"])
                except Exception as exc:  # noqa: BLE001 — one unusable answer
                    reason = f"batch: risposta inutilizzabile {exc!r}"
            if reason:
                setattr(row, kind.status_field, FAILED)
                row.last_error = reason[:500]
                row.save(update_fields=[kind.status_field, "last_error"])
                failed += 1
                continue
            # write() may already have set the status (the live paths do);
            # setting it again keeps every kind ending in the same state.
            setattr(row, kind.status_field, DONE)
            row.last_error = ""
            row.save(update_fields=[kind.status_field, "last_error"])
            written += 1

        run.status = "collected"
        run.collected_at = timezone.now()
        run.counts = {**st, "written": written, "failed": failed}
        run.save(update_fields=["status", "collected_at", "counts"])
        out["batches"] += 1
        out["written"] += written
        out["failed"] += failed
        t = out["per_tipo"].setdefault(run.kind, {"written": 0, "failed": 0})
        t["written"] += written
        t["failed"] += failed
        logger.info("[batch] %s (%s): scritte %s, fallite %s",
                    run.batch_id, run.kind, written, failed)
    return out


def run(ctx) -> dict:
    """The DAG stage: collect first, then submit what is still owed."""
    got = collect()
    sent = submit(limit=ctx.limit)
    return {"collect": got, "submit": sent}
