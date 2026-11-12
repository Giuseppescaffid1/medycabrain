"""
Upload and link import: that every link gets an answer, and no row is left lying.

The complaints behind these tests: links of other kinds vanished from a mixed
paste, a removed link could not be added again, a restart left rows "in
trascrizione" for ever, a transcribed interview was stamped as failed because
an LLM call hiccuped afterwards, and the client was shown a Python repr with a
server path in it. Network, ffmpeg, whisper and the LLM are all stubbed: what
is under test is the bookkeeping around them.
"""

import subprocess
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from core import upload_workflow
from core.link_ingest import LinkRefused, fetch_audio, scan_links
from core.management.commands.run_job import fail_upload_row
from core.models import (DONE, FAILED, PENDING, Job, KnowledgeDocument,
                         UploadedMedia)
from core.views import _fail_orphan_uploads, _reap_stale_jobs

YT = "https://www.youtube.com/watch?v=aCPj6fKx_Yc"
VIMEO = "https://vimeo.com/1220777690"
ARTICLE = "https://www.example-salute.it/menopausa/terapia"


class ScanLinks(SimpleTestCase):
    def test_a_mixed_paste_loses_nothing(self):
        scan = scan_links(
            f"Video: {YT}\nArticolo: {ARTICLE}.\n"
            "Reel: https://www.instagram.com/reel/Cabc123/\n"
            "Cartella: https://drive.google.com/drive/folders/xyz\n"
            "Scheda: https://example.org/files/scheda.pdf\n")
        self.assertEqual([v.url for v in scan.videos], [YT])
        self.assertEqual([a.url for a in scan.articles], [ARTICLE])
        self.assertEqual(len(scan.unknown), 3)
        # Each refusal carries a sentence for the client, not just a count.
        self.assertTrue(all(u["motivo"] for u in scan.unknown))

    def test_trailing_punctuation_and_fragment_are_not_part_of_the_page(self):
        scan = scan_links(f"(vedi {ARTICLE}#commenti), grazie")
        self.assertEqual([a.url for a in scan.articles], [ARTICLE])

    def test_same_article_twice_is_one_row(self):
        scan = scan_links(f"{ARTICLE} {ARTICLE}#a")
        self.assertEqual(len(scan.articles), 1)

    def test_tracking_noise_and_trailing_slash_do_not_make_a_second_article(self):
        scan = scan_links(
            f"{ARTICLE}/?utm_source=nl&utm_medium=mail&fbclid=abc "
            f"{ARTICLE}?gclid=1#top {ARTICLE}")
        self.assertEqual([a.url for a in scan.articles], [ARTICLE])

    def test_a_query_that_picks_the_page_is_kept(self):
        scan = scan_links("https://example.org/post?id=7&utm_source=x https://example.org/post?id=8")
        self.assertEqual([a.url for a in scan.articles],
                         ["https://example.org/post?id=7", "https://example.org/post?id=8"])

    def test_a_channel_page_is_not_mistaken_for_a_video(self):
        scan = scan_links("https://www.youtube.com/@TVRS/videos")
        self.assertEqual(scan.videos, [])
        self.assertEqual(len(scan.unknown), 1)

    def test_links_joined_by_a_comma_stay_separate(self):
        scan = scan_links(f"{ARTICLE},https://altro-sito.it/pagina")
        self.assertEqual(len(scan.articles), 2)

    def test_tvrs_pages_are_vimeo_videos_by_their_v_parameter(self):
        scan = scan_links(
            "https://tvrs.it/programmi/canale-salute/?v=1238425507\n"
            "https://tvrs.it/programmi/canale-salute/?v=1238424324\n"
            "https://www.tvrs.it/programmi/canale-salute/?v=1238423247")
        self.assertEqual([(v.provider, v.video_id, v.url) for v in scan.videos],
                         [("vimeo", i, f"https://vimeo.com/{i}")
                          for i in ("1238425507", "1238424324", "1238423247")])
        self.assertEqual(scan.articles, [])
        self.assertEqual(scan.unknown, [])

    def test_tvrs_without_a_numeric_v_stays_a_web_page(self):
        scan = scan_links("https://tvrs.it/programmi/canale-salute/ "
                          "https://tvrs.it/programmi/canale-salute/?v=abc")
        self.assertEqual(scan.videos, [])
        self.assertEqual(len(scan.articles), 2)

    def test_the_tvrs_and_vimeo_spelling_of_one_video_are_one_link(self):
        scan = scan_links("https://tvrs.it/programmi/canale-salute/?v=1238425507 "
                          "https://vimeo.com/1238425507")
        self.assertEqual([v.url for v in scan.videos],
                         ["https://vimeo.com/1238425507"])

    def test_a_video_is_never_also_an_article(self):
        scan = scan_links(f"{YT} {VIMEO}")
        self.assertEqual(scan.articles, [])


