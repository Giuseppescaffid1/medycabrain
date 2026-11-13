"""
core/progress_report.py
=======================
What `GET /api/v1/ops/progress/` and `GET /api/v1/ops/llm/` answer. Read-only
(apart from closing ghost rows, see `llm.usage.close_ghosts`): the numbers come
from `stage_runs`, `llm_calls`, `jobs` and `batch_runs`, written by
`core/progress.py` and `llm/usage.py`.

`progress_snapshot()` is polled every 2 seconds by an open page, so it is four
indexed reads and nothing else: no system commands, no log parsing
(`ops.snapshot()` measures 303-566 ms because it does both). The one exception
is the speed of earlier rounds, used before a stage has finished 3 items; it
reads `queue_eta._measured_rates()` (cached by the log's size and mtime) and is
itself cached here for a minute.

Speed and time left are computed HERE, not in the browser: processed items
divided by the time of the phase in progress; left = missing / speed. Before 3
items are processed there is no honest speed, so the rate of the previous
rounds is used and labelled as such; for stages without one, no number at all.

Nothing here splits Medyca from competitor content, and no row holds content:
a stage row has counts, a call row has numbers and a short item label.
"""

from __future__ import annotations

import statistics
import time
from datetime import datetime, timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone

from core import models, ops
from llm import usage
from pipeline.dag import STAGE_LABELS, STAGE_NAMES

MIN_ITEMS_FOR_SPEED = 3
MAX_ITEMS_SHOWN = 5
# "Di solito ancora ~N min" needs this many finished answers of the same
# process to take a median from; fewer would be a guess dressed as an estimate.
MIN_SAMPLES_TYPICAL = 5
# A previous speed is looked up at most this often (it reads the log).
_PREV_TTL = 60.0
_prev_cache: dict = {"at": 0.0, "value": {}}

# Who does the work of a stage, as a code the page turns into words. Stages
# that call a model say so from their calls (`llm_*`); these are the fixed ones.
_STAGE_WHO = {"scrape": "none", "download": "none", "blogscrape": "none",
              "batch": "batch", "embed": "embed", "cluster": "cluster",
              "transcribe": "stt", "enrich": "llm", "knowledge": "llm"}


def _previous_rates() -> dict[str, float]:
    """Seconds per item of earlier rounds, per stage (download, transcribe,
    enrich). Cached: the source reads the pipeline log."""
    now = time.monotonic()
    if now - _prev_cache["at"] > _PREV_TTL:
        try:
            from core import queue_eta
            rates = {k: v["seconds_per_item"] for k, v in queue_eta._measured_rates().items()}
        except Exception:  # noqa: BLE001 — an estimate is optional
            rates = {}
        _prev_cache.update(at=now, value=rates)
    return _prev_cache["value"]


def _typical_tokens(calls: list[models.LLMCall]) -> dict[str, int]:
    """Median answer length (tokens) of the last local answers, per process that
    has a local call writing right now."""
    out = {}
    for proc in {c.process for c in calls if c.is_local and c.tokens_so_far}:
        lens = list(models.LLMCall.objects
                    .filter(process=proc, is_local=True, kind="chat", status="done",
                            output_tokens__gt=0, truncated=False)
                    .order_by("-created_at").values_list("output_tokens", flat=True)[:20])
        if len(lens) >= MIN_SAMPLES_TYPICAL:
            out[proc] = int(statistics.median(lens))
    return out


def _stage_dict(s: models.StageRun, now, calls: list[models.LLMCall],
                tps: float | None, typical: dict) -> dict:
    elapsed_stage = ((s.finished_at or now) - s.started_at).total_seconds() if s.started_at else 0
    phase_start = s.phase_started_at or s.started_at
    elapsed_phase = ((s.finished_at or now) - phase_start).total_seconds() if phase_start else 0
    processed = s.done + s.failed + s.skipped

    rate = eta = None
    rate_source = None
    if s.status == "running" and s.total:
        if processed >= MIN_ITEMS_FOR_SPEED and elapsed_phase > 0:
            rate, rate_source = processed / elapsed_phase, "measured"
        else:
            spi = _previous_rates().get(s.stage)
            if spi:
                rate, rate_source = 1 / spi, "previous"
        if rate:
            eta = round(max(s.total - processed, 0) / rate)

    who = _STAGE_WHO.get(s.stage, "none")
    if who == "llm" and calls:
        locals_ = {c.is_local for c in calls}
        who = "llm_local" if locals_ == {True} else "llm_remote" if locals_ == {False} else "llm_mixed"

    items = [_item_dict(c, now, typical) for c in calls]
    return {
        "id": s.id, "stage": s.stage, "label": STAGE_LABELS.get(s.stage, s.stage),
        "status": s.status, "error": s.error, "note": s.note,
        "total": s.total, "done": s.done, "failed": s.failed, "skipped": s.skipped,
        "unit": s.unit, "phase": s.phase, "phases": s.phases,
        "started_at": s.started_at, "finished_at": s.finished_at,
        "elapsed_seconds": round(elapsed_stage), "phase_seconds": round(elapsed_phase),
        "rate_per_minute": round(rate * 60, 2) if rate else None,
        "rate_source": rate_source, "eta_seconds": eta,
        "tokens_per_second": tps, "who": who,
        "current": s.current or None,
        "items": items[:MAX_ITEMS_SHOWN], "items_more": max(len(items) - MAX_ITEMS_SHOWN, 0),
        "interrupted": s.status == "failed" and s.error == "giro interrotto",
    }


