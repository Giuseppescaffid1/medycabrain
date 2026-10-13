"""reprocess_topic: a dry run writes nothing, and only competitor articles
currently in tema are ever re-judged — never Medyca's own, never the
reference material the client chose."""

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from core.models import DONE, BlogSource, KnowledgeDocument


class ReprocessTopicTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        comp = BlogSource.objects.create(name="Catalogo", index_url="https://c.example/blog",
                                         owner_type="competitor")
        own = BlogSource.objects.create(name="Medyca", index_url="https://m.example/blog",
                                        owner_type="owned")
        common = dict(source_type="blog", enrich_status=DONE, is_on_topic=True,
                      content_text="testo")
        cls.comp = KnowledgeDocument.objects.create(
            source=comp, owner_type="competitor", source_url="https://c.example/1",
            title="Calamina crema", **common)
        cls.own = KnowledgeDocument.objects.create(
            source=own, owner_type="owned", source_url="https://m.example/1",
            title="Ricetta Medyca", **common)
        cls.rif = KnowledgeDocument.objects.create(
            source=None, owner_type="competitor", source_url="https://v.example/1",
            title="Riferimento", is_inspiration=True, **{**common, "source_type": "video"})

    def _run(self, *args):
        answer = {"is_on_topic": False, "off_topic_reason": "farmaco dermatologico"}
        with mock.patch("llm.client.chat_json", return_value=answer) as chat, \
                mock.patch("time.sleep"):
            call_command("reprocess_topic", "--pause", "0", *args, stdout=StringIO())
        return chat

    def test_dry_run_writes_nothing(self):
        self._run()
        self.comp.refresh_from_db()
        self.assertTrue(self.comp.is_on_topic)

    def test_apply_writes_only_the_competitor_article(self):
        chat = self._run("--apply")
        self.assertEqual(chat.call_count, 1)
        for doc, expected in ((self.comp, False), (self.own, True), (self.rif, True)):
            doc.refresh_from_db()
            self.assertEqual(doc.is_on_topic, expected, doc.title)
        self.assertEqual(self.comp.off_topic_reason, "farmaco dermatologico")
