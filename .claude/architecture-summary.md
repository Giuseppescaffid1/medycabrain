# Architecture summary (for a fast start)

A one-page map of the whole system, so an AI session (or a new dev) can get oriented before
touching anything. For depth, follow the links into `documentation/`.

## What this is

Content-intelligence platform for **Medyca** (menopause / bioidentical hormones). It watches
Medyca's Instagram + blog content **and** competitors', understands it, groups it into themes,
and helps decide what to publish next. The one rule that overrides everything: **Medyca's own
content (`owner_type="owned"`) is never mixed with competitors' (`owner_type="competitor"`).**

## Shape

- `BEC/` — Django, **one app `core`** holds all tables (`BEC/core/models.py`). Support
  packages: `pipeline/` (the nightly job), `scraper/` (Instagram), `llm/` (model access),
  `mcp_bridge/` (the Claude connector).
- `FEC/` — React + Vite + TS frontend (token stored as `brain_token`, API base `/api/v1`).
- Live: REST API on `:8010` (Gunicorn), app preview on `:9093`, MCP server on `127.0.0.1:8025`,
  all behind nginx on `messtudent.com`.

## Data model (the DB)

Four inputs → derived layers → themes. See `documentation/low-level/01-data-model.md`.
- **Inputs:** `TrackedAccount`→`Reel`, `BlogSource`→`KnowledgeDocument`, `UploadedMedia`, `CustomTopic`.
- **Reel layers (1:1):** `Transcript`, `Enrichment`, `ReelEmbedding`; plus `ReelArgument` (1:N, verbatim `quote`).
- **Doc layers:** `KnowledgeDocument` (embeddings inline) + `DocumentArgument` (1:N).
- **Themes:** `ClusterRun` (per `scope`, one `is_current`) → `TopicCluster` → `*ClusterAssignment` tables.
- **Vectors are JSON columns** in Postgres — no pgvector; cosine is computed in NumPy.
- `owner_type` on a document is **denormalised and authoritative** — read `doc.owner_type`, never the FK.

## Pipeline

`pipeline/dag.py` (which also owns the stage list, via `build_steps()`), entry
`core/management/commands/run_pipeline.py`, one agent per stage:
`scrape → download → transcribe → batch → enrich → embed → blogscrape → knowledge → cluster`.
`batch` hands the analysis to the Anthropic Batch API (half price, answers within 24h) and
collects finished deliveries; `enrich` is the live fallback for whatever the batch could
not take. Remote models are a priority chain declared in `.env` (`LLM_ENDPOINTS`), each
provider with its own key and dialect, and a dead provider is skipped rather than taking
the whole remote layer down with it.
**Collection is split in two on purpose**: Apify *lists* an account's reels (Instagram answers
`401 require_login` to anyone anonymous, and yt-dlp's profile extractor is `_WORKING = False`),
and yt-dlp *downloads* each reel anonymously and free. No Instagram account of ours is involved.
Apify is billed per result on a $5/cycle plan, so `scraper/apify_budget.py` enforces a $4.00
ceiling, adaptive per-account depth, and a cap on the downloader's url prefetch.
Idempotent via per-row status columns; failures stay `failed` (retry is explicit). Runs nightly
via host cron, **and on demand** — `POST /api/v1/ops/run/` queues a `Job(kind="pipeline")`
(`core/pipeline_run.py`), one run at a time. `core/queue_eta.py` says how much is left and how
long it should take, measured from the recent runs in `logs/pipeline.log`.
See `documentation/low-level/02-pipeline.md`.

## Models

Vendor-neutral. Code asks for a tier via `model_for("analysis"|"reasoning"|"bulk")`
(`llm/client.py`); the actual id is in `.env`. STT = Whisper large-v3 (remote) / faster-whisper
(local). Embeddings = multilingual MiniLM. RAG (`core/knowledge.py`): `semantic_search` blends
`0.75·cosine + 0.25·lexical`, keeps owned/competitor quotas, optional LLM reranker. Same engine
powers the chat and MCP `cerca`. See `documentation/low-level/03-llm-and-embeddings.md`.

## MCP connector

Standalone ASGI server `BEC/mcp_bridge/server.py` (systemd `medycabrain-mcp`, uvicorn `:8025`).
`django.setup()` in-process → queries Postgres via ORM. Four read-only tools:
- `panoramica()` — ORM counts. `temi(scope)` — cluster tables. `leggi("reel:ID"|"blog:ID")` —
  direct ORM lookup. `cerca(query, scope, tipo)` — `core.knowledge.semantic_search(rerank=True)`.
- Auth = secret path segment (`MCP_SECRET`); URL is the credential. See
  `documentation/low-level/04-mcp-connector.md`.

## When you change something

**`main` is never written to directly.** Every change goes: branch → commit → push → pull
request, and Giuseppe merges after reading the diff. Rule: `.claude/rules/git-flow.md`.

The work is done by a **team of agents**, hub and spoke: the main session becomes the team
lead via the `medyca-capo` skill, and launches five spokes in `.claude/agents/` —
`medyca-architetto` (designs, stops for approval) → `medyca-sviluppatore` (writes) →
`medyca-revisore` + `medyca-collaudatore` (in parallel: one reads, one executes) →
`medyca-rilasciatore` (deploys, asking before each step). They cannot talk to each other:
the shared task file in `.claude/tasks/` is the only channel. Start one with `/feature`,
see the board with `/bacheca`. Full description: `documentation/low-level/08-agent-team.md`.

Two required CI jobs guard the PR (`.github/workflows/ci.yml`): Django checks + migration
drift + tests on the light `BEC/requirements-ci.txt`, and the frontend build (which is also
the type check).

Read `.claude/rules/documentation.md`. Any new feature or structural change updates the
matching doc **in the same commit** — the `documentation/` folder, the in-app Documentazione
page, and the drawio diagram as applicable.
