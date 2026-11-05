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
| `/:scope/library` | `Library.tsx` | Every reel/article for that side, searchable. Reels **and** articles page with `LoadMore` ("n / total" + «Carica altri»; articles used to stop at 100 of 903). Typing keeps the previous results on screen (`keepPreviousData`). A «Mostra esclusi» chip in `FilterBar` lists the excluded reels (`excluded: true`), the way back to restore one; there is no dedicated page for them. |
| `/:scope/analytics` | `Analytics.tsx` | Engagement charts (recharts). |
| `/:scope/timeline` | `Timeline.tsx` | Content over time. The month histogram comes from `fetchEngagementOverTime` (`/analytics/?metric=engagement-over-time`, same key `an-time` as Analytics: one request serves both); the grid below pages `fetchReels` with `posted_after`/`posted_before` of the selected month, newest first. It used to ask for 400 reels, got the 200 **oldest** (API cap) and drew the histogram from them: recent months were missing. |
| `/:scope/clusters` + `/:scope/clusters/:id` | `Clusters.tsx`, `ClusterDetail.tsx` | The themes for that side. `ClusterDetail` reads `cluster.scope` and `Navigate`s to the right side when the URL disagrees (a competitor id pasted under `/medyca/`); reels and articles load only once the side agrees, and both page with `LoadMore` (the biggest cluster has 146 reels, 60 articles). |
| `/second-brain` | `SecondBrain.tsx` | Editorial planner: ideas, gaps, plan. Below the plan, the **«Bozze del blog»** section: `BlogDraftCard` (`components/plan/`) lists the cluster-driven drafts (`GET /second-brain/blog-drafts/`) with badge espansione/bozza, theme, collapsible body (`AnswerBody`, no citation buttons) and Copia / Tieni / Scarta. `JobsContext` already invalidates `blog-drafts` when a `blog` job ends. Ideas and drafts are read with `fetchAllPages` (they are one list with optimistic updates, not an infinite scroll). |
| `/knowledge-bank` | `KnowledgeBank.tsx` | The grounded RAG chat (below), with the "vai al contenuto" field in its header. |
| `/content/:kind/:id` | `ContentDetail.tsx` | Resolves a reference the MCP cited (`blog:843` / `reel:199`) to the content's detail card (below). |
| `/brain-map` | `BrainMap.tsx` | Cytoscape graph of themes/content (`components/graph/BrainGraph.tsx`). `components/graph/layout.ts` places a hub's themes in **concentric rings** (24 in the first, +8 per ring, +90 px radius) instead of one arc: 307 competitor themes sat ~8 px apart. Still deterministic. |
| `/workspace` | `Workspace.tsx` | Favorites / notes. |
| `/accounts` | `Accounts.tsx` | **Management screen** (nav label «Fonti», page title «Gestione fonti»). Three tabs — Instagram profiles, blogs, uploaded interviews — instead of the three stacked sections it used to be: one list at a time, header and tabs fixed, only the list scrolls. The open tab is in the URL (`?tab=blogs|uploads`), so reload, back and shared links land on the same list; tab counts reuse the panels' own react-query keys, so they cost no extra request. Panels: `components/sources/AccountsPanel.tsx`, `components/sources/BlogSourcesPanel.tsx`, `components/uploads/UploadPanel.tsx`, all built from the shared pieces in `components/manage/parts.tsx` (tabs, panel header, folded add form, search + status filter, table frame, empty state, row actions). Each list has search and a status filter (Instagram/blogs also filter by Medyca vs competitor) and the add form is folded away behind the primary button, so the list — not the form — is what you land on. Adding an Instagram profile now asks who it belongs to (`owner_type`, writable on `POST /accounts/`); before, every new profile was created as competitor by default. The **Caricamenti** tab has two doors into one list: drag a file, or paste a block of video links into the textarea below the drop zone (`importLinks` → `POST /uploads/from-links/`) — **YouTube and Vimeo**, mixed in the same paste, which is why the placeholder shows one example of each. Two controls travel with a pasted batch — a «Video di riferimento» checkbox and a «Di chi è» select — kept separate because they answer different questions; choosing «Di Medyca» shows an inline warning that the video will then count as Medyca's coverage and the editorial plan will stop flagging that subject as uncovered. Rows from a link show the channel, a clickable «Apri il video», a «riferimento» badge, and — for a failed download — **the error text inline**, not in a `title` tooltip: a blocked download has a remedy and the client can only act on it if he can read it. |
| `/documentazione` | `Documentation.tsx` | **The client-facing docs** (see note below). |
| `/stato` | `Status.tsx` | Live service/pipeline status. Carries `PipelineQueue` (`components/ops/`): how many reels are left, the estimated wait, and the **Aggiorna ora** button that starts a run (`POST /ops/run/`). While a run is alive the button is disabled and its `Job` progress replaces the estimate. Below it, `BudgetBar` shows what collection has cost this Apify cycle against the $4.00 ceiling (green → amber at 67% → red at the ceiling), because the button that spends the budget should sit next to the budget. |
| `/` | `Home.tsx` | Landing inside the app. |
| `/login` | `Login.tsx` | Token auth via `contexts/AuthContext.tsx`. Tells wrong credentials (400/401/403) from an unreachable server (no response) and from a server error ("codice N"). After login, `App.tsx` returns to the page asked for (below). |

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
- On a 504 or the browser's own timeout the chat says «La risposta ha superato il tempo
  massimo (3 minuti)…» instead of the generic error. nginx cut `/knowledge/ask/` at 180 s
  while the browser waits 300 s; `deploy/nginx-medycabrain.conf` now has an exact-match
  location for it at 300 s (the live file is copied at release, with a reload).
