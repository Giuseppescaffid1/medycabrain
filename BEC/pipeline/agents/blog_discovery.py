"""
pipeline/agents/blog_discovery.py
=================================
Finding the articles of an arbitrary blog — the non-deterministic half of
"paste a URL and the agent does the rest".

An Instagram account has one API shape; a blog has none. The lattice below
goes from cheap-and-certain to expensive-and-judged:

    1. sitemap.xml   (indexes recursed; WordPress/Yoast post-sitemaps direct)
    2. RSS/Atom feed (autodiscovery + common paths)
    3. index page    (bounded pagination)
    4. LLM           classifies URL *shapes* it has never seen

The LLM layer is paid once per site, not per crawl: whatever it decides is
written into BlogSource.discovery["patterns"], and every later crawl filters
deterministically against that cache. A feed item is an article by
definition, so feed URLs both skip classification and TEACH the cache their
shape at confidence 1.0 — on a WordPress site the first crawl learns the
article shape for free and the sitemap is filtered without any model call.

robots.txt is honoured. We are a recurring crawler on third-party sites from
one fixed IP; that is exactly the case robots exists for. The chat's one-off
fetch of a user-pasted page (core/external_ref.fetch_reference) stays exempt:
a human reading one page is not a crawler.
"""

from __future__ import annotations

import logging
import random
import re
import time
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from django.utils import timezone as dj_tz

logger = logging.getLogger(__name__)

_UA_HONEST = "medycabrain/1.0 (+https://www.medyca.it; content research crawler)"
_UA_BROWSER = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

MIN_YIELD = 3            # a strategy "worked" if it yielded this many articles
MAX_CLASSIFY_CALLS = 2   # LLM calls per source per run — hard cap
CONF_FLOOR = 0.6
CONF_SURE = 0.8          # above this, no verification fetch needed
RELEARN_DAYS = 180

# Path segments that never lead to an article, in either language this
# project meets. Kept deliberately short: the LLM handles the long tail.
_JUNK_SEGMENTS = {
    "category", "categoria", "tag", "author", "autore", "page", "product",
    "prodotto", "shop", "cart", "carrello", "checkout", "account", "login",
    "privacy", "cookie", "contatti", "contact", "chi-siamo", "about",
    "servizi", "services", "feed", "wp-content", "wp-json", "search",
}


@dataclass
class Candidate:
    url: str
    title: str = ""
    lastmod: datetime | None = None
    via: str = ""            # sitemap | feed | index


@dataclass
class Budget:
    """Request accounting for one crawl of one source."""
    pages: int
    delay_s: float
    spent: int = 0
    last_hit: float = field(default=0.0)

    def take(self) -> bool:
        if self.spent >= self.pages:
            return False
        # Per-host politeness with jitter, applied to every request we make.
        wait = self.delay_s * random.uniform(0.7, 1.3) - (time.time() - self.last_hit)
        if wait > 0:
            time.sleep(wait)
        self.last_hit = time.time()
        self.spent += 1
        return True


def _fetch(source, url: str, budget: Budget, *, xml: bool = False) -> str:
    """One polite, SSRF-validated request, with the honest UA first.

    On a 403 the browser UA is retried once and the fallback is RECORDED on
    the source — the dishonesty is a documented, per-source, observable
    exception rather than the default posture.
    """
    from core.external_ref import RefusedURL, safe_get

    if not budget.take():
        raise BudgetSpent()
    types = ("xml", "html", "text") if xml else ("html", "text")
    ua = _UA_BROWSER if source.crawl_state.get("ua_fallback") else _UA_HONEST
    try:
        return safe_get(url, allow_types=types, max_bytes=10_000_000, user_agent=ua)
    except RefusedURL as exc:
        if "403" in str(exc) and ua == _UA_HONEST:
            source.crawl_state["ua_fallback"] = True
            body = safe_get(url, allow_types=types, max_bytes=10_000_000,
                            user_agent=_UA_BROWSER)
            logger.info("[discovery] %s: 403 con UA onesto, passo al browser UA",
                        source.name)
            return body
        raise


class BudgetSpent(RuntimeError):
    pass


