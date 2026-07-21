"""
run_job
=======
Executor for a background Job (spawned detached by the API). Runs the work
for a Job row outside the web request, updating its status/progress so the
UI can poll and the global status bar can show progress.

    python manage.py run_job --job <id>

Dispatched by Job.kind. Currently: 'ideation'.
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Job


class Command(BaseCommand):
    help = "Run a queued background Job by id."

    def add_arguments(self, parser):
        parser.add_argument("--job", type=int, required=True)

    def handle(self, *args, **opts):
        try:
            job = Job.objects.get(id=opts["job"])
        except Job.DoesNotExist as exc:
            raise CommandError(f"job {opts['job']} not found") from exc

        job.status = "running"
        job.message = "Avvio…"
        job.progress = 1
        job.save(update_fields=["status", "message", "progress", "updated_at"])

        try:
            result = self._dispatch(job)
            job.status = "done"
            job.progress = 100
            job.message = job.message or "Completato"
            job.result = result or {}
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "progress", "message", "result",
                                    "finished_at", "updated_at"])
            self.stdout.write(self.style.SUCCESS(f"job {job.id} done: {result}"))
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error = repr(exc)[:2000]
            job.message = f"Errore: {str(exc)[:200]}"
            job.finished_at = timezone.now()
            job.save(update_fields=["status", "error", "message", "finished_at", "updated_at"])
            self.stderr.write(self.style.ERROR(f"job {job.id} failed: {exc!r}"))
            raise SystemExit(1)

    def _dispatch(self, job: Job) -> dict:
        if job.kind == "ideation":
            from core.ideation import generate_ideas
            n = int(job.params.get("n", 8))
            created = generate_ideas(n=n, job=job)
            return {"idea_ids": [c.id for c in created], "count": len(created)}
        raise CommandError(f"unknown job kind: {job.kind}")
