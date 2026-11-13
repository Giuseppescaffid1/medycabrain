"""_ollama_chat must pin the thread count: Ollama's default (all cores) is ~5x
slower on this VDS. Ollama itself is never called; requests.post is faked."""

from __future__ import annotations

from unittest import mock

from django.test import SimpleTestCase, override_settings

from llm import client


class OllamaThreadTests(SimpleTestCase):
    def _options_sent(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.iter_lines.return_value = [b'{"message": {"content": "ok"}, "done": true}']
        with mock.patch.object(client.requests, "post", return_value=resp) as post:
            client._ollama_chat("s", "u", 10, 0.0)
        return post.call_args.kwargs["json"]["options"]

    @override_settings(OLLAMA_NUM_THREAD=6)
    def test_num_thread_is_sent(self):
        self.assertEqual(self._options_sent()["num_thread"], 6)

    @override_settings(OLLAMA_NUM_THREAD=0)
    def test_zero_leaves_it_to_ollama(self):
        self.assertNotIn("num_thread", self._options_sent())
