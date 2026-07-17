"""
run_pipeline
============
DAG entrypoint (cron calls this). Orchestrates the agent modules.

    python manage.py run_pipeline
    python manage.py run_pipeline --dry-run
    python manage.py run_pipeline --only scrape --limit 5
    python manage.py run_pipeline --skip-scrape --skip-cluster

Heavy imports (whisper, sentence-transformers, hdbscan) are deferred
inside each agent module, so --dry-run and --only scrape stay light.
"""

from django.core.management.base import BaseCommand

from pipeline.dag import DAG, Context, Step

STAGE_NAMES = ["scrape", "download", "transcribe", "enrich", "cluster"]


class Command(BaseCommand):
    help = "Run the medycabrain content-intelligence pipeline."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=None,
                            help="Cap rows processed per agent (backfill throttle).")
        parser.add_argument("--only", type=str, default="",
                            help="Comma list of stages to run: " + ",".join(STAGE_NAMES))
        for name in STAGE_NAMES:
            parser.add_argument(f"--skip-{name}", action="store_true")

    def handle(self, *args, **opts):
        # Deferred agent imports (kept out of module import time).
        from pipeline.agents import (
            cluster_agent, downloader_agent, enrich_agent,
            scraper_agent, transcriber_agent,
        )

        steps = [
            Step("scrape", scraper_agent.run),
            Step("download", downloader_agent.run),
            Step("transcribe", transcriber_agent.run),
            Step("enrich", enrich_agent.run),
            Step("cluster", cluster_agent.run),
        ]

        only = {s.strip() for s in opts["only"].split(",") if s.strip()}
        skip = {name for name in STAGE_NAMES if opts.get(f"skip_{name}")}

        ctx = Context(dry_run=opts["dry_run"], limit=opts["limit"])
        code = DAG(steps).run(ctx, only=only, skip=skip)
        if code != 0:
            raise SystemExit(code)
