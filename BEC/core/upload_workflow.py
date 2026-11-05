"""
core/upload_workflow.py
=======================
An uploaded interview → a transcript → a Medyca knowledge document → a blog
draft. The fourth ingest path, after Instagram reels and crawled blogs.

Everything heavy is reused: the reel transcriber (`_transcribe`), the reel
ffmpeg helpers (`_has_audio`/`_extract_audio`), the document enrichment that
already runs source-agnostic (`knowledge_agent._enrich_one` / arguments /
embed), and the draft prompt machinery. What is new here is only the glue:
extract audio from a video, chunk audio too long for the remote STT, store
the transcript as a `KnowledgeDocument(source_type="manual", owner_type=
"owned")`, and produce a draft grounded in that one interview.

Runs as a detached Job (`kind="upload_transcribe"`), so the upload request
returns immediately and the minutes of transcription happen off the wire.

Three shapes of `UploadedMedia` go through `run_upload_transcribe`: a FILE, a
video LINK (title read first, then yt-dlp), and an ARTICLE link (a web page:
no audio, the blog reader fetches the text). The title is read HERE and not in
the HTTP request: 15 slow oEmbed calls in series once outlasted the 300 s
gunicorn/nginx limit and the client got a 504 for a paste that was fine.

What the client reads in `last_error` is always a sentence written for him
(`_client_message`); the Python repr goes to the log and to `Job.error` only.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
import uuid
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from core.models import (DONE, FAILED, PENDING, SKIPPED, BlogDraft, KnowledgeDocument,
                         UploadedMedia)

logger = logging.getLogger(__name__)


class ClientError(RuntimeError):
    """A failure whose message is already a sentence fit for the client."""


def _client_message(exc: Exception) -> str:
    """The sentence shown to the client for `exc`. Never a repr, never a path.

    ffmpeg's CalledProcessError, for one, carries the whole command line with
    the server's media path in it; showing that is both useless to him and
    information we do not hand out.
    """
    from core.link_ingest import LinkRefused, ToolMissing

    if isinstance(exc, (LinkRefused, ToolMissing, ClientError)):
        return str(exc)
    if isinstance(exc, subprocess.CalledProcessError):
        return ("Non riesco a leggere l'audio di questo file: potrebbe essere "
                "danneggiato o in un formato non supportato.")
    if isinstance(exc, subprocess.TimeoutExpired):
        return "L'operazione ha superato il tempo massimo (30 minuti)."
    return "Errore imprevisto durante la lavorazione."

# Groq's whisper endpoint rejects files past ~25 MB. A 16 kHz mono mp3 runs
# ~0.5-0.7 MB/min, so anything over ~30 min crosses it. Chunk below the line
# with headroom rather than silently falling back to the slower, less
# accurate local model.
_STT_MAX_BYTES = 24 * 1024 * 1024
_SEGMENT_SECONDS = 20 * 60  # ~12-14 MB per segment, safely under the cap


def _probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def _to_mono_mp3(src: Path, dest: Path) -> None:
    """Normalise any audio/video input to 16 kHz mono mp3 — what whisper
    wants, and what keeps the file small enough to chunk sanely."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-vn", "-acodec", "libmp3lame",
         "-q:a", "5", "-ar", "16000", "-ac", "1", str(dest)],
        check=True, capture_output=True,
    )


def _segment(mp3: Path, scratch: Path) -> list[Path]:
    """Split an over-large mp3 into time segments under the STT cap."""
    scratch.mkdir(parents=True, exist_ok=True)
    pattern = str(scratch / "seg_%03d.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp3), "-f", "segment",
         "-segment_time", str(_SEGMENT_SECONDS), "-c", "copy", pattern],
        check=True, capture_output=True,
    )
    return sorted(scratch.glob("seg_*.mp3"))


