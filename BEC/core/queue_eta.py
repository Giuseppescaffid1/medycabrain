"""
core/queue_eta.py
=================
"Quanti reel mancano, e quanto ci vuole."

The status page already showed how far each stage had got. It could not answer
the question the client actually asks — *quanto manca?* — because a percentage
does not say whether the remainder is ten minutes or ten hours.

Two numbers, both measured rather than guessed:

1. **How many.** The pending counts on the rows themselves, the same ones each
   agent selects from, carried forward through the stages: a reel waiting to be
   downloaded will also have to be transcribed and analysed, so it counts once
   per stage it has still to cross.
2. **How long.** Seconds per item, read from the completion lines the DAG
   writes into `logs/pipeline.log`. Only the most recent runs that actually
   processed something are used (`_RATE_RUNS`), because the per-item cost of
   this pipeline has changed by more than an order of magnitude as its models
   changed: transcription measured 245 s/reel on local faster-whisper and
   4.1 s/reel on remote STT. An average over all history would describe a
   machine that no longer exists.

Known limits, so nobody reads more into the estimate than it holds:

- **Download is the unreliable one.** Measured between 9 and 77 s/reel across
  runs, because the cost depends on how many urls Apify pre-filled (a cached
  CDN url is a plain fast fetch) and on whether Instagram starts throttling
  mid-run — in which case the run stops early and the rest waits for the next
  one. The estimate is the recent average, not a promise.
- **Silent reels skip transcription** (`transcribe_status='skipped'`), so the
  forward-carry counts a few items that will not actually be transcribed. The
  estimate is therefore slightly pessimistic, which is the right direction.
- **Failed rows are not counted as work.** They stay `failed` by design and
  are not auto-retried, so they are reported separately, never inside the ETA.
- **Stuck rows are not counted as work either — they are `blocked`.** A reel
  can say `pending` for a stage no agent will ever give it: a transcription
  waiting on a video that has no audio (the transcriber selects only
  `media_status=done` with an audio file), an analysis waiting on a
  transcription that failed. Counting them made "7 rimanenti" a number that
  never went down, however long the page was watched. Each stage's
  reachability below uses the same filters as its agent. Nothing is retried or
  re-marked here: blocked rows are only counted, and shown as such.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from django.conf import settings
from django.db.models import Count, Q

# Completion line written by pipeline/dag.py: "[ts UTC] ✓ <stage> done in <n>s — <dict>"
_DONE = re.compile(
    r"✓ (?P<stage>\w+) done in (?P<secs>[\d.]+)s — (?P<payload>\{.*\})\s*$"
)

# How many *productive* runs feed a rate. Small on purpose: see the module
# docstring — old runs describe a pipeline with different models in it.
_RATE_RUNS = 5
# Only the tail of the log is read. `/ops/status/` is polled every five seconds
# per open tab, and pipeline.log grows without bound — re-reading all of it on
# every poll would be the most expensive thing on the page. 2 MB is far more
# than the last few runs need.
_LOG_TAIL_BYTES = 2_000_000

# Parsing that tail is still wasted work when nothing has been appended since
# the last poll, which is the normal case between runs. Keyed on the log's size
# and mtime, so any new line invalidates it.
_rate_cache: dict = {"key": None, "value": {}}

# The reel stages, in the order a reel crosses them. For each: the status
# columns that gate it, the label the client sees, and the keys of the DAG
# result dict that say how many items that run actually handled.
#
# `enrich` carries two columns on purpose. Extracting the arguments is not a
# separate stage — `enrich_agent.run` analyses the reels and then extracts the
# claims inside the same step, and the log records one duration covering both.
# Giving the claims their own stage would count that duration twice, so they
# are counted as a second kind of item inside the stage that does the work.
REEL_STAGES = [
    ("download", ["media_status"], "Download dei video",
     ("downloaded", "failed", "skipped")),
    ("transcribe", ["transcribe_status"], "Trascrizione audio",
     ("transcribed", "failed")),
    ("enrich", ["enrich_status", "argument_status"], "Analisi dei contenuti",
     ("enriched", "arg_reels")),
]

# Which reels a stage's agent can ever pick up — the agents' own filters, in
# one place. A `pending` column outside this set is blocked, not queued.
# Written as functions because each one is built from the one before it: a
# reel still waiting to download will reach transcription once it has audio.
def _can_transcribe() -> Q:
    return Q(is_active=True) & (
        Q(media_status="pending") | (Q(media_status="done") & ~Q(audio_file="")))


def _can_enrich() -> Q:
    return Q(is_active=True) & (
        Q(transcribe_status__in=("done", "skipped"))
        | (Q(transcribe_status="pending") & _can_transcribe()))


def _can_argue() -> Q:
    return Q(is_active=True) & (
        Q(enrich_status="done") | (Q(enrich_status="pending") & _can_enrich()))


_REACHABLE = {
    "media_status": lambda: Q(is_active=True),
    "transcribe_status": _can_transcribe,
    "enrich_status": _can_enrich,
    "argument_status": _can_argue,
}

# Said to the client next to the number; plain words, one per stage.
_BLOCKED_WHY = {
    "download": "reel esclusi dall'analisi",
    "transcribe": "senza audio da trascrivere",
    "enrich": "trascrizione non riuscita o mancante",
}

# Used only until the log has a productive run for that stage to measure.
# Order-of-magnitude values from the runs recorded up to 2026-09-11.
_DEFAULT_RATES = {"download": 20.0, "transcribe": 10.0, "enrich": 10.0}


def _log_path() -> Path:
    return Path(settings.BASE_DIR) / "logs" / "pipeline.log"


def _measured_rates() -> dict[str, dict]:
    """Seconds per item for each stage, from the last productive runs.

    A run that processed zero items is skipped entirely: its duration is
    start-up cost, and averaging it in drags every estimate towards zero.
    """
    path = _log_path()
    if not path.exists():
        return {}
    try:
        stat = path.stat()
        key = (stat.st_size, stat.st_mtime_ns)
        if _rate_cache["key"] == key:
            return _rate_cache["value"]
        with path.open("rb") as fh:
            if stat.st_size > _LOG_TAIL_BYTES:
                fh.seek(stat.st_size - _LOG_TAIL_BYTES)
                fh.readline()  # drop the half line the seek landed inside
            lines = fh.read().decode("utf-8", errors="ignore").splitlines()
    except OSError:
        return {}

    keys = {key: item_keys for key, _cols, _l, item_keys in REEL_STAGES}
    samples: dict[str, list[tuple[float, int]]] = {}
    for line in lines:
        m = _DONE.search(line)
        if not m:
            continue
        stage = m.group("stage")
        if stage not in keys:
            continue
        try:
            payload = ast.literal_eval(m.group("payload"))
        except (ValueError, SyntaxError):
            continue
        if not isinstance(payload, dict):
            continue
        items = sum(int(payload.get(k) or 0) for k in keys[stage])
        if items <= 0:
            continue
        samples.setdefault(stage, []).append((float(m.group("secs")), items))

    rates = {}
    for stage, rows in samples.items():
        recent = rows[-_RATE_RUNS:]
        secs = sum(s for s, _ in recent)
        items = sum(n for _, n in recent)
        if items:
            rates[stage] = {"seconds_per_item": round(secs / items, 1),
                            "runs": len(recent), "source": "measured"}
    _rate_cache["key"], _rate_cache["value"] = key, rates
    return rates


def _reel_counts() -> dict[str, dict[str, int]]:
    """One query for every stage column, rather than one query per stage.

    This is served inside `/ops/status/`, which the page polls every five
    seconds per open tab. `pending` is what an agent can still pick up,
    `blocked` is pending that none ever will (see the module docstring).
    """
    from core.models import Reel

    cols = [c for _k, cols, _l, _i in REEL_STAGES for c in cols]
    aggs = {}
    for col in cols:
        reachable = _REACHABLE[col]()
        aggs[f"{col}__pending"] = Count("id", filter=Q(**{col: "pending"}) & reachable)
        aggs[f"{col}__blocked"] = Count("id", filter=Q(**{col: "pending"}) & ~reachable)
        aggs[f"{col}__failed"] = Count("id", filter=Q(**{col: "failed"}))
    agg = Reel.objects.aggregate(**aggs)
    return {col: {k: agg[f"{col}__{k}"] or 0 for k in ("pending", "blocked", "failed")}
            for col in cols}


def snapshot() -> dict:
    """What is left to process, and how long it should take.

    `remaining` is the headline: distinct reels with at least one stage still
    pending that an agent can reach; `blocked` counts the ones that cannot. Per stage, `waiting` carries the queue forward — a reel waiting to
    be downloaded is also waiting, later, to be transcribed.
    """
    from core.models import Reel

    rates = _measured_rates()
    counts = _reel_counts()

    stages, carry_reels, total_eta = [], 0, 0.0
    measured_any = False
    for key, cols, label, _item_keys in REEL_STAGES:
        pending = sum(counts[c]["pending"] for c in cols)
        failed = sum(counts[c]["failed"] for c in cols)
        # max, not sum: one stuck reel can be blocked in both columns of enrich
        blocked = max(counts[c]["blocked"] for c in cols)
        # Reels that will still arrive here from the stages before it. Each one
        # becomes as many items as this stage has columns: a reel reaching
        # `enrich` has both to be analysed and to have its claims extracted.
        items = pending + carry_reels * len(cols)

        rate_info = rates.get(key)
        rate = rate_info["seconds_per_item"] if rate_info else _DEFAULT_RATES[key]
        measured_any = measured_any or bool(rate_info)
        eta = items * rate
        total_eta += eta
        stages.append({
            "key": key,
            "label": label,
            "pending": pending,        # queued at this stage right now
            "waiting": items,          # items it will handle before draining
            "failed": failed,
            "blocked": blocked,
            "blocked_reason": _BLOCKED_WHY.get(key, "") if blocked else "",
            "seconds_per_item": round(rate, 1),
            "eta_seconds": round(eta),
            "measured": bool(rate_info),
            "runs": rate_info["runs"] if rate_info else 0,
        })
        # Reels — not items — flow on: how many items a reel becomes at the
        # next stage is that stage's own business. With more than one column a
        # reel can sit in several of them at once, so take the largest column
        # rather than the sum, which would carry the same reel forward twice.
        carry_reels += max(counts[c]["pending"] for c in cols)

    reachable_q, pending_q = Q(), Q()
    for _k, cols, _l, _i in REEL_STAGES:
        for col in cols:
            pending_q |= Q(**{col: "pending"})
            reachable_q |= Q(**{col: "pending"}) & _REACHABLE[col]()
    remaining = Reel.objects.filter(reachable_q).count()
    # Pending somewhere, and nothing it is waiting on can ever run.
    blocked = Reel.objects.filter(pending_q).exclude(reachable_q).count()

    return {
        "remaining": remaining,
        "blocked": blocked,
        "blocked_reasons": sorted({s["blocked_reason"] for s in stages if s["blocked_reason"]}),
        "total": Reel.objects.count(),
        "eta_seconds": round(total_eta),
        # False when no stage has a measured rate yet: the UI must say the
        # number is a default, not a measurement.
        "measured": measured_any,
        "failed": sum(s["failed"] for s in stages),
        "stages": stages,
    }
