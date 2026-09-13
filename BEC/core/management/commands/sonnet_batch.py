"""
manage.py sonnet_batch — drive the batch by hand.

The nightly pipeline runs `collect` then `submit` on its own (the `batch`
stage). This command is for the times you want to look: clear a backlog now,
check what is in flight, or pick up an answer without waiting for 3am.

    manage.py sonnet_batch --status              # what is in flight
    manage.py sonnet_batch --submit --limit 2    # hand over 2, to try it out
    manage.py sonnet_batch --collect             # pick up whatever is ready
    manage.py sonnet_batch --live --limit 224    # do it now, live calls, full price
    manage.py sonnet_batch --cancel <batch_id>

`--live` is the escape hatch: same work, immediate answers, twice the price.
Use it to clear a backlog you do not want to wait a night for.
"""

from django.core.management.base import BaseCommand

from core.models import BATCHED, BatchRun


class Command(BaseCommand):
    help = "Consegna, ritira o controlla le analisi affidate al batch di Anthropic."

    def add_arguments(self, parser):
        parser.add_argument("--submit", action="store_true",
                            help="consegna le analisi ancora da fare")
        parser.add_argument("--collect", action="store_true",
                            help="ritira le risposte pronte")
        parser.add_argument("--status", action="store_true",
                            help="mostra le consegne aperte")
        parser.add_argument("--live", action="store_true",
                            help="esegui subito con chiamate normali (prezzo pieno)")
        parser.add_argument("--cancel", metavar="BATCH_ID",
                            help="annulla una consegna in corso")
        parser.add_argument("--retry-failed", action="store_true",
                            help="rimetti in coda le analisi fallite (azione "
                                 "deliberata: per regola i falliti restano falliti)")
        parser.add_argument("--redo-model", metavar="PREFISSO", default="",
                            help="rimetti in coda le analisi prodotte da un modello "
                                 "scadente (es. 'ollama'), cosi' il prossimo batch "
                                 "le rifa' a meta' prezzo")
        parser.add_argument("--limit", type=int, default=None)

    def handle(self, *args, **opts):
        from llm import batch as batch_api
        from pipeline.agents import batch_agent

        if opts["cancel"]:
            self.stdout.write(f"stato: {batch_api.cancel(opts['cancel'])}")
            return

        if opts["status"]:
            runs = BatchRun.objects.all()[:10]
            if not runs:
                self.stdout.write("nessuna consegna registrata")
            for r in runs:
                live = ""
                if r.status in ("submitted", "ended"):
                    try:
                        live = f"  → {batch_api.status(r.batch_id)}"
                    except Exception as exc:  # noqa: BLE001
                        live = f"  → stato illeggibile: {exc!r}"
                self.stdout.write(
                    f"{r.submitted_at:%Y-%m-%d %H:%M}  {r.batch_id}  {r.status}  "
                    f"{len(r.items)} elementi  {r.model}{live}")
            from core.models import Reel
            self.stdout.write(
                f"\nreel in volo (stato '{BATCHED}'): "
                f"{Reel.objects.filter(enrich_status=BATCHED).count()}")
            return

        if opts["retry_failed"]:
            # The project rule is that failures stay failed — nothing requeues
            # them automatically, or a broken provider would be retried every
            # night forever. This flag is the human saying "now try again".
            from core.models import FAILED, PENDING, Reel
            n = Reel.objects.filter(enrich_status=FAILED, is_active=True).update(
                enrich_status=PENDING, last_error="")
            self.stdout.write(self.style.WARNING(
                f"{n} analisi fallite rimesse in coda"))

        if opts["redo_model"]:
            # Rows that are DONE but were produced by a weaker model. They are
            # not failures, so nothing would ever revisit them: this is how a
            # degraded stretch of the corpus gets redone, deliberately, and at
            # batch price rather than live price.
            from core.models import PENDING, Reel
            n = Reel.objects.filter(
                enrich_status="done", is_active=True,
                enrichment__llm_model__startswith=opts["redo_model"],
            ).update(enrich_status=PENDING)
            self.stdout.write(self.style.WARNING(
                f"{n} analisi prodotte da '{opts['redo_model']}*' rimesse in coda"))

        if opts["live"]:
            # Deliberately the ordinary live stage, so there is exactly one
            # code path for immediate analysis — no second implementation to
            # drift from it.
            from pipeline.agents import enrich_agent
            from pipeline.dag import Context
            res = enrich_agent.run(Context(limit=opts["limit"]))
            self.stdout.write(self.style.SUCCESS(f"live: {res}"))
            return

        if opts["collect"]:
            self.stdout.write(self.style.SUCCESS(f"ritiro: {batch_agent.collect()}"))
        if opts["submit"]:
            self.stdout.write(self.style.SUCCESS(
                f"consegna: {batch_agent.submit(limit=opts['limit'])}"))
        if not any((opts["collect"], opts["submit"])):
            self.stdout.write("niente da fare: usa --submit, --collect, --status o --live")
