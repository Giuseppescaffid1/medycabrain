"""
core/progress.py
================
The "how far along is this stage" counter behind the Avanzamento page — the
numbers tqdm would print (done / total, speed, elapsed, remaining), kept in
`stage_runs` so a browser can read them.

Why it exists: only the agent knows how many items its round covers (the list
is built in memory and dropped), and counting rows by status gives wrong
answers on the download stage (see `StageRun`). So each agent declares:

    progress.open(total, unit, phase)      # "this phase has N items"
    progress.start_item(kind, id, label)   # "I begin this one"
    progress.item_done("done"|"failed"|"skipped")

`pipeline/dag.py` creates one row per planned stage (`plan_stages`), binds the
running one (`bind`) and closes it (`end_stage`).

Rules, same as `llm/usage.py`:

* **Never stops a stage.** Every write goes through `usage.guard`; with the
  database down the stage carries on and the bar simply does not move.
* **Throttled**: one write per stage every 2 s, plus one when a phase opens or
  closes. Several threads (ENRICH_WORKERS) count on the same stage, so the
  counters are behind a lock.
* **No stage bound = no-op.** A Job or a manual command that calls an agent
  function directly has no bar; `start_item` still labels the model calls so
  they show the item's name.
* No owner, no content: only short names.
"""

from __future__ import annotations

import logging
import os
import threading
import time

from llm import usage

logger = logging.getLogger(__name__)

FLUSH_EVERY = 2.0

_lock = threading.Lock()
_state: dict = {}


def _fresh(stage_run_id: int) -> dict:
    return {"id": stage_run_id, "total": None, "done": 0, "failed": 0, "skipped": 0,
            "unit": "", "phase": "", "phases": [], "current": {}, "note": "",
            "phase_started": None, "last_flush": 0.0}


def plan_stages(run_id: str, stages: list[str], source: str,
                job_id: int | None = None) -> dict[str, int]:
    """One `waiting` row per stage of the round, so the page also shows what
    is still to come. Returns stage -> row id (empty if the database is down)."""
    def _do():
        from core.models import StageRun
        rows = StageRun.objects.bulk_create([
            StageRun(run_id=run_id, stage=s, source=source, job_id=job_id,
                     pid=os.getpid()) for s in stages])
        return {r.stage: r.id for r in rows}
    return usage.guard("piano degli stadi", _do) or {}


def drop_waiting(run_id: str) -> None:
    def _do():
        from core.models import StageRun
        StageRun.objects.filter(run_id=run_id, status="waiting").delete()
    usage.guard("pulizia degli stadi non partiti", _do)


def bind(stage_run_id: int | None) -> None:
    """The stage that is about to run. Counters restart from zero."""
    global _state
    with _lock:
        _state = _fresh(stage_run_id) if stage_run_id else {}
    if stage_run_id:
        from django.utils import timezone
        _write({"status": "running", "started_at": timezone.now(),
                "pid": os.getpid()})


def end_stage(status: str, error: str = "") -> None:
    """Close the stage (`done`/`failed`) with its final numbers."""
    from django.utils import timezone
    global _state
    with _lock:
        if not _state:
            return
        _close_phase_locked()
        fields = _snapshot_locked()
        fields["current"] = {}
        _state = {}
    sid = fields.pop("_id")
    fields.update(status=status, error=error[:300], finished_at=timezone.now())
    _write(fields, sid=sid)


def _snapshot_locked() -> dict:
    s = _state
    return {"_id": s["id"], "total": s["total"], "done": s["done"],
            "failed": s["failed"], "skipped": s["skipped"], "unit": s["unit"],
            "phase": s["phase"], "phases": list(s["phases"]),
            "current": dict(s["current"]), "note": s["note"]}


def _close_phase_locked() -> None:
    s = _state
    if not s.get("phase") and s["total"] is None and not s["done"] + s["failed"] + s["skipped"]:
        return
    seconds = round(time.monotonic() - s["phase_started"]) if s["phase_started"] else 0
    s["phases"].append({"phase": s["phase"], "total": s["total"], "done": s["done"],
                        "failed": s["failed"], "skipped": s["skipped"],
                        "unit": s["unit"], "seconds": seconds})


def _write(fields: dict, sid: int | None = None) -> None:
    from django.utils import timezone
    sid = sid or (_state.get("id") if _state else None)
    if not sid:
        return

    def _do():
        from core.models import StageRun
        StageRun.objects.filter(id=sid).update(updated_at=timezone.now(), **fields)
    usage.guard("avanzamento", _do)


def _flush(force: bool = False) -> None:
    with _lock:
        if not _state:
            return
        now = time.monotonic()
        if not force and now - _state["last_flush"] < FLUSH_EVERY:
            return
        _state["last_flush"] = now
        fields = _snapshot_locked()
    sid = fields.pop("_id")
    _write(fields, sid=sid)


def open(total: int | None, unit: str, phase: str = "") -> None:  # noqa: A001
    """Declare a phase: `total` items of `unit`. A phase already open is
    closed first and kept in `phases`."""
    from django.utils import timezone
    with _lock:
        if not _state:
            return
        _close_phase_locked()
        s = _state
        s.update(total=total, done=0, failed=0, skipped=0, unit=unit, phase=phase,
                 current={}, phase_started=time.monotonic(), last_flush=time.monotonic())
        fields = _snapshot_locked()
    sid = fields.pop("_id")
    fields["phase_started_at"] = timezone.now()
    _write(fields, sid=sid)


def describe(obj) -> tuple[str, int | None, str]:
    """(kind, id, short label) of a reel, article, account, blog source or
    upload. Never raises: a label is decoration, and an unknown object just
    gets an empty one."""
    try:
        name = type(obj).__name__
        if name == "Reel":
            return "reel", obj.id, f"@{obj.account.username} · {obj.shortcode}"
        if name == "KnowledgeDocument":
            return "article", obj.id, obj.title or obj.source_url
        if name == "TrackedAccount":
            return "account", obj.id, f"@{obj.username}"
        if name == "BlogSource":
            return "source", obj.id, obj.name
        if name == "UploadedMedia":
            return "upload", obj.id, obj.original_name
    except Exception:  # noqa: BLE001
        pass
    return "", getattr(obj, "id", None), ""


def start_item(kind: str, item_id: int | None, label: str, who: str = "") -> None:
    """Begin one item. Labels the model calls made from this thread with the
    item's name, and — for stages that do not call a model — shows it as
    "sta lavorando su". Call it inside the worker thread, not in the loop that
    collects results: there, results arrive in order and late."""
    usage.set_item(kind, item_id, label)
    with _lock:
        if not _state:
            return
        _state["current"] = {"kind": kind, "id": item_id, "label": (label or "")[:80],
                             "who": who}
    _flush()


def who(text: str) -> None:
    """Say who does the current item (e.g. "Whisper remoto")."""
    with _lock:
        if _state and _state["current"]:
            _state["current"]["who"] = text


def item_done(outcome: str = "done") -> None:
    """One item finished: `done`, `failed` or `skipped`."""
    usage.clear_item()
    with _lock:
        if not _state:
            return
        key = outcome if outcome in ("failed", "skipped") else "done"
        _state[key] += 1
    _flush()


def note(text: str) -> None:
    """A short remark on the stage, e.g. "fermato: quota Instagram esaurita"."""
    with _lock:
        if not _state:
            return
        _state["note"] = text[:200]
    _flush(force=True)


def is_bound() -> bool:
    return bool(_state)


def snapshot_counts() -> dict:
    """For tests."""
    with _lock:
        return dict(_state)
