"""
Fonti, account, temi e pagina Stato: i casi che il cliente ha segnalato.

Ogni test nasce da un errore visto davvero: l'indirizzo con la barra finale che
dava 500, «Rimuovi» che lasciava la riga, i «7 rimanenti» che non scendevano
mai, ogni notte mostrata come due esecuzioni. `embed_topic` è sostituito: la CI
non installa i modelli pesanti.
"""

from unittest import mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from core import models, ops, queue_eta
from core.serializers import blog_url_variants, clean_instagram_username


class AuthedTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("fonti", password="x")
        cls.token = Token.objects.create(user=cls.user)

    def setUp(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")


class BlogUrlTests(AuthedTestCase):
    def setUp(self):
        super().setUp()
        # niente scansione né processi veri
        for target in ("core.views._spawn_job", "core.external_ref._check_public"):
            p = mock.patch(target)
            p.start()
            self.addCleanup(p.stop)

    def _add(self, url, **extra):
        return self.client.post("/api/v1/blog-sources/",
                                {"name": "Blog", "index_url": url, **extra}, format="json")

    def test_variants_cover_www_scheme_and_slash(self):
        v = blog_url_variants("https://example.it/blog")
        self.assertEqual(len(v), 8)
        self.assertIn("http://www.example.it/blog/", v)

    def test_trailing_slash_is_a_clear_400_not_a_500(self):
        self.assertEqual(self._add("https://example.it/blog").status_code, 201)
        r = self._add("https://example.it/blog/")
        self.assertEqual(r.status_code, 400)
        self.assertIn("già tra le fonti", str(r.json()))
        self.assertNotIn("already exists", str(r.json()))

    def test_www_variant_is_recognised(self):
        self._add("https://example.it/blog")
        self.assertEqual(self._add("http://WWW.example.it/blog/").status_code, 400)

    def test_same_host_other_path_is_allowed(self):
        self._add("https://example.it/blog")
        self.assertEqual(self._add("https://example.it/menopausa").status_code, 201)

    def test_remove_then_add_again_restores_the_row(self):
        # una migrazione semina già la fonte di Medyca: si contano le differenze
        seeded = self.client.get("/api/v1/blog-sources/").json()["count"]
        row_id = self._add("https://example.it/blog").json()["id"]
        doc = models.KnowledgeDocument.objects.create(
            source=models.BlogSource.objects.get(pk=row_id), title="t",
            source_url="https://example.it/blog/a", is_active=True)
        self.assertEqual(self.client.delete(f"/api/v1/blog-sources/{row_id}/").status_code, 204)
        doc.refresh_from_db()
        self.assertFalse(doc.is_active)
        # fuori dalla lista normale, dentro «Rimossi»
        self.assertEqual(self.client.get("/api/v1/blog-sources/").json()["count"], seeded)
        self.assertEqual(self.client.get("/api/v1/blog-sources/?removed=1").json()["count"], 1)

        r = self._add("https://example.it/blog/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["restored"])
        self.assertEqual(r.json()["id"], row_id)
        doc.refresh_from_db()
        self.assertTrue(doc.is_active)
        self.assertEqual(models.BlogSource.objects.filter(index_url__contains="example.it").count(), 1)

    def test_editing_url_into_a_removed_one_is_400_not_500(self):
        gone = self._add("https://example.it/gone").json()["id"]
        self.client.delete(f"/api/v1/blog-sources/{gone}/")
        keep = self._add("https://example.it/keep").json()["id"]
        r = self.client.patch(f"/api/v1/blog-sources/{keep}/",
                              {"index_url": "https://example.it/gone/"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("tra le rimosse", str(r.json()))

    def test_restoring_with_another_owner_is_refused(self):
        row_id = self._add("https://example.it/blog", owner_type="competitor").json()["id"]
        self.client.delete(f"/api/v1/blog-sources/{row_id}/")
        r = self._add("https://example.it/blog", owner_type="owned")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Rimossi", str(r.json()))
        self.assertEqual(models.BlogSource.objects.get(pk=row_id).owner_type, "competitor")

    def test_resuming_a_paused_blog_brings_its_articles_back(self):
        row_id = self._add("https://example.it/blog").json()["id"]
        src = models.BlogSource.objects.get(pk=row_id)
        doc = models.KnowledgeDocument.objects.create(
            source=src, title="t", source_url="https://example.it/blog/a", is_active=False)
        src.is_active = False
        src.save()
        self.client.patch(f"/api/v1/blog-sources/{row_id}/", {"is_active": True}, format="json")
        doc.refresh_from_db()
        self.assertTrue(doc.is_active)


class AccountTests(AuthedTestCase):
    def _add(self, username, **extra):
        return self.client.post("/api/v1/accounts/",
                                {"username": username, **extra}, format="json")

    def test_username_cleaning(self):
        for raw, want in [("@Medyca.Menopausa", "medyca.menopausa"),
                          (" Medyca ", "medyca"),
                          ("https://www.instagram.com/Medyca.Menopausa/?hl=it", "medyca.menopausa"),
                          ("due parole", ""), ("", ""), ("a" * 40, "")]:
            self.assertEqual(clean_instagram_username(raw), want, raw)

    def test_junk_username_is_a_clear_400(self):
        r = self._add("due parole")
        self.assertEqual(r.status_code, 400)
        self.assertIn("Scrivi solo lo username", str(r.json()))

    def test_case_duplicates_are_one_account(self):
        self.assertEqual(self._add("Medyca").status_code, 201)
        r = self._add("medyca")
        self.assertEqual(r.status_code, 400)
        self.assertIn("già monitorato", str(r.json()))

    def test_remove_then_add_again_restores_and_keeps_reels_active(self):
        acc_id = self._add("prova").json()["id"]
        acc = models.TrackedAccount.objects.get(pk=acc_id)
        reel = models.Reel.objects.create(account=acc, shortcode="abc")
        self.client.delete(f"/api/v1/accounts/{acc_id}/")
        self.assertEqual(self.client.get("/api/v1/accounts/").json()["count"], 0)
        self.assertEqual(self.client.get("/api/v1/accounts/?removed=1").json()["count"], 1)
        reel.refresh_from_db()
        self.assertTrue(reel.is_active)

        r = self._add("@Prova")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["restored"])
        acc.refresh_from_db()
        self.assertTrue(acc.is_active)
        self.assertIsNone(acc.removed_at)

    def test_editing_username_into_a_removed_one_is_400_not_500(self):
        gone = self._add("vecchio").json()["id"]
        self.client.delete(f"/api/v1/accounts/{gone}/")
        keep = self._add("attuale").json()["id"]
        r = self.client.patch(f"/api/v1/accounts/{keep}/", {"username": "Vecchio"}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("tra le rimosse", str(r.json()))

    def test_restore_with_other_owner_is_refused(self):
        acc_id = self._add("prova", owner_type="competitor").json()["id"]
        self.client.delete(f"/api/v1/accounts/{acc_id}/")
        r = self._add("prova", owner_type="owned")
        self.assertEqual(r.status_code, 400)

    def test_restore_action(self):
        acc_id = self._add("prova").json()["id"]
        self.client.delete(f"/api/v1/accounts/{acc_id}/")
        r = self.client.post(f"/api/v1/accounts/{acc_id}/restore/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/accounts/").json()["count"], 1)

    def test_all_accounts_reachable_with_big_page_size(self):
        for i in range(30):
            models.TrackedAccount.objects.create(username=f"u{i}")
        r = self.client.get("/api/v1/accounts/?page_size=100").json()
        self.assertEqual(len(r["results"]), 30)

    def test_budget_spent_is_announced_on_creation(self):
        with mock.patch("scraper.apify_budget.spend",
                        return_value={"available_usd": 0.0, "cycle_end": "2026-11-26T00:00:00Z"}):
            r = self._add("nuovo")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["collection_paused_until"], "2026-11-26T00:00:00Z")


class CustomTopicTests(AuthedTestCase):
    def _add(self, label):
        return self.client.post("/api/v1/custom-topics/", {"label": label}, format="json")

    def test_case_insensitive_duplicate(self):
        with mock.patch("core.custom_topics.embed_topic"), \
             mock.patch("core.custom_topics.recompute_matches"):
            self.assertEqual(self._add("Tiroide").status_code, 201)
            r = self._add("  tiroide ")
        self.assertEqual(r.status_code, 400)
        self.assertIn("esiste già", str(r.json()))

    def test_failed_mapping_leaves_no_half_made_topic(self):
        with mock.patch("core.custom_topics.embed_topic", side_effect=RuntimeError("modello")):
            r = self._add("Osteoporosi")
        self.assertEqual(r.status_code, 503)
        self.assertIn("Riprova", str(r.json()))
        self.assertEqual(models.CustomTopic.objects.count(), 0)
        # e il secondo tentativo non trova un «esiste già» fantasma
        with mock.patch("core.custom_topics.embed_topic"), \
             mock.patch("core.custom_topics.recompute_matches"):
            self.assertEqual(self._add("Osteoporosi").status_code, 201)


class IdeaCountTests(AuthedTestCase):
    def test_junk_n_is_400(self):
        for url in ("/api/v1/second-brain/ideas/generate/", "/api/v1/second-brain/ideas/plan/"):
            r = self.client.post(url, {"n": "abc"}, format="json")
            self.assertEqual(r.status_code, 400, url)
            self.assertIn("numero intero", str(r.json()))


class QueueBlockedTests(TestCase):
    def setUp(self):
        self.acc = models.TrackedAccount.objects.create(username="q")

    def _reel(self, code, **kw):
        return models.Reel.objects.create(account=self.acc, shortcode=code, **kw)

    def test_reel_without_audio_is_blocked_not_remaining(self):
        # trascrizione «in coda» ma il video non ha audio: nessun agente lo prenderà
        self._reel("a", media_status="skipped", transcribe_status="pending")
        # trascrizione fallita: l'analisi in coda non partirà mai
        self._reel("b", media_status="done", audio_file="x.mp3",
                   transcribe_status="failed", enrich_status="pending",
                   argument_status="pending")
        with mock.patch.object(queue_eta, "_measured_rates", return_value={}):
            snap = queue_eta.snapshot()
        self.assertEqual(snap["remaining"], 0)
        self.assertEqual(snap["blocked"], 2)
        self.assertTrue(snap["blocked_reasons"])
        self.assertEqual(snap["eta_seconds"], 0)

    def test_reachable_work_still_counts(self):
        self._reel("c", media_status="pending")
        self._reel("d", media_status="done", audio_file="x.mp3", transcribe_status="pending")
        self._reel("e", media_status="done", audio_file="x.mp3", transcribe_status="done",
                   enrich_status="pending")
        with mock.patch.object(queue_eta, "_measured_rates", return_value={}):
            snap = queue_eta.snapshot()
        self.assertEqual(snap["remaining"], 3)
        self.assertEqual(snap["blocked"], 0)


class RunHistoryTests(SimpleTestCase):
    def test_stage_list_comes_from_the_pipeline_and_knows_batch(self):
        self.assertIn("batch", ops.STAGE_LABELS)
        self.assertEqual(list(ops.STAGE_NAMES), list(ops.STAGE_NAMES))

    def test_a_run_with_batch_is_one_run(self):
        import tempfile
        from pathlib import Path

        log = []
        for run_ts in ("2026-11-04 03:30:00", "2026-11-05 03:30:00"):
            day = run_ts[:10]
            for i, stage in enumerate(ops.STAGE_NAMES):
                log.append(f"[{day} 03:{30 + i:02d}:00 UTC] ▶ agent: {stage}")
                log.append(f"[{day} 03:{30 + i:02d}:30 UTC] ✓ {stage} done in 30.0s — {{}}")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "logs").mkdir()
            (Path(tmp) / "logs" / "pipeline.log").write_text("\n".join(log))
            with self.settings(BASE_DIR=tmp):
                runs = ops.run_history()
        self.assertEqual(len(runs), 2)
        self.assertEqual(len(runs[0]["stages"]), len(ops.STAGE_NAMES))

    def test_schedule_text_is_italian_whatever_the_crontab_comment_says(self):
        cron = ("# medycabrain — midday top-up (new reels, skip recluster)\n"
                "15 14 * * * cd /x/medycabrain/BEC && nice -n 19 venv/bin/python manage.py "
                "run_pipeline --skip-cluster --skip-blogscrape >> logs/pipeline.log 2>&1\n")
        with mock.patch.object(ops, "_run", return_value=cron):
            rows = ops.schedules()
        self.assertEqual(len(rows), 1)
        self.assertNotIn("top-up", rows[0]["what"])
        self.assertIn("senza raggruppamento", rows[0]["what"])

    def test_reanalysis_is_hidden_when_nothing_runs(self):
        self.assertIsNone(ops.reanalysis(running=[]))


class StatusViewTests(AuthedTestCase):
    def test_status_carries_the_new_fields(self):
        models.Job.objects.create(kind="pipeline", status="done", message="Aggiornamento completato.")
        models.TrackedAccount.objects.create(username="vivo")
        models.TrackedAccount.objects.create(username="tolto", is_active=False,
                                             removed_at="2026-11-01T00:00:00Z")
        with mock.patch("core.ops.snapshot", return_value={}), \
             mock.patch("scraper.apify_budget.spend", return_value=None):
            r = self.client.get("/api/v1/ops/status/")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["last_pipeline_job"]["status"], "done")
        self.assertEqual([a["username"] for a in data["accounts"]], ["vivo"])
        self.assertIn("blocked", data["queue"])


class BlogErrorTests(SimpleTestCase):
    def test_errors_are_sentences_not_reprs(self):
        import requests

        from pipeline.agents.blogscrape_agent import _human_error

        self.assertEqual(_human_error(requests.ReadTimeout("x")), "il sito non ha risposto in tempo")
        self.assertEqual(_human_error(requests.ConnectionError("x")), "sito non raggiungibile")
        resp = mock.Mock(status_code=503)
        self.assertIn("503", _human_error(requests.HTTPError("x", response=resp)))
