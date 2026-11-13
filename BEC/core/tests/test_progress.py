"""
La barra «tqdm» della pagina Avanzamento: i contatori degli stadi
(`core/progress.py`), la loro scrittura da `DAG.run`, e cosa rispondono i due
endpoint (`/ops/progress/`, `/ops/llm/`).

Ogni caso viene da un rischio nominato nel disegno: cinque thread sullo stesso
contatore, il database spento a metà, uno stadio fallito, un giro interrotto,
la velocità prima dei 3 elementi.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import OperationalError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from core import progress, progress_report
from core.models import BatchRun, Job, LLMCall, StageRun
from llm import usage
from pipeline import dag
from pipeline.agents import enrich_agent


class CounterThreadSafetyTests(SimpleTestCase):
    """ENRICH_WORKERS=5 threads touch the same counter."""

    def setUp(self):
        self.writes = []
        p = mock.patch.object(progress, "_write",
                              side_effect=lambda f, sid=None: self.writes.append(dict(f)))
        p.start()
        self.addCleanup(p.stop)
        progress.bind(1)
        self.addCleanup(lambda: progress.bind(None))

    def test_five_threads_lose_no_count(self):
        progress.open(500, "reel", "Analisi")

        def work(_):
            for _i in range(20):
                progress.item_done("done")
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(work, range(25)))
        self.assertEqual(progress.snapshot_counts()["done"], 500)

    def test_parallel_helper_counts_inside_the_workers_once_per_item(self):
        class Item:
            def __init__(self, i):
                self.id, self.shortcode = i, f"s{i}"

        calls = []

        def fn(item):
            calls.append(item.id)
            if item.id == 3:
                raise ValueError("no")

        progress.open(8, "reel", "Analisi")
        with mock.patch.object(enrich_agent, "_WORKERS", 4), \
             mock.patch("django.db.connection.close"):
            results = list(enrich_agent._parallel([Item(i) for i in range(8)], fn))
        self.assertEqual(len(results), 8)
        s = progress.snapshot_counts()
        self.assertEqual((s["done"], s["failed"]), (7, 1))

    def test_single_worker_path_counts_too(self):
        class Item:
            id, shortcode = 1, "s"

        progress.open(1, "reel", "Analisi")
        with mock.patch.object(enrich_agent, "_WORKERS", 1):
            list(enrich_agent._parallel([Item()], lambda _i: None))
        self.assertEqual(progress.snapshot_counts()["done"], 1)

    def test_a_rate_limit_retry_is_not_counted_as_a_second_item(self):
        class Item:
            id, shortcode = 1, "s"

        attempts = []

        def fn(_item):
            attempts.append(1)
            if len(attempts) == 1:
                raise enrich_agent.LLMRateLimit(0.0)

        progress.open(1, "reel", "Analisi")
        with mock.patch.object(enrich_agent, "_WORKERS", 2), \
             mock.patch.object(enrich_agent.time, "sleep"), \
             mock.patch("django.db.connection.close"):
            list(enrich_agent._parallel([Item()], fn))
        s = progress.snapshot_counts()
        self.assertEqual((len(attempts), s["done"], s["failed"]), (2, 1, 0))

    def test_without_a_bound_stage_everything_is_a_noop(self):
        progress.bind(None)
        progress.open(5, "reel", "x")
        progress.item_done("done")
        progress.note("x")
        self.assertEqual(progress.snapshot_counts(), {})

    def test_phases_are_kept_when_the_next_one_opens(self):
        progress.open(2, "reel", "Analisi")
        progress.item_done("done")
        progress.item_done("failed")
        progress.open(1, "reel", "Affermazioni")
        s = progress.snapshot_counts()
        self.assertEqual(s["phase"], "Affermazioni")
        self.assertEqual(s["phases"][0]["phase"], "Analisi")
        self.assertEqual((s["phases"][0]["done"], s["phases"][0]["failed"]), (1, 1))

    def test_writes_are_throttled(self):
        progress.open(100, "reel", "x")
        self.writes.clear()
        for _ in range(100):
            progress.item_done("done")
        self.assertLessEqual(len(self.writes), 1)


class DatabaseDownTests(TestCase):
    def setUp(self):
        usage._reset_breaker()
        self.addCleanup(usage._reset_breaker)

    def test_a_stage_goes_on_when_the_progress_writes_fail(self):
        boom = OperationalError("giù")
        row = StageRun.objects.create(run_id="r", stage="enrich")
        with mock.patch("django.db.models.query.QuerySet.update", side_effect=boom):
            progress.bind(row.id)
            progress.open(3, "reel", "Analisi")
            progress.start_item("reel", 1, "x")
            progress.item_done("done")
            progress.note("n")
            progress.end_stage("done")
        # nothing raised; the in-memory state was closed all the same
        self.assertEqual(progress.snapshot_counts(), {})

    def test_the_plan_is_empty_when_the_database_is_down(self):
        with mock.patch("django.db.models.query.QuerySet.bulk_create",
                        side_effect=OperationalError("x")):
            self.assertEqual(progress.plan_stages("r", ["scrape"], "cron"), {})


class DagWritesStageRunsTests(TestCase):
    def setUp(self):
        usage._reset_breaker()
        p = mock.patch("builtins.print")
        p.start()
        self.addCleanup(p.stop)

    def test_every_stage_gets_a_row_and_a_failed_one_says_why(self):
        def good(ctx):
            progress.open(10, "reel", "Download")
            for _ in range(10):
                progress.item_done("done")
            return {"ok": 1}

        def bad(ctx):
            progress.open(120, "reel", "Analisi")
            for _ in range(37):
                progress.item_done("done")
            raise RuntimeError("segreto: /srv/media/x.mp3")

        def later(ctx):
            return {}

        code = dag.DAG([dag.Step("download", good), dag.Step("enrich", bad),
                        dag.Step("embed", later)]).run(
            dag.Context(), source="manual")
        self.assertEqual(code, 1)
        rows = {r.stage: r for r in StageRun.objects.all()}
        self.assertEqual(set(rows), {"download", "enrich", "embed"})
        self.assertEqual(len({r.run_id for r in rows.values()}), 1)
        self.assertEqual(rows["download"].status, "done")
        self.assertEqual((rows["download"].done, rows["download"].total), (10, 10))
        e = rows["enrich"]
        self.assertEqual((e.status, e.done, e.total), ("failed", 37, 120))
        # a sentence, not a repr, and no server path
        self.assertNotIn("/srv", e.error)
        self.assertTrue(e.error)
        self.assertEqual(rows["embed"].status, "done")  # the next stage still ran
        self.assertEqual(rows["embed"].source, "manual")
        self.assertIsNotNone(e.finished_at)

    def test_a_fatal_stage_does_not_leave_phantom_waiting_rows(self):
        def boom(ctx):
            raise RuntimeError("x")

        dag.DAG([dag.Step("scrape", boom, fatal=True),
                 dag.Step("download", lambda c: {})]).run(dag.Context())
        self.assertEqual(list(StageRun.objects.values_list("stage", "status")),
                         [("scrape", "failed")])

    def test_a_dry_run_plans_nothing(self):
        dag.DAG([dag.Step("scrape", lambda c: {})]).run(dag.Context(dry_run=True))
        self.assertEqual(StageRun.objects.count(), 0)

    def test_model_calls_of_a_stage_carry_the_stage_and_the_round(self):
        seen = {}

        def step(ctx):
            seen.update(usage.current())
            return {}
        dag.DAG([dag.Step("enrich", step)]).run(dag.Context(), job_id=None)
        row = StageRun.objects.get()
        self.assertEqual((seen["process"], seen["stage"]), ("pipeline:enrich", "enrich"))
        self.assertEqual((seen["run_id"], seen["stage_run_id"]), (row.run_id, row.id))


class ProgressSnapshotTests(TestCase):
    def setUp(self):
        usage._reset_breaker()
        usage._last_reap = 1e18  # keep the ghost sweep out unless a test asks
        progress_report._prev_cache.update(at=1e18, value={})
        self.addCleanup(lambda: progress_report._prev_cache.update(at=0.0, value={}))
        self.pid = os.getpid()

    def _stage(self, **kw):
        kw.setdefault("run_id", "r1")
        kw.setdefault("pid", self.pid)
        return StageRun.objects.create(**kw)

    def test_speed_and_time_left_are_computed_on_the_server(self):
        now = timezone.now()
        self._stage(stage="enrich", status="running", total=120, done=37, unit="reel",
                    phase="Analisi", started_at=now - timedelta(minutes=8),
                    phase_started_at=now - timedelta(minutes=8))
        st = progress_report.progress_snapshot()["rounds"][0]["stages"][0]
        self.assertEqual(st["rate_source"], "measured")
        self.assertAlmostEqual(st["rate_per_minute"], 37 / 8, delta=0.1)
        self.assertAlmostEqual(st["eta_seconds"], (120 - 37) / (37 / 480), delta=15)

    def test_before_three_items_there_is_no_invented_speed(self):
        now = timezone.now()
        self._stage(stage="blogscrape", status="running", total=30, done=2,
                    started_at=now - timedelta(minutes=1),
                    phase_started_at=now - timedelta(minutes=1))
        st = progress_report.progress_snapshot()["rounds"][0]["stages"][0]
        self.assertIsNone(st["rate_per_minute"])
        self.assertIsNone(st["eta_seconds"])

    def test_before_three_items_the_previous_rounds_speed_is_used_and_labelled(self):
        progress_report._prev_cache.update(at=1e18, value={"download": 30.0})
        now = timezone.now()
        self._stage(stage="download", status="running", total=10, done=1,
                    started_at=now, phase_started_at=now)
        st = progress_report.progress_snapshot()["rounds"][0]["stages"][0]
        self.assertEqual(st["rate_source"], "previous")
        self.assertEqual(st["rate_per_minute"], 2.0)
        self.assertEqual(st["eta_seconds"], 270)

    def test_a_stage_without_a_total_shows_no_numbers(self):
        self._stage(stage="embed", status="running", started_at=timezone.now())
        st = progress_report.progress_snapshot()["rounds"][0]["stages"][0]
        self.assertIsNone(st["total"])
        self.assertIsNone(st["eta_seconds"])

    def test_open_calls_show_who_works_and_in_what_state(self):
        s = self._stage(stage="enrich", status="running", total=5,
                        started_at=timezone.now(), phase_started_at=timezone.now())
        now = timezone.now()
        base = dict(process="pipeline:enrich", stage_run=s, run_id="r1", pid=self.pid,
                    item_kind="reel", max_tokens=2000)
        LLMCall.objects.create(item_label="@a · 1", is_local=True, provider="ollama",
                               status="running", started_at=now - timedelta(seconds=50),
                               tokens_so_far=200, **base)
        LLMCall.objects.create(item_label="@b · 2", is_local=True, provider="ollama",
                               status="waiting", **base)
        LLMCall.objects.create(item_label="@c · 3", is_local=False, provider="gw",
                               status="running", started_at=now, **base)
        st = progress_report.progress_snapshot()["rounds"][0]["stages"][0]
        by = {i["label"]: i for i in st["items"]}
        self.assertEqual(by["@a · 1"]["state"], "writing")
        self.assertAlmostEqual(by["@a · 1"]["tokens_per_second"], 4.0, delta=0.3)
        self.assertEqual(by["@b · 2"]["state"], "waiting")
        self.assertEqual(by["@c · 3"]["state"], "running")
        self.assertIsNone(by["@c · 3"]["tokens"])  # remote: no live tokens
        self.assertEqual(st["who"], "llm_mixed")
        # not enough finished answers of this process: no "di solito"
        self.assertIsNone(by["@a · 1"]["usual_remaining_seconds"])
        self.assertAlmostEqual(by["@a · 1"]["max_remaining_seconds"], 1800 / 4.0, delta=150)

    def test_usual_time_left_needs_five_finished_answers(self):
        s = self._stage(stage="enrich", status="running", total=5,
                        started_at=timezone.now(), phase_started_at=timezone.now())
        base = dict(process="pipeline:enrich", is_local=True, provider="ollama", pid=self.pid)
        for _ in range(5):
            LLMCall.objects.create(status="done", output_tokens=400, **base)
        LLMCall.objects.create(status="running", stage_run=s, tokens_so_far=100,
                               started_at=timezone.now() - timedelta(seconds=25),
                               max_tokens=2000, **base)
        it = progress_report.progress_snapshot()["rounds"][0]["stages"][0]["items"][0]
        self.assertAlmostEqual(it["usual_remaining_seconds"], 300 / 4.0, delta=15)

    def test_a_round_whose_process_died_is_closed_as_interrupted_not_requeued(self):
        usage._last_reap = 0.0
        self._stage(stage="enrich", status="running", pid=999_999_999,
                    started_at=timezone.now())
        self._stage(stage="embed", status="waiting", pid=999_999_999)
        snap = progress_report.progress_snapshot()
        rnd = snap["rounds"][0]
        self.assertFalse(rnd["active"])
        self.assertTrue(rnd["interrupted"])
        self.assertEqual({s["status"] for s in rnd["stages"]}, {"failed"})
        self.assertEqual({s["error"] for s in rnd["stages"]}, {"giro interrotto"})

    def test_idle_shows_the_last_round(self):
        done = timezone.now() - timedelta(hours=2)
        self._stage(run_id="old", stage="enrich", status="done", total=3, done=3,
                    started_at=done, finished_at=done + timedelta(minutes=5))
        snap = progress_report.progress_snapshot()
        self.assertFalse(snap["running"])
        self.assertEqual(snap["rounds"][0]["run_id"], "old")
        self.assertFalse(snap["rounds"][0]["active"])

    def test_empty_database_is_an_empty_answer_not_an_error(self):
        snap = progress_report.progress_snapshot()
        self.assertEqual((snap["rounds"], snap["jobs"], snap["batches"]), ([], [], []))
        self.assertFalse(snap["running"])

    def test_jobs_and_open_batches(self):
        Job.objects.create(kind="strategy", status="running", progress=40, message="Leggo")
        Job.objects.create(kind="pipeline", status="running", progress=10)
        BatchRun.objects.create(kind="reel_enrich", batch_id="b1", model="m",
                                items=[{}, {}, {}], status="submitted")
        BatchRun.objects.create(kind="reel_enrich", batch_id="b2", status="collected")
        snap = progress_report.progress_snapshot()
        self.assertEqual([j["kind"] for j in snap["jobs"]], ["strategy"])  # no pipeline bar
        self.assertEqual(len(snap["batches"]), 1)
        b = snap["batches"][0]
        self.assertEqual(b["items"], 3)
        self.assertEqual(b["expected_by"] - b["submitted_at"], timedelta(hours=24))

    def test_a_call_outside_any_stage_is_shown_not_hidden(self):
        LLMCall.objects.create(process="web:chat", provider="ollama", is_local=True,
                               status="waiting", pid=self.pid)
        snap = progress_report.progress_snapshot()
        self.assertEqual(snap["other_calls"][0]["process_label"], "Chat sui contenuti")
        self.assertTrue(snap["running"])

    def test_query_count_stays_small(self):
        self._stage(stage="enrich", status="running", total=5,
                    started_at=timezone.now(), phase_started_at=timezone.now())
        with self.assertNumQueries(6):
            progress_report.progress_snapshot()


class EndpointTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("avanz", password="x")
        cls.token = Token.objects.create(user=cls.user)

    def auth(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def test_both_endpoints_need_login(self):
        for url in ("/api/v1/ops/progress/", "/api/v1/ops/llm/"):
            self.assertIn(self.client.get(url).status_code, (401, 403))

    def test_progress_endpoint_answers(self):
        self.auth()
        r = self.client.get("/api/v1/ops/progress/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["rounds"], [])

    def test_daily_totals_split_local_hours_from_remote(self):
        self.auth()
        now = timezone.now()
        mk = LLMCall.objects.create
        mk(process="pipeline:enrich", is_local=True, status="done", provider="ollama",
           duration_seconds=100, wait_seconds=20, prompt_tokens=300, output_tokens=400,
           eval_seconds=100, model="qwen")
        mk(process="pipeline:enrich", is_local=True, status="failed", provider="ollama",
           duration_seconds=50)
        mk(process="pipeline:transcribe", is_local=True, status="done", kind="stt",
           provider="whisper-locale", duration_seconds=60)
        mk(process="pipeline:enrich", is_local=False, status="done", provider="gw",
           duration_seconds=3, prompt_tokens=10, output_tokens=5)
        old = mk(process="pipeline:enrich", is_local=True, status="done", duration_seconds=999)
        LLMCall.objects.filter(id=old.id).update(created_at=now - timedelta(days=3))

        r = self.client.get("/api/v1/ops/llm/")
        self.assertEqual(r.status_code, 200)
        d = r.json()
        rows = {p["process"]: p for p in d["by_process"]}
        self.assertEqual(rows["pipeline:enrich"]["machine_seconds"], 150)
        self.assertEqual(rows["pipeline:enrich"]["failed"], 1)
        self.assertEqual(rows["pipeline:enrich"]["wait_seconds"], 20)
        self.assertEqual(rows["pipeline:enrich"]["label"], "Analisi dei contenuti")
        self.assertEqual(rows["pipeline:transcribe"]["transcription_seconds"], 60)
        self.assertEqual(d["total_machine_seconds"], 210)  # whisper hours included
        self.assertEqual(d["remote"]["calls"], 1)
        self.assertEqual(d["remote"]["tokens_out"], 5)
        self.assertEqual(d["speed"]["tokens_per_second"], 4.0)

    def test_daily_endpoint_takes_a_day_and_survives_junk(self):
        self.auth()
        self.assertEqual(self.client.get("/api/v1/ops/llm/?day=2026-01-02").json()["day"],
                         "2026-01-02")
        self.assertEqual(self.client.get("/api/v1/ops/llm/?day=boh").status_code, 200)


class PruneTests(TestCase):
    def test_old_closed_rows_go_open_ones_stay(self):
        old = timezone.now() - timedelta(days=100)
        a = LLMCall.objects.create(process="x", status="done")
        b = LLMCall.objects.create(process="x", status="running")
        c = LLMCall.objects.create(process="x", status="done")  # recent
        s = StageRun.objects.create(run_id="r", stage="enrich", status="failed")
        for obj in (a, b, s):
            type(obj).objects.filter(id=obj.id).update(created_at=old)
        out = StringIO()
        call_command("prune_llm_calls", "--dry-run", stdout=out)
        self.assertEqual(LLMCall.objects.count(), 3)
        call_command("prune_llm_calls", stdout=out)
        self.assertEqual(set(LLMCall.objects.values_list("id", flat=True)), {b.id, c.id})
        self.assertEqual(StageRun.objects.count(), 0)
