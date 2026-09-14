"""
What a pasted link must become, before it ever touches the network.

`extract_links` is the only piece of the link path that is pure string work,
and it is the piece that decides `KnowledgeDocument.source_url` — which is
`unique=True`. Get it wrong and the same video arrives three times, or an
unlisted Vimeo video arrives at an address nobody can open. Everything here
runs offline on purpose: no oEmbed call, no yt-dlp — the endpoint test at the
bottom stubs `probe` and the job spawn for the same reason.

Half of these tests are about **YouTube not moving**: the link path was built
for it, eleven of the client's videos are already in on it, and the provider
table is a rewrite of the module they go through.

The Vimeo ids are the client's three real TVRS links, dirty query string and
`#t=` fragment included, exactly as he pasted them (14/09/2026).
"""

from unittest import mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from core.link_ingest import LinkRefused, canonical_url, extract_links, provider_for
from core.models import UploadedMedia

# The three parts of "Canale Salute – Pressione Arteriosa", as pasted.
VIMEO_PASTED = [
    "https://vimeo.com/1220776839?fl=pl&fe=cm#t=3m12s",
    "https://vimeo.com/1220777690?fl=pl&fe=cm#t=41s",
    "https://vimeo.com/1220778172?fl=pl&fe=cm#t=41s",
]


class ExtractVimeo(SimpleTestCase):
    def test_the_three_real_links_are_recognised_and_cleaned(self):
        refs = extract_links("\n".join(
            f"Parte {n}: {u}" for n, u in enumerate(VIMEO_PASTED, 1)))
        self.assertEqual([r.video_id for r in refs],
                         ["1220776839", "1220777690", "1220778172"])
        self.assertEqual([r.url for r in refs], [
            "https://vimeo.com/1220776839",
            "https://vimeo.com/1220777690",
            "https://vimeo.com/1220778172",
        ])
        self.assertEqual({r.provider for r in refs}, {"vimeo"})

    def test_three_spellings_of_one_video_collapse_into_one_row(self):
        refs = extract_links(
            "https://vimeo.com/1220776839 "
            "https://vimeo.com/1220776839?fl=pl&fe=cm "
            "https://vimeo.com/1220776839?fl=pl&fe=cm#t=3m12s "
            "https://player.vimeo.com/video/1220776839"
        )
        self.assertEqual([r.url for r in refs], ["https://vimeo.com/1220776839"])

    def test_unlisted_hash_survives_or_the_video_is_unreachable(self):
        refs = extract_links("https://vimeo.com/1220776839/abc123def4")
        self.assertEqual(refs[0].url, "https://vimeo.com/1220776839/abc123def4")
        self.assertEqual(refs[0].unlisted_hash, "abc123def4")
        # Same video, same hash, written as a player link with `h=`.
        refs = extract_links("https://player.vimeo.com/video/1220776839?h=abc123def4")
        self.assertEqual(refs[0].url, "https://vimeo.com/1220776839/abc123def4")

    def test_channel_and_group_spellings(self):
        for url in ("https://vimeo.com/channels/staffpicks/1220776839",
                    "https://vimeo.com/groups/salute/videos/1220776839"):
            self.assertEqual(extract_links(url)[0].url,
                             "https://vimeo.com/1220776839", url)

    def test_ids_shorter_than_the_clients_ten_digits(self):
        # Older Vimeo videos have 7-9 digits; the length is not fixed.
        self.assertEqual(extract_links("vimeo.com/1234567")[0].video_id, "1234567")