class FetchAudioFailures(SimpleTestCase):
    def test_a_download_that_hangs_becomes_a_refusal_so_the_card_is_saved(self):
        with mock.patch("core.link_ingest.subprocess.run",
                        side_effect=subprocess.TimeoutExpired("yt-dlp", 1800)):
            with self.assertRaises(LinkRefused) as ctx:
                fetch_audio(YT, __import__("pathlib").Path("/tmp/x/a.mp3"))
        self.assertIn("30 minuti", str(ctx.exception))

    def test_raw_stderr_never_reaches_the_client(self):
        proc = mock.Mock(returncode=1, stderr="ERROR: /home/srv/venv/x boom")
        with mock.patch("core.link_ingest.subprocess.run", return_value=proc):
            with self.assertRaises(LinkRefused) as ctx:
                fetch_audio(YT, __import__("pathlib").Path("/tmp/x/a.mp3"))
        self.assertNotIn("/home/srv", str(ctx.exception))


class MissingTool(SimpleTestCase):
    def test_missing_yt_dlp_has_its_own_sentence_and_no_path(self):
        err = FileNotFoundError(2, "No such file or directory", "/srv/venv/bin/yt-dlp")
        with mock.patch("core.link_ingest.subprocess.run", side_effect=err):
            with self.assertRaises(Exception) as ctx:
                fetch_audio(YT, __import__("pathlib").Path("/tmp/x/a.mp3"))
        msg = upload_workflow._client_message(ctx.exception)
        self.assertEqual(
            msg, "Lo strumento per scaricare i video non è installato sul server.")
        self.assertNotIn("/srv", msg)


class FailedJobMessage(TestCase):
    def test_job_message_has_no_server_path_but_error_keeps_the_repr(self):
        from django.core.management import call_command
        from core.models import Job
        job = Job.objects.create(kind="upload_transcribe", params={"upload_id": 0})
        boom = RuntimeError("[Errno 2] No such file or directory: '/home/giuseppe/x.mp3'")
        with mock.patch("core.management.commands.run_job.Command._dispatch",
                        side_effect=boom):
            with self.assertRaises(SystemExit):
                call_command("run_job", job=job.id)
        job.refresh_from_db()
        self.assertEqual(job.status, "failed")
        self.assertNotIn("/home/giuseppe", job.message)
        self.assertIn("/home/giuseppe", job.error)


class ClientMessages(SimpleTestCase):
    def test_ffmpeg_failure_hides_the_command_and_the_path(self):
        exc = subprocess.CalledProcessError(
            1, ["ffmpeg", "-i", "/srv/medycabrain/media/uploads/x.amr"])
        msg = upload_workflow._client_message(exc)
        self.assertNotIn("/srv", msg)
        self.assertNotIn("CalledProcessError", msg)

    def test_unknown_errors_get_a_plain_sentence(self):
        self.assertEqual(upload_workflow._client_message(KeyError("x")),
                         "Errore imprevisto durante la lavorazione.")

    def test_our_own_italian_messages_pass_through(self):
        self.assertEqual(
            upload_workflow._client_message(upload_workflow.ClientError("Ciao")),
            "Ciao")