- `FEC/src/api/knowledge.ts` also exposes `POST /knowledge/search/`,
  `GET /knowledge/documents/`, `GET /knowledge/documents/:id/`.

## From a reference to the content — `GoToContent` + `ContentDetail.tsx`

The MCP cites content as `kind:id` — `blog:843`, `reel:199` (`server.py`). The
client had no way, from the brain, to see *which* content that was. Two small
pieces close the gap, with **no backend or MCP change**:

- `components/knowledge/GoToContent.tsx` — a field in the KnowledgeBank header.
  `parseRef()` reads the reference **forgivingly**: it keeps the kind word and the
  id after the colon and throws away anything in between, because the client's own
  Claude prepends a citation number (`[2] blog:843`, `blog 2:843`) that is not ours.
  `blog`/`articolo`/`article` → the blog card, `reel` → the reel card. It also accepts
  the **MCP's own link** (`…/content/blog/843`, the `apri_nel_brain` field), which has
  no colon and used to be rejected. An unrecognisable input shows an inline error. A valid
  one calls `onOpen(ref)`: `KnowledgeBank` opens `ReelDetailDrawer`/`ArticleDetailDrawer`
  **in place**, over the chat, without navigating — navigating unmounted the page and
  wiped the conversation. The route below stays for links opened from outside.
- `pages/ContentDetail.tsx` — the route. It reuses the Library's own
  `ReelDetailDrawer` (`reelId`) / `ArticleDetailDrawer` (`docId`); no new card was
  designed. It resolves the content first (same react-query keys as the drawers, so
  no extra request) and only mounts the drawer once the data is cached. The endpoints
  answer by id blind to scope, so a Medyca or a competitor item both resolve.

  It has **three states before the card**, and keeping them apart is the point:
  **caricamento** (spinner), **non trovato** (a bad address, or a 404 — the detail
  endpoints filter `is_active=True`, so a removed id 404s and the drawer alone would
  spin forever), and **errore** (any other failure: a 502 while gunicorn restarts, the
  network dropping) which says "non riesco a caricare questo contenuto adesso" and
  offers a retry. Folding the second and third together told the client the content had
  been removed while it was still there — the exact misinformation this feature exists
  to remove. 401 is not handled here: `api/client.ts` logs the client out.

  Closing goes back only when the navigation carried `state.fromApp` (set by
  `GoToContent`), otherwise it goes to `/knowledge-bank`. It must **not** use
  `window.history.length`, which counts the whole browser tab: on an MCP link opened in
  an already-used tab, stepping back sends the client out of the brain.

  **Logged-out links (decision reversed 2026-11-05).** This file used to record "no
  return-to-content after login, by decision". The client's complaint came from exactly
  that: an MCP link opened while logged out landed on the Home after login. Now the
  redirect to `/login` carries `state.from` (path + query + hash) and the `/login` route,
  once authenticated, returns there (`AfterLogin` in `App.tsx`). `from` must start with a
  single `/` and not be `/login`, otherwise it falls back to `/`: no open redirect.

