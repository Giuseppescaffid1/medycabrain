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

import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from core.link_ingest import (
    LinkRefused,
    canonical_url,
    extract_links,
    fetch_audio,
    provider_for,
)
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

    def test_the_hash_is_found_wherever_it_sits_in_the_query(self):
        """Vimeo's own share/embed buttons rarely put `h=` first.

        With the hash read only in first position, these three spellings lose
        it, the oEmbed call answers 403, and the client is told the video "is
        private or removed" — a reason that is simply false.
        """
        for pasted in (
            "https://player.vimeo.com/video/76979871?h=8272103f6e&badge=0",
            "https://player.vimeo.com/video/76979871?badge=0&h=8272103f6e",
            "https://player.vimeo.com/video/76979871"
            "?badge=0&autopause=0&h=8272103f6e&player_id=0",
        ):
            self.assertEqual(extract_links(pasted)[0].url,
                             "https://vimeo.com/76979871/8272103f6e", pasted)

    def test_share_copy_is_the_link_the_client_actually_copies(self):
        refs = extract_links("https://vimeo.com/1220776839?share=copy&h=abc123def4")
        self.assertEqual(refs[0].unlisted_hash, "abc123def4")
        self.assertEqual(refs[0].url, "https://vimeo.com/1220776839/abc123def4")

    def test_a_trailing_word_is_not_an_unlisted_hash(self):
        """Real hashes are lowercase hexadecimal, 8-12 chars.

        A looser class reads `/settings` as a hash: the address invented from
        it opens nothing and, worse, does not dedup with the same video
        pasted bare.
        """
        for tail in ("/settings", "/collections", "/likes"):
            refs = extract_links(f"https://vimeo.com/1220776839{tail}")
            self.assertEqual(refs[0].unlisted_hash, "", tail)
            self.assertEqual(refs[0].url, "https://vimeo.com/1220776839", tail)
        # And therefore the two spellings are one row, not two.
        refs = extract_links("https://vimeo.com/1220776839/settings "
                             "https://vimeo.com/1220776839")
        self.assertEqual([r.url for r in refs], ["https://vimeo.com/1220776839"])

    def test_a_lookalike_host_is_not_vimeo(self):
        """`fakevimeo.com/1234567` used to canonicalise onto a real Vimeo id."""
        for url in ("https://fakevimeo.com/1234567",
                    "https://notvimeo.com/1220776839",
                    "https://evilvimeo.com/1220776839?h=abc123def4"):
            self.assertEqual(extract_links(url), [], url)
            with self.assertRaises(LinkRefused, msg=url):
                provider_for(url)

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

    def test_a_lookalike_host_is_not_youtube(self):
        """Same anchoring fix as Vimeo: a substring match is not a host."""
        for url in ("https://notyoutube.com/watch?v=aCPj6fKx_Yc",
                    "https://fakeyoutu.be/aCPj6fKx_Yc"):
            self.assertEqual(extract_links(url), [], url)

    def test_the_subdomains_the_client_pastes_still_match(self):
        for url in ("https://m.youtube.com/watch?v=aCPj6fKx_Yc",
                    "https://music.youtube.com/watch?v=aCPj6fKx_Yc",
                    "youtube.com/watch?v=aCPj6fKx_Yc",
                    "(https://www.youtube.com/watch?v=aCPj6fKx_Yc)"):
            self.assertEqual(extract_links(url)[0].url,
                             "https://www.youtube.com/watch?v=aCPj6fKx_Yc", url)

    def test_canonical_url_still_defaults_to_youtube(self):
        self.assertEqual(canonical_url("aCPj6fKx_Yc"),
                         "https://www.youtube.com/watch?v=aCPj6fKx_Yc")