class FromLinks(APITestCase):
    def setUp(self):
        self.client.force_authenticate(User.objects.create_user("t", password="x"))
        patcher = mock.patch("core.views._spawn_job")
        self.spawn = patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, text, **extra):
        # probe raises: the request must not touch the network at all.
        with mock.patch("core.link_ingest.probe", side_effect=AssertionError("rete")):
            return self.client.post(
                "/api/v1/uploads/from-links/",
                {"text": text, "owner_type": "competitor", **extra}, format="json")

    def test_unrecognised_links_are_listed_with_a_reason_not_dropped(self):
        resp = self._post(f"{YT}\nhttps://www.instagram.com/reel/Cabc123/")
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(len(resp.data["creati"]), 1)
        self.assertEqual(len(resp.data["non_riconosciuti"]), 1)
        self.assertIn("motivo", resp.data["non_riconosciuti"][0])

    def test_only_unrecognised_links_is_a_202_with_the_list_not_a_400(self):
        resp = self._post("https://www.instagram.com/reel/Cabc123/")
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.data["creati"], [])

    def test_a_web_page_becomes_an_article_row(self):
        resp = self._post(ARTICLE)
        row = UploadedMedia.objects.get()
        self.assertEqual((row.kind, row.source_url, row.owner_type),
                         ("article", ARTICLE, "competitor"))
        self.assertEqual(resp.data["creati"][0]["kind"], "article")
        self.spawn.assert_called_once()

    def test_a_wrong_owner_is_a_400_not_silently_medyca(self):
        resp = self._post(YT, owner_type="chiunque")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(UploadedMedia.objects.count(), 0)

    def test_pasting_a_failed_link_again_restarts_it(self):
        row = UploadedMedia.objects.create(
            kind="video", source_url=YT, transcribe_status=FAILED,
            last_error="boh", owner_type="competitor")
        resp = self._post(YT, owner_type="owned")
        self.assertEqual(resp.data["riprovati"], [YT])
        self.assertEqual(resp.data["creati"], [])
        row.refresh_from_db()
        self.assertEqual((row.transcribe_status, row.last_error, row.owner_type),
                         (PENDING, "", "owned"))
        self.assertEqual(Job.objects.filter(params__upload_id=row.id).count(), 1)

    def test_a_link_in_progress_or_done_is_already_there(self):
        UploadedMedia.objects.create(kind="video", source_url=YT,
                                     transcribe_status=PENDING)
        UploadedMedia.objects.create(kind="video", source_url=VIMEO,
                                     transcribe_status=DONE)
        resp = self._post(f"{YT} {VIMEO}")
        self.assertEqual(sorted(resp.data["gia_presenti"]), sorted([YT, VIMEO]))
        self.assertEqual(Job.objects.count(), 0)

    def test_a_removed_link_can_be_added_again(self):
        """Deleting an upload leaves its document, inactive, on the same url."""
        KnowledgeDocument.objects.create(
            source_url=YT, source_type="video", title="t", is_active=False,
            published_at=timezone.now())
        resp = self._post(YT)
        self.assertEqual(len(resp.data["creati"]), 1)

    def test_a_live_document_under_the_address_blocks_a_duplicate(self):
        KnowledgeDocument.objects.create(
            source_url=ARTICLE, source_type="blog", title="t",
            published_at=timezone.now())
        resp = self._post(ARTICLE)
        self.assertEqual(resp.data["gia_presenti"], [ARTICLE])

    def test_the_database_refuses_the_same_link_twice(self):
        UploadedMedia.objects.create(kind="video", source_url=YT)
        with self.assertRaises(IntegrityError), transaction.atomic():
            UploadedMedia.objects.create(kind="video", source_url=YT)
        # Files all have source_url="" and must not collide.
        UploadedMedia.objects.create(kind="audio")
        UploadedMedia.objects.create(kind="audio")


class RetryAction(APITestCase):
    def setUp(self):
        self.client.force_authenticate(User.objects.create_user("t", password="x"))
        patcher = mock.patch("core.views._spawn_job")
        self.spawn = patcher.start()
        self.addCleanup(patcher.stop)

    def test_retry_requeues_only_a_failed_item(self):
        up = UploadedMedia.objects.create(kind="video", source_url=YT,
                                          transcribe_status=FAILED, last_error="x")
        resp = self.client.post(f"/api/v1/uploads/{up.id}/retry/")
        self.assertEqual(resp.status_code, 202)
        up.refresh_from_db()
        self.assertEqual((up.transcribe_status, up.last_error), (PENDING, ""))
        # The second click finds it already pending: one job, not two.
        resp = self.client.post(f"/api/v1/uploads/{up.id}/retry/")
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(Job.objects.count(), 1)

    def test_a_done_item_cannot_be_retried(self):
        up = UploadedMedia.objects.create(kind="video", source_url=YT,
                                          transcribe_status=DONE)
        self.assertEqual(
            self.client.post(f"/api/v1/uploads/{up.id}/retry/").status_code, 409)

    def test_a_file_whose_original_is_gone_says_so(self):
        up = UploadedMedia.objects.create(kind="audio", transcribe_status=FAILED)
        resp = self.client.post(f"/api/v1/uploads/{up.id}/retry/")
        self.assertEqual(resp.status_code, 409)
        self.assertIn("caricalo di nuovo", resp.data["detail"])


