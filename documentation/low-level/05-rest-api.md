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
| `accounts` | `AccountViewSet` | ModelViewSet | Tracked IG accounts (CRUD). |
| `blog-sources` | `BlogSourceViewSet` | ModelViewSet | Blogs. Actions: `crawl/`, `reactivate/` (the explicit human retry for a source that auto-deactivated). |
| `uploads` | `UploadedMediaViewSet` | ModelViewSet | Client audio/video uploads; creating one spawns an `upload_transcribe` `Job`. |
| `reels` | `ReelViewSet` | **ReadOnly** | `ReelListSerializer`/`ReelDetailSerializer`. Postgres full-text search over caption + transcript (`SearchVector`, italian config). Actions: `exclude/`, `restore/` (toggle `is_active`), `annotation/` (PATCH favorite/inspiration/note), `tags/` (add/remove). Injects current cluster labels via `_current_cluster_labels()`. |
| `tags` | `TagViewSet` | ModelViewSet | Ordered by usage. |
| `clusters` | `ClusterViewSet` | **ReadOnly** | Serves only the `is_current` run for `?scope=`. Actions: `arguments/` (deduped merged reel+article claims), `blog/` (spawn a cluster-driven `BlogDraft` `Job`). |
| `knowledge/documents` | `KnowledgeDocumentViewSet` | **ReadOnly** | Blog/manual documents. |
| `second-brain/ideas` | `ContentIdeaViewSet` | ModelViewSet | Actions: `plan/`, `generate/` (ideation via `core/ideation.py`, `core/editorial.py`). |
| `second-brain/blog-drafts` | `BlogDraftViewSet` | ModelViewSet | Browse / save / dismiss drafts. |
| `second-brain/briefs` | `StrategyBriefViewSet` | ModelViewSet | Actions: `analyze/`, `draft/` (`core/strategy.py`). |
| `custom-topics` | `CustomTopicViewSet` | ModelViewSet | Create embeds label+keywords and computes matches synchronously. Action: `matches/` (assets by scope, verbatim-first ordering). |
| `jobs` | `JobViewSet` | **ReadOnly** | Poll background jobs; reaps stale jobs. |

## Function / APIViews

| Route (`/api/v1/…`) | View | Serves |
|---|---|---|
| `auth/login/`, `auth/logout/`, `auth/me/` | token auth | The single shared client user. |
| `stats/overview/` | `StatsView` | Headline counts. |
| `analytics/` | `AnalyticsView` | Engagement per scope (`core/analytics.py` + `core/weighting.py` normalized engagement — a reel doing 2× the account average counts double). |
| `ops/status/` | `PipelineStatusView` | Per-stage done/pending/failed counts by owner scope, active jobs, per-account reel counts, embed count. Polled ~every 5 s by the app's ops panel. |
| `second-brain/coverage-map/` | `CoverageMapView` | Medyca themes (covered) vs competitor clusters whose centroid cosine is < 0.8 to any Medyca centroid (opportunities/gaps), plus custom topics. |
| `second-brain/graph/` | `SecondBrainGraphView` | Graph nodes/edges: three hubs (Medyca / Competitor / Opportunità), theme→content edges, competitor→opportunity→Medyca flow edges. |
| `knowledge/search/` | `KnowledgeSearchView` | Wraps `semantic_search`. |
| `knowledge/ask/` | `KnowledgeAskView` | Wraps `answer` (the grounded RAG chat). |

## Read-only by design

`reels`, `clusters`, `knowledge/documents`, and `jobs` are **ReadOnly** viewsets: the pipeline
owns that data, and the UI only reads it. The writable surfaces are the human/editorial ones
(accounts, blog sources, uploads, tags, custom topics, and the Second-Brain outputs). This
mirrors the "failures stay `failed`, retry is explicit" rule — the app never quietly mutates
pipeline state.

Next: [the frontend](06-frontend.md).