class RobotsForbidden(RuntimeError):
    """robots.txt forbids the index page itself — the source cannot be used."""


# ── robots ──────────────────────────────────────────────────────────────────

def _robots(source) -> urllib.robotparser.RobotFileParser:
    """Parsed robots.txt, cached 24h on the source.

    Unreachable robots.txt is not a prohibition: the parser stays permissive
    and we log it.
    """
    rp = urllib.robotparser.RobotFileParser()
    cached = source.crawl_state.get("robots") or {}
    now = dj_tz.now()
    if cached.get("fetched_at"):
        try:
            age_h = (now - datetime.fromisoformat(cached["fetched_at"])).total_seconds() / 3600
        except ValueError:
            age_h = 999
        if age_h < 24:
            rp.parse((cached.get("body") or "").splitlines())
            return rp
    origin = source.site_url or f"{urlparse(source.index_url).scheme}://{urlparse(source.index_url).netloc}"
    try:
        import requests
        r = requests.get(f"{origin}/robots.txt", timeout=15,
                         headers={"User-Agent": _UA_HONEST})
        body = r.text if r.status_code == 200 else ""
    except Exception:  # noqa: BLE001 — absence of robots is not an error
        body = ""
    source.crawl_state["robots"] = {"body": body[:20000], "fetched_at": now.isoformat()}
    rp.parse(body.splitlines())
    return rp


def _can_fetch(rp, url: str) -> bool:
    try:
        return rp.can_fetch(_UA_HONEST, url) and rp.can_fetch("*", url)
    except Exception:  # noqa: BLE001
        return True


# ── URL shapes: the unit of learning ────────────────────────────────────────

def _shape(url: str) -> str:
    """Collapse a URL into the pattern the LLM classifies and we cache.

    Slug-like, dated or numeric segments become '*'; literal segments stay.
        /blog/menopausa-e-sonno   -> /blog/*
        /2024/03/tos-cosa-sapere  -> /*/*/*
        /category/salute          -> /category/*
    ~900 URLs collapse into a handful of shapes, which is what makes the
    LLM layer affordable and the cache small.
    """
    path = urlparse(url).path.rstrip("/") or "/"
    parts = []
    for seg in path.split("/"):
        if not seg:
            continue
        if (re.fullmatch(r"\d{1,4}", seg)
                or "-" in seg or "_" in seg
                or len(seg) > 24):
            parts.append("*")
        else:
            parts.append(seg.lower())
    return "/" + "/".join(parts) if parts else "/"


def _prefilter(source, cands: list[Candidate]) -> list[Candidate]:
    """Free, deterministic rejection before any learning or model call."""
    from courlan import is_navigation_page, is_not_crawlable

    host = urlparse(source.index_url).netloc.removeprefix("www.")
    index_path = urlparse(source.index_url).path.rstrip("/")
    dead = set(source.crawl_state.get("dead_urls") or [])
    out, seen = [], set()
    for c in cands:
        u = c.url.split("#")[0]
        p = urlparse(u)
        if p.netloc.removeprefix("www.") != host:
            continue
        if u in seen or u in dead:
            continue
        if p.query:                      # article URLs on blogs are path-shaped
            continue
        if p.path.rstrip("/") in ("", index_path):
            continue
        if is_not_crawlable(u) or is_navigation_page(u):
            continue
        if any(seg.lower() in _JUNK_SEGMENTS for seg in p.path.split("/") if seg):
            continue
        seen.add(u)
        out.append(Candidate(url=u, title=c.title, lastmod=c.lastmod, via=c.via))
    return out


def _apply_learned(source, cands):
    """Partition candidates by the pattern cache: (accepted, unknown)."""
    patterns = (source.discovery or {}).get("patterns") or {}
    accepted, unknown = [], []
    for c in cands:
        sh = _shape(c.url)
        known = patterns.get(sh)
        if known is None:
            unknown.append(c)
        elif known.get("article"):
            accepted.append(c)
        # known non-article: dropped silently
    return accepted, unknown


def _learn(source, shape: str, article: bool, conf: float, by: str) -> None:
    pats = source.discovery.setdefault("patterns", {})
    pats[shape] = {"article": bool(article), "conf": round(float(conf), 2),
                   "by": by, "at": dj_tz.now().isoformat()}


