"""
core/management/commands/progress.py
====================================
Live progress of the pipeline, one bar per stage, with a real ETA.

The web page at /stato answers "is anything moving" for the client. This
answers "how long until it is done" for whoever is watching the run, in a
terminal, without tailing a log and doing arithmetic.

The rate is measured, not assumed: each refresh feeds tqdm the actual number
of reels that changed state, so the ETA reflects what the machine is doing
right now rather than a constant written down weeks ago. A stage that is not
running simply shows no rate, which is the honest answer.

Read-only. Safe to run at any time, including against a live pipeline.
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from django.db.models import Count
from tqdm import tqdm

from core.models import Reel

# Order matters: it is the order a reel actually travels through.
STAGES = [
    ("Download video", "media_status"),
    ("Trascrizione  ", "transcribe_status"),
    ("Analisi       ", "enrich_status"),
    ("Affermazioni  ", "argument_status"),
]

# Seconds per reel, measured on 2026-07-27. Used only for the overall
# estimate before any movement has been observed; once reels start changing
# state the bars use the live rate instead.
NOMINAL = {"media_status": 10.0, "transcribe_status": 2.9,
           "enrich_status": 3.6, "argument_status": 3.6}


def _counts(field: str) -> tuple[int, int]:
    """(finished, total) for a stage. 'skipped' is finished: it will not move."""
    rows = dict(Reel.objects.values_list(field).annotate(n=Count("id")))
    total = sum(rows.values())
    return rows.get("done", 0) + rows.get("skipped", 0), total


class Command(BaseCommand):
    help = "Barra di avanzamento dal vivo della pipeline, con stima del tempo residuo."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=float, default=5.0,
                            help="secondi fra un aggiornamento e il successivo")
        parser.add_argument("--once", action="store_true",
                            help="stampa lo stato una volta sola ed esce")

    def handle(self, *args, **opts):
        bars = []
        for i, (label, field) in enumerate(STAGES):
            done, total = _counts(field)
            bars.append(tqdm(
                total=total, initial=done, position=i, desc=label,
                unit="reel", leave=True, dynamic_ncols=True,
                # No space before {postfix}: tqdm already prefixes it with ", ".
                bar_format="{desc} {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt}{postfix}",
            ))
        # tqdm's own rate stays unknown here: it smooths over update() calls,
        # and a stage that yields a handful of reels a minute never gives it
        # enough to work with. Measuring over our own window is both more
        # reliable and more truthful about how long the run has been watched.
        history: list[tuple[float, dict[str, int]]] = []
        WINDOW = 180.0

        summary = tqdm(total=0, position=len(STAGES), bar_format="{desc}", leave=True)
        try:
            while True:
                now = time.monotonic()
                snapshot = {f: _counts(f) for _label, f in STAGES}
                history.append((now, {f: v[0] for f, v in snapshot.items()}))
                # Keep only the recent past: a rate averaged over the whole
                # session would keep reporting a stage that stopped an hour ago.
                history[:] = [h for h in history if now - h[0] <= WINDOW] or history[-1:]

                remaining = 0
                for bar, (_label, field) in zip(bars, STAGES):
                    done, total = snapshot[field][0], snapshot[field][1]
                    bar.total = total
                    # tqdm counts increments, so feed it the change since the
                    # last look; a stage can only move forward.
                    if done > bar.n:
                        bar.update(done - bar.n)
                    else:
                        bar.refresh()

                    t0, counts0 = history[0]
                    dt, dn = now - t0, done - counts0[field]
                    rate = dn / dt if dt > 5 and dn > 0 else 0.0
                    left = max(total - done, 0)
                    eta = left / rate if rate else left * NOMINAL[field]
                    remaining += eta
                    bar.set_postfix_str(
                        f"{rate * 60:.1f} reel/min · {eta / 60:.0f} min" if rate
                        else (f"fermo · stima {eta / 60:.0f} min" if left else "completato"),
                        refresh=True,
                    )

                summary.set_description_str(
                    f"  tempo stimato al termine: {remaining / 60:.0f} min "
                    f"({remaining / 3600:.1f} ore)"
                )
                if opts["once"]:
                    break
                time.sleep(opts["interval"])
        except KeyboardInterrupt:
            pass
        finally:
            summary.close()
            for bar in bars:
                bar.close()
            self.stdout.write("")
