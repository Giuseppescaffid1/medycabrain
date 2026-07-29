"""
pipeline/agents/blog_agent.py
=============================
Blog ingestion for the Medyca knowledge bank (MEDYC-9 / MEDYC-12).

Fetches a blog article URL, extracts the readable main content as Markdown
(trafilatura — strips nav/boilerplate), and stores it as a
KnowledgeDocument. Can also crawl the /blog index to discover article URLs.

Manual single-URL ingest is the MEDYC-12 "for now" path; --crawl handles
the whole index for MEDYC-9.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests

from core.models import PENDING, KnowledgeDocument

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _download(url: str, attempts: int = 3) -> str | None:
    """Fetch page HTML through the SSRF-validated fetcher, with retries.

    Every body this module STORES comes through here, so redirects are
    validated hop by hop — a crawled site must not become a way of reading
    addresses only this server can reach.
    """
    from core.external_ref import RefusedURL, safe_get

    for i in range(attempts):
        try:
            return safe_get(url, max_bytes=5_000_000)
        except RefusedURL as exc:
            logger.debug("[blog] fetch rifiutato per %s: %s", url, exc)
            return None  # a refusal is a verdict, not a transient error
        except Exception as exc:  # noqa: BLE001
            logger.debug("[blog] fetch attempt %d failed for %s: %r", i + 1, url, exc)
        time.sleep(1.5 * (i + 1))
    return None


def fetch_article(url: str) -> dict | None:
    """Return {title, markdown, text, published_at, author} or None."""
    import trafilatura

    downloaded = _download(url)
    if not downloaded:
        logger.warning("[blog] could not fetch %s", url)
        return None

    # trafilatura 2.x: extract() honors output_format; bare_extraction's .text
    # does not carry the markdown, so use extract() for the body + metadata
    # separately.
    markdown = trafilatura.extract(
        downloaded, output_format="markdown", favor_precision=True,
        include_links=False, include_images=False,
    ) or ""
    if len(markdown.strip()) < 120:  # too short → probably failed extraction
        logger.warning("[blog] extraction too short for %s (%d chars)", url, len(markdown))
        return None

    title, author, published = "", "", None
    try:
        meta = trafilatura.extract_metadata(downloaded)
        if meta:
            title = (meta.title or "").strip()
            author = (meta.author or "").strip()[:200]
            if meta.date:
                try:
                    published = datetime.fromisoformat(str(meta.date)).replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    pass
    except Exception:  # noqa: BLE001 — metadata is a nicety
        pass

    plain = re.sub(r"[#*_>`\[\]()]", "", markdown)
    plain = re.sub(r"\n{2,}", "\n", plain).strip()

    return {
        "title": title,
        "markdown": markdown.strip(),
        "text": plain,
        "language": _detect_language(downloaded, plain),
        "author": author,
        "published_at": published,
    }


def _detect_language(html: str, text: str) -> str:
    """it/en, cheapest signal first. No new dependency for a 2-way guess."""
    m = re.search(r'<html[^>]+lang=["\']?([a-zA-Z]{2})', html or "")
    if m:
        return m.group(1).lower()
    words = re.findall(r"[a-zàèéìòù]+", (text or "").lower())[:200]
    if not words:
        return ""
    it = {"il", "la", "che", "di", "per", "con", "una", "sono", "della", "anche"}
    en = {"the", "and", "for", "with", "that", "this", "are", "from", "have", "which"}
    it_n = sum(1 for w in words if w in it)
    en_n = sum(1 for w in words if w in en)
    return "it" if it_n >= en_n else "en"


def ingest(url: str, *, source=None,
           source_type: str = "blog") -> tuple[KnowledgeDocument | None, str]:
    """Fetch + store one article. Returns (doc, action):
    'created' | 'updated' | 'unchanged' | 'failed'.

    A boolean cannot express what matters here. 'unchanged' makes recrawls
    free — the body hash matched, nothing is touched, the enrich queue does
    not churn over articles nobody edited. 'updated' resets the enrichment
    statuses: this used to be the bug — a rewritten article kept forever the
    summary and vector of its old text, because update_or_create left both
    statuses at done.

    `source` sets provenance AND owner_type — this function and the seed
    migration are the only writers of owner_type, by rule.
    """
    import hashlib

    art = fetch_article(url)
    if not art:
        return None, "failed"
    # Crawled sources get a higher floor than the 120-char extraction check:
    # a cookie-consent wall plus a title clears 120 and then pollutes the
    # index as an "article" whose text is a banner. Measured on imsociety.org.
    if source is not None and len(art["text"]) < 400:
        return None, "failed"

    new_hash = hashlib.sha256(art["markdown"].encode()).hexdigest()
    owner = source.owner_type if source is not None else "owned"

    existing = KnowledgeDocument.objects.filter(source_url=url).first()
    if existing and existing.content_hash == new_hash:
        # Same body: touch nothing, not even updated_at.
        changed = []
        if source is not None and existing.source_id != source.id:
            existing.source, existing.owner_type = source, owner
            changed += ["source", "owner_type"]
        if changed:
            existing.save(update_fields=changed)
        return existing, "unchanged"

    doc, created = KnowledgeDocument.objects.update_or_create(
        source_url=url,
        defaults={
            "source_type": source_type,
            "source": source,
            "owner_type": owner,
            "title": art["title"][:300],
            "content_md": art["markdown"],
            "content_text": art["text"],
            "content_hash": new_hash,
            "language": art.get("language", ""),
            "author": art["author"],
            "published_at": art["published_at"],
            "is_active": True,
            # New text means the old analysis no longer describes it. The
            # stale summary stays visible until re-enrichment lands — a stale
            # summary beats an empty card while the queue drains — but the
            # statuses go back to pending so it WILL be redone.
            "enrich_status": PENDING,
            "embed_status": PENDING,
            "argument_status": PENDING,
            "last_error": "",
        },
    )
    return doc, ("created" if created else "updated")
