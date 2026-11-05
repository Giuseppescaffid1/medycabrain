"""
Every list endpoint must return 200 for an authenticated user.

Trivial as it looks, this is the test that would have caught a missing comma
in `StrategyBriefSerializer.fields` — Python silently concatenated two field
names into one that does not exist, and every request to the briefs endpoint
answered 500 for a day without anything in the logs saying so.
"""

from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from core import models

ENDPOINTS = [
    "/api/v1/reels/",
    "/api/v1/accounts/",
    "/api/v1/clusters/",
    "/api/v1/tags/",
    "/api/v1/jobs/",
    "/api/v1/custom-topics/",
    "/api/v1/knowledge/documents/",
    "/api/v1/second-brain/ideas/",
    "/api/v1/second-brain/blog-drafts/",
    "/api/v1/second-brain/briefs/",
    "/api/v1/second-brain/coverage-map/",
    "/api/v1/second-brain/graph/",
    "/api/v1/stats/overview/",
    "/api/v1/ops/status/",
    "/api/v1/analytics/?metric=overview&scope=medyca",
]


class EndpointSmokeTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("smoke", password="smoke-pass")
        cls.token = Token.objects.create(user=cls.user)
        # One row per model whose serializer is exercised only when it has a
        # row to serialise: DRF builds `fields` lazily, so with empty tables a
        # misspelt field (the missing comma in BlogDraftSerializer, which made
        # /second-brain/blog-drafts/ answer 500 for weeks) passed this test.
        models.BlogDraft.objects.create(
            mode="draft", cluster_label="Tiroide", title="Bozza", content_md="Testo",
            llm_model="test-model")
        models.ContentIdea.objects.create(argument_it="Idea")
        models.StrategyBrief.objects.create(input_text="Tema")

    def setUp(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def test_list_endpoints_answer_200(self):
        for url in ENDPOINTS:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(
                    resp.status_code, 200,
                    f"{url} ha risposto {resp.status_code}: {resp.content[:200]!r}",
                )

    def test_endpoints_require_authentication(self):
        self.client.credentials()  # drop the token
        resp = self.client.get("/api/v1/reels/")
        self.assertIn(resp.status_code, (401, 403))
