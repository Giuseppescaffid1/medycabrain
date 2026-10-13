"""
Ask again, with the current rule, whether competitor articles are "in tema".

Needed after TOPIC_CRITERION changed (2026-10-13): the stored verdicts came
from a prompt that never said what "in tema" means, so pharmacy catalogue
pages (calamine, veterinary tylosin) were marked in tema and surfaced in the
client's searches. Re-running the whole analysis would also rewrite every
summary and topic and move the theme map; this asks ONLY the verdict.

Dry run by default: it prints what would change and writes nothing.

    python manage.py reprocess_topic                       # dry run, all
    python manage.py reprocess_topic --source Farmagalenica
    python manage.py reprocess_topic --apply

Only competitor articles currently IN TEMA, with a finished analysis, are
re-judged: the wrong verdicts are false "yes" answers, and asking only those
keeps a full run near 730 calls instead of 1.450. The fast provider's free
tier caps tokens per minute, so calls are paced (--pause) and a rate-limited
call waits and retries instead of being counted as an answer. Medyca's own
articles and the reference material the client added on purpose are never
touched: a model's opinion must not remove a human's choice.
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import DONE, KnowledgeDocument
from llm import client
from pipeline.agents.knowledge_agent import KB_SYSTEM, TOPIC_CRITERION

USER = """\
Articolo del blog di {source} (un concorrente di Medyca).

TITOLO: {title}

RIASSUNTO: {summary}

INIZIO DEL TESTO:
{text}

""" + TOPIC_CRITERION.replace("{", "{{").replace("}", "}}") + """
Restituisci SOLO un JSON:
{{"is_on_topic": true oppure false, "off_topic_reason": "se false: di cosa parla davvero"}}
"""


class Command(BaseCommand):
    help = "Re-judge only the in-tema verdict of competitor articles (dry run by default)."

    def add_arguments(self, parser):
        parser.add_argument("--source", default="", help="Only this blog source name.")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--pause", type=float, default=4.0,
                            help="Seconds between calls (free tiers cap tokens per minute).")
        parser.add_argument("--apply", action="store_true",
                            help="Write the new verdicts. Without it nothing is saved.")

    def handle(self, *args, source, limit, pause, apply, **_):
        qs = (KnowledgeDocument.objects
              .filter(is_active=True, owner_type="competitor", is_on_topic=True,
                      is_inspiration=False, enrich_status=DONE)
              .select_related("source").order_by("id"))
        if source:
            qs = qs.filter(source__name=source)
        if limit:
            qs = qs[:limit]

        model = client.model_for("analysis")
        on_off = off_on = same = failed = 0
        def ask(doc):
            prompt = USER.format(source=doc.source.name if doc.source else "?",
                                 title=doc.title, summary=doc.summary_it[:600],
                                 text=(doc.content_text or "")[:1500])
            for attempt in range(4):
                try:
                    return client.chat_json(KB_SYSTEM, prompt, max_tokens=600,
                                            temperature=0.0, model=model)
                except Exception as exc:  # noqa: BLE001
                    if "rate limit" not in str(exc).lower() or attempt == 3:
                        raise
                    time.sleep(20 * (attempt + 1))

        for doc in qs:
            time.sleep(pause)
            try:
                data = ask(doc)
                if isinstance(data, list):
                    data = next((d for d in data if isinstance(d, dict)), {})
                verdict = data.get("is_on_topic")
                if not isinstance(verdict, bool):
                    raise ValueError(f"verdetto non booleano: {verdict!r}")
            except Exception as exc:  # noqa: BLE001 — one bad answer never stops the run
                # Left as it was, and counted: an unanswered question is not a "no".
                failed += 1
                self.stderr.write(f"  ? {doc.id} {doc.title[:60]}: {exc!r}"[:200])
                continue

            if verdict == doc.is_on_topic:
                same += 1
                continue
            reason = str(data.get("off_topic_reason") or "")[:300] if not verdict else ""
            arrow = "in tema → fuori tema" if doc.is_on_topic else "fuori tema → in tema"
            if doc.is_on_topic:
                on_off += 1
            else:
                off_on += 1
            self.stdout.write(f"  {arrow}  {doc.id} [{doc.source.name if doc.source else '?'}] "
                              f"{doc.title[:60]}  {reason[:80]}")
            if apply:
                doc.is_on_topic = verdict
                doc.off_topic_reason = reason
                # updated_at is listed on purpose: the search index notices a
                # change through Max(updated_at), and auto_now is only written
                # when it is in update_fields.
                doc.updated_at = timezone.now()
                doc.save(update_fields=["is_on_topic", "off_topic_reason", "updated_at"])

        self.stdout.write(
            f"\n{'SCRITTO' if apply else 'PROVA (nulla salvato)'}: "
            f"{on_off} in tema → fuori tema, {off_on} fuori tema → in tema, "
            f"{same} invariati, {failed} senza risposta.")
