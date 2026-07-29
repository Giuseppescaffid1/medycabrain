"""
pipeline/agents/blogscrape_agent.py
===================================
The DAG stage that keeps blog articles flowing — the scraper_agent of the
article world. For every active BlogSource: discover, ingest what is new,
account for failures.

Cadence lives on the source (crawl_interval_h), not in the crontab: our own
blog matters daily, a third-party site should not see us more than weekly.
So this stage can run in every pipeline invocation and self-throttles.

Failure semantics follow the project rule — failures stay failed:
consecutive failures deactivate the source with a readable error, and coming
back is an explicit human action (POST /blog-sources/{id}/reactivate/),
never an automatic retry loop.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from core.models import BlogSource, KnowledgeDocument, ScraperConfig
from pipeline.agents import blog_agent, blog_discovery

logger = logging.getLogger(__name__)


def _cfg() -> dict:
    raw = ScraperConfig.get("blog_crawl", {"value": {}})
    raw = raw.get("value", raw) if isinstance(raw, dict) else {}
    return {
        "per_source_pages": int(raw.get("per_source_pages", 25)),
        "max_new_per_run": int(raw.get("max_new_per_run", 40)),
        "delay_s": float(raw.get("delay_s", 1.5)),
        "global_page_budget": int(raw.get("global_page_budget", 200)),
        "max_consecutive_failures": int(raw.get("max_consecutive_failures", 5)),
        "min_body_chars": int(raw.get("min_body_chars", 400)),
    }


def crawl_source(source: BlogSource, *, job=None, force: bool = False,
                 limit: int | None = None, enrich: bool = False) -> dict:
    """One source, end to end. Shared by run() and the blogsource_discover
    Job — which passes job= for progress and enrich=True, so someone who just
    added a source sees Italian summaries without waiting for the nightly.
    """
    cfg = _cfg()

    def progress(pct, msg):
        if job is not None:
            job.progress = pct
            job.message = msg
            job.save(update_fields=["progress", "message", "updated_at"])

    if not force and source.last_crawled_at:
        age_h = (timezone.now() - source.last_crawled_at).total_seconds() / 3600
        if age_h < source.crawl_interval_h:
            return {"source": source.name, "skipped": "interval"}

    progress(10, f"Cerco gli articoli di {source.name}…")
    budget = blog_discovery.Budget(pages=cfg["per_source_pages"],
                                   delay_s=cfg["delay_s"])
    try:
        candidates = blog_discovery.discover_articles(source, budget=budget)
    except blog_discovery.RobotsForbidden as exc:
        # Not transient: the site said no. Deactivate with the reason
        # visible, instead of counting up to it over five silent nights.
        source.is_active = False
        source.last_error = str(exc)
        source.last_crawled_at = timezone.now()
        source.save()
        logger.warning("[blogscrape] %s: %s — fonte disattivata", source.name, exc)
        return {"source": source.name, "failed": str(exc), "deactivated": True}
    except Exception as exc:  # noqa: BLE001
        source.consecutive_failures += 1
        source.last_error = repr(exc)[:500]
        source.last_crawled_at = timezone.now()
        if source.consecutive_failures >= cfg["max_consecutive_failures"]:
            source.is_active = False
            source.last_error = (f"disattivata dopo {source.consecutive_failures} "
                                 f"tentativi falliti: {source.last_error}")[:500]
        source.save()
        logger.warning("[blogscrape] %s: scoperta fallita (%s consecutivi): %r",
                       source.name, source.consecutive_failures, exc)
        return {"source": source.name, "failed": repr(exc)[:120],
                "deactivated": not source.is_active}

    known = set(KnowledgeDocument.objects.filter(
        source=source).values_list("source_url", flat=True))
    fresh = [c for c in candidates if c.url not in known]
    cap = min(cfg["max_new_per_run"], limit or cfg["max_new_per_run"])
    to_fetch = fresh[:cap]

    progress(30, f"{source.name}: {len(fresh)} articoli nuovi, ne scarico {len(to_fetch)}")
    created = updated = unchanged = failed = 0
    dead = source.crawl_state.setdefault("dead_urls", [])
    for i, cand in enumerate(to_fetch):
        # take() both paces the request and counts it against the budget;
        # the body fetch inside ingest() is the request being paid for.
        if not budget.take():
            break
        doc, action = blog_agent.ingest(cand.url, source=source)
        if action == "created":
            created += 1
        elif action == "updated":
            updated += 1
        elif action == "unchanged":
            unchanged += 1
        else:
            failed += 1
            # Remember URLs that will not extract, so they are never
            # refetched — a capped ring, not an unbounded list.
            dead.append(cand.url)
            del dead[:-200]
        if job is not None and i % 5 == 4:
            progress(30 + int(30 * (i + 1) / max(len(to_fetch), 1)),
                     f"{source.name}: {created + updated} articoli acquisiti")

    # Success bookkeeping. Zero candidates on a source that never produced
    # anything is a failure in disguise — the discovery is not working.
    if candidates or KnowledgeDocument.objects.filter(source=source).exists():
        source.consecutive_failures = 0
        source.last_error = ""
    else:
        source.consecutive_failures += 1
        source.last_error = "nessun articolo trovato"
        if source.consecutive_failures >= cfg["max_consecutive_failures"]:
            source.is_active = False
            source.last_error = (f"disattivata dopo {source.consecutive_failures} "
                                 "tentativi senza articoli")
    source.last_crawled_at = timezone.now()
    totals = source.crawl_state.setdefault("totals", {"pages": 0, "articles": 0})
    totals["pages"] = totals.get("pages", 0) + budget.spent
    totals["articles"] = totals.get("articles", 0) + created
    source.save()

    result = {"source": source.name, "candidates": len(candidates),
              "new": created, "updated": updated, "unchanged": unchanged,
              "failed": failed, "requests": budget.spent}

    if enrich and (created or updated):
        progress(70, f"Analizzo gli articoli di {source.name}…")
        from pipeline.agents import knowledge_agent
        from pipeline.dag import Context
        result["enrich"] = knowledge_agent.run(Context())
        progress(95, "Quasi fatto…")

    logger.info("[blogscrape] %s: %s", source.name, result)
    return result


def run(ctx) -> dict:
    """The DAG stage: every active source, isolated failures, global budget."""
    cfg = _cfg()
    sources = list(BlogSource.objects.filter(is_active=True))
    if not sources:
        return {"sources": 0}

    out = {"sources": len(sources), "crawled": 0, "new": 0, "updated": 0,
           "failed": 0, "deactivated": [], "detail": {}}
    pages_left = cfg["global_page_budget"]
    for source in sources:
        if pages_left <= 0:
            logger.warning("[blogscrape] budget globale esaurito, mi fermo")
            break
        try:
            r = crawl_source(source, limit=ctx.limit)
        except Exception as exc:  # noqa: BLE001 — one dead site never stops the others
            logger.warning("[blogscrape] %s: errore inatteso %r", source.name, exc)
            out["failed"] += 1
            out["detail"][source.name] = {"failed": repr(exc)[:120]}
            continue
        out["detail"][source.name] = r
        if r.get("skipped"):
            continue
        out["crawled"] += 1
        out["new"] += r.get("new", 0)
        out["updated"] += r.get("updated", 0)
        if r.get("failed"):
            out["failed"] += 1
        if r.get("deactivated"):
            out["deactivated"].append(source.name)
        pages_left -= r.get("requests", 0)
    return out
