"""
The MCP gate test: all ten connector tools, wired end to end, on a tiny seeded
corpus — with the embedder and the LLM reranker FAKED so it runs in CI, where
`requirements-ci.txt` deliberately has no torch, no sentence-transformers and no
LLM keys (the heavy models are imported lazily and never load here).

It tests the CONTRACT and the WIRING, not retrieval quality: the shape of every
hit, that each typed search keeps only its side of the corpus, that ownership
labels are right (competitor → "competitor", owned → "Medyca", reference
material → "riferimento", never a bare "competitor"/"Medyca"), that a typed
search does not starve when its type is the minority, and that all ten tools are
still registered on the server. Retrieval quality against real models is
`manage.py eval_mcp`, which runs on the VPS, not in this gate.

Two tricks keep the heavy models out of the path (see the design,
`.claude/tasks/2026-09-16-mcp-search-affidabile.md`):
  - `core.knowledge._get_embedder` is stubbed with a fake whose `.encode()`
    returns fixed-width normalised vectors. It is the ONLY place search needs the
    embedder, because document vectors are read from the DB.
  - every seeded text is < 700 chars, so `_best_passage` short-circuits to the
    single chunk without ever encoding it (`core/knowledge.py`, `len(parts)==1`).
  - `core.knowledge.client.chat_json` (the reranker's one network call) is
    stubbed to `{}`, which makes `_rerank` keep the blend order — the wiring runs,
    nothing leaves the process.
"""

from __future__ import annotations

import zlib
from unittest import mock

import numpy as np
from django.test import TestCase

# Tool functions are plain module-level callables: @server.tool returns the
# function unchanged, so the gate can call them in-process without the HTTP
# server. Importing the module runs django.setup() (idempotent under the test
# runner) and spawns a daemon warm thread whose embedder import is lazy and
# swallowed — it never touches this test's path.
from mcp_bridge import server

_DIM = 16


def _vec(text: str) -> np.ndarray:
    """A deterministic non-negative unit vector from a text's word buckets.

    Non-negative so any two vectors have cosine >= 0 (keeps the relevance floor
    well-behaved on a tiny corpus); a shared word lifts the similarity, which is
    all the ranking needs here. crc32, not hash(), so it does not move with
    PYTHONHASHSEED — the stored document vectors and the query vector must land
    in the same buckets.
    """
    v = np.zeros(_DIM, dtype=np.float32)
    import re
    for w in re.findall(r"\w+", (text or "").lower()):
        v[zlib.crc32(w.encode()) % _DIM] += 1.0
    n = float(np.linalg.norm(v))
    if n == 0.0:
        v[:] = 1.0 / np.sqrt(_DIM)
        return v
    return v / n


class _FakeEmbedder:
    """Stands in for SentenceTransformer: same `.encode` signature, no torch."""

    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        return np.asarray([_vec(t) for t in texts], dtype=np.float32)