Known limit: covers only `reel:`/`blog:`. Theme/cluster references (`temi` returns a
cluster id in a different id space) are out of scope.

## Shared foundations for browsing pages

Added so the same fix is not repeated in ten pages.

- **Error boundary** — `components/ui/ErrorBoundary.tsx`, the only class component (React has
  no hook for it). Two levels: around the whole app in `main.tsx` («La piattaforma ha avuto un
  problema» + Ricarica) and around `<main>` in `Shell` with `key={pathname}`, so an error stays
  in its page; menu and status bar live on, «Riprova» resets that page, «Torna alla Home».
- **`ErrorState`** (`ui/primitives.tsx`) — icon + sentence + «Riprova» (`onRetry`, `retrying`),
  `compact` for one card of a dashboard. **Rule on every page: loading → `Skeleton`, error →
  `ErrorState`, nothing to show → `EmptyState`.** An error must never look like an empty list
  or an endless spinner. A broken Analytics chart shows its own compact error and leaves the
  others alone; `StatBar` stays mute on error (shows nothing).
- **`LoadMore`** (`ui/LoadMore.tsx`) — «n / total» + «Carica altri», for infinite queries.
- **`lib/queryKeys.ts`** — `invalidateReelViews(qc, reelId)` invalidates every prefix that can
  show a reel (`reels`, `workspace`, `timeline`, `cluster-reels`, `topic-matches`, `tags`,
  `stats`, `an-*`). The reel drawer used to refresh only two.
- **Remount on scope change** — `Scoped` in `App.tsx` keys the page on `:scope`: React Router
  keeps the same page mounted when only the parameter changes, so filters, the selected month
  and an open drawer survived the Medyca↔Competitor switch. The sidebar switch keeps only the
  **section** (`/competitor/clusters/123` → `/medyca/clusters`, never `/medyca/clusters/123`).
- **Query retry** (`main.tsx`) — one retry, only for network errors and 5xx; a 404 is not retried.
- **`fetchAllPages`** (`api/client.ts`) — follows the paginator's `next`, capped at 10 pages.
- **Detail drawers** (`ReelDetailDrawer`, `ArticleDetailDrawer`) have three states like
  `ContentDetail`: loading, not found (404), error with Riprova. The article badge says
  «Medyca» / «Competitor» from `owner_type` (never from the source: 14 competitor articles
  have none and were labelled «Medyca»); the source name is a second badge. The reel note
  saves after 800 ms of pause and once more on unmount (Esc used to lose it). `AnswerBody`
  turns `[n]` into buttons **only when `onCite` is passed**.
- **Excluded reels** open (see `05-rest-api.md`), show the «Escluso» badge and «Ripristina».

## Job bar (`StatusBar`, `JobsContext`)

In the flow under `<main>` (it was `fixed bottom-0` and covered the chat's send row); on the
Home, which has no shell, it floats. `JobsContext` polls once on mount (a reload used to make
a running job disappear), exposes `starting` (disables the button at once: a double click
queued two jobs) and `lastError` (a refused start shows a dismissible red row instead of an
unhandled rejection). Kinds `editorial`, `blogsource_discover`, `upload_transcribe`,
`link_transcribe` have their own labels (they all said «Pipeline»). At job end it also
invalidates `uploads`, `blog-sources` and `knowledge-docs` — the keys read in
`UploadPanel.tsx` and `BlogSourcesPanel.tsx`; if those panels rename them the refresh stops
silently, so keep them in step.

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