class ExtractYouTubeStillWorks(SimpleTestCase):
    """Non-regression: the eleven links already in production must not move."""

    def test_the_spellings_collapse_as_before(self):
        refs = extract_links(
            "Parte I: https://www.youtube.com/watch?v=aCPj6fKx_Yc\n"
            "di nuovo: https://youtu.be/aCPj6fKx_Yc\n"
            "col minuto: https://www.youtube.com/watch?v=aCPj6fKx_Yc&t=365s\n"
            "Parte II: https://www.youtube.com/watch?v=FKPZN17KEcg (Gezzi)\n"
        )
        self.assertEqual([r.url for r in refs], [
            "https://www.youtube.com/watch?v=aCPj6fKx_Yc",
            "https://www.youtube.com/watch?v=FKPZN17KEcg",
        ])
        self.assertEqual({r.provider for r in refs}, {"youtube"})

    def test_shorts_embed_and_live(self):
        for url in ("https://www.youtube.com/shorts/aCPj6fKx_Yc",
                    "https://www.youtube.com/embed/aCPj6fKx_Yc",
                    "https://www.youtube.com/live/aCPj6fKx_Yc"):
            self.assertEqual(extract_links(url)[0].url,
                             "https://www.youtube.com/watch?v=aCPj6fKx_Yc", url)

    def test_canonical_url_still_defaults_to_youtube(self):
        self.assertEqual(canonical_url("aCPj6fKx_Yc"),
                         "https://www.youtube.com/watch?v=aCPj6fKx_Yc")


class MixedAndRejected(SimpleTestCase):
    def test_a_blob_with_both_hosts_keeps_the_order_it_was_pasted_in(self):
        refs = extract_links(
            "Parte I: https://www.youtube.com/watch?v=aCPj6fKx_Yc\n"
            "Parte II: https://vimeo.com/1220777690?fl=pl&fe=cm#t=41s\n"
            "Parte III: https://youtu.be/FKPZN17KEcg\n"
        )
        self.assertEqual([r.provider for r in refs],
                         ["youtube", "vimeo", "youtube"])

    def test_text_without_links_finds_nothing(self):
        self.assertEqual(extract_links("TVRS – Canale Salute (8/10/2025)"), [])
        self.assertEqual(extract_links(""), [])

    def test_a_host_we_cannot_read_is_refused_with_a_sentence(self):
        with self.assertRaises(LinkRefused):
            provider_for("https://www.dailymotion.com/video/x8abcde")

    def test_provider_is_read_from_the_address(self):
        self.assertEqual(provider_for("https://vimeo.com/1220776839").name, "vimeo")
        self.assertEqual(
            provider_for("https://www.youtube.com/watch?v=aCPj6fKx_Yc").name,
            "youtube")


class FromLinksEndpoint(APITestCase):
    """The endpoint, with the two network calls stubbed.

    `probe` and the job spawn are the only things here that leave the process;
    stubbing them leaves exactly what this test is about — that a paste mixing
    the two hosts creates one row per canonical video, and that pasting it
    again creates none.
    """

    def setUp(self):
        user = User.objects.create_user("t", password="x")
        self.client.force_authenticate(user=user)
        self.paste = (
            "Parte I: https://www.youtube.com/watch?v=aCPj6fKx_Yc&t=365s\n"
            "Parte II: https://vimeo.com/1220777690?fl=pl&fe=cm#t=41s\n"
            "Parte II (di nuovo): https://youtu.be/aCPj6fKx_Yc\n"
        )

    def _post(self):
        with mock.patch("core.link_ingest.probe",
                        return_value={"title": "Canale Salute",
                                      "channel": "TVRS SRL", "thumbnail": ""}), \
             mock.patch("core.views._spawn_job"):
            return self.client.post("/api/v1/uploads/from-links/",
                                    {"text": self.paste, "owner_type": "competitor"},
                                    format="json")

    def test_one_row_per_video_whatever_the_host(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(
            sorted(m.source_url for m in UploadedMedia.objects.all()),
            ["https://vimeo.com/1220777690",
             "https://www.youtube.com/watch?v=aCPj6fKx_Yc"])

    def test_the_same_paste_twice_adds_nothing(self):
        self._post()
        resp = self._post()
        self.assertEqual(len(resp.data["creati"]), 0)
        self.assertEqual(len(resp.data["gia_presenti"]), 2)
        self.assertEqual(UploadedMedia.objects.count(), 2)

    def test_text_without_links_is_a_400_with_a_sentence(self):
        self.paste = "TVRS – Canale Salute, puntata del 3 giugno"
        self.assertEqual(self._post().status_code, 400)
