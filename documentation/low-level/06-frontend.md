# Low-level: the frontend

The web UI the client uses. React 18 + TypeScript + Vite + Tailwind v4, all in Italian.

## Setup

- Entry: `FEC/src/main.tsx`. Routing: `FEC/src/App.tsx`. Nav: `FEC/src/components/layout/Sidebar.tsx`.
- Stack (`FEC/package.json`): `react-router-dom` v6, `@tanstack/react-query` (all server
  state), `axios`, `framer-motion`, `cytoscape` (the Brain Map graph), `recharts` (analytics),
  `react-markdown` + `remark-gfm` (answer rendering), `i18next`/`react-i18next` (strings in
  `FEC/src/i18n/it.json`).

## Talking to the backend

- `FEC/src/api/client.ts` — one axios instance. `baseURL = VITE_API_URL ?? "/api/v1"`. It
  injects `Authorization: Token <token>` from `localStorage["brain_token"]` and clears auth on
  a `401`.
- `FEC/vite.config.ts` — dev proxy: `/api` and `/media` → `http://127.0.0.1:8010` (the Django
  backend). In production the app is served on `:9093` and nginx proxies `/api/`.
- API modules under `FEC/src/api/`: `endpoints.ts` (reels, accounts, clusters, tags, stats,
  exclude/restore), `knowledge.ts` (RAG), `secondBrain.ts`, `strategy.ts`, `graph.ts`,
  `analytics.ts`, `jobs.ts`, `uploads.ts`, `blogSources.ts`, `customTopics.ts`, `types.ts`.

## Pages (`FEC/src/pages/`)

Most pages are **scoped**: the route carries `:scope` = `medyca` | `competitor`, so the same
screen shows either side without mixing them.

| Route | Page | What it is |
|---|---|---|
| `/:scope/library` | `Library.tsx` | Every reel/article for that side, searchable. |
| `/:scope/analytics` | `Analytics.tsx` | Engagement charts (recharts). |
| `/:scope/timeline` | `Timeline.tsx` | Content over time. |
| `/:scope/clusters` + `/:scope/clusters/:id` | `Clusters.tsx`, `ClusterDetail.tsx` | The themes for that side. |
| `/second-brain` | `SecondBrain.tsx` | Editorial planner: ideas, gaps, plan. |
| `/knowledge-bank` | `KnowledgeBank.tsx` | The grounded RAG chat (below). |
| `/brain-map` | `BrainMap.tsx` | Cytoscape graph of themes/content (`components/graph/BrainGraph.tsx`). |
| `/workspace` | `Workspace.tsx` | Favorites / notes. |
| `/accounts` | `Accounts.tsx` | Add IG accounts + blog sources + upload interviews. |
| `/documentazione` | `Documentation.tsx` | **The client-facing docs** (see note below). |
| `/stato` | `Status.tsx` | Live service/pipeline status. Carries `PipelineQueue` (`components/ops/`): how many reels are left, the estimated wait, and the **Aggiorna ora** button that starts a run (`POST /ops/run/`). While a run is alive the button is disabled and its `Job` progress replaces the estimate. Below it, `BudgetBar` shows what collection has cost this Apify cycle against the $4.00 ceiling (green → amber at 67% → red at the ceiling), because the button that spends the budget should sit next to the budget. |
| `/` | `Home.tsx` | Landing inside the app. |
| `/login` | `Login.tsx` | Token auth via `contexts/AuthContext.tsx`. |

## The RAG chat — `KnowledgeBank.tsx`

The "Chiedi alla Knowledge Bank" screen. Chat over everything the platform knows.

- Two filter pills: **scope** (`all` / `medyca` / `competitor`) and **content type**
  (`all` / `reel` / `article`).
- Calls `askKnowledge()` → `POST /knowledge/ask/` with
  `{query, top_k: 8, scope, content_type, history (last 6 msgs), references}` and a 300 s
  timeout. **No streaming** — a live seconds counter is shown while it thinks (~30 s answers).
- URLs typed into a question are auto-detected (`URL_RE`) and sent as `references` — read on
  the fly for that one answer, badged "reading page", never added to the bank, never mixed with
  Medyca content.
- Answers render via `components/knowledge/AnswerBody.tsx` with clickable `[n]` citations that
  scroll to and highlight the matching source. The `Sources` component groups hits by origin
  (external / owned / competitor) with colour coding (**blue = Medyca, amber = competitor**) and
  a per-source relevance %. The code stresses that confusing Medyca's content with a
  competitor's is the worst failure this screen can make.
- `FEC/src/api/knowledge.ts` also exposes `POST /knowledge/search/`,
  `GET /knowledge/documents/`, `GET /knowledge/documents/:id/`.

## The in-app Documentazione page (client-facing docs)

`FEC/src/pages/Documentation.tsx` (route `/documentazione`) is the **client's** documentation —
all prose lives in `FEC/src/i18n/it.json` under `docs.*`, `flow.*`, `ops.*`. It explains, in
plain Italian: what comes in, the four stages (Raccoglie / Capisce / Organizza / Consiglia),
which model does what, how the chat works, and the known limits. It also embeds live ops
(`components/ops/`, reading `GET /ops/status/`) and a download of the two-page `.drawio` schema.

> Keep the two separate: **this `documentation/` folder is for maintainers; the
> `Documentation.tsx` page is for the client.** When you change behaviour, update both — see
> [`.claude/rules/documentation.md`](../../.claude/rules/documentation.md).

Back to the [index](../README.md).