# ── the three deterministic layers ──────────────────────────────────────────

def _from_sitemap(source, budget: Budget, rp) -> list[Candidate]:
    """URLs from sitemap.xml, indexes recursed, post-sitemaps preferred.

    Hand-parsed rather than via trafilatura.sitemaps: their downloader does
    not hop-validate redirects, and here the XML host is whatever the site
    says — we keep every fetch inside safe_get.
    """
    origin = source.site_url or f"{urlparse(source.index_url).scheme}://{urlparse(source.index_url).netloc}"
    roots = []
    # robots may declare the sitemap; then the conventional paths.
    for line in (source.crawl_state.get("robots", {}).get("body") or "").splitlines():
        if line.lower().startswith("sitemap:"):
            roots.append(line.split(":", 1)[1].strip())
    roots += [f"{origin}/sitemap.xml", f"{origin}/sitemap_index.xml",
              f"{origin}/wp-sitemap.xml"]
    cached = (source.discovery or {}).get("sitemap_url")
    if cached:
        roots.insert(0, cached)

    seen_maps, out = set(), []
    queue = []
    for r in roots:
        if r not in seen_maps:
            seen_maps.add(r)
            queue.append(r)

    while queue and len(out) < 3000:
        sm = queue.pop(0)
        if not _can_fetch(rp, sm):
            continue
        try:
            xml = _fetch(source, sm, budget, xml=True)
        except BudgetSpent:
            break
        except Exception:  # noqa: BLE001 — try the next conventional path
            continue
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
        if not locs:
            continue
        if "<sitemapindex" in xml:
            # A WordPress post-sitemap IS the article list: when one exists,
            # the page/product/recipe siblings are exactly what we do not
            # want, so they are not queued at all. Only a site without a
            # post-like child falls back to its other sitemaps.
            posts = [u for u in locs if re.search(r"post|article|news|blog", u, re.I)]
            rest = [] if posts else [u for u in locs if u not in posts][:3]
            for u in posts + rest:
                if u not in seen_maps:
                    seen_maps.add(u)
                    queue.append(u)
            continue
        source.discovery["sitemap_url"] = sm
        # URLs out of a post-sitemap are articles by WordPress definition —
        # like feed items, they teach the pattern cache for free. This is
        # what saves sites whose articles live at the root (/slug/), where
        # one URL shape would otherwise cover articles and about-pages alike.
        from_posts = bool(re.search(r"post|article|news", sm, re.I))
        mods = re.findall(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", xml)
        for i, u in enumerate(locs):
            lastmod = None
            if i < len(mods):
                try:
                    lastmod = datetime.fromisoformat(mods[i].replace("Z", "+00:00"))
                    # Sitemaps carry both aware and date-only naive stamps;
                    # a naive one in the sort would TypeError against aware.
                    if lastmod.tzinfo is None:
                        lastmod = lastmod.replace(tzinfo=timezone.utc)
                except ValueError:
                    pass
            out.append(Candidate(url=u, lastmod=lastmod,
                                 via="sitemap-post" if from_posts else "sitemap"))
    return out


def _from_feed(source, budget: Budget, rp) -> list[Candidate]:
    """URLs from RSS/Atom. A feed item IS an article: these teach the cache."""
    origin = source.site_url or f"{urlparse(source.index_url).scheme}://{urlparse(source.index_url).netloc}"
    urls = []
    cached = (source.discovery or {}).get("feed_url")
    if cached:
        urls.append(cached)
    # autodiscovery from the index page happens in _from_index; here the
    # conventional endpoints, which cover WordPress and most generators.
    base = source.index_url.rstrip("/")
    urls += [f"{base}/feed/", f"{origin}/feed/", f"{origin}/rss",
             f"{origin}/rss.xml", f"{origin}/atom.xml", f"{origin}/index.xml"]

    for fu in dict.fromkeys(urls):
        if not _can_fetch(rp, fu):
            continue
        try:
            xml = _fetch(source, fu, budget, xml=True)
        except BudgetSpent:
            break
        except Exception:  # noqa: BLE001
            continue
        items = re.findall(r"<item[\s>].*?</item>", xml, re.S) or \
            re.findall(r"<entry[\s>].*?</entry>", xml, re.S)
        out = []
        for it in items:
            m = (re.search(r"<link>\s*([^<\s]+)\s*</link>", it)
                 or re.search(r'<link[^>]+href=["\']([^"\']+)["\']', it))
            if not m:
                continue
            t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", it, re.S)
            out.append(Candidate(url=m.group(1).strip(),
                                 title=(t.group(1).strip()[:120] if t else ""),
                                 via="feed"))
        if out:
            source.discovery["feed_url"] = fu
            return out
    return []


def _from_index(source, budget: Budget, rp, max_depth: int = 3) -> list[Candidate]:
    """Same-host links from the index page, following pagination briefly."""
    out, page_url = [], source.index_url
    for _depth in range(max_depth):
        if not _can_fetch(rp, page_url):
            break
        try:
            html = _fetch(source, page_url, budget)
        except (BudgetSpent, Exception):  # noqa: BLE001
            break
        links = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.S)
        before = len(out)
        for href, anchor in links:
            full = urljoin(page_url, href)
            text = re.sub(r"<[^>]+>", "", anchor)[:120].strip()
            out.append(Candidate(url=full, title=text, via="index"))
        nxt = re.search(
            r'<a[^>]+href=["\']([^"\']+)["\'][^>]*(?:rel=["\']next["\']|class=["\'][^"\']*next)', html) \
            or re.search(r'href=["\']([^"\']*/page/\d+[^"\']*)["\']', html)
        if not nxt or len(out) == before:
            break
        page_url = urljoin(page_url, nxt.group(1))
    return out


