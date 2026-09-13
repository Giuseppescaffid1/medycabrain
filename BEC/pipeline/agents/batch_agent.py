"""
pipeline/agents/batch_agent.py
==============================
The two halves of batch analysis: **consegna** (submit) and **ritiro**
(collect).

The Batch API answers within 24 hours, not within seconds, so one nightly run
hands the work over and a later one picks the answers up. The pipeline never
waits: a batch that takes twenty hours costs nothing but time, and the rest of
the stages carry on around it.

    notte 1  collect()  → picks up whatever last night's delivery produced
             submit()   → hands over everything still pending
    notte 2  collect()  → those answers land, and so on

Collect runs BEFORE submit on purpose: answers that are ready should be in the
database before we decide what is still missing, or we pay twice for the same
reel.

What is in flight carries `enrich_status = "batched"`, which is why a
resubmission cannot happen: the pending query does not see those rows.

Costs, measured on this corpus (Sonnet 5, ~1.500 token in / ~400 out per reel):
about 4 $ for all 1.113 reels through the batch, against about 8 $ with live
calls. Nightly volume is a handful of new reels, so cents.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from core.models import BATCHED, DONE, FAILED, PENDING, SKIPPED, BatchRun, Reel
from llm import batch as batch_api
from pipeline.agents import enrich_agent

logger = logging.getLogger(__name__)


def _pending_reels(limit: int | None = None):
    """Reels whose analysis is still owed — the same rule the live stage uses,
    minus anything already handed to a batch."""
    from django.db.models import Q

    qs = Reel.objects.filter(
        Q(transcribe_status=DONE) | Q(transcribe_status=SKIPPED),
        enrich_status=PENDING, is_active=True,
    ).order_by("-id")
    return list(qs[:limit] if limit else qs)


def submit(limit: int | None = None) -> dict:
    """Hand the pending analyses to the Batch API.

    Returns a summary. Never raises for a normal failure: if the delivery is
    refused, the rows stay `pending` and the live stage will do them tonight —
    degraded, but nothing is lost.
    """
    if not batch_api.available():
        return {"skipped": "batch non configurato"}

    cap = min(limit or settings.BATCH_MAX_REQUESTS, settings.BATCH_MAX_REQUESTS)
    reels = _pending_reels(cap)
    if not reels:
        return {"submitted": 0, "note": "niente da consegnare"}

    items, by_id, insufficient = [], {}, []
    for reel in reels:
        built = enrich_agent.build_enrich_prompt(reel)
        if built is None:
            # Nothing to analyse — handled locally, never sent to a model.
            insufficient.append(reel)
            continue
        system, user, evidence = built
        cid = f"reel-{reel.id}"
        items.append(batch_api.BatchItem(
            custom_id=cid, system=system, user=user,
            max_tokens=enrich_agent.ENRICH_MAX_TOKENS))
        by_id[cid] = (reel, evidence)

    for reel in insufficient:
        enrich_agent._enrich_one(reel)   # writes the empty, evidence-tagged row
        reel.enrich_status = DONE
        reel.save(update_fields=["enrich_status"])

    if not items:
        return {"submitted": 0, "insufficient": len(insufficient)}

    try:
        batch_id, sent = batch_api.submit(items)
    except batch_api.BatchError as exc:
        logger.warning("[batch] consegna fallita: %s — le righe restano pending", exc)
        return {"submitted": 0, "failed": str(exc)[:200],
                "insufficient": len(insufficient)}

    run = BatchRun.objects.create(
        kind="enrich", batch_id=batch_id,
        model=settings.BATCH_MODEL,
        items=[{"custom_id": cid, "reel_id": by_id[cid][0].id,
                "evidence": by_id[cid][1]} for cid in sent],
    )
    # Mark them in flight only AFTER the provider accepted the batch: if the
    # call had failed we would have parked them in a state nothing collects.
    Reel.objects.filter(id__in=[by_id[c][0].id for c in sent]).update(
        enrich_status=BATCHED)
    logger.info("[batch] %s: consegnate %s analisi", batch_id, len(sent))
    return {"submitted": len(sent), "batch_id": batch_id, "run": run.id,
            "insufficient": len(insufficient),
            "left_behind": len(_pending_reels())}


def collect() -> dict:
    """Pick up every delivery that has finished, and write the answers down.

    A batch still working is left alone — no waiting, no polling loop. A
    result that errored or expired sets the reel to `failed` with the reason,
    per the project rule that failures stay failed.
    """
    if not batch_api.available():
        return {"skipped": "batch non configurato"}

    out = {"batches": 0, "written": 0, "failed": 0, "still_working": 0}
    for run in BatchRun.objects.filter(status__in=("submitted", "ended")):
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
            cid = entry["custom_id"]
            reel = Reel.objects.filter(id=entry["reel_id"]).first()
            if reel is None:
                continue
            res = results.get(cid)
            if res is None:
                # Ended, yet no answer for this id: treat as failure rather
                # than leaving the reel stuck in "batched" forever.
                reel.enrich_status = FAILED
                reel.last_error = "nessuna risposta nel batch"
                reel.save(update_fields=["enrich_status", "last_error"])
                failed += 1
                continue
            if not res["ok"]:
                reel.enrich_status = FAILED
                reel.last_error = f"batch: {res['error']}"[:500]
                reel.save(update_fields=["enrich_status", "last_error"])
                failed += 1
                continue
            try:
                enrich_agent.write_enrichment(reel, res["data"], entry["evidence"],
                                              res.get("model", run.model))
            except Exception as exc:  # noqa: BLE001 — one malformed answer
                reel.enrich_status = FAILED
                reel.last_error = f"batch: risposta inutilizzabile {exc!r}"[:500]
                reel.save(update_fields=["enrich_status", "last_error"])
                failed += 1
                continue
            reel.enrich_status = DONE
            reel.last_error = ""
            reel.save(update_fields=["enrich_status", "last_error"])
            written += 1

        run.status = "collected"
        run.collected_at = timezone.now()
        run.counts = {**st, "written": written, "failed": failed}
        run.save(update_fields=["status", "collected_at", "counts"])
        out["batches"] += 1
        out["written"] += written
        out["failed"] += failed
        logger.info("[batch] %s: scritte %s analisi, %s fallite",
                    run.batch_id, written, failed)
    return out


def run(ctx) -> dict:
    """The DAG stage: collect first, then submit what is still owed."""
    got = collect()
    sent = submit(limit=ctx.limit)
    return {"collect": got, "submit": sent}