def _item_dict(c: models.LLMCall, now, typical: dict) -> dict:
    """One open model call, as a line under its stage's bar.

    Time left is given as two numbers that say what they are: "di solito" (the
    median length of earlier answers of this process) and "al massimo" (the
    token ceiling asked for). Waiting and reading get none: nothing honest to
    divide by yet.
    """
    since = c.created_at if c.status == "waiting" else (c.started_at or c.created_at)
    seconds = round((now - since).total_seconds())
    if c.status == "waiting":
        state = "waiting"
    elif c.is_local:
        state = "writing" if c.tokens_so_far else "reading"
    else:
        state = "running"
    tps = usual = most = None
    if c.is_local and c.tokens_so_far and seconds > 0:
        tps = round(c.tokens_so_far / seconds, 1)
        if tps > 0:
            if c.max_tokens:
                most = round(max(c.max_tokens - c.tokens_so_far, 0) / tps)
            if typical.get(c.process):
                # None once past the median: the page says "più lunga del solito".
                left = typical[c.process] - c.tokens_so_far
                usual = round(left / tps) if left > 0 else None
    return {"label": c.item_label, "kind": c.item_kind, "provider": c.provider,
            "model": c.model, "is_local": c.is_local, "state": state,
            "seconds": seconds, "tokens": c.tokens_so_far if c.is_local else None,
            "tokens_per_second": tps, "max_tokens": c.max_tokens,
            "usual_remaining_seconds": usual, "max_remaining_seconds": most,
            "longer_than_usual": bool(tps and typical.get(c.process)
                                      and c.tokens_so_far >= typical[c.process]),
            "process": c.process}


def _local_speed_by_stage_run(ids: list[int]) -> dict[int, float]:
    """Output tokens per second of the local calls already finished, per stage row."""
    rows = (models.LLMCall.objects
            .filter(stage_run_id__in=ids, is_local=True, status="done", kind="chat",
                    eval_seconds__gt=0)
            .values("stage_run_id")
            .annotate(tok=Sum("output_tokens"), sec=Sum("eval_seconds")))
    return {r["stage_run_id"]: round(r["tok"] / r["sec"], 1)
            for r in rows if r["tok"] and r["sec"]}


def _round_dict(rows: list[models.StageRun], now, calls_by_stage: dict, tps: dict,
                typical: dict, active: bool) -> dict:
    stages = [_stage_dict(s, now, calls_by_stage.get(s.id, []), tps.get(s.id), typical)
              for s in sorted(rows, key=lambda r: STAGE_NAMES.index(r.stage)
                              if r.stage in STAGE_NAMES else 99)]
    first = min((s["started_at"] for s in stages if s["started_at"]), default=None)
    last = max((s["finished_at"] for s in stages if s["finished_at"]), default=None)
    head = rows[0]
    return {
        "run_id": head.run_id, "source": head.source, "job_id": head.job_id,
        "active": active, "started_at": first,
        "finished_at": None if active else last,
        "interrupted": any(s["interrupted"] for s in stages),
        "stages": stages,
    }


def progress_snapshot() -> dict:
    """The whole page, in four indexed reads (plus the ghost sweep, throttled)."""
    usage.close_ghosts()
    now = timezone.now()

    open_rows = list(models.StageRun.objects.filter(status__in=("waiting", "running")))
    run_ids = list(dict.fromkeys(r.run_id for r in open_rows))
    active = bool(run_ids)
    if not run_ids:
        latest = models.StageRun.objects.order_by("-created_at").values_list(
            "run_id", flat=True).first()
        run_ids = [latest] if latest else []
    rows = list(models.StageRun.objects.filter(run_id__in=run_ids)) if run_ids else []

    stage_ids = [r.id for r in rows]
    open_calls = list(models.LLMCall.objects
                      .filter(status__in=("waiting", "running"), kind="chat")
                      .filter(Q(stage_run_id__in=stage_ids) | Q(stage_run_id__isnull=True))
                      .order_by("created_at"))
    by_stage: dict[int, list] = {}
    loose = []
    for c in open_calls:
        if c.stage_run_id:
            by_stage.setdefault(c.stage_run_id, []).append(c)
        else:
            loose.append(c)
    # Finished calls give each stage its tokens/s; asked only when idle rounds
    # are not the whole answer.
    tps = _local_speed_by_stage_run(stage_ids) if stage_ids else {}

    typical = _typical_tokens(open_calls)
    rounds = []
    for rid in run_ids:
        group = [r for r in rows if r.run_id == rid]
        if group:
            rounds.append(_round_dict(
                group, now, by_stage, tps, typical,
                active=any(r.status in ("waiting", "running") for r in group)))

    jobs = [{"id": j.id, "kind": j.kind, "kind_label": ops.JOB_KIND_LABELS.get(j.kind, j.kind),
             "status": j.status, "progress": j.progress, "message": j.message,
             "created_at": j.created_at}
            for j in models.Job.objects.filter(status__in=("queued", "running"))
            .exclude(kind="pipeline")]

    batches = [{"id": b.id, "kind": b.kind, "kind_label": b.get_kind_display(),
                "items": len(b.items or []), "status": b.status, "model": b.model,
                "submitted_at": b.submitted_at,
                "expected_by": b.submitted_at + timedelta(hours=24),
                "counts": b.counts or {}}
               for b in models.BatchRun.objects.filter(status__in=("submitted", "ended"))]

    return {
        "now": now, "running": active or bool(jobs) or bool(loose),
        "rounds": rounds,
        # Calls that belong to no stage of this round: a Job's, the chat's, a
        # command's. Shown as loose lines, never hidden.
        "other_calls": [dict(_item_dict(c, now, typical), process_label=process_label(c.process))
                        for c in loose[:MAX_ITEMS_SHOWN]],
        "jobs": jobs, "batches": batches,
    }


