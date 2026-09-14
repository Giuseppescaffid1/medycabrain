"""
manage.py sonnet_batch — drive the batch by hand.

The nightly pipeline runs `collect` then `submit` on its own (the `batch`
stage). This command is for the times you want to look: clear a backlog now,
check what is in flight, or pick up an answer without waiting for 3am.

    manage.py sonnet_batch --status
    manage.py sonnet_batch --submit --kind doc_enrich --limit 5
    manage.py sonnet_batch --collect
    manage.py sonnet_batch --retry-failed --kind doc_enrich
    manage.py sonnet_batch --redo-model ollama          # reel analisi scadenti
    manage.py sonnet_batch --live                       # subito, prezzo pieno
    manage.py sonnet_batch --cancel <batch_id>

Kinds (see batch_agent.KINDS): `reel_enrich`, `doc_enrich`, `doc_arguments`,
or `all` (the default).

`--live` is the escape hatch: same work, immediate answers, twice the price.
"""

from django.core.management.base import BaseCommand, CommandError

from core.models import BATCHED, BatchRun, KnowledgeDocument, Reel

# Which model class and status column each kind touches — used by the retry
# flags, which work on the rows rather than on the batch.
_ROWS = {
    "reel_enrich": (Reel, "enrich_status"),
    "doc_enrich": (KnowledgeDocument, "enrich_status"),
    "doc_arguments": (KnowledgeDocument, "argument_status"),
}


class Command(BaseCommand):
    help = "Consegna, ritira o controlla le analisi affidate al batch di Anthropic."

    def add_arguments(self, parser):
        parser.add_argument("--submit", action="store_true",
                            help="consegna il lavoro ancora da fare")
        parser.add_argument("--collect", action="store_true",
                            help="ritira le risposte pronte")
        parser.add_argument("--status", action="store_true",
                            help="mostra le consegne aperte e quanto resta")
        parser.add_argument("--live", action="store_true",
                            help="esegui subito con chiamate normali (prezzo pieno)")
        parser.add_argument("--cancel", metavar="BATCH_ID",
                            help="annulla una consegna in corso")
        parser.add_argument("--kind", default="all",
                            help="reel_enrich | doc_enrich | doc_arguments | all")
        parser.add_argument("--retry-failed", action="store_true",
                            help="rimetti in coda i falliti (azione deliberata: "
                                 "per regola i falliti restano falliti)")
        parser.add_argument("--redo-model", metavar="PREFISSO", default="",
                            help="rimetti in coda le analisi di reel prodotte da "
                                 "un modello scadente (es. 'ollama')")
        parser.add_argument("--limit", type=int, default=None)

    def _kinds(self, opts):
        from pipeline.agents.batch_agent import KINDS

        if opts["kind"] == "all":
            return list(KINDS)
        if opts["kind"] not in KINDS:
            raise CommandError(
                f"tipo sconosciuto {opts['kind']!r}: usa {', '.join(KINDS)} o 'all'")
        return [opts["kind"]]

    def handle(self, *args, **opts):
        from core.models import DONE, FAILED, PENDING
        from llm import batch as batch_api
        from pipeline.agents import batch_agent

        if opts["cancel"]:
            self.stdout.write(f"stato: {batch_api.cancel(opts['cancel'])}")
            return

        if opts["status"]:
            self._status(batch_api)
            return

        if opts["retry_failed"]:
            # The project rule is that failures stay failed — nothing requeues
            # them automatically, or a broken provider would be retried every
            # night forever. This flag is the human saying "now try again".
            for k in self._kinds(opts):
                model_cls, field = _ROWS[k]
                n = model_cls.objects.filter(
                    is_active=True, **{field: FAILED}).update(
                        **{field: PENDING}, last_error="")
                self.stdout.write(self.style.WARNING(
                    f"{k}: {n} righe fallite rimesse in coda"))

        if opts["redo_model"]:
            # Rows that are DONE but produced by a weaker model. They are not
            # failures, so nothing would ever revisit them: this is how a
            # degraded stretch of the corpus gets redone, deliberately.
            n = Reel.objects.filter(
                enrich_status=DONE, is_active=True,
                enrichment__llm_model__startswith=opts["redo_model"],
            ).update(enrich_status=PENDING)
            self.stdout.write(self.style.WARNING(
                f"reel_enrich: {n} analisi di '{opts['redo_model']}*' rimesse in coda"))

        if opts["live"]:
            # Deliberately the ordinary live stages, so there is exactly one
            # code path for immediate analysis — no second implementation to
            # drift from it.
            from pipeline.agents import enrich_agent, knowledge_agent
            from pipeline.dag import Context
            ctx = Context(limit=opts["limit"])
            kinds = self._kinds(opts)
            if "reel_enrich" in kinds:
                self.stdout.write(self.style.SUCCESS(
                    f"live reel: {enrich_agent.run(ctx)}"))
            if {"doc_enrich", "doc_arguments"} & set(kinds):
                self.stdout.write(self.style.SUCCESS(
                    f"live articoli: {knowledge_agent.run(ctx)}"))
            return

        if opts["collect"]:
            self.stdout.write(self.style.SUCCESS(f"ritiro: {batch_agent.collect()}"))
        if opts["submit"]:
            for k in self._kinds(opts):
                res = batch_agent.submit_kind(k, limit=opts["limit"])
                self.stdout.write(self.style.SUCCESS(f"consegna {k}: {res}"))
        if not any((opts["collect"], opts["submit"], opts["retry_failed"],
                    opts["redo_model"])):
            self.stdout.write(
                "niente da fare: usa --submit, --collect, --status o --live")

    def _status(self, batch_api):
        from pipeline.agents.batch_agent import KINDS

        runs = BatchRun.objects.all()[:10]
        if not runs:
            self.stdout.write("nessuna consegna registrata")
        for r in runs:
            live = ""
            if r.status in ("submitted", "ended"):
                try:
                    s = batch_api.status(r.batch_id)
                    live = (f"  → {s['processing_status']} "
                            f"(in lavorazione {s['processing']}, ok {s['succeeded']}, "
                            f"errori {s['errored']})")
                except Exception as exc:  # noqa: BLE001
                    live = f"  → stato illeggibile: {exc!r}"
            self.stdout.write(
                f"{r.submitted_at:%Y-%m-%d %H:%M}  {r.batch_id}  {r.kind}  "
                f"{r.status}  {len(r.items)} elementi{live}")

        self.stdout.write("\nquanto resta da fare:")
        for name, kind in KINDS.items():
            model_cls, field = _ROWS[name]
            todo = len(kind.pending())
            flying = model_cls.objects.filter(**{field: BATCHED}).count()
            self.stdout.write(f"   {name:14} da fare {todo:5}   in volo {flying:5}")