# ── the LLM layer ───────────────────────────────────────────────────────────

_CLASSIFY_SYSTEM = (
    "You classify URL patterns from one website. For each pattern, decide "
    "whether pages matching it are individual editorial articles (blog post, "
    "news item, case study) or something else (homepage, category, tag, "
    "author, archive, pagination, product, service, contact, legal). "
    "Reply ONLY with valid JSON."
)
# English on purpose: the input is URLs and anchors, possibly English, and
# the output is booleans — the Italian-prompt rule serves Italian OUTPUT.


def _classify_llm(source, unknown: list[Candidate]) -> dict:
    """Ask the model which url SHAPES are articles. Returns {shape: verdict}.

    Non-fatal by design: on any failure returns {} and the shapes fall back
    to the heuristic WITHOUT being persisted — one bad run must not poison
    the source's cache permanently.
    """
    from llm import client

    if not client.available():
        return {}
    by_shape: dict[str, list[Candidate]] = {}
    for c in unknown:
        by_shape.setdefault(_shape(c.url), []).append(c)
    shapes = list(by_shape)[:25]
    if not shapes:
        return {}

    lines = []
    for i, sh in enumerate(shapes, 1):
        lines.append(f"{i}. {sh}")
        for c in by_shape[sh][:3]:
            title = f'  "{c.title}"' if c.title else ""
            lines.append(f"   - {urlparse(c.url).path}{title}")
    user = (f"SITE: {source.site_url or source.index_url} — {source.name}\n"
            "This is a health/medical content site.\n\nPATTERNS\n"
            + "\n".join(lines)
            + '\n\nReturn: {"patterns":[{"i":1,"article":true,'
              '"confidence":0.93,"why":"..."}]}')
    try:
        data = client.chat_json(_CLASSIFY_SYSTEM, user, max_tokens=700,
                                temperature=0.0,
                                model=client.model_for("bulk"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[discovery] %s: classificazione LLM fallita: %r",
                       source.name, exc)
        return {}
    out = {}
    rows = data.get("patterns") if isinstance(data, dict) else data
    for row in rows or []:
        try:
            idx = int(row["i"]) - 1
            if 0 <= idx < len(shapes):
                out[shapes[idx]] = {"article": bool(row.get("article")),
                                    "conf": float(row.get("confidence", 0.5))}
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _heuristic(shape: str) -> bool:
    """The no-LLM fallback: slug-with-hyphens or dated path, no junk segment."""
    return "*" in shape and not any(
        seg in _JUNK_SEGMENTS for seg in shape.split("/") if seg and seg != "*")


def _verify(source, cand: Candidate, budget: Budget) -> bool:
    """Fetch ONE example and check it extracts as a real article.

    Run only for shapes the model accepted at middling confidence: one
    request turns a guess into knowledge, and it is the difference between
    a learned pattern and a category page ingested as an article for the
    next two years.
    """
    from pipeline.agents.blog_agent import fetch_article

    if not budget.take():
        return False
    art = fetch_article(cand.url)
    return bool(art and len(art.get("text") or "") >= 400)


# ── entry point ─────────────────────────────────────────────────────────────

def discover_articles(source, *, budget: Budget | None = None,
                      use_llm: bool = True) -> list[Candidate]:
    """Article candidates for `source`, newest first. Never raises for a
    normal site — a total failure returns [] and the caller does the failure
    bookkeeping. Raises RobotsForbidden only when robots.txt forbids the
    index page itself: that is not a transient error, it is the site saying
    no, and the caller must surface it as such.
    """
    from core.models import ScraperConfig

    cfg = ScraperConfig.get("blog_crawl", {"value": {}})
    cfg = cfg.get("value", cfg) if isinstance(cfg, dict) else {}
    budget = budget or Budget(pages=int(cfg.get("per_source_pages", 25)),
                              delay_s=float(cfg.get("delay_s", 1.5)))

    rp = _robots(source)
    if not _can_fetch(rp, source.index_url):
        raise RobotsForbidden("Il file robots.txt del sito vieta la scansione.")

    first_crawl = not (source.discovery or {}).get("patterns")

    cands: list[Candidate] = []
    strategies = []
    try:
        sm = _prefilter(source, _from_sitemap(source, budget, rp))
        if sm:
            strategies.append("sitemap")
            for c in sm:
                if c.via == "sitemap-post":
                    _learn(source, _shape(c.url), True, 0.95, "sitemap-post")
            cands += sm
        # A feed is truncated to the last ~20 posts, so it cannot replace the
        # sitemap — but its items are articles BY DEFINITION, and on a first
        # crawl they teach the cache the article shape for free.
        if first_crawl or not cands:
            fd = _prefilter(source, _from_feed(source, budget, rp))
            if fd:
                strategies.append("feed")
                for c in fd:
                    _learn(source, _shape(c.url), True, 1.0, "feed")
                cands += fd
        if len(cands) < MIN_YIELD:
            ix = _prefilter(source, _from_index(source, budget, rp))
            if ix:
                strategies.append("index")
                cands += ix
    except BudgetSpent:
        pass

    accepted, unknown = _apply_learned(source, cands)

    if unknown and use_llm:
        verdicts = _classify_llm(source, unknown)
        for sh, v in verdicts.items():
            ok, conf = v["article"], v["conf"]
            if ok and conf < CONF_FLOOR:
                ok = False
            if ok and conf < CONF_SURE:
                sample = next((c for c in unknown if _shape(c.url) == sh), None)
                if sample and not _verify(source, sample, budget):
                    ok = False
            _learn(source, sh, ok, conf, "llm")
        accepted2, still_unknown = _apply_learned(source, unknown)
        accepted += accepted2
        # Shapes the model never ruled on: heuristic, NOT persisted.
        accepted += [c for c in still_unknown if _heuristic(_shape(c.url))]
    elif unknown:
        accepted += [c for c in unknown if _heuristic(_shape(c.url))]

    # Dedup preserving the richest candidate, newest first.
    by_url: dict[str, Candidate] = {}
    for c in accepted:
        cur = by_url.get(c.url)
        if cur is None or (c.lastmod and not cur.lastmod):
            by_url[c.url] = c
    result = sorted(by_url.values(),
                    key=lambda c: (c.lastmod or datetime.min.replace(tzinfo=timezone.utc)),
                    reverse=True)

    source.strategy = (strategies[0] if len(strategies) == 1
                       else "mixed" if strategies else "unknown")
    source.crawl_state["last_run"] = {
        "at": dj_tz.now().isoformat(), "strategies": strategies,
        "candidates": len(cands), "accepted": len(result),
        "requests": budget.spent,
    }
    return result
