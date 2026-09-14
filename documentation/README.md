# medycabrain — Technical Documentation

This folder explains **how the platform is built underneath**: the data model, the
database structure, the processing pipeline, the language models, the REST API, the
frontend, and how the `Medyca` MCP connector queries the data.

It is written for whoever maintains or extends the codebase. Read a section, then jump
straight to the source files it names.

## Two kinds of documentation — don't confuse them

| Audience | Where it lives | What it says |
|---|---|---|
| **The client** (Alberto / Medyca) | the in-app **Documentazione** page (`/documentazione`, source `FEC/src/pages/Documentation.tsx` + strings in `FEC/src/i18n/it.json`) | what the platform *does for them*, in plain Italian, no class names |
| **Maintainers / developers** | **this folder** | the engine underneath — tables, stages, models, queries |

This folder does **not** replace the in-app page. The in-app page is the promise to the
client; this folder is the machine that keeps it.

## How this folder is organised

### `high-level/`
- **[architecture.md](high-level/architecture.md)** — the whole system on one page: the four
  things that come in, the eight-stage pipeline, the knowledge bank, what comes out, and the
  two ways you reach it (the web UI and the MCP connector). Start here.

### `low-level/`
- **[01-data-model.md](low-level/01-data-model.md)** — the database: an ER diagram plus every
  table, its fields, and how the tables link. Explains `owner_type`, `source_type`, the
  per-row status columns, and why embeddings are stored as JSON (no pgvector).
- **[02-pipeline.md](low-level/02-pipeline.md)** — the eight stages (`scrape → download →
  transcribe → enrich → embed → blogscrape → knowledge → cluster`), the file behind each,
  the management commands, and the nightly cron.
- **[03-llm-and-embeddings.md](low-level/03-llm-and-embeddings.md)** — which model does what
  (`model_for`), the provider fallback chain, speech-to-text, the MiniLM embeddings, and how
  the RAG search + reranker rank results.
- **[04-mcp-connector.md](low-level/04-mcp-connector.md)** — the four MCP tools
  (`panoramica`, `cerca`, `leggi`, `temi`), the exact query each one runs, and how the
  server is deployed and secured.
- **[05-rest-api.md](low-level/05-rest-api.md)** — every REST endpoint and what it serves.
- **[06-frontend.md](low-level/06-frontend.md)** — the React app: pages, how it talks to the
  API, and the RAG chat screen.
- **[07-content-lineage.md](low-level/07-content-lineage.md)** — follows **one Instagram reel**
  end to end: what is produced at each step, where it is stored (disk vs Postgres vs discarded),
  and how the vectors become the search index. Read this for "where did this field come from?"
  and "is it in SQL?".
- **[08-agent-team.md](low-level/08-agent-team.md)** — how changes to this repo get built and
  shipped: the five `medyca-*` agents, the shared task board in `.claude/tasks/`, the CI, and
  the rule that `main` only opens through a pull request. Read this **before your first change**.

## One-paragraph summary

Instagram reels, blog articles, client audio/video uploads, and client-named topics come in.
A nightly pipeline downloads them, transcribes audio, reads the text with an LLM, turns each
piece into a vector, and groups everything into themes — keeping **Medyca's own content**
strictly separate from **competitors'**. The result is a searchable *knowledge bank* that
powers a web UI (library, analytics, themes, a grounded chat, and an editorial planner) and a
read-only **MCP connector** so Claude can query the same knowledge from claude.ai.

## Repository map (top level)

```
medycabrain/
  BEC/            Django backend (one app: core) + pipeline/ scraper/ llm/ mcp_bridge/
  FEC/            React + Vite frontend
  documentation/  ← you are here (technical docs)
  docs/           client-facing .drawio pipeline diagrams (source of the in-app diagram)
  deploy/         systemd units, nginx config, crontab
  landing/        marketing landing page for the Medyca clinic (separate from the app)
  CLAUDE.md       project rules for AI-assisted work
  README.md       setup + deploy runbook
```
