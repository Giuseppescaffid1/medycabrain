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
| `accounts` | `AccountViewSet` | ModelViewSet | Tracked IG accounts (CRUD). `POST` takes `username` and `owner_type` (`owned` \| `competitor`) — the management screen sends it, so a profile lands on the right side from the start. `DELETE` is a soft delete: the account is deactivated and its reels stay. |
| `blog-sources` | `BlogSourceViewSet` | ModelViewSet | Blogs. Actions: `crawl/`, `reactivate/` (the explicit human retry for a source that auto-deactivated). |
| `uploads` | `UploadedMediaViewSet` | ModelViewSet | Client audio/video uploads; creating one spawns an `upload_transcribe` `Job`. |
| `reels` | `ReelViewSet` | **ReadOnly** | `ReelListSerializer`/`ReelDetailSerializer`. Postgres full-text search over caption + transcript (`SearchVector`, italian config): **two subqueries OR-ed on the reel id** (`id IN caption-match OR id IN transcript-match`), each served by its own GIN index (migration `0023_search_indexes`). Not one concatenated vector and not a plain OR after a join — neither can use an index. **With several words the search keeps its old meaning — every word must appear, each one anywhere in caption + transcript**: the filter is one such `id IN … OR id IN …` pair per word, AND-ed (a single `SearchQuery` over all words would need them in the *same* field: «tibolone dosaggio» would miss a reel with one word in the caption and one in the audio). Words the Italian config discards (stop words such as «di») are dropped, as inside one tsquery; a search made only of them matches nothing. Quoted phrases are not treated specially (they were not before either: plain query). Measured on a scratch copy of the live data (1618 reels, 1473 transcripts, 13 MB): same ids as the old concatenated vector for «menopausa» (940), «tibolone dosaggio» (25) and «menopausa terapia ormonale» (273); **~3.2–3.4 s → 8–11 ms** for the id query, `EXPLAIN ANALYZE` 17–23 ms with Bitmap Index Scans on both GIN indexes. Only the **list** hides `is_active=False` reels (`?excluded=1` shows only those); `retrieve`, `annotation/` and `tags/` work by id, so an excluded reel opens (200, `is_active: false`) and can be restored — it used to 404. `ReelDetailSerializer` now carries `is_active`. Actions: `exclude/`, `restore/` (toggle `is_active`), `annotation/` (PATCH favorite/inspiration/note), `tags/` (add/remove). Injects current cluster labels via `_current_cluster_labels()`. |
| `tags` | `TagViewSet` | ModelViewSet | Ordered by usage. |
| `clusters` | `ClusterViewSet` | **ReadOnly** | Serves only the `is_current` run for `?scope=`. Each cluster carries **`scope`** (`medyca` if `run.scope == "owned"`, otherwise `competitor`, so an unexpected value falls on the competitor side, never on Medyca's); `retrieve` answers any id and the page redirects when the URL's side disagrees. `reel_count`/`doc_count`/`has_blog` are annotated subqueries and the three preview thumbnails come from one batch query: the competitor list went from 1230 queries (3.2 s) to ~4. Actions: `arguments/` (deduped merged reel+article claims), `blog/` (spawn a cluster-driven `BlogDraft` `Job`). |
| `knowledge/documents` | `KnowledgeDocumentViewSet` | **ReadOnly** | Blog/manual documents. |
| `second-brain/ideas` | `ContentIdeaViewSet` | ModelViewSet | Actions: `plan/`, `generate/` (ideation via `core/ideation.py`, `core/editorial.py`). |
| `second-brain/blog-drafts` | `BlogDraftViewSet` | ModelViewSet | Browse / save / dismiss drafts. Fields include `llm_model` (read-only). It answered 500 on any non-empty table until a missing comma in `BlogDraftSerializer.fields` was fixed; the smoke test now creates one row per model so DRF builds the fields. |
| `second-brain/briefs` | `StrategyBriefViewSet` | ModelViewSet | Actions: `analyze/`, `draft/` (`core/strategy.py`). |
| `custom-topics` | `CustomTopicViewSet` | ModelViewSet | Create embeds label+keywords and computes matches synchronously. Action: `matches/` (assets by scope, verbatim-first ordering). |
| `jobs` | `JobViewSet` | **ReadOnly** | Poll background jobs; reaps stale jobs. |

## Function / APIViews

| Route (`/api/v1/…`) | View | Serves |
|---|---|---|
| `auth/login/`, `auth/logout/`, `auth/me/` | token auth | The single shared client user. |
| `stats/overview/` | `StatsView` | Headline counts. |
| `analytics/` | `AnalyticsView` | `cluster-performance` reads the whole run in **one query** (was 310 queries, 2.6 s, for 233 clusters) and `top-content` looks at **every** active reel of the scope (was the first 400; 0.53 s on all 1548). Engagement per scope (`core/analytics.py` + `core/weighting.py` normalized engagement — a reel doing 2× the account average counts double). |
| `ops/status/` | `PipelineStatusView` | Per-stage done/pending/failed counts by owner scope, active jobs, per-account reel counts, embed count, **plus `queue`** — what is left to process and how long it should take (`core/queue_eta.py`) — and **`budget`** — what collection has cost this Apify cycle (`scraper/apify_budget.py`, cached 5 min). Polled ~every 5 s by the app's ops panel. |
| `ops/run/` (**POST**) | `PipelineRunView` | Start the pipeline by hand. Body (both optional): `only` (subset of the stage names), `limit` (cap rows per agent). **202** with `{job_id}`, or **409** when a run is already alive. See [the manual run](02-pipeline.md#starting-a-run-by-hand). |
| `second-brain/coverage-map/` | `CoverageMapView` | Medyca themes (covered) vs competitor clusters whose centroid cosine is < 0.8 to any Medyca centroid (opportunities/gaps), plus custom topics. |
| `second-brain/graph/` | `SecondBrainGraphView` | Built in bulk (counts annotated, top 5 reels and top 3 articles per cluster from one query each: 1221 queries / 8.9 s → 17). Only the columns the map draws are loaded (`.only()`): the embedding / chunk-vector / raw-response JSON columns were half of the remaining 5.5 s, decoded for nothing. Same response byte for byte (hash checked), **5.5 s → 0.6 s** on a scratch copy of the live data (1681 nodes, 2186 edges). A deferred field that is read anyway costs one query per row (`run` of the cluster did: 335 queries), so it is kept in the `only()` list. Graph nodes/edges: three hubs (Medyca / Competitor / Opportunità), theme→content edges, competitor→opportunity→Medyca flow edges. |
| `knowledge/search/` | `KnowledgeSearchView` | Wraps `semantic_search`. |
| `knowledge/ask/` | `KnowledgeAskView` | Wraps `answer` (the grounded RAG chat). |

## Read-only by design

`reels`, `clusters`, `knowledge/documents`, and `jobs` are **ReadOnly** viewsets: the pipeline
owns that data, and the UI only reads it. The writable surfaces are the human/editorial ones
(accounts, blog sources, uploads, tags, custom topics, and the Second-Brain outputs). This
mirrors the "failures stay `failed`, retry is explicit" rule — the app never quietly mutates
pipeline state.

Next: [the frontend](06-frontend.md).