# ── the day's totals ────────────────────────────────────────────────────────

def process_label(process: str) -> str:
    """The name the client reads for a `process` label."""
    kind, _, name = process.partition(":")
    if kind == "pipeline":
        return STAGE_LABELS.get(name, name)
    if kind == "job":
        return ops.JOB_KIND_LABELS.get(name, name)
    if process == "web:chat":
        return "Chat sui contenuti"
    if process == "mcp:cerca":
        return "Ricerca dal connettore"
    if kind == "cmd":
        return f"Comando {name}"
    return "Altro"


def _day_bounds(day: str | None) -> tuple[datetime, datetime, str]:
    tz = timezone.get_current_timezone()
    try:
        d = datetime.strptime(day, "%Y-%m-%d").date() if day else timezone.localdate()
    except ValueError:
        d = timezone.localdate()
    start = datetime(d.year, d.month, d.day, tzinfo=tz)
    return start, start + timedelta(days=1), d.isoformat()


def daily_report(day: str | None = None) -> dict:
    """Machine hours per kind of process on one day (Rome time).

    "Machine hours" = time the local model held the lock (local chat calls) plus
    local transcription: the machine does one such job at a time, so seconds are
    NOT multiplied by the 18 cores. Waiting for the lock is shown apart.
    """
    start, end, label = _day_bounds(day)
    calls = models.LLMCall.objects.filter(created_at__gte=start, created_at__lt=end)

    local = (calls.filter(is_local=True)
             .values("process")
             .annotate(n=Count("id"),
                       machine=Sum("duration_seconds"), wait=Sum("wait_seconds"),
                       tin=Sum("prompt_tokens"), tout=Sum("output_tokens"),
                       failed=Count("id", filter=Q(status="failed")),
                       stt=Sum("duration_seconds", filter=Q(kind="stt")))
             .order_by("-machine"))
    by_process = [{
        "process": r["process"], "label": process_label(r["process"]),
        "calls": r["n"], "machine_seconds": round(r["machine"] or 0),
        "wait_seconds": round(r["wait"] or 0),
        "tokens_in": r["tin"] or 0, "tokens_out": r["tout"] or 0,
        "failed": r["failed"], "transcription_seconds": round(r["stt"] or 0),
    } for r in local]

    rem = calls.filter(is_local=False).aggregate(
        n=Count("id"), sec=Sum("duration_seconds"),
        tin=Sum("prompt_tokens"), tout=Sum("output_tokens"),
        failed=Count("id", filter=Q(status="failed")))
    remote = {"calls": rem["n"], "seconds": round(rem["sec"] or 0),
              "tokens_in": rem["tin"] or 0, "tokens_out": rem["tout"] or 0,
              "failed": rem["failed"]}

    return {"day": label, "by_process": by_process,
            "total_machine_seconds": sum(p["machine_seconds"] for p in by_process),
            "total_wait_seconds": sum(p["wait_seconds"] for p in by_process),
            "remote": remote, "speed": local_speed()}


def local_speed() -> dict:
    """Median tokens/s of the local calls of the last 24 hours, and the model."""
    since = timezone.now() - timedelta(hours=24)
    rows = list(models.LLMCall.objects
                .filter(is_local=True, kind="chat", status="done",
                        created_at__gte=since, eval_seconds__gt=0,
                        output_tokens__gt=0)
                .order_by("-created_at")
                .values("output_tokens", "eval_seconds", "model")[:200])
    if not rows:
        return {"tokens_per_second": None, "model": "", "samples": 0}
    return {"tokens_per_second": round(statistics.median(
        r["output_tokens"] / r["eval_seconds"] for r in rows), 1),
        "model": rows[0]["model"], "samples": len(rows)}
