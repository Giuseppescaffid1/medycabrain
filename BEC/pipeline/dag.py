"""
pipeline/dag.py
===============
Lightweight custom DAG runner — the "system of agents" orchestration.

Not a real DAG library: a linear, ordered sequence of named steps wrapped
by a runner that collects failures and prints banners, mirroring the SPI
pipeline.py pattern. Every step is non-fatal by default: because each
agent only processes rows in its own `pending` state, a failed scrape
still lets yesterday's downloads get transcribed, etc.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _header(msg: str):
    print(f"\n{'=' * 68}\n  {msg}\n{'=' * 68}", flush=True)


def _step(msg: str):
    print(f"\n[{_ts()}] ▶ {msg}", flush=True)


def _ok(msg: str):
    print(f"[{_ts()}] ✓ {msg}", flush=True)


def _fail(msg: str):
    print(f"[{_ts()}] ✗ {msg}", flush=True)


@dataclass
class Context:
    dry_run: bool = False
    limit: int | None = None
    stats: dict = field(default_factory=dict)


@dataclass
class Step:
    name: str
    fn: Callable[[Context], dict]
    fatal: bool = False


class DAG:
    def __init__(self, steps: list[Step]):
        self.steps = steps

    def run(self, ctx: Context, only: set[str] | None = None,
            skip: set[str] | None = None,
            on_step: Callable[[int, int, str], None] | None = None) -> int:
        """Run the steps in order.

        `on_step(index, total, stage)` is called as each stage begins, so a
        caller that is not a terminal — a `Job` row the UI polls — can report
        progress. It is optional and never fatal: the cron entrypoint passes
        nothing and behaves exactly as before.
        """
        only = only or set()
        skip = skip or set()
        failed: list[str] = []
        planned = [s for s in self.steps
                   if (not only or s.name in only) and s.name not in skip]

        _header(f"medycabrain pipeline — {'DRY RUN' if ctx.dry_run else 'LIVE'}")
        for step in self.steps:
            if only and step.name not in only:
                continue
            if step.name in skip:
                print(f"[{_ts()}] ⤳ skipping {step.name}", flush=True)
                continue

            if on_step:
                try:
                    on_step(planned.index(step), len(planned), step.name)
                except Exception as exc:  # noqa: BLE001 — reporting is never fatal
                    print(f"[{_ts()}] ! progress report failed: {exc!r}", flush=True)

            _step(f"agent: {step.name}")
            if ctx.dry_run:
                _ok(f"{step.name} (dry-run, no-op)")
                continue

            t0 = time.time()
            try:
                result = step.fn(ctx) or {}
                ctx.stats[step.name] = result
                dt = time.time() - t0
                _ok(f"{step.name} done in {dt:.1f}s — {result}")
            except Exception as exc:  # noqa: BLE001
                failed.append(step.name)
                _fail(f"{step.name} FAILED: {exc!r}")
                if step.fatal:
                    _fail("fatal step failed — aborting pipeline")
                    break

        _header("pipeline summary")
        for name, res in ctx.stats.items():
            print(f"  {name}: {res}", flush=True)
        if failed:
            _fail(f"failed steps: {', '.join(failed)}")
            return 1
        _ok("all steps completed")
        return 0


# The pipeline itself: the ordered stages and how to build them. It lives here
# rather than in the management command because there are now two callers — the
# cron entrypoint (`manage.py run_pipeline`) and the run the client starts from
# the interface (a `Job` of kind "pipeline") — and two copies of this list would
# eventually disagree about what "the pipeline" is.
STAGE_NAMES = ["scrape", "download", "transcribe", "batch", "enrich", "embed",
               "blogscrape", "knowledge", "cluster"]

# What each stage is called on the client's screen. Same words as core/ops.py.
STAGE_LABELS = {
    "scrape": "Raccolta da Instagram",
    "download": "Download dei video",
    "transcribe": "Trascrizione audio",
    "enrich": "Analisi dei contenuti",
    "embed": "Indicizzazione per la ricerca",
    "blogscrape": "Scoperta articoli blog",
    "knowledge": "Analisi degli articoli",
    "cluster": "Raggruppamento per tema",
}


def build_steps() -> list[Step]:
    """The eight agents, in order.

    Imports are deferred to call time on purpose: the agent modules pull in
    whisper, sentence-transformers and hdbscan, and importing those at module
    load would make every `manage.py` command — and every web request that
    touches this file — pay for them.
    """
    from pipeline.agents import (
        batch_agent, blogscrape_agent, cluster_agent, downloader_agent,
        embed_agent, enrich_agent, knowledge_agent, scraper_agent,
        transcriber_agent,
    )

    return [
        Step("scrape", scraper_agent.run),
        Step("download", downloader_agent.run),
        Step("transcribe", transcriber_agent.run),
        # Batch before enrich, and collect before submit inside it: answers
        # that are ready land first, then everything still pending is handed
        # over at half price. What the batch could not take (batch disabled,
        # delivery refused) stays `pending` and `enrich` does it live tonight
        # — so the live stage is now the fallback, not the main road.
        Step("batch", batch_agent.run),
        Step("enrich", enrich_agent.run),
        Step("embed", embed_agent.run),
        Step("blogscrape", blogscrape_agent.run),
        Step("knowledge", knowledge_agent.run),
        Step("cluster", cluster_agent.run),
    ]
