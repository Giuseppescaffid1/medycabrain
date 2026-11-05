from django.db import migrations, models


def drop_duplicate_links(apps, schema_editor):
    """Collapse links that were added twice before the constraint existed.

    The constraint below would refuse to be created while two rows share an
    address. NOT REVERSIBLE: the deleted rows do not come back on rollback
    (the reverse step is a no-op). Only the constraint and `kind` go back.
    On the real database there were 0 duplicates when this was written, so
    nothing is deleted today. The duplicates are queue rows, not content: the document they
    produced is keyed on the same url (unique) and is untouched. Of each
    group we keep the row that got furthest (done first, then the oldest).
    """
    UploadedMedia = apps.get_model("core", "UploadedMedia")
    seen: dict[str, int] = {}
    rank = {"done": 0, "batched": 1, "skipped": 2, "pending": 3, "failed": 4}
    rows = (UploadedMedia.objects.exclude(source_url="")
            .order_by("source_url", "id"))
    best: dict[str, object] = {}
    for row in rows:
        cur = best.get(row.source_url)
        if cur is None or rank.get(row.transcribe_status, 9) < rank.get(cur.transcribe_status, 9):
            best[row.source_url] = row
        seen[row.source_url] = seen.get(row.source_url, 0) + 1
    for url, n in seen.items():
        if n > 1:
            UploadedMedia.objects.filter(source_url=url).exclude(
                id=best[url].id).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0023_removed_at'),
    ]

    operations = [
        migrations.AlterField(
            model_name='uploadedmedia',
            name='kind',
            field=models.CharField(
                choices=[('audio', 'Audio'), ('video', 'Video'),
                         ('article', 'Articolo')],
                default='audio', max_length=8),
        ),
        migrations.RunPython(drop_duplicate_links, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='uploadedmedia',
            constraint=models.UniqueConstraint(
                condition=models.Q(('source_url', ''), _negated=True),
                fields=('source_url',), name='uploaded_media_source_url_uniq'),
        ),
    ]