def _transcribe_long(mp3: Path, progress=None) -> dict:
    """Transcribe an mp3 of any length, chunking when it exceeds the STT cap.

    Segment timestamps are offset back onto the original timeline so the
    stored segments stay coherent across chunk boundaries.
    """
    from pipeline.agents.transcriber_agent import _transcribe

    if mp3.stat().st_size <= _STT_MAX_BYTES:
        # One long call: no segment boundary to report from, so say it before
        # it starts. The job's heartbeat (run_job) keeps it from being reaped
        # as dead while whisper works.
        if progress:
            progress(45, "Trascrivo l'audio (può richiedere diversi minuti)…")
        return _transcribe(mp3)

    scratch = mp3.parent / f"seg_{uuid.uuid4().hex[:8]}"
    parts = _segment(mp3, scratch)
    texts, segments, offset, model_name = [], [], 0.0, ""
    try:
        for i, part in enumerate(parts):
            if progress:
                progress(40 + int(35 * i / max(len(parts), 1)),
                         f"Trascrivo il segmento {i + 1} di {len(parts)}…")
            out = _transcribe(part)
            texts.append(out["text"])
            for s in out.get("segments", []):
                segments.append({"start": round(s["start"] + offset, 2),
                                 "end": round(s["end"] + offset, 2),
                                 "text": s["text"]})
            offset += _probe_duration(part)
            model_name = out.get("model_name", model_name)
    finally:
        for part in parts:
            part.unlink(missing_ok=True)
        scratch.rmdir()
    return {"text": " ".join(t for t in texts if t).strip(),
            "segments": segments, "language": "it",
            "duration": offset, "model_name": model_name}


def _save_reference_only(up, reason: str) -> None:
    """Store a link whose audio we could not get, as a reference card.

    No transcript means no analysis: asking a model to describe a video from
    its title alone is how invented claims get into a medical knowledge bank.
    So the document carries what is actually known — title, channel, link —
    `enrich_status=SKIPPED`, and a vector built from the title so it can still
    be FOUND and handed back as a reference.

    (Embedding the title is safe in a way embedding an empty string was not:
    the empty-string vector sits at a fixed point close to every question,
    which is how ten contentless reels once took the top of a search.)
    """
    from pipeline.agents.knowledge_agent import _embed_one

    doc = KnowledgeDocument.objects.filter(source_url=up.source_url).first()
    if doc is not None and not doc.is_active:
        # Deleted earlier and pasted again: bring the card back, or the
        # client's "Rimuovi" would make the link impossible to re-add.
        doc.is_active = True
        doc.owner_type, doc.is_inspiration = up.owner_type, up.is_inspiration
        doc.save(update_fields=["is_active", "owner_type", "is_inspiration"])
    if doc is None:
        doc = KnowledgeDocument.objects.create(
            source_type="video", owner_type=up.owner_type,
            is_inspiration=up.is_inspiration, source=None,
            source_url=up.source_url, title=(up.title or up.source_url)[:300],
            author=up.channel, language="it",
            content_text="", content_md="",
            published_at=timezone.now(),
            enrich_status=SKIPPED, argument_status=SKIPPED,
            embed_status=PENDING,
            last_error=reason[:500],
        )
    up.document = doc
    up.save(update_fields=["document"])
    try:
        _embed_one(doc)
    except Exception as exc:  # noqa: BLE001 — findability is a bonus here
        logger.warning("[upload] riferimento %s non indicizzato: %r", doc.id, exc)
        # Said, not left PENDING: a card without a vector is invisible to the
        # chat, and "pending" would promise a retry nobody schedules.
        KnowledgeDocument.objects.filter(id=doc.id).update(embed_status=FAILED)


