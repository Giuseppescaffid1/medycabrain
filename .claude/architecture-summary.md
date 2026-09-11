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

`pipeline/dag.py`, entry `core/management/commands/run_pipeline.py`, one agent per stage:
`scrape → download → transcribe → enrich → embed → blogscrape → knowledge → cluster`.
Idempotent via per-row status columns; failures stay `failed` (retry is explicit). Runs nightly
via host cron. See `documentation/low-level/02-pipeline.md`.

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

Read `.claude/rules/documentation.md`. Any new feature or structural change updates the
matching doc **in the same commit** — the `documentation/` folder, the in-app Documentazione
page, and the drawio diagram as applicable.
