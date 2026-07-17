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

    def run(self, ctx: Context, only: set[str] | None = None, skip: set[str] | None = None) -> int:
        only = only or set()
        skip = skip or set()
        failed: list[str] = []

        _header(f"medycabrain pipeline — {'DRY RUN' if ctx.dry_run else 'LIVE'}")
        for step in self.steps:
            if only and step.name not in only:
                continue
            if step.name in skip:
                print(f"[{_ts()}] ⤳ skipping {step.name}", flush=True)
                continue

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