class DeadWorkers(APITestCase):
    def setUp(self):
        self.client.force_authenticate(User.objects.create_user("t", password="x"))

    def _old(self, obj, minutes):
        type(obj).objects.filter(id=obj.id).update(
            updated_at=timezone.now() - timedelta(minutes=minutes))

    def test_a_pending_row_with_no_job_becomes_failed_with_a_remedy(self):
        up = UploadedMedia.objects.create(kind="video", source_url=YT)
        self._old(up, 10)
        self.client.get("/api/v1/uploads/")
        up.refresh_from_db()
        self.assertEqual(up.transcribe_status, FAILED)
        self.assertIn("Riprova", up.last_error)

    def test_a_fresh_row_is_given_time_for_its_job_to_appear(self):
        up = UploadedMedia.objects.create(kind="video", source_url=YT)
        _fail_orphan_uploads()
        up.refresh_from_db()
        self.assertEqual(up.transcribe_status, PENDING)

    def test_a_row_with_a_live_job_is_left_alone_and_shows_its_progress(self):
        up = UploadedMedia.objects.create(kind="video", source_url=YT)
        self._old(up, 10)
        Job.objects.create(kind="link_transcribe", status="running", progress=55,
                           message="Trascrivo il segmento 2 di 4…",
                           params={"upload_id": up.id})
        resp = self.client.get("/api/v1/uploads/")
        row = (resp.data["results"] if "results" in resp.data else resp.data)[0]
        self.assertEqual(row["transcribe_status"], PENDING)
        self.assertEqual(row["job_progress"], 55)
        self.assertIn("segmento 2", row["job_message"])

    def test_reaping_a_stale_job_fails_the_upload_row_too(self):
        up = UploadedMedia.objects.create(kind="video", source_url=YT)
        job = Job.objects.create(kind="link_transcribe", status="running",
                                 params={"upload_id": up.id})
        self._old(job, 30)
        _reap_stale_jobs()
        up.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual((job.status, up.transcribe_status), ("failed", FAILED))

    def test_a_job_with_a_recent_heartbeat_is_not_reaped(self):
        up = UploadedMedia.objects.create(kind="video", source_url=YT)
        job = Job.objects.create(kind="link_transcribe", status="running",
                                 params={"upload_id": up.id})
        self._old(job, 3)
        _reap_stale_jobs()
        job.refresh_from_db()
        self.assertEqual(job.status, "running")

    def test_the_signal_handler_path_fails_the_row_but_never_a_finished_one(self):
        pending = UploadedMedia.objects.create(kind="video", source_url=YT)
        done = UploadedMedia.objects.create(kind="video", source_url=VIMEO,
                                            transcribe_status=DONE)
        fail_upload_row(Job(kind="link_transcribe", params={"upload_id": pending.id}))
        fail_upload_row(Job(kind="link_transcribe", params={"upload_id": done.id}))
        pending.refresh_from_db()
        done.refresh_from_db()
        self.assertEqual((pending.transcribe_status, done.transcribe_status),
                         (FAILED, DONE))
        # A job of another kind never touches uploads.
        fail_upload_row(Job(kind="ideation", params={"upload_id": 1}))


class LibraryVisibility(APITestCase):
    def test_a_competitor_link_the_model_called_off_topic_still_shows(self):
        self.client.force_authenticate(User.objects.create_user("t", password="x"))
        for url, insp in ((ARTICLE, True), (YT, False)):
            KnowledgeDocument.objects.create(
                source_url=url, source_type="other", title=url,
                owner_type="competitor", is_on_topic=False,
                is_inspiration=insp, published_at=timezone.now())
        resp = self.client.get("/api/v1/knowledge/documents/?scope=competitor")
        rows = resp.data["results"] if "results" in resp.data else resp.data
        self.assertEqual([r["source_url"] for r in rows], [ARTICLE])


