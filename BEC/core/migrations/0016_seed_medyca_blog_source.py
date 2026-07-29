"""Attach the existing Medyca blog documents to a real BlogSource.

Only the Medyca source is seeded here. The competitor sources are
operational data, not schema: a migration that creates them would silently
start crawling third-party sites on every fresh `migrate`, which is not a
side effect a migration should have. They are added through the API — the
very feature this schema exists to support.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    BlogSource = apps.get_model("core", "BlogSource")
    KnowledgeDocument = apps.get_model("core", "KnowledgeDocument")

    src, _ = BlogSource.objects.get_or_create(
        index_url="https://www.medyca.it/blog",
        defaults={
            "name": "Medyca",
            "site_url": "https://www.medyca.it",
            "owner_type": "owned",
            "language": "it",
            "strategy": "index",
            "crawl_interval_h": 24,
            "discovery": {
                # The shape the old regex crawler knew, seeded so the first
                # agent-driven crawl of medyca.it needs no LLM call.
                "patterns": {"/blog/*": {"article": True, "conf": 1.0,
                                          "by": "seed"}},
            },
        },
    )
    # Host-matched rows only: the 11 known documents. Anything else keeps
    # source=NULL, owner_type="owned" — the pre-existing semantics.
    KnowledgeDocument.objects.filter(
        source__isnull=True, source_url__contains="medyca.it",
    ).update(source=src, owner_type="owned", language="it")


class Migration(migrations.Migration):
    dependencies = [("core", "0015_knowledgedocument_argument_status_and_more")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