class LinksGluedTogether(SimpleTestCase):
    """A greedy query group eats the link that follows it.

    Regression found in review, not by the tests: the query was read with a
    class that excluded only whitespace, so a comma, a semicolon or a bracket
    between two links was read as part of the FIRST link's query. The client
    pastes exactly like that — a spreadsheet cell, a chat message — so this is
    not a theoretical input.
    """

    def test_three_real_links_joined_by_commas_stay_three(self):
        # The client's own three, with their dirty query, as a spreadsheet
        # cell would hand them over.
        paste = (
            "https://vimeo.com/1220776839?fl=pl&fe=cm,"
            "https://vimeo.com/1220777690?fl=pl&fe=cm,"
            "https://vimeo.com/1220778172?fl=pl&fe=cm"
        )
        self.assertEqual(
            [r.url for r in extract_links(paste)],
            ["https://vimeo.com/1220776839",
             "https://vimeo.com/1220777690",
             "https://vimeo.com/1220778172"])

    def test_the_second_videos_hash_never_lands_on_the_first(self):
        # The worst case: not a lost link, an INVENTED one. The address below
        # opens nothing, and source_url is unique=True, so the wrong row would
        # stay forever and make the real video impossible to paste.
        paste = ("https://vimeo.com/1111111?fl=pl;"
                 "https://vimeo.com/2222222?h=8272103f6e")
        self.assertEqual(
            [r.url for r in extract_links(paste)],
            ["https://vimeo.com/1111111",
             "https://vimeo.com/2222222/8272103f6e"])

    def test_brackets_do_not_glue_two_links(self):
        paste = "(https://vimeo.com/1111111?a=1)(https://vimeo.com/2222222)"
        self.assertEqual(len(extract_links(paste)), 2)

    def test_a_missing_separator_still_splits(self):
        # No separator at all: the `http` guard is what stops the query here.
        paste = "https://vimeo.com/1111111?fl=plhttps://vimeo.com/2222222"
        self.assertEqual(len(extract_links(paste)), 2)

    def test_a_clean_single_link_keeps_its_hash(self):
        # The guard must not undo the fix it sits next to.
        self.assertEqual(
            extract_links(
                "https://player.vimeo.com/video/76979871?badge=0&h=8272103f6e"
            )[0].url,
            "https://vimeo.com/76979871/8272103f6e")


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


class RefusalsBecomeSentences(SimpleTestCase):
    """What yt-dlp says on stderr, turned into something the client can act on.

    yt-dlp is never run here: only the mapping stderr → sentence is under
    test, and that mapping is the whole reason the client sees a remedy
    instead of a stack of flags.
    """

    def _message_for(self, url, stderr):
        proc = mock.Mock(returncode=1, stderr=stderr)
        with tempfile.TemporaryDirectory() as out, \
                mock.patch("core.link_ingest.subprocess.run", return_value=proc):
            with self.assertRaises(LinkRefused) as caught:
                fetch_audio(url, Path(out) / "a.mp3")
        return str(caught.exception)

    def test_removed_video_is_recognised_whatever_the_casing(self):
        # yt-dlp writes this refusal with different casing per extractor;
        # a case-sensitive list let one of them through to the raw stderr.
        for stderr in ("ERROR: [vimeo] 1220776839: Video unavailable",
                       "ERROR: [vimeo] 1220776839: Video UNAVAILABLE",
                       "ERROR: [youtube] aCPj6fKx_Yc: Private video",
                       "ERROR: [youtube] aCPj6fKx_Yc: private video"):
            self.assertEqual(
                self._message_for("https://vimeo.com/1220776839", stderr)
                if "vimeo" in stderr else
                self._message_for("https://youtu.be/aCPj6fKx_Yc", stderr),
                "Il video non è disponibile (privato o rimosso).", stderr)

    def test_the_cookies_remedy_is_shown_only_when_it_is_the_cookies(self):
        logged_in = self._message_for(
            "https://vimeo.com/1220776839",
            "ERROR: [vimeo] 1220776839: The web client only works when "
            "logged-in. Use --cookies, --cookies-from-browser ...")
        self.assertIn("VIMEO_COOKIES_FILE", logged_in)
        # Password-protected and group-restricted videos get the same
        # --cookies suggestion from yt-dlp, and re-exporting cookies would
        # not fix either: the client must not be sent to do it.
        protected = self._message_for(
            "https://vimeo.com/1220776839",
            "ERROR: [vimeo] 1220776839: This video is protected by a "
            "password. Use --video-password or --cookies-from-browser ...")
        self.assertNotIn("VIMEO_COOKIES_FILE", protected)


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
