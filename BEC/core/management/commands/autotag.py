"""
Generate tags from the LLM primary_topic, for reels and articles alike.

    python manage.py autotag

Tags used to be a write-only, reel-only, manual field disconnected from the
topics/primary_topic layer that actually powers the product — so they helped
nobody. This turns the primary_topic (the one specific subject the analysis
already extracts) into a real Tag and applies it, giving the library a
filter that means something and the client a starting point they can edit.

Idempotent and safe with manual tags: it only ever creates/updates tags it
owns (auto=True) and never removes a hand-applied one. Re-running refreshes
auto-tags to the current primary_topic without touching the client's work.
"""

from __future__ import annotations

import re

from django.core.management.base import BaseCommand

from core.models import DONE, KnowledgeDocument, Reel, ReelAnnotation, Tag


def _norm(topic: str) -> str:
    """The tag name for a primary_topic: trimmed, lowercased, collapsed.

    Keyed on the normalised form so 'Terapia BHRT' and 'terapia bhrt' are the
    same tag, not two."""
    t = re.sub(r"\s+", " ", (topic or "").strip().lower())
    return t[:50]


class Command(BaseCommand):
    help = "Genera tag automatici dal primary_topic (reel + articoli)."

    def handle(self, *args, **opts):
        # An auto-tag cache so we resolve each topic to its Tag once.
        cache: dict[str, Tag] = {}

        def tag_for(topic: str) -> Tag | None:
            name = _norm(topic)
            # Umbrella terms tag nothing useful — every item is "menopausa".
            if len(name) < 3 or name in {"menopausa", "salute femminile",
                                          "salute", "benessere"}:
                return None
            if name not in cache:
                tag, _ = Tag.objects.get_or_create(
                    name=name, defaults={"auto": True, "color": "#4a6fac"})
                cache[name] = tag
            return cache[name]

        reels = tagged = 0
        for reel in (Reel.objects.filter(is_active=True, enrich_status=DONE)
                     .select_related("enrichment")):
            enr = getattr(reel, "enrichment", None)
            tag = tag_for(enr.primary_topic if enr else "")
            if not tag:
                continue
            reels += 1
            ann, _ = ReelAnnotation.objects.get_or_create(reel=reel)
            if not ann.tags.filter(id=tag.id).exists():
                ann.tags.add(tag)
                tagged += 1

        docs = doc_tagged = 0
        for doc in KnowledgeDocument.objects.filter(is_active=True, is_on_topic=True):
            tag = tag_for(doc.primary_topic)
            if not tag:
                continue
            docs += 1
            if not doc.tags.filter(id=tag.id).exists():
                doc.tags.add(tag)
                doc_tagged += 1

        auto_total = Tag.objects.filter(auto=True).count()
        self.stdout.write(self.style.SUCCESS(
            f"[autotag] {auto_total} tag automatici · "
            f"reel taggati: {tagged}/{reels} · articoli: {doc_tagged}/{docs}"))
