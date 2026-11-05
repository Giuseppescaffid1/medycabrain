"""
Browsing pages: what the client sees when it opens a list or a detail.

Each test pins a bug the client reported: an excluded reel that answered 404
(so "Ripristina" never appeared), a competitor cluster served under Medyca,
counts and thumbnails that must not change when they are computed in bulk,
and a library search that must keep returning the same reels now that it
runs on two indexes instead of one concatenated vector.
"""

from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from core import analytics, models


class NavigationBase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("nav", password="nav-pass")
        cls.token = Token.objects.create(user=cls.user)
        cls.med = models.TrackedAccount.objects.create(username="medyca", owner_type="owned")
        cls.comp = models.TrackedAccount.objects.create(username="rivale", owner_type="competitor")

    def setUp(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

    def reel(self, account, code, **kw):
        return models.Reel.objects.create(account=account, shortcode=code, **kw)


class ExcludedReelTests(NavigationBase):
    def test_excluded_reel_opens_and_says_so(self):
        r = self.reel(self.comp, "ESC1", is_active=False)
        resp = self.client.get(f"/api/v1/reels/{r.id}/")
        self.assertEqual(resp.status_code, 200)
        # The detail serializer must carry the flag, or the drawer cannot
        # tell an excluded reel from a normal one.
        self.assertIn("is_active", resp.json())
        self.assertFalse(resp.json()["is_active"])

    def test_excluded_reel_stays_out_of_the_list(self):
        self.reel(self.comp, "ESC2", is_active=False)
        self.reel(self.comp, "OK1")
        codes = [r["shortcode"] for r in self.client.get("/api/v1/reels/").json()["results"]]
        self.assertEqual(codes, ["OK1"])
        codes = [r["shortcode"] for r in
                 self.client.get("/api/v1/reels/?excluded=1").json()["results"]]
        self.assertEqual(codes, ["ESC2"])

    def test_missing_id_is_still_404(self):
        self.assertEqual(self.client.get("/api/v1/reels/999999/").status_code, 404)

    def test_restore_brings_it_back_to_the_list(self):
        r = self.reel(self.comp, "ESC3", is_active=False)
        self.assertEqual(self.client.post(f"/api/v1/reels/{r.id}/restore/").status_code, 200)
        codes = [x["shortcode"] for x in self.client.get("/api/v1/reels/").json()["results"]]
        self.assertIn("ESC3", codes)


class ReelSearchTests(NavigationBase):
    def test_search_matches_caption_and_transcript_only(self):
        a = self.reel(self.comp, "S1", caption="Terapia ormonale e menopausa")
        b = self.reel(self.comp, "S2", caption="Altro")
        models.Transcript.objects.create(reel=b, text="parliamo di menopausa precoce")
        self.reel(self.comp, "S3", caption="Ricetta della torta")
        resp = self.client.get("/api/v1/reels/?search=menopausa")
        ids = sorted(r["id"] for r in resp.json()["results"])
        self.assertEqual(ids, sorted([a.id, b.id]))

    def test_search_does_not_duplicate_a_reel(self):
        a = self.reel(self.comp, "S4", caption="menopausa")
        models.Transcript.objects.create(reel=a, text="menopausa menopausa")
        resp = self.client.get("/api/v1/reels/?search=menopausa")
        self.assertEqual(resp.json()["count"], 1)


class ClusterScopeTests(NavigationBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.run_c = models.ClusterRun.objects.create(scope="competitor", is_current=True)
        cls.run_o = models.ClusterRun.objects.create(scope="owned", is_current=True)
        cls.cl_c = models.TopicCluster.objects.create(run=cls.run_c, label_it="Rivale", size=3)
        cls.cl_o = models.TopicCluster.objects.create(run=cls.run_o, label_it="Nostro", size=1)
        cls.empty = models.TopicCluster.objects.create(run=cls.run_c, label_it="Vuoto", size=0)
        for i in range(3):
            r = cls.reel_for(cls.comp, f"C{i}", views=100 * (i + 1), thumb=f"t{i}.jpg")
            models.ReelClusterAssignment.objects.create(run=cls.run_c, reel=r, cluster=cls.cl_c)
        # a reel without thumbnail must not appear among the previews
        r = cls.reel_for(cls.comp, "C9", views=1, thumb="")
        models.ReelClusterAssignment.objects.create(run=cls.run_c, reel=r, cluster=cls.cl_c)
        r = cls.reel_for(cls.med, "M0", views=5, thumb="m.jpg")
        models.ReelClusterAssignment.objects.create(run=cls.run_o, reel=r, cluster=cls.cl_o)
        doc = models.KnowledgeDocument.objects.create(
            source_type="blog", source_url="https://x.test/a", title="Articolo",
            owner_type="competitor")
        models.DocClusterAssignment.objects.create(run=cls.run_c, document=doc, cluster=cls.cl_c)

    @classmethod
    def reel_for(cls, account, code, views, thumb):
        return models.Reel.objects.create(
            account=account, shortcode=code, view_count=views, thumbnail_file=thumb)

    def test_detail_reports_its_real_scope(self):
        c = self.client.get(f"/api/v1/clusters/{self.cl_c.id}/").json()
        o = self.client.get(f"/api/v1/clusters/{self.cl_o.id}/").json()
        self.assertEqual(c["scope"], "competitor")
        self.assertEqual(o["scope"], "medyca")

    def test_unexpected_run_scope_falls_on_the_competitor_side(self):
        run = models.ClusterRun.objects.create(scope="boh", is_current=False)
        cl = models.TopicCluster.objects.create(run=run, label_it="Strano")
        self.assertEqual(self.client.get(f"/api/v1/clusters/{cl.id}/").json()["scope"],
                         "competitor")

    def test_annotated_counts_match_the_row_by_row_ones(self):
        for scope in ("competitor", "medyca"):
            rows = self.client.get(f"/api/v1/clusters/?scope={scope}").json()
            self.assertTrue(rows)
            for row in rows:
                c = models.TopicCluster.objects.get(id=row["id"])
                self.assertEqual(row["reel_count"], c.reel_assignments.count())
                self.assertEqual(row["doc_count"], c.doc_assignments.count())
                self.assertEqual(row["has_blog"], c.doc_assignments.exists())
                self.assertEqual(row["scope"], scope)

    def test_previews_are_three_at_most_and_skip_missing_thumbnails(self):
        rows = {r["id"]: r for r in self.client.get("/api/v1/clusters/?scope=competitor").json()}
        thumbs = rows[self.cl_c.id]["preview_thumbs"]
        self.assertEqual(len(thumbs), 3)
        self.assertNotIn("", thumbs)
        self.assertEqual(rows[self.empty.id]["preview_thumbs"], [])

    def test_list_cost_does_not_grow_with_the_clusters(self):
        def cost():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get("/api/v1/clusters/?scope=competitor")
            return len(ctx)
        before = cost()
        for i in range(5):
            models.TopicCluster.objects.create(run=self.run_c, label_it=f"Extra{i}")
        self.assertEqual(cost(), before)

    def test_graph_theme_counts_and_children(self):
        data = self.client.get("/api/v1/second-brain/graph/").json()
        node = next(n for n in data["nodes"] if n["id"] == f"competitor:cluster:{self.cl_c.id}")
        self.assertEqual(node["sub"], "4 reel")
        children = [e["target"] for e in data["edges"] if e["source"] == node["id"]]
        self.assertEqual(sum(t.startswith("reel:") for t in children), 4)
        self.assertEqual(sum(t.startswith("doc:") for t in children), 1)

    def test_graph_cost_does_not_grow_with_the_clusters(self):
        def cost():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get("/api/v1/second-brain/graph/")
            return len(ctx)
        before = cost()
        for i in range(5):
            models.TopicCluster.objects.create(run=self.run_c, label_it=f"Extra{i}")
        self.assertEqual(cost(), before)


class AnalyticsTests(ClusterScopeTests):
    def test_cluster_performance_counts_and_average(self):
        rows = analytics.cluster_performance("competitor")
        self.assertEqual([r["label"] for r in rows], ["Rivale"])
        self.assertEqual(rows[0]["reels"], 4)
        self.assertEqual(rows[0]["avg_views"], round((100 + 200 + 300 + 1) / 4))

    def test_cluster_performance_ignores_excluded_reels(self):
        models.Reel.objects.filter(shortcode="C9").update(is_active=False)
        self.assertEqual(analytics.cluster_performance("competitor")[0]["reels"], 3)

    def test_top_content_looks_at_every_reel(self):
        # 450 reels > the old 400 cut: the best one is created last.
        acc = models.TrackedAccount.objects.create(username="grande", owner_type="competitor")
        models.Reel.objects.bulk_create(
            [models.Reel(account=acc, shortcode=f"B{i}", view_count=10) for i in range(450)])
        models.Reel.objects.create(account=acc, shortcode="TOP", view_count=1_000_000)
        top = analytics.top_content("competitor", limit=1)
        self.assertEqual(top[0]["shortcode"], "TOP")