def run_upload_transcribe(upload_id: int, job=None) -> dict:
    """Transcribe one item the client brought in, store it, enrich it, draft.

    Handles both shapes of `UploadedMedia`: an uploaded FILE, and a pasted
    LINK whose audio yt-dlp fetches first. Everything after the audio exists
    is identical, on purpose.
    """
    from pipeline.agents.downloader_agent import _extract_audio, _has_audio

    def progress(p, m):
        if job is not None:
            job.set_progress(p, m)

    up = UploadedMedia.objects.filter(id=upload_id).first()
    if not up:
        raise ClientError(f"Elemento {upload_id} non trovato.")

    up.transcribe_status = PENDING
    up.last_error = ""
    up.save(update_fields=["transcribe_status", "last_error"])

    scratch = Path(settings.TMP_DIR)
    scratch.mkdir(parents=True, exist_ok=True)
    mp3 = Path(settings.MEDIA_ROOT) / f"uploads/audio/{uuid.uuid4().hex}.mp3"

    try:
        if up.kind == "article":
            return _run_article(up, progress)

        progress(10, "Preparo l'audio…")
        if up.source_url and not up.file:
            # Came from a pasted link: yt-dlp fetches the audio, and from
            # there this is the same flow as an uploaded file. Deliberately
            # one code path — a second transcription pipeline for links would
            # drift from this one within a month.
            from core.link_ingest import LinkRefused, fetch_audio, probe
            if not up.channel:
                # The title comes first, here and not in the request (see the
                # module docstring). A private or removed video fails the row
                # with the reason — visible in the list, retryable — instead
                # of vanishing as a synchronous "rifiutato".
                meta = probe(up.source_url)
                up.title = meta["title"] or up.title
                up.original_name = (meta["title"] or up.original_name)[:300]
                up.channel = meta["channel"]
                up.save(update_fields=["title", "original_name", "channel"])
            try:
                fetch_audio(up.source_url, mp3)
            except LinkRefused as exc:
                # The audio is unreachable (expired cookies on either host,
                # a private video). The REFERENCE is still worth having — title, channel
                # and link are what the client asked to get back out of the
                # MCP — so it is saved as a document with no transcript,
                # rather than leaving the video invisible to every surface.
                _save_reference_only(up, str(exc))
                raise
        elif up.kind == "video":
            src = Path(up.file.path)
            if not _has_audio(src):
                raise ClientError("Il video non contiene una traccia audio.")
            _extract_audio(src, mp3)
        else:
            _to_mono_mp3(Path(up.file.path), mp3)
        up.audio_file = str(mp3.relative_to(settings.MEDIA_ROOT))
        up.duration_s = _probe_duration(mp3)
        up.save(update_fields=["audio_file", "duration_s"])

        progress(40, "Trascrivo l'intervista…")
        result = _transcribe_long(mp3, progress=progress)
        text = (result.get("text") or "").strip()
        if len(text) < 40:
            raise ClientError("La trascrizione è risultata vuota o troppo breve.")

        # A video keeps only its audio: the file was the transport, the
        # transcript is the asset. Drop the (large) original to save disk.
        # A link-sourced row never had a file to drop.
        if up.kind == "video" and up.file:
            Path(up.file.path).unlink(missing_ok=True)

        progress(78, "Salvo e analizzo il contenuto…")
        title = up.title or up.original_name or "Intervista"
        # A link may already have a reference-only document from an earlier
        # attempt whose audio was refused (see _save_reference_only). This run
        # UPGRADES that card into a full document — creating a second one
        # would collide on source_url's unique constraint, which is exactly
        # what happened the first time a blocked link was retried.
        doc, _created = KnowledgeDocument.objects.update_or_create(
            # Keyed on the url, with everything else in `defaults`: ownership
            # and the inspiration flag are read from the row, never hardcoded,
            # because the client decides per item whether a video is his own
            # material — and that decides whether it counts as his coverage.
            #
            # For a link, the REAL page url — that is the reference the client
            # gets back out of the MCP, and `unique=True` makes pasting the
            # same link twice a no-op instead of a duplicate. An uploaded file
            # has no web address, so it keeps a synthetic one; .create() skips
            # URLField validation, so a non-http scheme is fine in the DB.
            source_url=up.source_url or f"upload://interview/{uuid.uuid4().hex}",
            defaults={
                "source_type": "video" if up.source_url else "manual",
                "owner_type": up.owner_type,
                "is_inspiration": up.is_inspiration,
                "source": None,
                # A link deleted and pasted again finds its old (inactive)
                # document under the same unique url: bring it back.
                "is_active": True,
                "title": title[:300],
                "content_text": text, "content_md": text, "language": "it",
                "author": up.channel,
                "content_hash": hashlib.sha256(text.encode()).hexdigest(),
                "published_at": timezone.now(),
                # Back to pending on purpose: the card was SKIPPED because
                # there was nothing to analyse, and now there is.
                "enrich_status": PENDING, "embed_status": PENDING,
                "argument_status": PENDING, "last_error": "",
            },
        )
        up.document = doc
        up.transcribe_status = DONE
        up.save(update_fields=["document", "transcribe_status"])

        analysis = _analyse(up, doc)

        # The draft is a bonus; the document in the bank is the real result.
        # An LLM hiccup here (rate limit, empty reply) must not fail the whole
        # upload and lose the transcript that already made it in. Isolated,
        # logged, and the draft stays regenerable from the document.
        # A draft is Medyca writing in their own voice, grounded in this text.
        # Doing that from someone ELSE's material is the mixing this project
        # forbids — blog_workflow already filters `owner_type="owned"` when it
        # picks documents for a cluster draft, and the same rule has to hold
        # here now that an item can be marked as another party's. (Caught the
        # first time a competitor's TV episode produced a Medyca draft.)
        draft_id = None
        if doc.owner_type != "owned":
            logger.info("[upload] doc %s è di terzi (%s): nessuna bozza",
                        doc.id, doc.owner_type)
            progress(100, "Fatto.")
            return {"document_id": doc.id, "blog_draft_id": None,
                    "chars": len(text), "analysis": analysis}

        progress(88, "Preparo una bozza di articolo…")
        try:
            from core.blog_workflow import run_document_blog
            draft_id = run_document_blog(doc.id, job=job).get("blog_draft_id")
            if draft_id:
                up.blog_draft_id = draft_id
                up.save(update_fields=["blog_draft"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[upload] bozza fallita per doc %s (l'articolo è "
                           "comunque in banca dati): %r", doc.id, exc)

        progress(100, "Fatto.")
        logger.info("[upload] %s → doc %s, draft %s",
                    up.original_name, doc.id, draft_id)
        return {"document_id": doc.id, "blog_draft_id": draft_id,
                "chars": len(text), "analysis": analysis}

    except Exception as exc:  # noqa: BLE001
        up.transcribe_status = FAILED
        # A LinkRefused already carries a sentence written for the client,
        # named for the host it came from ("YouTube ha bloccato il download…",
        # "Vimeo lascia scaricare l'audio solo a chi è collegato"). Anything
        # else is translated, never repr()'d: the repr stays in the log and,
        # through run_job, in Job.error — which is where a developer looks.
        up.last_error = _client_message(exc)[:500]
        up.save(update_fields=["transcribe_status", "last_error"])
        logger.warning("[upload] %s fallito: %r", up.original_name or up.source_url, exc)
        raise


_DEFERRED_NOTE = ("Trascritto. L'analisi verrà completata nella prossima "
                  "elaborazione notturna.")


def _analyse(up, doc) -> str:
    """Enrich + arguments + embed inline, so the item is queryable in chat and
    a draft can be grounded now, not next nightly. Returns "done"/"deferred".

    Isolated from the transcription on purpose: by the time we are here the
    text is already saved and the row is DONE. An LLM hiccup used to flow into
    the outer `except` and stamp a SUCCESSFUL upload as FAILED, with the
    client's transcript sitting in the library. The document stays
    `enrich_status=PENDING`, which the nightly `knowledge` stage picks up by
    status (not by source), so nothing is lost and nothing is retried here.
    """
    from pipeline.agents import knowledge_agent
    try:
        knowledge_agent._enrich_one(doc)
        knowledge_agent._extract_arguments(doc)
        knowledge_agent._embed_one(doc)
        return "done"
    except Exception as exc:  # noqa: BLE001
        logger.warning("[upload] analisi rimandata per doc %s: %r", doc.id, exc)
        up.last_error = _DEFERRED_NOTE
        up.save(update_fields=["last_error"])
        return "deferred"


def _run_article(up, progress) -> dict:
    """A pasted web page: the blog reader fetches it, no audio involved.

    `blog_agent.ingest` stays the only writer of the document (and of its
    owner_type): the client's choice from the form is passed to it, never
    decided here.
    """
    from pipeline.agents import blog_agent

    progress(15, "Leggo la pagina…")
    doc, action = blog_agent.ingest(
        up.source_url, source_type="other",
        owner_type=up.owner_type, is_inspiration=up.is_inspiration)
    if doc is None:
        raise ClientError(
            "Non riesco a leggere il testo di questa pagina: potrebbe essere "
            "protetta, vuota o non raggiungibile.")
    if not doc.is_active:
        raise ClientError(
            "Questa pagina fa già parte di una fonte che è stata disattivata: "
            "riattiva la fonte per vederla.")
    up.document = doc
    up.title = (doc.title or up.title)[:300]
    up.original_name = up.title
    up.channel = (doc.author or "")[:200]
    up.transcribe_status = DONE
    up.save(update_fields=["document", "title", "original_name", "channel",
                           "transcribe_status"])
    progress(60, "Analizzo il contenuto…")
    analysis = _analyse(up, doc) if action != "unchanged" else "done"
    # No draft: an article is somebody's text, not an interview of Medyca's.
    progress(100, "Fatto.")
    return {"document_id": doc.id, "blog_draft_id": None,
            "chars": len(doc.content_text or ""), "analysis": analysis}
