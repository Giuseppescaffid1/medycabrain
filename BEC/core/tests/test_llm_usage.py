"""
Il registratore delle chiamate al modello (`llm/usage.py`, agganciato in
`llm/client.py`): cosa scrive, quando, e che non rompa mai una chiamata.

Ollama non c'è in CI: `requests.post` è finto e il lucchetto vero (un file) è
sostituito o puntato a una cartella temporanea. Il modello remoto è finto allo
stesso modo. Nessun test usa la rete.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from django.db import OperationalError
from django.test import SimpleTestCase, TestCase, override_settings

from django.utils import timezone

from core.models import LLMCall, StageRun
from llm import client, usage

SECRET_PROMPT = "TESTO-RISERVATO-DEL-PROMPT-12345"


def _ollama_response(lines: list[dict]):
    resp = mock.MagicMock()
    resp.__enter__.return_value = resp
    resp.iter_lines.return_value = [json.dumps(x).encode() for x in lines]
    return resp


_STREAM = [
    {"message": {"content": "ci"}, "done": False},
    {"message": {"content": "ao"}, "done": False},
    {"message": {"content": ""}, "done": True, "done_reason": "stop",
     "prompt_eval_count": 35, "eval_count": 2,
     "load_duration": 2_000_000_000, "prompt_eval_duration": 3_000_000_000,
     "eval_duration": 4_000_000_000, "total_duration": 9_000_000_000},
]


@override_settings(LLM_PROVIDER_ORDER=["ollama"])
class OllamaRecordingTests(TestCase):
    def setUp(self):
        usage._reset_breaker()
        lock = tempfile.mktemp(prefix="test-ollama-lock-")
        p = override_settings(OLLAMA_LOCK_PATH=lock)
        p.enable()
        self.addCleanup(p.disable)

    def _chat(self, **kw):
        with mock.patch.object(client.requests, "post",
                               return_value=_ollama_response(_STREAM)):
            return client.chat("sistema", SECRET_PROMPT, retries=0, **kw)

    def test_row_carries_the_real_numbers_from_ollamas_last_line(self):
        with usage.scope("pipeline:enrich", stage="enrich"):
            usage.set_item("reel", 7, "@medyca · ABC")
            self.assertEqual(self._chat(max_tokens=300), "ciao")
        c = LLMCall.objects.get()
        self.assertEqual((c.status, c.is_local, c.provider), ("done", True, "ollama"))
        self.assertEqual((c.process, c.stage), ("pipeline:enrich", "enrich"))
        self.assertEqual((c.item_kind, c.item_id, c.item_label), ("reel", 7, "@medyca · ABC"))
        self.assertEqual((c.prompt_tokens, c.output_tokens), (35, 2))
        self.assertEqual((c.load_seconds, c.prompt_seconds, c.eval_seconds), (2.0, 3.0, 4.0))
        self.assertEqual(c.max_tokens, 300)
        self.assertIsNotNone(c.started_at)
        self.assertIsNotNone(c.wait_seconds)
        self.assertFalse(c.truncated)

    def test_the_prompt_and_the_answer_are_never_saved(self):
        self._chat()
        row = LLMCall.objects.values().get()
        blob = json.dumps(row, default=str)
        self.assertNotIn(SECRET_PROMPT, blob)
        self.assertNotIn("ciao", blob)
        self.assertEqual(row["prompt_chars"], len("sistema") + len(SECRET_PROMPT))

    def test_the_row_is_born_waiting_before_the_lock(self):
        seen = {}

        @contextlib.contextmanager
        def slot(**_kw):
            seen["status"] = LLMCall.objects.get().status
            yield

        with mock.patch.object(client, "_ollama_slot", slot):
            self._chat()
        self.assertEqual(seen["status"], "waiting")
        self.assertEqual(LLMCall.objects.get().status, "done")

    def test_length_cut_is_marked_truncated(self):
        cut = [dict(_STREAM[-1], done_reason="length")]
        with mock.patch.object(client.requests, "post",
                               return_value=_ollama_response(cut)):
            client.chat("s", "u", retries=0)
        self.assertTrue(LLMCall.objects.get().truncated)

    def test_a_timeout_that_returns_partial_text_is_marked_truncated(self):
        # Ollama keeps streaming past the deadline: the answer is cut and the
        # caller never knew (fact 13 of the design).
        endless = [{"message": {"content": "x"}, "done": False}] * 3
        with mock.patch.object(client.requests, "post",
                               return_value=_ollama_response(endless)):
            client.chat("s", "u", retries=0, timeout=-1)
        c = LLMCall.objects.get()
        self.assertTrue(c.truncated)
        self.assertEqual(c.status, "done")

    def test_an_error_closes_the_row_as_failed(self):
        with mock.patch.object(client.requests, "post", side_effect=OSError("giù")):
            with self.assertRaises(client.LLMError):
                client.chat("s", "u", retries=0)
        c = LLMCall.objects.get()
        self.assertEqual(c.status, "failed")
        self.assertIn("giù", c.error)

    def test_no_free_slot_is_a_failure_not_a_silent_row(self):
        @contextlib.contextmanager
        def busy(**_kw):
            raise client.LLMError("ollama busy: no free slot after 900s")
            yield  # pragma: no cover

        with mock.patch.object(client, "_ollama_slot", busy):
            with self.assertRaises(client.LLMError):
                client.chat("s", "u", retries=0)
        c = LLMCall.objects.get()
        self.assertEqual(c.status, "failed")
        self.assertIsNone(c.started_at)  # it never got the lock

    def test_live_tokens_are_throttled_to_one_write_per_interval(self):
        # 30 chunks in well under 2 s: one live write at most, then the real numbers.
        lines = [{"message": {"content": "a"}, "done": False}] * 30 + [_STREAM[-1]]
        with mock.patch.object(client.requests, "post",
                               return_value=_ollama_response(lines)):
            with mock.patch.object(usage.Call, "_update", autospec=True) as upd:
                client.chat("s", "u", retries=0)
        live = [c for c in upd.call_args_list
                if "tokens_so_far" in c.kwargs and c.kwargs.get("status") != "done"]
        self.assertLessEqual(len(live), 1)


class RemoteRecordingTests(TestCase):
    ENDPOINT = {"name": "gw", "api_key": "k", "base_url": "http://x/v1",
                "models": {"analysis": "m1", "reasoning": "m1", "bulk": "m1"}}

    def setUp(self):
        usage._reset_breaker()

    @override_settings(LLM_PROVIDER_ORDER=["fast"], FAST_ENDPOINTS=[ENDPOINT])
    def test_remote_row_has_tokens_and_is_not_local(self):
        resp = mock.MagicMock(status_code=200)
        resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 33}}
        with mock.patch.object(client.requests, "post", return_value=resp):
            self.assertEqual(client.chat("s", SECRET_PROMPT, retries=0), "ok")
        c = LLMCall.objects.get()
        self.assertEqual((c.status, c.is_local, c.provider), ("done", False, "gw"))
        self.assertEqual((c.prompt_tokens, c.output_tokens), (120, 33))
        self.assertEqual(c.model, "m1")
        self.assertIsNotNone(c.duration_seconds)

    @override_settings(LLM_PROVIDER_ORDER=["fast"], FAST_ENDPOINTS=[ENDPOINT])
    def test_remote_without_usage_still_writes_the_row(self):
        resp = mock.MagicMock(status_code=200)
        resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        with mock.patch.object(client.requests, "post", return_value=resp):
            client.chat("s", "u", retries=0)
        c = LLMCall.objects.get()
        self.assertEqual(c.status, "done")
        self.assertIsNone(c.output_tokens)


@override_settings(LLM_PROVIDER_ORDER=["ollama"])
class RecordingNeverBreaksTheCallTests(TestCase):
    """The hot spot of the design: client.py is where everything passes."""

    def setUp(self):
        usage._reset_breaker()
        self.addCleanup(usage._reset_breaker)
        p = override_settings(OLLAMA_LOCK_PATH=tempfile.mktemp(prefix="test-lock-"))
        p.enable()
        self.addCleanup(p.disable)

    def _chat(self):
        with mock.patch.object(client.requests, "post",
                               return_value=_ollama_response(_STREAM)):
            return client.chat("s", "u", retries=0)

    def test_database_down_the_answer_still_arrives(self):
        boom = OperationalError("la connessione è caduta")
        with mock.patch.object(LLMCall.objects, "create", side_effect=boom), \
             mock.patch("django.db.models.query.QuerySet.update", side_effect=boom):
            self.assertEqual(self._chat(), "ciao")

    def test_database_down_trips_the_breaker_so_the_next_call_does_not_retry(self):
        boom = OperationalError("giù")
        with mock.patch.object(LLMCall.objects, "create", side_effect=boom) as create:
            self._chat()
            self._chat()
        self.assertEqual(create.call_count, 1)

    def test_any_other_error_in_a_write_is_swallowed_too(self):
        with mock.patch.object(LLMCall.objects, "create", side_effect=ValueError("x")):
            self.assertEqual(self._chat(), "ciao")

    def test_a_failed_write_inside_a_transaction_does_not_poison_it(self):
        # The write runs in a savepoint, so a caller inside atomic() survives.
        from django.db import transaction
        with transaction.atomic():
            with mock.patch.object(LLMCall.objects, "create",
                                   side_effect=OperationalError("x")):
                self._chat()
            usage._reset_breaker()
            LLMCall.objects.count()  # would raise TransactionManagementError if poisoned


class ScopeTests(SimpleTestCase):
    def test_default_label_for_a_command_and_for_nothing(self):
        with mock.patch.object(usage.sys, "argv", ["manage.py", "reprocess"]):
            self.assertEqual(usage.current()["process"], "cmd:reprocess")
        with mock.patch.object(usage.sys, "argv", ["gunicorn"]):
            self.assertEqual(usage.current()["process"], "altro")

    def test_pool_threads_keep_the_stage_through_the_process_fallback(self):
        # enrich runs its calls in a thread pool, where a contextvar is empty.
        with usage.scope("pipeline:enrich", stage="enrich", run_id="r1"):
            with ThreadPoolExecutor(max_workers=5) as pool:
                seen = list(pool.map(lambda _: usage.current(), range(10)))
        self.assertTrue(all(s["process"] == "pipeline:enrich" and s["run_id"] == "r1"
                            for s in seen))
        with mock.patch.object(usage.sys, "argv", ["gunicorn"]):
            self.assertEqual(usage.current()["process"], "altro")  # and it is restored

    def test_inner_scope_inherits_the_job(self):
        with usage.scope("job:pipeline", job_id=9, run_id="r9"):
            with usage.scope("pipeline:enrich", stage="enrich") as inner:
                self.assertEqual((inner["job_id"], inner["run_id"]), (9, "r9"))

    def test_default_scope_does_not_override_an_outer_one(self):
        with usage.scope("web:chat"):
            with usage.scope("mcp:cerca", default=True):
                self.assertEqual(usage.current()["process"], "web:chat")
        with usage.scope("mcp:cerca", default=True):
            self.assertEqual(usage.current()["process"], "mcp:cerca")


class GhostTests(TestCase):
    def setUp(self):
        usage._reset_breaker()
        usage._last_reap = 0.0

    def test_a_row_of_a_dead_process_is_closed_as_failed_never_requeued(self):
        dead = LLMCall.objects.create(process="x", status="running", pid=999_999_999)
        alive = LLMCall.objects.create(process="y", status="running",
                                       pid=__import__("os").getpid())
        usage.close_ghosts()
        dead.refresh_from_db()
        alive.refresh_from_db()
        self.assertEqual((dead.status, dead.error), ("failed", "processo interrotto"))
        self.assertIsNotNone(dead.finished_at)
        self.assertEqual(alive.status, "running")

    def test_sweep_runs_at_most_once_per_interval(self):
        usage.close_ghosts()
        LLMCall.objects.create(process="x", status="running", pid=999_999_999)
        usage.close_ghosts()  # inside the interval: no write
        self.assertEqual(LLMCall.objects.get().status, "running")


class LongRoundsAreNotGhostsTests(TestCase):
    """A round of more than 3 hours (enrich on the local model) must not be
    closed by the sweep while its process lives and keeps writing."""

    def setUp(self):
        usage._reset_breaker()
        usage._last_reap = 0.0
        self.pid = os.getpid()

    def _stage(self, stage, status, created_ago, beat_ago):
        row = StageRun.objects.create(run_id="long", stage=stage, status=status,
                                      pid=self.pid)
        now = timezone.now()
        StageRun.objects.filter(id=row.id).update(
            created_at=now - created_ago, updated_at=now - beat_ago)
        return row

    def test_a_live_round_with_a_recent_beat_is_left_alone_waiting_stages_too(self):
        running = self._stage("enrich", "running", timedelta(hours=5), timedelta(seconds=3))
        waiting = self._stage("embed", "waiting", timedelta(hours=5), timedelta(hours=5))
        usage.close_ghosts()
        for r in (running, waiting):
            r.refresh_from_db()
            self.assertIn(r.status, ("running", "waiting"))
            self.assertEqual(r.error, "")

    def test_a_live_pid_with_no_beat_for_hours_is_closed_as_a_reused_pid(self):
        stuck = self._stage("enrich", "running", timedelta(hours=5), timedelta(hours=4))
        usage.close_ghosts()
        stuck.refresh_from_db()
        self.assertEqual((stuck.status, stuck.error), ("failed", "giro interrotto"))

    def test_a_dead_pid_is_still_closed_at_once(self):
        row = StageRun.objects.create(run_id="d", stage="enrich", status="running",
                                      pid=999_999_999)
        usage.close_ghosts()
        row.refresh_from_db()
        self.assertEqual(row.status, "failed")

    def test_a_row_closed_done_in_the_meantime_is_not_rewritten_failed(self):
        row = StageRun.objects.create(run_id="d", stage="enrich", status="running",
                                      pid=999_999_999)
        real = StageRun.objects.filter

        def closed_meanwhile(*a, **kw):
            if "id__in" in kw:
                StageRun.objects.filter(id=row.id).update(status="done")
            return real(*a, **kw)
        with mock.patch.object(StageRun.objects, "filter", side_effect=closed_meanwhile):
            usage.close_ghosts()
        row.refresh_from_db()
        self.assertEqual(row.status, "done")


class FinalTokensTests(TestCase):
    def test_a_finished_call_closes_on_the_real_token_count(self):
        usage._reset_breaker()
        rec = usage.begin("ollama", "m", is_local=True, waiting=False)
        rec.tokens(49)
        rec.stats(output_tokens=60)
        rec.done()
        c = LLMCall.objects.get()
        self.assertEqual((c.tokens_so_far, c.output_tokens), (60, 60))
