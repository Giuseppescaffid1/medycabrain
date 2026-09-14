"""
core/link_ingest.py
===================
From a pasted blob of text to video links the platform can work with.

The client does not send a tidy list. He sends what he had in his notes:

    TVRS – Canale Salute: Salute metabolica (8/10/2025)(Gezzi)
    Parte I: https://www.youtube.com/watch?v=aCPj6fKx_Yc
    Parte II: https://www.youtube.com/watch?v=FKPZN17KEcg
    Parte III:

So this module takes the whole blob and pulls the videos out of it, rather
than asking him to paste one link at a time.

Two providers, one table
------------------------
The client's material lives on **YouTube** and on **Vimeo** (the TVRS "Canale
Salute" episodes). The two differ in four places at once — the spelling of a
link, the canonical form, the oEmbed endpoint, and what yt-dlp needs to get
the audio — and those four have to stay in agreement. Written as `if provider
== "vimeo"` they would be four branches in four functions, and the way that
shape breaks is that someone updates three of the four. So each provider is
**one row in `PROVIDERS`**, and the functions below read the row.

The provider is derived from the address. There is no column for it anywhere:
`source_url` already says who it is, and a real field would cost a migration
plus a serializer plus documentation for information already in the string.

Three jobs, in order of how much they can go wrong:

1. `extract_links(text)` — pure string work, **no network**. Reduces every
   spelling onto the provider's canonical address, which is what makes
   `youtu.be/X`, `watch?v=X` and `watch?v=X&t=365s` collapse into one video
   instead of three rows — and, on Vimeo, what makes `vimeo.com/1220776839`,
   `vimeo.com/1220776839?fl=pl&fe=cm` and `…#t=3m12s` one row instead of
   three. `KnowledgeDocument.source_url` is `unique=True`; this is what feeds
   it. What must NOT be dropped is Vimeo's unlisted hash, which the share and
   embed buttons write anywhere in the query (`?badge=0&h=8272103f6e`): lose
   it and the video is unreachable, and the client is told it "is private or
   removed" — a false reason. Both patterns anchor the host, or
   `fakevimeo.com/1234567` would be canonicalised onto a real video.
2. `probe(url)` — the provider's public oEmbed endpoint. Gives the real title
   and channel without any authentication. Verified on all eleven YouTube
   links on 2026-09-13 and on the three Vimeo links on 2026-09-14 (Vimeo also
   returns duration and thumbnail, and accepts the dirty address as pasted).
3. `fetch_audio(url, dest)` — yt-dlp. **Both providers need a cookies file**
   exported from a logged-in browser, and neither is optional on this machine:

   * **YouTube** (`YT_COOKIES_FILE`): without cookies it answers "Sign in to
     confirm you're not a bot" to every player client from a datacentre IP.
     It also needs **a JavaScript runtime**, passed explicitly with
     `--js-runtimes node`: YouTube signs its media URLs with a JS challenge,
     and yt-dlp does NOT enable an unsandboxed runtime on its own (Node is not
     sandboxed the way Deno is), so it must be named. Symptom when missing:
     "Signature solving failed", with only storyboards on offer — which
     surfaces as the misleading "Requested format is not available".
   * **Vimeo** (`VIMEO_COOKIES_FILE`): yt-dlp 2026.08.19 refuses *before
     calling Vimeo at all* — `vimeo.py:391` marks the `web` client
     `REQUIRES_AUTH: True` — with "The web client only works when logged-in".
     There is no anonymous way round it (the `android` client wants cached
     OAuth tokens; `player.vimeo.com/…/config` answers 401/403 with or without
     a Referer). With the cookies file the audio downloads normally
     (`hls-fastly_skyfire-audio-high-italiano`, verified 14/09/2026). No JS
     runtime is needed: that challenge is a YouTube thing.

   Both cookie files live **outside the repository**, mode 0600, under
   `~/.config/medycabrain/`: they are access to an account, not an API key.
   When one is absent or stale the caller must degrade gracefully: title,
   channel and link are already saved and useful on their own.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import quote
from urllib.request import Request as _Req
from urllib.request import urlopen

from django.conf import settings

logger = logging.getLogger(__name__)

# The host is anchored on both patterns: without `(?:^|[^\w.])` in front,
# `fakevimeo.com/1234567` and `notyoutube.com/watch?v=…` match as substrings
# and get canonicalised onto a real video the client never pasted. Anchoring
# means the known subdomains have to be spelled out (`www.`, `m.`, `music.`,
# `player.`), because a leading dot is no longer allowed to start a match.

# Every YouTube spelling that carries an id, reduced to the id itself.
# The id is exactly 11 chars of [A-Za-z0-9_-]; anything after it (&t=365s,
# &list=…, a trailing bracket from the client's notes) is deliberately
# ignored, because two links to the same video must become ONE row.
_YT_ID = re.compile(
    r"(?:^|[^\w.])(?:www\.|m\.|music\.)?"
    r"(?:youtube\.com/(?:watch\?(?:[^\s\"'<>]*&)?v=|shorts/|embed/|live/)"
    r"|youtu\.be/)([A-Za-z0-9_-]{11})"
)

# Vimeo ids are NUMERIC, and their length is not fixed: the client's three are
# 10 digits (1220776839), older videos have 7-9. Hence {6,12}, not "10".
# Group 2 is the *unlisted* hash written as a path segment
# (`vimeo.com/<id>/<hash>`); written as a query parameter it is found by
# `_VIMEO_QUERY_HASH` over group `query`, because Vimeo puts `h=` wherever it
# likes in the query (`?badge=0&h=8272103f6e`, `?share=copy&h=…`) and an hash
# read only in first position is an hash lost. The hash is lowercase
# hexadecimal: a looser class would read `vimeo.com/<id>/settings` as an hash
# and invent an address that opens nothing and dedups with nothing.
# `?fl=pl&fe=cm` and `#t=3m12s` carry no `h=` and are therefore dropped,
# which is the whole point.
_VIMEO_ID = re.compile(
    r"(?:^|[^\w.])(?:www\.|player\.)?vimeo\.com/"
    r"(?:video/|channels/[\w-]+/|groups/[\w-]+/videos/)?"
    r"(\d{6,12})"
    r"(?:/([0-9a-f]{8,12})(?![\w-]))?"
    r"(?P<query>\?[^\s\"'<>]*)?"
)

_VIMEO_QUERY_HASH = re.compile(r"[?&]h=([0-9a-f]{8,12})(?![\w-])")

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


class LinkRefused(ValueError):
    """The link cannot be used, with a reason fit to show the client."""


@dataclass(frozen=True)
class Provider:
    """Everything that differs between two video hosts, in one place."""

    name: str
    # Finds ids in a blob. Group 1 is the id.
    pattern: re.Pattern
    # (video_id, extra) → the ONE address that goes into source_url.
    canonical: Callable[[str, str], str]
    # match → the extra piece that must survive canonicalisation (Vimeo's
    # unlisted hash). A function and not a group number because the hash can
    # be in the path or anywhere in the query: only the provider knows where
    # to look.
    extra: Callable[[re.Match], str]
    # url → the public oEmbed endpoint that describes it.
    oembed: Callable[[str], str]
    # Setting name holding the path to the cookies file ("" = no cookies).
    cookies_setting: str = ""
    # Extra yt-dlp arguments, built at call time (they read settings).
    extra_args: Callable[[], list[str]] = list
    # Ordered (needles, message): the first row whose needles appear in
    # yt-dlp's stderr wins. Provider-specific, because a remedy that names the
    # wrong product sends the reader hunting for a bug that is not there.
    errors: tuple[tuple[tuple[str, ...], str], ...] = ()


def _yt_extra_args() -> list[str]:
    # Named explicitly: yt-dlp will not enable an unsandboxed runtime by
    # itself, and without one YouTube's signature challenge goes unanswered
    # and only storyboards come back.
    return ["--js-runtimes", settings.YT_JS_RUNTIME]


def _vimeo_canonical(video_id: str, unlisted_hash: str = "") -> str:
    return (f"https://vimeo.com/{video_id}/{unlisted_hash}" if unlisted_hash
            else f"https://vimeo.com/{video_id}")


def _vimeo_extra(m: re.Match) -> str:
    """The unlisted hash, wherever Vimeo decided to put it.

    Vimeo's own share and embed buttons write `?badge=0&h=8272103f6e` and
    `?share=copy&h=abc123def4` — the hash is rarely the first parameter — so
    the whole query is searched, not just what follows the id. Losing it here
    is not a cosmetic bug: the oEmbed call then answers 403 and the client is
    told his video "is private or removed", which is false.
    """
    if m.group(2):
        return m.group(2)
    in_query = _VIMEO_QUERY_HASH.search(m.group("query") or "")
    return in_query.group(1) if in_query else ""


PROVIDERS: tuple[Provider, ...] = (
    Provider(
        name="youtube",
        pattern=_YT_ID,
        canonical=lambda vid, extra="": f"https://www.youtube.com/watch?v={vid}",
        extra=lambda m: "",
        oembed=lambda url: (
            f"https://www.youtube.com/oembed?url={quote(url, safe='')}&format=json"
        ),
        cookies_setting="YT_COOKIES_FILE",
        extra_args=_yt_extra_args,
        errors=(
            (("not a bot", "Sign in to confirm"),
             "YouTube ha bloccato il download da questo server. I cookie "
             "(YT_COOKIES_FILE) sono scaduti o mancanti: vanno riesportati "
             "da un browser dove sei loggato. In alternativa carica il file "
             "video a mano."),
            # Almost always the JS runtime, not the format: YouTube offers
            # only storyboards when the signature challenge went unanswered.
            (("Requested format is not available", "Signature solving"),
             "YouTube non ha restituito l'audio di questo video. Di solito "
             "manca il motore JavaScript che risolve le firme: controlla "
             "che `node` sia installato e che yt-dlp-ejs sia aggiornato."),
        ),
    ),
    Provider(
        name="vimeo",
        pattern=_VIMEO_ID,
        canonical=_vimeo_canonical,
        extra=_vimeo_extra,
        oembed=lambda url: (
            f"https://vimeo.com/api/oembed.json?url={quote(url, safe='')}"
        ),
        cookies_setting="VIMEO_COOKIES_FILE",
        errors=(
            # yt-dlp raises this before contacting Vimeo (vimeo.py:391,
            # REQUIRES_AUTH on the web client), so it is always the cookies —
            # never a network problem and never the video itself.
            # Only this needle, and deliberately: yt-dlp suggests --cookies
            # for password-protected and group-restricted videos too, and
            # naming the cookies file there sends the client to re-export
            # cookies that were never the problem.
            (("only works when logged-in",),
             "Vimeo lascia scaricare l'audio solo a chi è collegato con un "
             "account. I cookie (VIMEO_COOKIES_FILE) sono scaduti o mancanti: "
             "vanno riesportati da un browser dove sei loggato. In "
             "alternativa carica il file video a mano."),
        ),
    ),
)

# Refusals that read the same whatever the host is, tried after the
# provider's own rows.
# Needles are matched case-insensitively (see fetch_audio): yt-dlp writes the
# same refusal with different casing depending on the extractor, and a
# case-sensitive list lets one of them fall through to the raw stderr.
_COMMON_ERRORS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("private video", "unavailable"),
     "Il video non è disponibile (privato o rimosso)."),
)


@dataclass(frozen=True)
class VideoRef:
    """One video found in the pasted text, already in its canonical form."""

    provider: str
    video_id: str
    url: str
    unlisted_hash: str = field(default="")


def provider_for(url: str) -> Provider:
    """Which host this address belongs to, read from the address itself.

    Raises LinkRefused rather than guessing: a url we cannot place is a url
    we cannot probe or download, and saying so here keeps the caller from
    sending a YouTube request to Vimeo.
    """
    for prov in PROVIDERS:
        if prov.pattern.search(url or ""):
            return prov
    raise LinkRefused(
        "Questo indirizzo non è un video YouTube o Vimeo che io sappia leggere."
    )


def extract_links(text: str) -> list[VideoRef]:
    """Videos found in a blob of text, in order of appearance, deduplicated.

    Pure string work: no network call, by design. That is why two spellings of
    the same *unlisted* Vimeo video — one with the hash, one without — stay
    two different rows: telling them apart would need a request, and this
    function must stay cheap enough to run on every paste.
    """
    found: list[tuple[int, VideoRef]] = []
    for prov in PROVIDERS:
        for m in prov.pattern.finditer(text or ""):
            extra = prov.extra(m)
            found.append((m.start(), VideoRef(
                provider=prov.name,
                video_id=m.group(1),
                url=prov.canonical(m.group(1), extra),
                unlisted_hash=extra,
            )))
    found.sort(key=lambda pair: pair[0])
    seen: dict[str, VideoRef] = {}
    for _pos, ref in found:
        seen.setdefault(ref.url, ref)
    return list(seen.values())


def canonical_url(video_id: str, provider: str = "youtube",
                  unlisted_hash: str = "") -> str:
    """The one address for a video id. `extract_links` already returns it.

    Kept for callers that hold a bare id. The provider cannot be read from an
    id alone (it is the address that carries it), so it is named, and defaults
    to YouTube — which is what every existing caller meant.
    """
    for prov in PROVIDERS:
        if prov.name == provider:
            return prov.canonical(video_id, unlisted_hash)
    raise LinkRefused(f"Fornitore video sconosciuto: {provider}")


def probe(url: str) -> dict:
    """{title, channel, thumbnail} from the provider's public oEmbed.

    No API key, no cookies — this keeps working even when the audio download
    is blocked, which is what lets a link still be worth saving as a
    reference. Raises LinkRefused when the video is private or removed.
    """
    from core.external_ref import RefusedURL, _check_public

    try:
        _check_public(url)
    except RefusedURL as exc:
        raise LinkRefused(str(exc)) from exc

    api = provider_for(url).oembed(url)
    try:
        with urlopen(_Req(api, headers={"User-Agent": _UA}), timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001 — private, deleted, or unreachable
        raise LinkRefused(
            "Non riesco a leggere questo video: potrebbe essere privato o rimosso."
        ) from exc
    return {
        "title": (data.get("title") or "")[:300],
        "channel": (data.get("author_name") or "")[:200],
        "thumbnail": data.get("thumbnail_url") or "",
    }


def _cookies_args(prov: Provider) -> list[str]:
    """`--cookies <file>` when the provider has one configured and present.

    Pointing at a missing file makes yt-dlp fail with a confusing error, so
    a stale setting is treated as no setting and logged once.
    """
    if not prov.cookies_setting:
        return []
    path = (getattr(settings, prov.cookies_setting, "") or "").strip()
    if not path:
        return []
    if not Path(path).is_file():
        logger.warning("[link] %s punta a un file inesistente: %s",
                       prov.cookies_setting, path)
        return []
    return ["--cookies", path]


def fetch_audio(url: str, dest_mp3: Path) -> None:
    """Download the audio of `url` into `dest_mp3` (16 kHz mono mp3).

    Raises LinkRefused with a message the client can act on. The cookie cases
    are singled out per provider because they are the ones that actually
    happen here and the ones with a concrete remedy — a generic "download
    failed", or a YouTube remedy shown for a Vimeo link, would send the reader
    hunting for a bug that is not in our code.
    """
    prov = provider_for(url)
    dest_mp3.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(settings.TMP_DIR)) as tmp:
        out = Path(tmp) / "a.%(ext)s"
        cmd = [
            str(Path(settings.BASE_DIR) / "venv" / "bin" / "yt-dlp"),
            *prov.extra_args(),
            "-f", "bestaudio/best", "--no-playlist", "--no-warnings",
            # Let yt-dlp do the transcode: it already knows the container.
            "-x", "--audio-format", "mp3",
            # 16 kHz mono is what whisper wants and what the rest of the
            # pipeline produces for reels and uploads alike.
            "--postprocessor-args", "ffmpeg:-ar 16000 -ac 1",
            *_cookies_args(prov),
            "-o", str(out), url,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        err = (proc.stderr or "")[-800:]
        if proc.returncode != 0:
            lowered = err.lower()
            for needles, message in (*prov.errors, *_COMMON_ERRORS):
                if any(n.lower() in lowered for n in needles):
                    raise LinkRefused(message)
            raise LinkRefused(f"Download non riuscito: {err.strip()[-200:]}")
        made = sorted(Path(tmp).glob("a.*"))
        mp3 = next((p for p in made if p.suffix == ".mp3"), None)
        if mp3 is None:
            raise LinkRefused("Il download non ha prodotto un file audio.")
        os.replace(mp3, dest_mp3)
