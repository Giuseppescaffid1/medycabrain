"""
core/pipeline_run.py
====================
The pipeline, started by the client instead of by cron.

Same eight agents, same order, same idempotent per-row state — the only new
things here are the two that a person watching a screen needs and a crontab
does not:

1. **Progress on a `Job` row**, so the interface can show which stage is
   running without reading a log file.
2. **The output still goes to `logs/pipeline.log`.** A detached job writes to
   its own file (`logs/jobs/job-<id>.log`), and everything that reports on the
   pipeline — the run timeline in `core/ops.py`, the per-item rates in
   `core/queue_eta.py` — is built by reading `pipeline.log`. A manual run that
   wrote elsewhere would be invisible to exactly the screen that started it,
   and would drag every estimate towards the last cron run instead of the most
   recent work. So stdout is teed into both.

Only one run at a time. Two concurrent runs are not merely wasteful: the
downloader paces itself against Instagram's quota, and a second run doubles the
request rate against a limit that is already the bottleneck. The caller
(`core/views.py`) refuses to start one when another is alive.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)


class _Tee:
    """Write to the job's own log and to `pipeline.log` at once."""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, data):
        for s in self._streams:
            try:
                s.write(data)
            except (OSError, ValueError):  # a closed stream must not kill the run
                pass
        return len(data)

    def flush(self):
        for s in self._streams:
            with contextlib.suppress(OSError, ValueError):
                s.flush()

    def isatty(self):
        return False


def run_pipeline_job(job, only: list[str] | None = None,
                     limit: int | None = None) -> dict:
    """Run the DAG for a `Job`, reporting each stage as it starts."""
    import sys

    from pipeline.dag import DAG, STAGE_LABELS, Context, build_steps

    only_set = {s for s in (only or []) if s}
    steps = build_steps()
    ctx = Context(limit=limit)

    def on_step(index: int, total: int, stage: str):
        # 5–95%: the bar must not sit at 0 while the first (often longest)
        # stage runs, nor claim 100% before the summary is written.
        pct = 5 + int(90 * index / max(total, 1))
        job.set_progress(pct, STAGE_LABELS.get(stage, stage))

    log_path = Path(settings.BASE_DIR) / "logs" / "pipeline.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", buffering=1) as pipeline_log:
        with contextlib.redirect_stdout(_Tee(sys.stdout, pipeline_log)):
            code = DAG(steps).run(ctx, only=only_set, on_step=on_step)

    stats = ctx.stats
    done_stages = list(stats)
    # A stage only lands in ctx.stats when it succeeds, so whatever was planned
    # and is missing from it is what failed.
    planned = [s.name for s in steps if not only_set or s.name in only_set]
    failed = [name for name in planned if name not in stats]

    if code == 0:
        job.set_progress(100, "Aggiornamento completato.")
    else:
        # Not a failed job: every stage is non-fatal by design, and the stages
        # that did run really did their work. Say which ones did not, rather
        # than throwing away a run that was mostly successful.
        labels = ", ".join(STAGE_LABELS.get(n, n) for n in failed)
        job.set_progress(100, f"Completato, ma senza: {labels}")
        logger.warning("[pipeline] run dall'interfaccia: passaggi non riusciti: %s",
                       ", ".join(failed) or "?")
    return {"exit_code": code, "stages": done_stages, "failed_stages": failed,
            "stats": stats}
