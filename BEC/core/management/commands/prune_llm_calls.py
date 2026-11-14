"""
prune_llm_calls
===============
Delete the per-call detail (`llm_calls`) and per-stage rows (`stage_runs`)
older than LLM_CALL_RETENTION_DAYS (default 90). Daily totals older than that
are lost with them: there is no summary table in v1.

    python manage.py prune_llm_calls
    python manage.py prune_llm_calls --days 30 --dry-run

Runs from cron, once a day; never from the page that reads the data.
Rows still `waiting`/`running` are kept whatever their age: closing them is the
ghost sweep's job (`llm.usage.close_ghosts`), and deleting an open row would
hide it instead of marking it failed.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import LLMCall, StageRun


class Command(BaseCommand):
    help = "Delete llm_calls and stage_runs older than the retention window."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=None,
                            help="Override LLM_CALL_RETENTION_DAYS.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        days = opts["days"] if opts["days"] is not None else settings.LLM_CALL_RETENTION_DAYS
        cutoff = timezone.now() - timedelta(days=days)
        closed = ("done", "failed")
        calls = LLMCall.objects.filter(created_at__lt=cutoff, status__in=closed)
        stages = StageRun.objects.filter(created_at__lt=cutoff, status__in=closed)
        n_calls, n_stages = calls.count(), stages.count()
        if not opts["dry_run"]:
            calls.delete()
            stages.delete()
        verb = "da cancellare" if opts["dry_run"] else "cancellate"
        self.stdout.write(f"llm_calls {verb}: {n_calls}, stage_runs {verb}: {n_stages} "
                          f"(più vecchie di {days} giorni)")
