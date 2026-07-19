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
    """Fetch page HTML with a browser UA + retries (trafilatura.fetch_url is
    flaky under rapid sequential calls; requests is reliable)."""
    for i in range(attempts):
        try:
            r = requests.get(url, headers={"User-Agent": _UA}, timeout=30,
                             allow_redirects=True)
            if r.status_code == 200 and r.text:
                return r.text
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
        "author": author,
        "published_at": published,
    }


def crawl_index(index_url: str, limit: int = 50) -> list[str]:
    """Discover article URLs from a blog index page (same host, /blog/ paths)."""
    downloaded = _download(index_url)
    if not downloaded:
        return []
    host = urlparse(index_url).netloc
    index_path = urlparse(index_url).path.rstrip("/")
    hrefs = set(re.findall(r'href=["\']([^"\']+)["\']', downloaded))
    urls = []
    for h in hrefs:
        full = urljoin(index_url, h).split("?")[0].split("#")[0]
        p = urlparse(full)
        # article pages live under /blog/<slug>; skip the index and category pages
        if (p.netloc == host and re.search(r"/blog/[^/]+$", p.path)
                and "/category/" not in p.path
                and p.path.rstrip("/") != index_path):
            urls.append(full)
    return sorted(set(urls))[:limit]


def ingest(url: str, source_type: str = "blog") -> tuple[KnowledgeDocument | None, bool]:
    """Fetch + store one article. Returns (doc, created)."""
    art = fetch_article(url)
    if not art:
        return None, False
    doc, created = KnowledgeDocument.objects.update_or_create(
        source_url=url,
        defaults={
            "source_type": source_type,
            "title": art["title"][:300],
            "content_md": art["markdown"],
            "content_text": art["text"],
            "author": art["author"],
            "published_at": art["published_at"],
            "is_active": True,
        },
    )
    if created:
        doc.enrich_status = PENDING
        doc.embed_status = PENDING
        doc.save(update_fields=["enrich_status", "embed_status"])
    return doc, created
