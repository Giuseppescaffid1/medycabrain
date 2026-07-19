"""
ingest_blog
===========
Ingest Medyca blog articles into the knowledge bank (MEDYC-9 / MEDYC-12).

    # one article (manual URL — the MEDYC-12 "for now" path)
    python manage.py ingest_blog https://www.medyca.it/blog/come-funziona-...

    # crawl the whole blog index
    python manage.py ingest_blog --crawl https://www.medyca.it/blog

    # ...and enrich + embed straight away
    python manage.py ingest_blog --crawl https://www.medyca.it/blog --enrich

Fetched text is stored as Markdown. --enrich runs the knowledge agent
(LLM summary + topics + embedding).
"""

import time

from django.core.management.base import BaseCommand, CommandError

from pipeline.agents import blog_agent


class Command(BaseCommand):
    help = "Fetch Medyca blog article(s) into the knowledge bank."

    def add_arguments(self, parser):
        parser.add_argument("url", nargs="?", help="Single article URL to ingest.")
        parser.add_argument("--crawl", metavar="INDEX_URL",
                            help="Crawl a blog index page and ingest every article found.")
        parser.add_argument("--enrich", action="store_true",
                            help="Run LLM enrichment + embedding after ingesting.")
        parser.add_argument("--limit", type=int, default=50)

    def handle(self, *args, **opts):
        if not opts["url"] and not opts["crawl"]:
            raise CommandError("provide an article URL or --crawl <index_url>")

        urls = []
        if opts["crawl"]:
            urls = blog_agent.crawl_index(opts["crawl"], limit=opts["limit"])
            self.stdout.write(f"discovered {len(urls)} article URLs")
        if opts["url"]:
            urls.append(opts["url"])

        created = updated = failed = 0
        for u in urls:
            try:
                doc, was_created = blog_agent.ingest(u)
                if doc is None:
                    failed += 1
                    self.stdout.write(self.style.WARNING(f"  ✗ could not extract {u}"))
                elif was_created:
                    created += 1
                    self.stdout.write(self.style.SUCCESS(f"  + {doc.title[:70]}"))
                else:
                    updated += 1
                    self.stdout.write(f"  = {doc.title[:70]} (updated)")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                self.stdout.write(self.style.ERROR(f"  ✗ {u}: {exc!r}"))
            time.sleep(1.0)  # be polite to the blog

        self.stdout.write(self.style.SUCCESS(
            f"done — {created} new, {updated} updated, {failed} failed"))

        if opts["enrich"]:
            self.stdout.write("running enrichment + embedding…")
            from pipeline.agents import knowledge_agent
            from pipeline.dag import Context
            res = knowledge_agent.run(Context(limit=None))
            self.stdout.write(self.style.SUCCESS(f"knowledge agent: {res}"))
