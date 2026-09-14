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

Three jobs, in order of how much they can go wrong:

1. `extract_ids(text)` — pure string work, no network. Normalises every
   YouTube spelling onto the 11-character video id, which is what makes
   `youtu.be/X`, `watch?v=X` and `watch?v=X&t=365s` collapse into one video
   instead of three rows.
2. `probe(url)` — the public oEmbed endpoint. Gives the real title and the
   channel without any authentication. Verified on all eleven of the
   client's links on 2026-09-13.
3. `fetch_audio(url, dest)` — yt-dlp. Two things are required here, and
   neither is optional on this machine (both found the hard way, 2026-09-14):

   * **A cookies file** (`YT_COOKIES_FILE`), exported from a logged-in
     browser — the same arrangement the sibling SPI project uses for
     Facebook. Without it YouTube answers "Sign in to confirm you're not a
     bot" to every player client from a datacentre IP.
   * **A JavaScript runtime**, passed explicitly with `--js-runtimes node`.
     YouTube signs its media URLs with a JS challenge; yt-dlp needs a runtime
     plus the `yt-dlp-ejs` solver scripts to answer it. Node is installed
     here but yt-dlp does NOT enable it on its own (it is not sandboxed the
     way Deno is), so it must be named. Symptom when it is missing:
     "Signature solving failed", and the only formats offered are
     storyboards — which surfaces as the misleading "Requested format is not
     available".

   When either is absent the caller must degrade gracefully: title, channel
   and link are already saved and useful on their own.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request as _Req
from urllib.request import urlopen

from django.conf import settings

logger = logging.getLogger(__name__)

# Every YouTube spelling that carries an id, reduced to the id itself.
# The id is exactly 11 chars of [A-Za-z0-9_-]; anything after it (&t=365s,
# &list=…, a trailing bracket from the client's notes) is deliberately
# ignored, because two links to the same video must become ONE row.
_YT_ID = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:[^\s\"'<>]*&)?v=|shorts/|embed/|live/)"
    r"|youtu\.be/)([A-Za-z0-9_-]{11})"
)

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


class LinkRefused(ValueError):
    """The link cannot be used, with a reason fit to show the client."""


def extract_ids(text: str) -> list[str]:
    """Video ids from a blob of text, in order, without duplicates."""
    return list(dict.fromkeys(_YT_ID.findall(text or "")))


def canonical_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


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

    api = f"https://www.youtube.com/oembed?url={quote(url, safe='')}&format=json"
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


def _cookies_args() -> list[str]:
    """`--cookies <file>` when one is configured and actually present.

    Pointing at a missing file makes yt-dlp fail with a confusing error, so
    a stale setting is treated as no setting and logged once.
    """
    path = (settings.YT_COOKIES_FILE or "").strip()
    if not path:
        return []
    if not Path(path).is_file():
        logger.warning("[link] YT_COOKIES_FILE punta a un file inesistente: %s", path)
        return []
    return ["--cookies", path]


def fetch_audio(url: str, dest_mp3: Path) -> None:
    """Download the audio of `url` into `dest_mp3` (16 kHz mono mp3).

    Raises LinkRefused with a message the client can act on. The bot-check
    case is singled out because it is the one that actually happens here and
    the one with a concrete remedy — a generic "download failed" would send
    the reader hunting for a bug that is not in our code.
    """
    dest_mp3.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(settings.TMP_DIR)) as tmp:
        out = Path(tmp) / "a.%(ext)s"
        cmd = [
            str(Path(settings.BASE_DIR) / "venv" / "bin" / "yt-dlp"),
            # Named explicitly: yt-dlp will not enable an unsandboxed runtime
            # by itself, and without one YouTube's signature challenge goes
            # unanswered and only storyboards come back.
            "--js-runtimes", settings.YT_JS_RUNTIME,
            "-f", "bestaudio/best", "--no-playlist", "--no-warnings",
            # Let yt-dlp do the transcode: it already knows the container.
            "-x", "--audio-format", "mp3",
            # 16 kHz mono is what whisper wants and what the rest of the
            # pipeline produces for reels and uploads alike.
            "--postprocessor-args", "ffmpeg:-ar 16000 -ac 1",
            *_cookies_args(),
            "-o", str(out), url,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        err = (proc.stderr or "")[-800:]
        if proc.returncode != 0:
            if "not a bot" in err or "Sign in to confirm" in err:
                raise LinkRefused(
                    "YouTube ha bloccato il download da questo server. I cookie "
                    "(YT_COOKIES_FILE) sono scaduti o mancanti: vanno riesportati "
                    "da un browser dove sei loggato. In alternativa carica il file "
                    "video a mano."
                )
            if "Requested format is not available" in err or "Signature solving" in err:
                # Almost always the JS runtime, not the format: YouTube offers
                # only storyboards when the signature challenge went unanswered.
                raise LinkRefused(
                    "YouTube non ha restituito l'audio di questo video. Di solito "
                    "manca il motore JavaScript che risolve le firme: controlla "
                    "che `node` sia installato e che yt-dlp-ejs sia aggiornato."
                )
            if "Private video" in err or "unavailable" in err.lower():
                raise LinkRefused("Il video non è disponibile (privato o rimosso).")
            raise LinkRefused(f"Download non riuscito: {err.strip()[-200:]}")
        made = sorted(Path(tmp).glob("a.*"))
        mp3 = next((p for p in made if p.suffix == ".mp3"), None)
        if mp3 is None:
            raise LinkRefused("Il download non ha prodotto un file audio.")
        os.replace(mp3, dest_mp3)
