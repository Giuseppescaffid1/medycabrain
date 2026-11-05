# Low-level: the REST API

The web app talks to the backend through this API. The MCP connector does **not** use it (see
[04-mcp-connector.md](04-mcp-connector.md)); it hits the database directly.

## Setup

- Root URLconf: `BEC/config/urls.py` — mounts `admin/` and `api/v1/` → `BEC/core/urls.py`.
- Views: `BEC/core/views.py`. Serializers: `BEC/core/serializers.py`. Filters: `BEC/core/filters.py`.
- **Auth:** `config.authentication.SafeTokenAuthentication` + `SessionAuthentication`. There is
  a single shared client user; the frontend stores its token as `brain_token`.
- **Renderer:** JSON only. **Filtering:** `DjangoFilterBackend` + Ordering + Search.
- **Pagination:** `core.pagination.StandardPagination` (`PAGE_SIZE=24`).
- **Throttle:** anonymous 120/min.

## Router viewsets (`core/urls.py`)

| Route (`/api/v1/…`) | Viewset | Type | Serves / notable actions |
|---|---|---|---|
| `accounts` | `AccountViewSet` | ModelViewSet | Tracked IG accounts (CRUD). `POST` takes `username` and `owner_type` (`owned` \| `competitor`) — the management screen sends it, so a profile lands on the right side from the start. `username` is cleaned server-side (`@`, spaces, a pasted `instagram.com/<user>` link, upper case → bare lower-case handle; anything else → 400 «Scrivi solo lo username…»). **`DELETE` is a reversible removal**: it sets `removed_at` + `is_active=false`, the reels stay. The default list excludes removed rows; **`?removed=1`** lists only them; action **`restore/`** brings one back. `POST` of a username that was removed **restores that row** (200, `"restored": true`); of one already monitored → 400 «Questo account è già monitorato.»; of a removed one with a different `owner_type` → 400 (owned/competitor never flips silently). A `PATCH` that changes `username` into one held by a removed row → 400 «Questa fonte esiste già tra le rimosse…» (same for a blog `index_url`). The response carries `collection_paused_until` (the Apify `cycle_end`) when the budget is spent, so the form can say reels will only arrive after the renewal. |
| `blog-sources` | `BlogSourceViewSet` | ModelViewSet | Blogs. Actions: `crawl/`, `reactivate/` (the explicit human retry for a source that auto-deactivated), **`restore/`**. Same removal model as `accounts`: `DELETE` = `removed_at` (+ its documents hidden), `?removed=1`, `POST` of a removed URL restores it (200, `"restored": true`, queues a crawl). `index_url` is normalised (no fragment, no trailing slash, lower-case host) and compared against **every spelling** — http/https × with/without `www.` × with/without `/` — so a variant of an existing source is a 400 «Questo blog è già tra le fonti: «Nome»», never a 500. Same host with a **different path** is allowed (medyca.it/blog and /menopausa are separate sources). `PATCH is_active=true` on a paused blog also reactivates its documents. |
| `uploads` | `UploadedMediaViewSet` | ModelViewSet | Client audio/video uploads; creating one spawns an `upload_transcribe` `Job`. |
| `reels` | `ReelViewSet` | **ReadOnly** | `ReelListSerializer`/`ReelDetailSerializer`. Postgres full-text search over caption + transcript (`SearchVector`, italian config): **two subqueries OR-ed on the reel id** (`id IN caption-match OR id IN transcript-match`), each served by its own GIN index (migration `0023_search_indexes`). Not one concatenated vector and not a plain OR after a join — neither can use an index. Measured on the live data (1618 reels, 1473 transcripts, 13 MB), same query: **1460 ms → 4.6 ms** (`EXPLAIN ANALYZE`, scratch copy). Only the **list** hides `is_active=False` reels (`?excluded=1` shows only those); `retrieve`, `annotation/` and `tags/` work by id, so an excluded reel opens (200, `is_active: false`) and can be restored — it used to 404. `ReelDetailSerializer` now carries `is_active`. Actions: `exclude/`, `restore/` (toggle `is_active`), `annotation/` (PATCH favorite/inspiration/note), `tags/` (add/remove). Injects current cluster labels via `_current_cluster_labels()`. |
| `tags` | `TagViewSet` | ModelViewSet | Ordered by usage. |
| `clusters` | `ClusterViewSet` | **ReadOnly** | Serves only the `is_current` run for `?scope=`. Each cluster carries **`scope`** (`medyca` if `run.scope == "owned"`, otherwise `competitor`, so an unexpected value falls on the competitor side, never on Medyca's); `retrieve` answers any id and the page redirects when the URL's side disagrees. `reel_count`/`doc_count`/`has_blog` are annotated subqueries and the three preview thumbnails come from one batch query: the competitor list went from 1230 queries (3.2 s) to ~4. Actions: `arguments/` (deduped merged reel+article claims), `blog/` (spawn a cluster-driven `BlogDraft` `Job`). |
| `knowledge/documents` | `KnowledgeDocumentViewSet` | **ReadOnly** | Blog/manual documents. |
| `second-brain/ideas` | `ContentIdeaViewSet` | ModelViewSet | Actions: `plan/`, `generate/` (ideation via `core/ideation.py`, `core/editorial.py`). `n` must be a whole number (clamped to 3–12); anything else → 400 «Il numero di idee deve essere un numero intero.» |
| `second-brain/blog-drafts` | `BlogDraftViewSet` | ModelViewSet | Browse / save / dismiss drafts. Fields include `llm_model` (read-only). It answered 500 on any non-empty table until a missing comma in `BlogDraftSerializer.fields` was fixed; the smoke test now creates one row per model so DRF builds the fields. |
| `second-brain/briefs` | `StrategyBriefViewSet` | ModelViewSet | Actions: `analyze/`, `draft/` (`core/strategy.py`). |
| `custom-topics` | `CustomTopicViewSet` | ModelViewSet | Create embeds label+keywords and computes matches synchronously, **in one transaction**: if mapping fails the row is not kept and the answer is 503 «Non sono riuscito a mappare il tema adesso. Riprova tra un minuto.» (a half-made theme used to block the retry with «esiste già»). `label` is trimmed and compared case-insensitively (400 «Questo tema esiste già («Tiroide»)»). The 201 body carries the match counts. Action: `matches/` (assets by scope, verbatim-first ordering). |
| `jobs` | `JobViewSet` | **ReadOnly** | Poll background jobs; reaps stale jobs. |

## Function / APIViews

| Route (`/api/v1/…`) | View | Serves |
|---|---|---|
| `auth/login/`, `auth/logout/`, `auth/me/` | token auth | The single shared client user. |
| `stats/overview/` | `StatsView` | Headline counts. |
| `analytics/` | `AnalyticsView` | `cluster-performance` reads the whole run in **one query** (was 310 queries, 2.6 s, for 233 clusters) and `top-content` looks at **every** active reel of the scope (was the first 400; 0.53 s on all 1548). Engagement per scope (`core/analytics.py` + `core/weighting.py` normalized engagement — a reel doing 2× the account average counts double). |
| `ops/status/` | `PipelineStatusView` | Per-stage done/pending/failed counts by owner scope, active jobs, per-account reel counts, embed count, **plus `queue`** — what is left to process and how long it should take (`core/queue_eta.py`) — and **`budget`** — what collection has cost this Apify cycle (`scraper/apify_budget.py`, cached 5 min). Polled ~every 5 s by the app's ops panel. `queue` also has **`blocked`** (+ `blocked_reasons`, and `blocked`/`blocked_reason` per stage): reels pending for a stage no agent can ever reach, not counted in `remaining` or the wait. `jobs[]` carry **`kind_label`** (Italian name of `Job.kind`); **`last_pipeline_job`** is the latest `kind=pipeline` Job in any state (`status`, `message`, `error`, `at`), so a finished or failed run does not vanish; `accounts[]` excludes removed ones; `operations.activity` also lists runs started from the UI (`manage.py run_job --job N`, read from the Job row); `operations.reanalysis` is `null` unless a `reprocess` process really runs. |
| `ops/run/` (**POST**) | `PipelineRunView` | Start the pipeline by hand. Body (both optional): `only` (subset of the stage names), `limit` (cap rows per agent). **202** with `{job_id}`, or **409** when a run is already alive. See [the manual run](02-pipeline.md#starting-a-run-by-hand). |
| `second-brain/coverage-map/` | `CoverageMapView` | Medyca themes (covered) vs competitor clusters whose centroid cosine is < 0.8 to any Medyca centroid (opportunities/gaps), plus custom topics. |
| `second-brain/graph/` | `SecondBrainGraphView` | Built in bulk (counts annotated, top 5 reels and top 3 articles per cluster from one query each: 1221 queries / 8.9 s → ~8). Graph nodes/edges: three hubs (Medyca / Competitor / Opportunità), theme→content edges, competitor→opportunity→Medyca flow edges. |
| `knowledge/search/` | `KnowledgeSearchView` | Wraps `semantic_search`. |
| `knowledge/ask/` | `KnowledgeAskView` | Wraps `answer` (the grounded RAG chat). |

## Read-only by design

`reels`, `clusters`, `knowledge/documents`, and `jobs` are **ReadOnly** viewsets: the pipeline
owns that data, and the UI only reads it. The writable surfaces are the human/editorial ones
(accounts, blog sources, uploads, tags, custom topics, and the Second-Brain outputs). This
mirrors the "failures stay `failed`, retry is explicit" rule — the app never quietly mutates
pipeline state.

Next: [the frontend](06-frontend.md).

**`knowledge/documents` list filter.** Hides documents the model judged off-topic **unless** the
client added them on purpose (`is_inspiration=True`) — the same rule as the chat index — so
"Vedi in Libreria" on an imported link never opens an empty list. Detail by id is unrestricted.