@mock.patch("core.upload_workflow._probe_duration", return_value=60.0)
class RunUpload(TestCase):
    TEXT = "Una trascrizione abbastanza lunga da superare il minimo richiesto dal sistema."

    def _link(self, **kw):
        return UploadedMedia.objects.create(
            kind="video", source_url=YT, title=YT, owner_type="competitor", **kw)

    def _run(self, up, **patches):
        meta = {"title": "Canale Salute", "channel": "TVRS", "thumbnail": ""}
        with mock.patch("core.link_ingest.probe", **patches.get("probe", {"return_value": meta})), \
             mock.patch("core.link_ingest.fetch_audio"), \
             mock.patch("core.upload_workflow._transcribe_long",
                        return_value={"text": self.TEXT}), \
             mock.patch("pipeline.agents.knowledge_agent._enrich_one",
                        **patches.get("enrich", {})), \
             mock.patch("pipeline.agents.knowledge_agent._extract_arguments"), \
             mock.patch("pipeline.agents.knowledge_agent._embed_one"):
            return upload_workflow.run_upload_transcribe(up.id)

    def test_the_title_is_read_by_the_worker(self, _d):
        up = self._link()
        self._run(up)
        up.refresh_from_db()
        self.assertEqual((up.title, up.channel, up.transcribe_status),
                         ("Canale Salute", "TVRS", DONE))

    def test_a_private_video_fails_the_row_with_the_reason(self, _d):
        up = self._link()
        with self.assertRaises(LinkRefused):
            self._run(up, probe={"side_effect": LinkRefused("Il video è privato.")})
        up.refresh_from_db()
        self.assertEqual((up.transcribe_status, up.last_error),
                         (FAILED, "Il video è privato."))

    def test_an_analysis_error_does_not_turn_a_good_upload_into_a_failure(self, _d):
        up = self._link()
        result = self._run(up, enrich={"side_effect": RuntimeError("LLM giù")})
        up.refresh_from_db()
        self.assertEqual(up.transcribe_status, DONE)
        self.assertIn("notturna", up.last_error)
        self.assertEqual(result["analysis"], "deferred")
        doc = up.document
        self.assertEqual(doc.enrich_status, PENDING)  # the nightly picks it up
        self.assertTrue(doc.content_text)

    def test_a_removed_link_pasted_again_revives_its_document(self, _d):
        KnowledgeDocument.objects.create(
            source_url=YT, source_type="video", title="vecchio",
            is_active=False, published_at=timezone.now())
        up = self._link()
        self._run(up)
        up.refresh_from_db()
        self.assertTrue(up.document.is_active)

    def test_an_unexpected_error_shows_a_plain_sentence_not_a_repr(self, _d):
        up = self._link()
        with self.assertRaises(KeyError):
            self._run(up, enrich={"side_effect": None},
                      probe={"side_effect": KeyError("segreto /srv/x")})
        up.refresh_from_db()
        self.assertEqual(up.last_error, "Errore imprevisto durante la lavorazione.")

    def test_an_article_is_read_and_stored_under_the_clients_choice(self, _d):
        up = UploadedMedia.objects.create(
            kind="article", source_url=ARTICLE, title=ARTICLE,
            owner_type="competitor", is_inspiration=True)
        art = {"title": "Terapia ormonale", "markdown": "# Terapia\n" + "testo " * 60,
               "text": "testo " * 60, "published_at": None, "author": "Dr. X"}
        with mock.patch("pipeline.agents.blog_agent.fetch_article", return_value=art), \
             mock.patch("pipeline.agents.knowledge_agent._enrich_one"), \
             mock.patch("pipeline.agents.knowledge_agent._extract_arguments"), \
             mock.patch("pipeline.agents.knowledge_agent._embed_one"):
            result = upload_workflow.run_upload_transcribe(up.id)
        up.refresh_from_db()
        doc = up.document
        self.assertEqual(up.transcribe_status, DONE)
        self.assertEqual((doc.owner_type, doc.is_inspiration, doc.is_active),
                         ("competitor", True, True))
        self.assertIsNone(result["blog_draft_id"])  # someone else's text: no Medyca draft

    def test_an_unreadable_page_fails_with_a_sentence(self, _d):
        up = UploadedMedia.objects.create(
            kind="article", source_url=ARTICLE, title=ARTICLE)
        with mock.patch("pipeline.agents.blog_agent.fetch_article", return_value=None):
            with self.assertRaises(upload_workflow.ClientError):
                upload_workflow.run_upload_transcribe(up.id)
        up.refresh_from_db()
        self.assertEqual(up.transcribe_status, FAILED)
        self.assertIn("pagina", up.last_error)