class MCPToolsGate(TestCase):
    @classmethod
    def setUpTestData(cls):
        from core.models import (
            DONE, ArgumentAssignment, BlogSource, ClusterRun, DocumentArgument,
            Enrichment, KnowledgeDocument, Reel, ReelArgument, ReelEmbedding,
            TopicCluster, TrackedAccount, Transcript,
        )

        owned_acc = TrackedAccount.objects.create(
            username="medyca.menopausa", owner_type="owned")
        comp_acc = TrackedAccount.objects.create(
            username="competitor.ig", owner_type="competitor")

        def _reel(acc, shortcode, text, topic, views=100):
            r = Reel.objects.create(
                account=acc, shortcode=shortcode, caption=text,
                enrich_status=DONE, view_count=views, like_count=10)
            Transcript.objects.create(reel=r, text=text)
            Enrichment.objects.create(
                reel=r, summary_it=f"Riassunto: {topic}", topics=[topic],
                primary_topic=topic, hook_text=f"Gancio su {topic}",
                hook_analysis_it="Analisi del gancio.",
                content_format="talking_head",
                target_audience_it="Donne in menopausa.")
            ReelEmbedding.objects.create(
                reel=r, vector=_vec(text).tolist(), chunk_vectors=[])
            return r

        cls.reel_owned = _reel(
            owned_acc, "OWNEDREEL1",
            "Vampate di calore in menopausa: rimedi e terapia ormonale bioidentica.",
            "vampate", views=500)
        cls.reel_comp = _reel(
            comp_acc, "COMPREEL1",
            "Vampate di calore: cosa dicono i competitor sulla menopausa.",
            "vampate", views=300)
        # Pad the corpus so reels are the clear majority — the pre-fix starvation
        # case, where a typed article search over-fetched a reel-dominated pool.
        for i in range(6):
            _reel(comp_acc, f"COMPREEL{i+2}",
                  "Ormoni e menopausa: contenuto generico del competitor.",
                  "ormoni")

        owned_blog = BlogSource.objects.create(
            name="Blog Medyca", owner_type="owned",
            index_url="https://medyca.it/blog")
        comp_blog = BlogSource.objects.create(
            name="Blog Competitor", owner_type="competitor",
            index_url="https://competitor.example/blog")

        owned_text = ("Il metodo Marion Gluck applica la terapia ormonale "
                      "bioidentica alla menopausa con ormoni su misura.")
        cls.doc_owned = KnowledgeDocument.objects.create(
            source_type="blog", source=owned_blog, owner_type="owned",
            source_url="https://medyca.it/blog/marion-gluck",
            title="Il metodo Marion Gluck", content_text=owned_text,
            summary_it="Metodo Marion Gluck.", primary_topic="marion gluck",
            is_on_topic=True, embedding=_vec(owned_text).tolist())
        DocumentArgument.objects.create(
            document=cls.doc_owned,
            text_it="Il metodo usa ormoni bioidentici su misura.",
            quote="terapia ormonale bioidentica")

        comp_text = ("La terapia ormonale in menopausa secondo un blog "
                     "competitor: indicazioni generali e cautele.")
        cls.doc_comp = KnowledgeDocument.objects.create(
            source_type="blog", source=comp_blog, owner_type="competitor",
            source_url="https://competitor.example/blog/tos",
            title="Terapia ormonale in menopausa", content_text=comp_text,
            summary_it="TOS competitor.", primary_topic="terapia ormonale",
            is_on_topic=True, embedding=_vec(comp_text).tolist())

        # Reference material: a TV episode the client added on purpose. It carries
        # owner_type="competitor" and is_on_topic=False (a menopause-centred
        # verdict would reject it) but is_inspiration exempts it — it must appear
        # in cerca_riferimenti and be labelled by its source, "YouTVRS".
        rif_text = ("Puntata Canale Salute: sindrome metabolica, sovrappeso e "
                    "pressione arteriosa, salute metabolica.")
        cls.doc_rif = KnowledgeDocument.objects.create(
            source_type="video", source=None, owner_type="competitor",
            source_url="https://vimeo.com/1220776839",
            title="Canale Salute — Sindrome metabolica", content_text=rif_text,
            author="YouTVRS", summary_it="Sindrome metabolica.",
            primary_topic="sindrome metabolica", is_on_topic=False,
            off_topic_reason="Tratta salute metabolica, non menopausa.",
            is_inspiration=True, embedding=_vec(rif_text).tolist())

        # A current competitor cluster with one assigned reel argument, for `temi`.
        run = ClusterRun.objects.create(
            scope="competitor", status="done", is_current=True)
        cluster = TopicCluster.objects.create(
            run=run, label_it="Vampate di calore", description_it="Tema vampate.",
            size=2, keywords=["vampate", "calore", "menopausa"])
        arg = ReelArgument.objects.create(
            reel=cls.reel_comp, text_it="Le vampate si trattano con la TOS.",
            quote="Vampate di calore")
        ArgumentAssignment.objects.create(
            run=run, argument=arg, cluster=cluster, similarity=0.9)

    def setUp(self):
        import core.knowledge as knowledge
        # The index cache is module-global and outlives a test; drop it so this
        # class's seeded corpus is read fresh.
        knowledge._INDEX_CACHE.clear()
        self._p1 = mock.patch.object(knowledge, "_get_embedder",
                                     return_value=_FakeEmbedder())
        self._p2 = mock.patch.object(knowledge.client, "chat_json",
                                     return_value={})
        self._p1.start()
        self._p2.start()
        self.addCleanup(self._p1.stop)
        self.addCleanup(self._p2.stop)

    # ── hit shape ──────────────────────────────────────────────────────────
    _HIT_KEYS = {"id", "tipo", "di", "titolo", "estratto", "url",
                 "ispirazione", "pertinenza"}

    def test_search_hits_have_the_documented_shape(self):
        hits = server.cerca_tutto("menopausa vampate terapia", limite=8)
        self.assertTrue(hits, "cerca_tutto non ha restituito nulla")
        for h in hits:
            self.assertEqual(set(h), self._HIT_KEYS, h)
            self.assertRegex(h["id"], r"^(reel|blog):\d+$")

    # ── typed searches keep only their side ────────────────────────────────
    def test_cerca_reel_returns_only_reels(self):
        hits = server.cerca_reel("vampate di calore menopausa", limite=8)
        self.assertTrue(hits)
        self.assertTrue(all(h["id"].startswith("reel:") for h in hits), hits)
        self.assertTrue(all(h["tipo"] == "reel" for h in hits), hits)

    def test_cerca_articoli_returns_only_articles(self):
        hits = server.cerca_articoli("terapia ormonale menopausa", limite=8)
        self.assertTrue(hits)
        self.assertTrue(all(h["id"].startswith("blog:") for h in hits), hits)

    def test_cerca_riferimenti_returns_only_inspiration(self):
        hits = server.cerca_riferimenti("sindrome metabolica pressione", limite=8)
        self.assertTrue(hits, "cerca_riferimenti non ha trovato il materiale")
        self.assertTrue(all(h["ispirazione"] for h in hits), hits)
        self.assertIn(f"blog:{self.doc_rif.id}", [h["id"] for h in hits])

    # ── no starvation: the minority type still comes back ──────────────────
    def test_typed_article_search_does_not_starve_against_a_reel_majority(self):
        # Eight reels, two on-topic articles: pre-fix the over-fetched pool was
        # mostly reels and the post-filter could return zero. Both articles must
        # come back now that the type filter runs before the rerank.
        ids = {h["id"] for h in
               server.cerca_articoli("terapia ormonale menopausa", limite=8)}
        self.assertIn(f"blog:{self.doc_owned.id}", ids, ids)
        self.assertIn(f"blog:{self.doc_comp.id}", ids, ids)

    # ── ownership / reference labels ───────────────────────────────────────
    def test_hit_label_owned_competitor_and_reference(self):
        owned = server._hit({"kind": "blog", "id": 1, "owner": "owned",
                             "account": "Blog Medyca", "title": "t"})
        self.assertEqual(owned["di"], "Medyca")

        comp = server._hit({"kind": "reel", "id": 2, "owner": "competitor",
                            "account": "competitor.ig", "title": "t"})
        self.assertIn("competitor", comp["di"].lower())

        rif = server._hit({"kind": "blog", "id": 3, "owner": "competitor",
                          "account": "YouTVRS", "inspiration": True, "title": "t"})
        self.assertEqual(rif["di"], "riferimento: YouTVRS")
        # Reference material is neither side, spelled out: never a bare label.
        self.assertNotIn("competitor", rif["di"].lower())
        self.assertNotIn("medyca", rif["di"].lower())

    def test_reference_search_never_labels_inspiration_as_a_side(self):
        for h in server.cerca_riferimenti("sindrome metabolica", limite=8):
            self.assertTrue(h["di"].startswith("riferimento:"), h)
            self.assertNotIn("competitor", h["di"].lower())
            self.assertNotIn("medyca", h["di"].lower())

    # ── leggi_* ────────────────────────────────────────────────────────────
    def test_leggi_reel_reads_one_reel_with_its_video_fields(self):
        doc = server.leggi_reel(f"reel:{self.reel_owned.id}")
        self.assertEqual(doc["tipo"], "reel")
        self.assertEqual(doc["di"], "Medyca")
        self.assertIn("vampate", doc["trascrizione"].lower())
        self.assertIn("gancio", doc)

    def test_leggi_articolo_labels_owned_and_reference(self):
        owned = server.leggi_articolo(f"blog:{self.doc_owned.id}")
        self.assertEqual(owned["di"], "Medyca")
        self.assertEqual(owned["tipo"], "articolo")

        rif = server.leggi_articolo(f"blog:{self.doc_rif.id}")
        self.assertEqual(rif["di"], "riferimento: YouTVRS")
        self.assertEqual(rif["tipo"], "video di riferimento")
        self.assertTrue(rif["ispirazione"])
        self.assertNotIn("competitor", rif["di"].lower())

    def test_leggi_routes_on_the_id_prefix(self):
        self.assertEqual(server.leggi(f"reel:{self.reel_owned.id}")["tipo"], "reel")
        self.assertEqual(
            server.leggi(f"blog:{self.doc_comp.id}")["tipo"], "articolo")
        self.assertIn("errore", server.leggi("nope:1"))

    # ── the ORM-only tools ─────────────────────────────────────────────────
    def test_panoramica_counts_by_side_and_keeps_reference_apart(self):
        pano = server.panoramica()
        self.assertEqual(pano["reel"]["medyca"], 1)
        self.assertEqual(pano["reel"]["competitor"], 7)
        self.assertEqual(pano["articoli"]["medyca"], 1)
        self.assertEqual(pano["articoli"]["competitor"], 1)
        # The reference video is not folded into the article totals.
        self.assertEqual(pano["materiale_di_riferimento"]["totale"], 1)

    def test_fonti_blog_labels_each_source(self):
        by_name = {b["nome"]: b for b in server.fonti_blog()}
        self.assertEqual(by_name["Blog Medyca"]["di"], "Medyca")
        self.assertEqual(by_name["Blog Competitor"]["di"], "competitor")

    def test_temi_returns_the_current_competitor_cluster(self):
        temi = server.temi(scope="competitor")
        self.assertTrue(temi)
        self.assertEqual(temi[0]["tema"], "Vampate di calore")
        self.assertTrue(temi[0]["esempi_affermazioni"])

    # ── contract barrier: the ten tools stay registered ────────────────────
    def test_all_ten_tools_are_registered_on_the_server(self):
        names = {t.name for t in server.server._tool_manager.list_tools()}
        self.assertEqual(names, {
            "panoramica", "cerca_reel", "cerca_articoli", "cerca_tutto",
            "leggi_reel", "leggi_articolo", "leggi", "cerca_riferimenti",
            "fonti_blog", "temi",
        })
