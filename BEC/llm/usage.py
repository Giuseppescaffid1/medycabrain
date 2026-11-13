"""
llm/usage.py
============
The recorder behind the "Avanzamento" page: one `LLMCall` row per attempt to
ask a model (or to transcribe one audio file). `llm/client.py` calls it from
the single place every request passes through, so the 16 callers of `chat()`
are not touched.

Rules that hold for every function here:

* **Recording never breaks a call.** Every write is wrapped: if the database
  does not answer, a warning goes to the log and the generation carries on. A
  dead database also trips a 30 s breaker, so a model call does not pay a
  connection timeout twice per request while it is down.
* **Numbers and short labels only.** No prompt, no answer, no transcript.
* **Failures stay failures.** A row closed by someone else (the process died)
  is `failed`; nothing here re-queues anything.

Who is calling (`process`, `stage`, `job`, `run_id`) lives in a contextvar AND
in a process-wide fallback. `enrich` and `knowledge` run their calls in a
thread pool, and a contextvar does not cross into a pool's threads: alone it
would lose the stage exactly where most calls happen. The pipeline and each
Job are a process of their own doing one stage at a time, so the fallback is
always right there. `ENRICH_WORKERS` threads share it read-only.

Which item (reel, article) is being worked on is a contextvar only, set by
`core/progress.py` inside each worker thread — each thread owns its item.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import os
import sys
import threading
import time
import uuid

logger = logging.getLogger(__name__)

# Tokens counted per chunk are written at most this often: at ~4 tok/s a 5 s
# interval would show jumps of 20.
TOKEN_WRITE_EVERY = 2.0
# After the database failed once, skip every write for this long.
BREAKER_SECONDS = 30.0
# A queued or running row older than this belongs to a process that is gone,
# even if its pid has been reused by another one.
GHOST_AFTER_SECONDS = 3 * 3600

_scope_var: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "llm_usage_scope", default=None)
_item_var: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "llm_usage_item", default=None)
# Tokens a remote provider reported for the call that just ended, read by the
# wrapper in client.py (the provider functions return plain strings).
_last_tokens: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "llm_usage_tokens", default=None)

_process_scope: dict | None = None
_lock = threading.Lock()
_breaker_until = 0.0


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


# ── who is calling ──────────────────────────────────────────────────────────

def _default_process() -> str:
    """`cmd:<name>` for a management command run by hand, else `altro`."""
    argv = sys.argv
    if len(argv) > 1 and os.path.basename(argv[0]) == "manage.py":
        return f"cmd:{argv[1]}"[:40]
    return "altro"


def current() -> dict:
    scope = _scope_var.get() or _process_scope
    if scope:
        return scope
    return {"process": _default_process(), "stage": "", "job_id": None,
            "run_id": "", "stage_run_id": None}


@contextlib.contextmanager
def scope(process: str, stage: str = "", job_id: int | None = None,
          run_id: str = "", stage_run_id: int | None = None,
          default: bool = False):
    """Label every model call made inside the block.

    Inner blocks inherit what they leave empty (a pipeline started by a Job
    keeps the Job's id). `default=True` only labels when nothing else does, so
    the reranker called from the chat stays `web:chat`.
    """
    global _process_scope
    outer = _scope_var.get() or _process_scope
    if default and outer:
        yield
        return
    outer = outer or {}
    new = {"process": process[:40], "stage": stage or "",
           "job_id": job_id if job_id is not None else outer.get("job_id"),
           "run_id": run_id or outer.get("run_id") or new_run_id(),
           "stage_run_id": stage_run_id}
    token = _scope_var.set(new)
    # The fallback is only set from the main thread (the pipeline, a Job). A web
    # server runs requests in threads, and a fallback shared among them would
    # let one request's label leak into another, and be restored out of order.
    main = threading.current_thread() is threading.main_thread()
    if main:
        with _lock:
            previous, _process_scope = _process_scope, new
    try:
        yield new
    finally:
        _scope_var.reset(token)
        if main:
            with _lock:
                _process_scope = previous


def set_item(kind: str, item_id: int | None, label: str) -> None:
    _item_var.set({"kind": kind[:8], "id": item_id, "label": (label or "")[:80]})


def clear_item() -> None:
    _item_var.set(None)


def note_tokens(prompt: int | None, output: int | None) -> None:
    """Called by a remote provider function with the `usage` it received."""
    with contextlib.suppress(Exception):
        _last_tokens.set({"prompt": _as_int(prompt), "output": _as_int(output)})


def _as_int(v) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# ── writing, never raising ──────────────────────────────────────────────────

def guard(label: str, fn, *args, **kwargs):
    """Run a database write; on any failure log and return None."""
    global _breaker_until
    if time.monotonic() < _breaker_until:
        return None
    try:
        from django.db import transaction
        # A savepoint: if a caller ever sits inside an atomic block, a failed
        # write must not poison the caller's transaction.
        with transaction.atomic():
            return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — recording is never fatal
        from django.db import InterfaceError, OperationalError
        if isinstance(exc, (OperationalError, InterfaceError)):
            _breaker_until = time.monotonic() + BREAKER_SECONDS
        logger.warning("[usage] %s non registrato: %r", label, exc)
        return None


def _reset_breaker() -> None:  # tests
    global _breaker_until
    _breaker_until = 0.0


class Call:
    """Handle on one `LLMCall` row. With no row (the database did not answer)
    every method does nothing, so callers never check."""

    def __init__(self, row_id: int | None, waiting: bool):
        self.row_id = row_id
        self._created = time.monotonic()
        self._started = None if waiting else self._created
        self._fields: dict = {}
        self._last_tokens_write = 0.0

    def _update(self, **fields):
        if self.row_id is None:
            return

        def _do():
            from core.models import LLMCall
            LLMCall.objects.filter(id=self.row_id).update(**fields)
        guard("aggiornamento", _do)

    def running(self) -> None:
        """The lock is ours: waiting is over, the model starts."""
        from django.utils import timezone
        self._started = time.monotonic()
        self._update(status="running", started_at=timezone.now(),
                     wait_seconds=round(self._started - self._created, 2))

    def tokens(self, n: int) -> None:
        now = time.monotonic()
        if now - self._last_tokens_write < TOKEN_WRITE_EVERY:
            return
        self._last_tokens_write = now
        self._update(tokens_so_far=n)

    def stats(self, **fields) -> None:
        """Remember numbers to write when the call ends (Ollama's last line)."""
        self._fields.update({k: v for k, v in fields.items() if v is not None})

    def done(self, truncated: bool = False, model: str = "") -> None:
        from django.utils import timezone
        end = time.monotonic()
        fields = dict(self._fields)
        truncated = bool(truncated or fields.pop("truncated", False))
        if model:
            fields["model"] = model[:80]
        if self._started is not None:
            fields["duration_seconds"] = round(end - self._started, 2)
        else:  # a remote call that never saw a lock: all of it was the call
            fields["duration_seconds"] = round(end - self._created, 2)
        self._update(status="done", finished_at=timezone.now(),
                     truncated=truncated, **fields)

    def done_remote(self, model: str = "") -> None:
        t = _last_tokens.get() or {}
        _last_tokens.set(None)
        self.stats(prompt_tokens=t.get("prompt"), output_tokens=t.get("output"))
        self.done(model=model)

    def fail(self, exc: BaseException) -> None:
        from django.utils import timezone
        msg = f"{type(exc).__name__}: {exc}"[:200]
        end = time.monotonic()
        self._update(status="failed", finished_at=timezone.now(), error=msg,
                     duration_seconds=round(end - (self._started or self._created), 2))


def begin(provider: str, model: str, is_local: bool, waiting: bool,
          max_tokens: int | None = None, prompt_chars: int | None = None,
          kind: str = "chat") -> Call:
    """Open the row. `waiting` is for the local model: it queues for a lock
    before it can start, and that wait is exactly what the page shows."""
    scope_ = current()
    item = _item_var.get() or {}

    def _do():
        from core.models import LLMCall
        from django.utils import timezone
        row = LLMCall.objects.create(
            kind=kind, process=scope_["process"], stage=scope_["stage"],
            job_id=scope_["job_id"], run_id=scope_["run_id"], pid=os.getpid(),
            stage_run_id=scope_["stage_run_id"],
            item_kind=item.get("kind", ""), item_id=item.get("id"),
            item_label=item.get("label", ""),
            provider=provider[:40], is_local=is_local, model=(model or "")[:80],
            status="waiting" if waiting else "running",
            started_at=None if waiting else timezone.now(),
            max_tokens=max_tokens, prompt_chars=prompt_chars,
        )
        return row.id

    return Call(guard("riga di chiamata", _do), waiting)


@contextlib.contextmanager
def stt(model: str, is_local: bool):
    """A transcription is not a `chat()` call, but it takes the same machine:
    its hours belong in the "Oggi" totals (decision of 2026-11-13)."""
    rec = begin("whisper-locale" if is_local else "whisper", model, is_local,
                waiting=False, kind="stt")
    try:
        yield rec
    except BaseException as exc:
        rec.fail(exc)
        raise
    rec.done()


# ── ghosts ──────────────────────────────────────────────────────────────────

_last_reap = 0.0


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    return os.path.exists(f"/proc/{pid}")


def close_ghosts(min_interval: float = 30.0) -> None:
    """Close rows left open by a process that died, as `failed`.

    Same idea as `views._reap_stale_jobs`: the dead cannot report their own
    death, so whoever reads the page does it. At most once per `min_interval`
    seconds — the page asks every 2 s and this is a write. Never re-queues.
    """
    global _last_reap
    now = time.monotonic()
    if now - _last_reap < min_interval:
        return
    _last_reap = now

    def _do():
        from datetime import timedelta

        from core.models import LLMCall, StageRun
        from django.utils import timezone
        old = timezone.now() - timedelta(seconds=GHOST_AFTER_SECONDS)
        for model_cls, msg in ((LLMCall, "processo interrotto"),
                               (StageRun, "giro interrotto")):
            rows = model_cls.objects.filter(status__in=("waiting", "running"))
            dead = [r.id for r in rows.only("id", "pid", "created_at")
                    if not _pid_alive(r.pid) or r.created_at < old]
            if dead:
                model_cls.objects.filter(id__in=dead).update(
                    status="failed", finished_at=timezone.now(), error=msg)
    guard("chiusura righe interrotte", _do)
