# Low-level: the processing pipeline

How raw content becomes searchable knowledge. This is the eight-stage nightly job.

## Where it lives

- **Runner:** `BEC/pipeline/dag.py` — a small linear DAG. It holds an ordered list of
  `Step(name, fn, fatal=False)` and runs them with `DAG.run(ctx, only, skip)`. Every step is
  **non-fatal**: if `scrape` fails, the later stages still run on whatever is already in the
  database.
- **Entry point:** `BEC/core/management/commands/run_pipeline.py`. Its docstring says
  *"DAG entrypoint (cron calls this)"*.
- **One agent per stage:** `BEC/pipeline/agents/<stage>_agent.py`, each exposing `run(...)`.

`pipeline/` is a plain Python package, **not** a Django app.

## The nine stages, in order

`STAGE_NAMES` (in `run_pipeline.py`):

```
scrape → download → transcribe → batch → enrich → embed → blogscrape → knowledge → cluster
```

```mermaid
flowchart LR
    scrape --> download --> transcribe --> batch --> enrich --> embed --> cluster
    blogscrape --> knowledge --> cluster
    classDef reel fill:#dbeafe,stroke:#3b82f6;
    classDef blog fill:#fef3c7,stroke:#f59e0b;
    class scrape,download,transcribe,batch,enrich,embed reel;
    class blogscrape,knowledge blog;
```

| # | Stage | Agent file | What it does | Sets next state |
|---|---|---|---|---|
| 1 | **scrape** | `scraper_agent.py` | For each active `TrackedAccount`: list recent reels **through Apify** (see [below](#where-the-list-of-reels-comes-from)) at a per-account adaptive depth, dump raw JSON to `data/raw/{account}/{shortcode}.json`, upsert `Reel` rows. Stops on the request budget **and** on the Apify spending ceiling. | `media_status=pending` |
| 2 | **download** | `downloader_agent.py` | For `media_status=pending`: get the mp4 (three sources, cheapest first — [below](#how-a-reels-video-actually-arrives)), ffmpeg-extract audio → `media/audio/{account}/{shortcode}.mp3`, save thumbnail → `media/thumbs/…`, delete the mp4. 3 attempts then `skipped`; a block defers the reel instead of charging it an attempt. | `media_status=done`, `transcribe_status=pending` |
| 3 | **transcribe** | `transcriber_agent.py` | faster-whisper (local CPU, int8) over each mp3 → `Transcript`. Remote STT (`llm.client.transcribe_audio`) is used instead when `USE_REMOTE_STT`. Also processes `UploadedMedia`. | `transcribe_status=done`, `enrich_status=pending` |
| 4 | **batch** | `batch_agent.py` | Analysis at **half price**, answered within 24h, for **three kinds of work**: `reel_enrich`, `doc_enrich`, `doc_arguments` (declared once in `batch_agent.KINDS`). **Collects** finished deliveries first (each answer written to the row its `custom_id` names), then **submits** everything still `pending`, marking it `batched` so it can never be sent twice. Skipped entirely when `BATCH_ENABLED=0` or no Anthropic key is set. | `batched`, then `done` on collect |
| 5 | **enrich** | `enrich_agent.py` | The **live fallback** for whatever the batch could not take (batch disabled, delivery refused): one LLM call per `enrich_status=pending` reel → `Enrichment` (summary, topics, hook, target, format, `primary_topic`, `evidence`). Runs `ENRICH_WORKERS` (default 5) in parallel. Then extracts `ReelArgument`s for `argument_status=pending` — each with a required **verbatim quote**. | `enrich_status=done`, `argument_status` advanced |
| 6 | **embed** | `embed_agent.py` | Give every enriched reel a `vector` (via `cluster_agent._ensure_reel_embeddings`) and compute `chunk_vectors` passage embeddings for reels **and** documents (`_embed_passages`). Split from `enrich` on purpose so "analysed" and "searchable" can never drift apart. | embeddings written |
| 7 | **blogscrape** | `blogscrape_agent.py` | For each active `BlogSource`, self-throttling on `crawl_interval_h`: discover article URLs (`blog_discovery.py`) and ingest new ones (`blog_agent.py` — trafilatura → Markdown → `KnowledgeDocument`). Deactivates a source after N consecutive failures. | new `KnowledgeDocument` rows |
| 8 | **knowledge** | `knowledge_agent.py` | The **live fallback** for articles the batch could not take, plus embedding (which needs no LLM and always runs here). Enrich + embed blog articles (Medyca's and competitors'), using `model_for("analysis")`: `primary_topic`, on-topic verdict, `DocumentArgument` extraction (verbatim quote required). No hook/format — those are video-craft only. | `enrich_status`/`embed_status`/`argument_status=done` |
| 9 | **cluster** | `cluster_agent.py` | Two-layer clustering (below). Writes a fresh `ClusterRun` **per scope**, flips `is_current` atomically, then refreshes `CustomTopic` matches (`core/custom_topics.recompute_matches`). | new current `ClusterRun` per scope |

## Video taken from a link (the fourth door, widened)

`BEC/core/link_ingest.py` + the existing upload flow. The client pastes a **blob of his own
notes** — "Parte I: <url>", dates, names in brackets — and every video link in it becomes an
item. `POST /api/v1/uploads/from-links/` (an action on `UploadedMediaViewSet`, with its own
`JSONParser` because that ViewSet is multipart for file uploads).

**Two hosts, one table.** The client's material is on **YouTube** and on **Vimeo** (the TVRS
"Canale Salute" episodes). They differ in four places at once — link spelling, canonical form,
oEmbed endpoint, yt-dlp arguments and error messages — so each is **one row of `PROVIDERS`** in
`link_ingest.py` and the three functions below read the row. There is **no provider column and
no migration**: `source_url` already says who the host is, and `provider_for(url)` reads it back.
Adding a third host is one more row.

1. `extract_links(text)` → `[VideoRef(provider, video_id, url)]`, pure string work, **no
   network**. Reduces every spelling onto the host's canonical address, which is what makes two
   links to the same video **one** row (`KnowledgeDocument.source_url` is `unique=True`):

   | host | recognised | canonical | dropped |
   |---|---|---|---|
   | YouTube | `watch?v=`, `youtu.be/`, `shorts/`, `embed/`, `live/`; id = 11 chars `[A-Za-z0-9_-]` | `https://www.youtube.com/watch?v=<id>` | `&t=365s`, `&list=…`, brackets from the notes |
   | Vimeo | `vimeo.com/<id>`, `player.vimeo.com/video/<id>`, `vimeo.com/<id>/<hash>`, `h=<hash>` **anywhere in the query** (`?badge=0&h=…`, `?share=copy&h=…`), `channels/<x>/<id>`, `groups/<x>/videos/<id>`; id = **numeric**, `\d{6,12}`; hash = lowercase hex, `[0-9a-f]{8,12}` | `https://vimeo.com/<id>`, or `https://vimeo.com/<id>/<hash>` when unlisted | `?fl=pl&fe=cm`, `#t=3m12s`, and trailing pages like `/settings` |

   **TVRS video pages** (`tvrs.it/<any path>?v=<digits>`, with or without `www.`) are Vimeo
   videos too: `v` is the Vimeo id, and the link is canonicalised to `https://vimeo.com/<id>`,
   so the TVRS and the Vimeo spelling of one video are **one** row. The pattern `_TVRS_VIDEO`
   sits next to `PROVIDERS`, not in it (it has no cookies or oEmbed of its own: it *is* Vimeo).
   The id comes from `v`, **never** from the first player in the page's HTML: the page embeds
   a whole playlist. Without a numeric `v`, a `tvrs.it` address stays an ordinary web page.

   The query is read **only** to find `h=` in it, and it stops where the link
   stops: a comma, a semicolon, a bracket, a pipe — or the next `http://`,
   when there is no separator at all. This is not cosmetic. A class that
   excluded only whitespace read the separator as part of the first link's
   query and swallowed the link after it: three links pasted from a
   spreadsheet cell became one, silently (the missing two never reached
   `rifiutati`, because they were never found), and worse, the **second**
   video's hash was attached to the **first** video's id — an invented address
   that opens nothing and that `source_url` (`unique=True`) would then hold
   forever, making the real video impossible to paste. Found in review, not by
   the tests; covered now by `LinksGluedTogether` in
   `BEC/core/tests/test_link_ingest.py`.

   Vimeo ids are numeric and their length is **not** fixed: the client's three are 10 digits
   (`1220776839`), older videos have 7-9. The unlisted hash must survive into the canonical url
   or the video becomes unreachable — and Vimeo's own share and embed buttons put `h=` wherever
   they like in the query (`?badge=0&h=8272103f6e`), so the **whole query** is searched, not just
   what follows the id. A hash read only in first position is a hash lost: the oEmbed call then
   answers 403 and the client is told the video "is private or removed", which is false.
   The hash is lowercase hexadecimal (`[0-9a-f]{8,12}`) on purpose: with a looser class,
   `vimeo.com/<id>/settings` reads as the hash `settings`, invents an address that opens nothing,
   and does not dedup with the same video pasted bare.

   **The host is anchored** on both patterns (`(?:^|[^\w.])(?:www\.|player\.)?vimeo\.com/`, and
   the matching shape on YouTube): without it, `fakevimeo.com/1234567` matches as a substring and
   is canonicalised onto a real Vimeo video the client never pasted. The cost of anchoring is that
   the accepted subdomains have to be spelled out — `www.`, `m.`, `music.` for YouTube, `www.`,
   `player.` for Vimeo — so a subdomain outside that list is not recognised.
   **`scan_links(text)`** is the wider net used by `from-links`: it returns `LinkScan(videos,
   articles, unknown)`. Every other `http(s)` address is sorted — a plain web page becomes an
   **article** (`WebRef`), and what we cannot read comes back with a reason in `unknown`:
   Instagram, other social networks, Drive/Dropbox/OneDrive/WeTransfer, PDF/Word/Excel/zip,
   audio/video files, a YouTube/Vimeo address that is not a single video (channel, playlist),
   an address over 500 characters. Pure string work, no network. Before this a link of any
   other kind was not even seen, so in a mixed paste it vanished without a trace.
2. `probe(url)` reads the host's public **oEmbed** endpoint for the title, channel and thumbnail.
   No key, no cookies — this is what keeps a link worth saving even when the audio is refused.
   YouTube: `youtube.com/oembed?url=…`. Vimeo: `vimeo.com/api/oembed.json?url=…`, which also
   returns duration and accepts the dirty pasted address as-is (so the cleaning above is for our
   deduplication, not for Vimeo). A non-existent Vimeo id answers 404 → `LinkRefused`, the same
   path a private or removed video already took. **`probe` runs in the worker**
   (`run_upload_transcribe`, before `fetch_audio`), not in the HTTP request: 15 slow oEmbed calls
   in series (20 s timeout each) outlasted the 300 s gunicorn/nginx limit and the client got a 504
   for a perfectly good paste. The request creates rows titled with the url and returns in
   milliseconds; a private or removed video becomes a `failed` row with the reason.
3. `fetch_audio(url, dest)` runs **yt-dlp** (`-x --audio-format mp3`, 16 kHz mono), then the item
   rejoins `run_upload_transcribe` and is transcribed, analysed, embedded and drafted exactly
   like an uploaded file — **on both hosts**. **One code path**: a second transcription pipeline
   for links would drift from this one within a month.

### Three walls, all real, all cleared (2026-09-13 / 14)

Neither host gives audio to an anonymous datacentre IP. **Without the proxy (see «Proxy residenziale» below) both need a cookies file**, exported
from a logged-in browser, in **Netscape** format (a Cookie-Editor JSON export must be
converted). Both live **outside the repository**, mode 0600, and neither is ever committed:

| host | setting | file |
|---|---|---|
| YouTube | `YT_COOKIES_FILE` | `~/.config/medycabrain/yt_cookies.txt` |
| Vimeo | `VIMEO_COOKIES_FILE` | `~/.config/medycabrain/vimeo_cookies.txt` |

Those cookies are access to an account, not an API key. `_cookies_args()` treats a missing file
as no file and logs it once, because pointing yt-dlp at a path that is not there produces a
confusing error instead of a clear one.

**1. YouTube: the datacentre-IP bot check.** Without cookies, yt-dlp **2026.7.4 and 2026.8.19**
both return, on all five player clients (`android`, `ios`, `tv`, `web_embedded`, `mweb`):

```
ERROR: [youtube] <id>: Sign in to confirm you're not a bot.
```

**2. YouTube: the JavaScript signature challenge.** With cookies accepted, the download *still*
failed:

```
ERROR: [youtube] <id>: Requested format is not available.
```

That message is misleading. `--list-formats` showed only storyboards, and `-v` gave the real
cause: `Signature solving failed … JS runtimes: none`. YouTube signs its media URLs with a JS
challenge; answering it needs a runtime **plus** the `yt-dlp-ejs` solver scripts. Node 22 was
already installed, but yt-dlp lists it as `node (unavailable)` and will not enable it on its own
— Node is not sandboxed the way Deno is, so it must be named explicitly. Hence
`--js-runtimes node` (`YT_JS_RUNTIME`) on every call, and `yt-dlp-ejs` pinned in
`requirements.txt`. With both in place the same video resolved to `format 251, 120 kbps webm,
1135 s`. **This wall is YouTube's alone**: Vimeo needs no JS runtime, and the error message that
names it is on the YouTube row of the table only.

**3. Vimeo: login required, refused before the network call.** yt-dlp 2026.08.19 answers:

```
ERROR: [vimeo] 1220776839: The web client only works when logged-in.
```

This is a rule **inside yt-dlp** — `yt_dlp/extractor/vimeo.py:391`, the `web` client carries
`REQUIRES_AUTH: True` — raised *before* any request to Vimeo, so it is never a block on our IP
and never the video itself. Four anonymous ways round it were tried and all failed
(14/09/2026): `--extractor-args vimeo:client=android` ("unable to fetch new OAuth tokens, only
for previously cached tokens"); `client=ios` / `web_fallback` (do not exist — only `android` and
`web` are supported); `player.vimeo.com/video/<id>` through yt-dlp (401); and
`player.vimeo.com/video/<id>/config` through curl, with and without a Referer (403). With
`VIMEO_COOKIES_FILE` the audio downloads normally: `hls-fastly_skyfire-audio-high-italiano`,
and the full path measured end to end on the client's Parte 3 gave **595 s of 16 kHz mono mp3,
2.8 MB, in 91 s**.

Because this rule belongs to yt-dlp rather than to Vimeo, an upgrade could reopen or re-close
it. The message shown to the client therefore says "the cookies are expired or missing", never
"impossible".

`fetch_audio` maps each failure to the sentence that names its remedy, **per host**, precisely
because the YouTube runtime one points at the wrong thing by default and because a YouTube
remedy shown for a Vimeo link would send the reader hunting for a bug that is not there.

**Cookies expire.** When they do, items go back to `failed` with the message naming the right
file to re-export, and `_save_reference_only` keeps the title, channel and link as a citable
reference. Nothing retries on its own.

### Proxy residenziale (YTDLP_PROXY, 2026-11-12)

I cookie sono la via vecchia e fragile (scadono, sono l'accesso a un account). Dal 2026-11-12 i
download di YouTube e Vimeo passano da un **proxy residenziale** (IPRoyal, IP italiano) quando
il setting `YTDLP_PROXY` non è vuoto. **Vuoto = la via dei cookie qui sopra, invariata.**

**Perché.** Misurato il 2026-11-12 sul VPS: dall'IP di datacenter YouTube chiede il login a
**ogni** player client (6 provati) e Vimeo risponde 401. Dal proxy, senza cookie: video YouTube
5 MB di audio in **68 s**; video Vimeo 38 MB in **434 s** scaricando un pezzo alla volta, **39 s** con `--concurrent-fragments 8` (vedi sotto).

**Come funziona** (`fetch_audio` in `core/link_ingest.py`):

- `YTDLP_PROXY` sta **solo in `.env`** (contiene la password), es.
  `http://utente:password_session-{session}@host:porta`. `{session}` è sostituito a ogni download
  con un id nuovo: stesso IP per tutto il download, IP diverso al tentativo dopo.
- Con il proxy **non si mandano cookie** (`YT_COOKIES_FILE` / `VIMEO_COOKIES_FILE` ignorati).
- **Vimeo** passa dal player pubblico `player.vimeo.com/video/<id>[?h=hash]` con
  `Referer: https://vimeo.com/`, perché la pagina `vimeo.com/<id>` richiede il login.
- Formato `bestaudio/worst` **solo con il proxy**: si paga a GB, meglio il flusso più leggero.
  Senza proxy resta `bestaudio/best`, e yt-dlp è quello del venv principale come prima.
- **`--concurrent-fragments 8`, solo con il proxy.** Vimeo dà l'audio in HLS (centinaia di pezzi
  piccoli); yt-dlp li scaricava uno alla volta e ognuno aspettava il proxy. Misurato il 2026-11-12
  su `https://vimeo.com/1220776839`: **434 s** uno alla volta contro **39 s** con 8 in parallelo,
  stessi 38 MB di traffico (quindi stesso costo del proxy). Senza proxy il comando non cambia.
- La password è tolta da errori e log (`_scrub`: prima sul testo intero, poi si taglia agli ultimi
  800 caratteri; toglie l'indirizzo, la password da sola e la sua forma con `%`). Due frasi nuove per il cliente: «bloccato anche tramite
  proxy» e «il proxy non ha risposto».

**yt-dlp gira in un venv separato**, `BEC/venv-ytdlp` (yt-dlp 2026.10.26 + curl_cffi 0.17.0 +
yt-dlp-ejs 0.8.0). Vimeo risponde 401 senza l'impronta TLS di un browser e serve curl_cffi 0.17,
ma il venv principale tiene curl_cffi 0.7.4 per il client Instagram. Se `venv-ytdlp` manca si
usa `BEC/venv`. Si usa **solo con il proxy**: senza proxy resta `BEC/venv/bin/yt-dlp`. Per crearlo:

```bash
python3 -m venv BEC/venv-ytdlp && BEC/venv-ytdlp/bin/pip install -r BEC/requirements-ytdlp.txt
```

**Limiti noti.** Il traffico del proxy costa a GB. Se il
traffico finisce, i download falliscono con la frase «il proxy non ha risposto» (restano `failed`,
nessun ritentativo automatico; la scheda-riferimento resta salvata). L'indirizzo del proxy, con la
password, sta sulla riga di comando di yt-dlp: gli altri utenti del server lo vedono con `ps`.
Va bene su un VPS con un solo utente; non su una macchina condivisa.

### Articles (web pages) from a link

An address that is not a video and not refused becomes an `UploadedMedia(kind="article")` and
a `link_transcribe` job. The worker (`upload_workflow._run_article`) calls
`blog_agent.ingest(url, source_type="other", owner_type=…, is_inspiration=…)`: the page is
fetched through `safe_get` (anti-SSRF, redirects checked hop by hop), the text extracted by
trafilatura, the document stored. `ingest` stays the only writer of `owner_type`; the value is the
one the client chose in the form. A document that belongs to a crawled source is never re-owned by
a paste. Enrichment/embedding run inline (`_analyse`); **no blog draft** (it is somebody's text).
Pages behind a login or paywall, or with under 120 characters of text, fail with a sentence.

### Retry, restarts and dead workers

- **Pasting a `failed` link again restarts it** (reported as `riprovati`, with the owner and
  inspiration the client picked this time), and `POST /uploads/<id>/retry/` does the same from
  a button. Both go through one conditional `UPDATE failed→pending`, so two clicks start ONE job.
  A link the client removed leaves an inactive document; pasting it again creates a new row and
  the worker revives the document (`is_active=True`). Nothing retries by itself: failed stays failed.
- **A restart used to leave rows "in trascrizione" for ever.** Now: (1) `run_job`'s signal
  handler also marks the `UploadedMedia` row `failed` ("Interrotto da un riavvio del server.
  Premi «Riprova»."), only if still pending; (2) `_reap_stale_jobs` does the same for jobs it
  reaps; (3) `GET /uploads/` (the 4-second poll) calls the reaper and fails pending rows with
  no live job behind them (2-minute grace for the gap between row and job). This is a write in
  a GET, on purpose: it is the only endpoint polled often enough to notice.
- **Heartbeat.** `run_job` touches `Job.updated_at` every 60 s from a daemon thread, so the
  25-minute "no progress" rule means *dead*, not *slow*. A single whisper call on a long file
  reports nothing for more than 25 minutes and used to be reaped while working.
- **Analysis errors do not fail an upload.** `_enrich_one`/arguments/embed run in their own
  `try` (`_analyse`): the row stays `done`, the document stays `enrich_status=pending` (the
  nightly `knowledge` stage selects by status), `last_error` carries an informative note, the job
  result says `analysis: "deferred"`.
- **Messages for the client.** `last_error` is always a sentence from `_client_message`
  (ffmpeg → "Non riesco a leggere l'audio…", timeout → "…tempo massimo (30 minuti)", anything
  unknown → "Errore imprevisto…"). The repr goes to the log and `Job.error` only; yt-dlp's stderr
  too. A yt-dlp `TimeoutExpired` is now a `LinkRefused`, so the reference card is saved.
  If the card cannot be embedded it is marked `embed_status=failed` instead of staying pending.
- Accepted files: audio `mp3 m4a wav aac ogg flac opus amr wma aiff aif caf`, video
  `mp4 mov m4v webm mkv avi 3gp` (all through ffmpeg). The UI list is identical
  (`api/uploads.ts`). Size limit 1 GB, measured on nginx (`client_max_body_size 1G` on
  `/api/v1/uploads/`); the UI checks it before uploading.

### Known limits of the link path

- **Not supported**: Instagram reels from a link, PDF/Word documents, Drive/Dropbox/OneDrive
  (they ask for an account). They are listed back with a reason. Planned in a separate task.
- **YouTube/Vimeo cookies** (only used when `YTDLP_PROXY` is empty; `~/.config/medycabrain/*_cookies.txt`) were last written 14–15
  Sep 2026: transcription from a link fails with the "cookie scaduti" sentence until they are
  re-exported. Operational, not code; the reference card is still saved.

- **An unlisted Vimeo video pasted twice, once with its hash and once without, stays two rows.**
  Telling them apart would need a network call inside `extract_links`, which is deliberately
  pure and must stay cheap enough to run on every keystroke-sized paste.
- The `vimeo.com/channels/<x>/<id>` and `vimeo.com/groups/<x>/videos/<id>` spellings are
  supported by the regex but were **never tried on a real link of the client's** — he has none.
- **Only the listed subdomains are recognised**, as the price of anchoring the host: `www.`, `m.`
  and `music.` on YouTube, `www.` and `player.` on Vimeo. Anything else (a regional or future
  subdomain) is not read as a link at all — it fails closed, and the client sees the paste find
  nothing rather than a wrong video.
- Deduplication is a `filter(...).first()` before the `create` in `views.from_links`, now backed by
  the database constraint on `UploadedMedia.source_url`: the losing request gets an
  `IntegrityError`, reported as "già presente".

### Known limit: a TV recording opens with its sponsors

Measured on the first episode ingested (doc 842, 1 135 s, 14 733 characters): the transcript
begins with roughly a page of **local advertising** — a clinic, an orthopaedic shop, phone
numbers — before the medical conversation starts. The analysis window is
`content_text[:6000]` (`knowledge_agent.build_doc_enrich_prompt`), so a real share of what the
model reads is sponsor copy.

Two consequences, both observed on that document:

- The **on-topic verdict came back `False`**, with the reason "il contenuto è principalmente una
  sequenza di spot pubblicitari". That is a fair reading of what it was shown, and it is exactly
  why reference material is exempt from the `is_on_topic` filter — otherwise the video would
  have disappeared from search the moment it was added.
- The **claims were still correct**: all six were medical ("l'aumento di peso corporeo è
  associato a un aumento della pressione arteriosa", the 140/90 thresholds), none came from the
  adverts. The verbatim-quote contract held.

Not fixed here, because trimming a sponsor block reliably is guesswork. If it becomes a problem,
the honest lever is the analysis window, not a heuristic that deletes text.

### No draft from someone else's material

`run_upload_transcribe` writes a blog draft only when `owner_type == "owned"`. A draft is Medyca
writing in their own voice grounded in the text, and doing that from a third party's episode is
the mixing this project forbids — `blog_workflow` already filters `owner_type="owned"` when
picking cluster documents, and the same rule has to hold here now that an item can be marked as
someone else's. Caught the first time a competitor's TV episode produced a Medyca draft.

**What happens meanwhile is the point.** `_save_reference_only()` stores the video as a
`KnowledgeDocument` carrying title, channel and link, `enrich_status=SKIPPED`, with a vector
built from the **title** so it can still be found and handed back through `cerca_riferimenti`.
No transcript means no analysis: asking a model to describe a video from its title alone is how
invented claims get into a medical knowledge bank. The `UploadedMedia` row stays `failed` with a
sentence the client can act on ("Serve un file di cookie… oppure carica il file video a mano"),
shown inline in the UI rather than hidden in a tooltip.

(Embedding the title is safe in a way embedding an empty string was not: the empty-string vector
sits at a fixed point close to every question, which is how ten contentless reels once took the
top of a search.)

## Where the list of reels comes from

Downloading a reel and knowing *which* reels exist are two different problems,
and only the first one is easy. This section is the one to read before anyone
proposes changing the collection path again.

### What is closed, and why (measured 2026-09-11)

| Path | Status |
|---|---|
| Anonymous profile listing | `GET /api/v1/users/web_profile_info/` → **`401 {"require_login": true}`**. The profile page redirects to `/accounts/login/`. |
| **yt-dlp** listing an account | Impossible. Its `InstagramUserIE` carries `_WORKING = False` and a `_QUERY_HASH` Instagram retired. Tested on 2026.07.04 and 2026.08.19 — both fail. |
| instaloader | Removed its anonymous branch in March 2026; the endpoint requires a session. |
| Logged-in session (`ig_client.py`) | Works, but was removed on 2026-07-29: it ran as a personal account, and the log shows Instagram had begun blocking it — **23 checkpoint/401 blocks on 26 July, 15 more on the 29th**, plus the session file being reissued on the 26th. |
| Mirror sites (Picuki, Picnob, Pixwox, Pixnoy, Imginn) | All **403** to this VPS. Picuki has served nothing since 2025. |
| Meta Graph API | Supported in code (`graph_client`), takes precedence when `IG_GRAPH_TOKEN` is set. Not configured, by the client's decision. |

**What is open:** a single reel, given its shortcode, is fetchable anonymously —
which is exactly what `yt-dlp` does in stage 2, and why it stays there.

### The split that resolves it

- **Apify lists.** `apify/instagram-reel-scraper` returns the recent reels of an
  account — shortcode, caption, counts, timestamp and a signed `videoUrl` — from
  Apify's own infrastructure. **No Instagram account of ours is involved.**
- **yt-dlp downloads.** Free, anonymous, already proven (3/3 reels, 4-6 s each,
  re-verified 2026-09-11).

A useful side effect: because the scrape call already returns a fresh `videoUrl`,
a reel collected and downloaded in the same run costs nothing extra — the
downloader's Apify prefetch finds a usable url and never fires. Measured on the
first real collection: `apify_accounts: 0, apify_urls: 0`.

## The money, and what stops it

`scraper/apify_budget.py`. The plan is **Apify FREE: $5.00 per cycle, renewing
monthly** (verified 2026-09-11, cycle 27 Aug → 26 Sep). Not a one-off allowance,
but a hard wall — past it the actor stops answering and collection dies quietly.

**Prices**, read from the actor's own pricing (PAY_PER_EVENT, FREE tier):

| Event | Price | |
|---|---|---|
| `reel` | **$0.0026** | every result returned, new or already known |
| `actor-start` | **$0.0010** | flat, once per account queried |
| `shares-count` | $0.0070 | ⛔ never enabled |
| `video-download` | $0.0200 | ⛔ never enabled — yt-dlp does it free |
| `transcript` | $0.0480 | ⛔ never enabled — the pipeline transcribes itself |

The three add-ons are **one JSON field away** and cost up to **18×** the base
price. `apify_provider.fetch_reels` therefore sends a closed payload — only
`username` and `resultsLimit` — and the restriction is a comment in the code as
well as a line here, because a stray field would burn a cycle in one night.

### Three defences, in order

1. **The ceiling.** `apify_budget.check()` asks Apify what the cycle has already
   cost, adds what the call is about to cost, and refuses past
   `ScraperConfig["apify_ceiling_usd"]` (default **$4.00** — below the plan's $5
   on purpose, so a mis-estimate cannot reach zero). A refusal surfaces as
   `ApifyUnavailable`, which every caller already treats as "this source cannot
   help right now". The scrape stage says it once and skips the rest of the
   accounts rather than logging a dozen identical failures.
2. **Adaptive depth.** Every result is billed whether or not it is new, so
   asking a fixed depth of everyone makes the quiet accounts pay the prolific
   ones' price — measured posting rates here range from every 0.1 days to every
   34 days. `_apify_depth()` asks for *the gap since their last known post
   divided by how often they post, plus three*, clamped to
   `[3, ScraperConfig["apify_max_depth"]=30]`.
3. **The prefetch cap.** `downloader_agent._prefetch_urls` used to ask for
   `known + 60`. On this plan that is the most expensive thing the pipeline can
   do: `menopausa_insieme` has 124 known reels → 184 results → **$0.48 for one
   account, one night**, and roughly **$3.70 across twelve** — a whole cycle, to
   fetch urls yt-dlp does not need. Now capped at `_PREFETCH_MAX_DEPTH = 30`.

### What it actually costs

Measured, not estimated:

- Catching up the six-week gap across the 12 live accounts: **~$0.71, once.**
- Steady state, 12 accounts: **$3.17/month nightly**, **$1.58/month every two
  days**, $1.12/month weekly.
- First real collection (`@medyca.menopausa`, depth 9, 1 new reel): **$0.014.**

The estimate in `estimate_usd()` assumes every account returns the full depth,
so it runs **pessimistic** — the first real run was billed less than estimated.
That is the right direction to be wrong in on a $5 plan.

### Known limits

- **11 of the 23 tracked accounts are dead weight.** Eight have never returned a
  single reel (one, `elena,palliotto`, has a comma where a dot belongs — the
  username is simply wrong), and `buonarroti_medical_center` last posted in
  January 2025. Querying them costs `actor-start` for nothing. They should be
  diagnosed once and deactivated; until then they are billed.
- **Reels only.** Stories, carousels and static posts are not collected.
- **The ceiling stops collection, nothing else.** Transcription, analysis,
  clustering and the whole interface keep working on what is already in the bank.
- **Apify is an external dependency.** If the actor changes its output or its
  prices, this stage changes with it.

### How a reel's video actually arrives

Stage 2 is the only stage that touches Instagram, and Instagram is the part of the
system that fights back. There is no official way to download a reel's mp4, so the
downloader tries **three sources, cheapest and safest first**, and falls through.

```mermaid
flowchart TD
    start([reel with media_status=pending]) --> prefetch

    subgraph P["once per run, per account"]
      prefetch["<b>1. Apify prefetch</b><br/>_prefetch_urls()<br/>one actor call per account<br/>fills video_url in bulk"]
    end

    prefetch --> cached{"<b>2. cached CDN url</b><br/>video_url present<br/>and oe= not expired?"}
    cached -->|yes| get["plain GET on the CDN<br/>_download() · no quota · no pacing"]
    cached -->|no| ytdlp
    get -->|"HTTP error<br/>(revoked / expired early)"| ytdlp
    get -->|ok| have

    ytdlp["<b>3. yt-dlp fallback</b><br/>_ytdlp_fetch()<br/>public permalink, anonymous<br/>instagram.com/reel/&lt;shortcode&gt;/<br/>~6-8s per reel"]
    ytdlp -->|ok| have
    ytdlp -->|"DownloadError saying<br/>login / rate / 429"| throttled
    ytdlp -->|other error| failed

    have(["mp4 on disk"]) --> audio{"_has_audio()<br/>does it carry<br/>an audio stream?"}
    audio -->|yes| mp3["ffmpeg → 16kHz mono mp3<br/>transcribe_status=pending"]
    audio -->|"no (silent reel)"| silent["transcribe_status=skipped<br/>enrich_status=pending"]
    mp3 --> thumb
    silent --> thumb
    thumb["thumbnail saved (non-fatal)<br/>mp4 deleted<br/><b>media_status=done</b>"]

    throttled["<b>IGThrottled</b> — the reel did nothing wrong<br/>stays media_status=pending, <b>no attempt charged</b>"]
    throttled --> streak{"3rd block<br/>of this run?"}
    streak -->|no| next([next reel])
    streak -->|yes| stop["stopped_early: for the rest of the run,<br/>only reels that already hold a usable url<br/>are processed — the others are deferred"]

    failed["media_attempts += 1<br/>media_status=failed"] --> tries{"attempts &gt;= 3?"}
    tries -->|no| retry["flipped back to pending<br/>at the end of the run"]
    tries -->|yes| skipped["media_status=skipped<br/>(stays skipped — never auto-reset)"]

    classDef ok fill:#dcfce7,stroke:#22c55e;
    classDef warn fill:#fef3c7,stroke:#f59e0b;
    classDef bad fill:#fee2e2,stroke:#ef4444;
    class get,have,mp3,thumb,silent ok;
    class ytdlp,throttled,stop,retry warn;
    class failed,skipped bad;
```

**1. Apify prefetch** (`_prefetch_urls`, only when `apify_provider.enabled()`). One actor
call per account fills `video_url` for the whole batch, plus any missing caption /
thumbnail / counters. Depth is `max(reels known for that account, reels in this batch) + 60`
— a flat margin, because our pending rows sit scattered through the account's real
timeline, not at the top of it: a first attempt sized from the batch asked for 7 reels and
matched 0 of them. Overshooting costs a fraction of a cent; undershooting wastes the call.

**2. The cached CDN url.** Instagram signs media urls with `oe=<hex unix timestamp>`;
past it the CDN answers 403. `_url_expired()` reads that parameter with a 15-minute margin.
A url with no `oe=` is assumed good — the download attempt decides. This path is a plain
`requests` GET against the CDN, which has **no quota**, so the run does not pace itself here.

**3. yt-dlp on the public permalink** (`_ytdlp_fetch`). Downloads
`https://www.instagram.com/reel/<shortcode>/` **anonymously — no account, no cookies**.
This replaced the old renewal path (`/api/v1/media/{pk}/info/`), which needed a logged-in
session and was removed on **2026-07-29** because it ran as Giuseppe's personal account.
Measured from this VPS on **2026-07-30**: 3/3 reels, 6-8s each, valid MP4s with correct
durations.

#### The limits, written down before the next person hits them

- **yt-dlp is unofficial.** Instagram can block the IP or change the page at any time.
  A block arrives as a `yt_dlp.utils.DownloadError` whose text mentions *login*, *rate*,
  *429* or *wait a few minutes* — mapped to `IGThrottled` so the run **defers** instead of
  burning three attempts per reel on a wall that is not the reel's fault.
- **A block ends the run early, on purpose.** After the 3rd block (`_THROTTLE_STREAK`,
  counted *total*, not consecutive) the run sets `stopped_early` and from then on skips only
  the reels that would need the network — reels holding a fresh url keep going. Counting
  consecutively was the bug: a run alternates between reels that succeed and reels that are
  blocked, every success reset the streak, and the run paid the 20-40s pacing sleep on every
  doomed call — **2 reels/min instead of ~12**.
- **Pacing applies only after a web hit.** `_process_one` returns `used_api`; the loop sleeps
  `uniform(download_delay_s, 2 × download_delay_s)` only when the previous reel actually went
  out to Instagram. Sleeping after CDN cache hits would waste hours.
- **A reel can be silent.** `has_audio=False` means every video stream is video-only:
  transcription is skipped and the reel goes straight to enrichment on its caption.
- **Order and cap.** Medyca's own reels first (`owner_type="owned"`), then each competitor's
  best-performing ones, so a 122-reel account cannot starve the other twelve. Per-run size is
  capped by `ScraperConfig["download_max_per_run"]`; the backlog drains across runs.
- **`_fetch_media_details` still exists** and is still the only source of the richer metadata,
  but it needs cookies. With no session file it raises `IGThrottled` rather than failing the
  reel.

### What "cluster" actually does

- **Layer 1 (content → themes).** Embed each enriched reel + the `owned`/`competitor`
  documents. Cluster with **HDBSCAN** (`min_cluster_size=4`, `min_samples=2`; requires n ≥ 60,
  ≥ 3 clusters, noise ≤ 0.6). If that fails the size test, fall back to **Agglomerative**
  (cosine, `distance_threshold` from `ScraperConfig`, default `0.30`). Each cluster is named in
  Italian by one LLM call (`model_for("analysis")`). A new cluster reuses the previous run's
  label when centroid cosine ≥ 0.80, so themes keep stable names run to run.
- **Layer 2 (claims → themes).** Assign each `ReelArgument` to the nearest centroid; cosine
  < 0.35 counts as noise.
- Runs **once per scope** (`owned`, then `competitor`) — the two sides never share a cluster.

## Starting a run by hand

The pipeline used to run only from cron, which meant that adding an account or a
blog source and then wanting to see the result involved waiting for the night.
The status page now has an **Aggiorna ora** button.

- `POST /api/v1/ops/run/` (`PipelineRunView`) queues a `Job(kind="pipeline")` and
  `run_job` executes it detached, exactly like every other background job.
- The work itself is `core/pipeline_run.py` → `pipeline.dag.build_steps()`. **The
  stage list lives in `pipeline/dag.py`, not in the management command**, because
  there are now two callers and two copies would eventually disagree about what
  "the pipeline" is. `manage.py run_pipeline` uses the same function.
- `DAG.run(..., on_step=…)` reports each stage as it begins, so the `Job` row
  carries a percentage and a stage name the interface can show. The cron
  entrypoint passes no callback and behaves exactly as before.
- **The output is teed into `logs/pipeline.log`** as well as the job's own log.
  Everything that reports on the pipeline reads that file — the run timeline in
  `core/ops.py`, the per-item rates below — so a manual run that wrote only to
  `logs/jobs/job-<id>.log` would be invisible to the very page that started it.
- A stage that fails does **not** fail the job: every step is non-fatal by
  design, and the stages that did run really did their work. The job finishes
  with `Completato, ma senza: <stages>` and `result.failed_stages`.

**Only one run at a time, and the guard is wider than the `jobs` table.** A
second concurrent run is not merely wasteful: the downloader paces itself against
Instagram's quota, and two runs double the request rate against the limit that is
already the bottleneck. So the view checks both the job rows *and* the process
table (`ops.activity()`) — the nightly cron run leaves no row in the database and
is the run most likely to be in progress when someone presses the button. Either
way the answer is **409** with a sentence saying so.

## How much is left, and how long it takes

`core/queue_eta.py`, served inside `/ops/status/` as `queue`, and shown by
`PipelineQueue` on the status page. It exists because the stage bars answer *how
far has it got* and the client asks *quanto manca* — and a percentage cannot say
whether the remainder is ten minutes or ten hours.

**How many.** The pending counts on the rows themselves — the same ones each
agent selects from — carried forward: a reel waiting to be downloaded will also
have to be transcribed and analysed, so it counts once per stage it has still to
cross. `remaining` (the headline number) is distinct reels with at least one
stage pending **that an agent can reach**. A reel pending for a stage nobody will
ever run is `blocked`, a separate number: transcription needs `media_status=done`
and an audio file (or a download still to come); analysis needs a transcription
`done`/`skipped` (or one still reachable); claim extraction needs the analysis
`done` (or reachable). These are the agents' own filters
(`transcriber_agent.run`, `enrich_agent.run`). Measured on 2026-11-05: the old
«7 rimanenti» were 6 reels with `media_status=skipped` + `transcribe_status=pending`
and one with a failed transcription — stuck, not queued, so the number never went
down. Now `remaining` is 0 for them and `blocked` is 7. Nothing is retried or
re-marked by the status page.

**How long.** Seconds per item, read from the `✓ <stage> done in <n>s — {…}`
lines the DAG writes into `logs/pipeline.log`, over the **last 5 runs that
actually processed something**. The window is small on purpose: the per-item cost
of this pipeline has changed by more than an order of magnitude as its models
changed — transcription measured **245 s/reel** on local faster-whisper and
**4.1 s/reel** on remote STT. An average over all history would describe a
machine that no longer exists. A run that handled zero items is skipped
entirely: its duration is start-up cost, and averaging it in drags every
estimate towards zero.

| Stage | Status columns it drains | Result keys counted as items |
|---|---|---|
| `download` | `media_status` | `downloaded`, `failed`, `skipped` |
| `transcribe` | `transcribe_status` | `transcribed`, `failed` |
| `enrich` | `enrich_status` **and** `argument_status` | `enriched`, `arg_reels` |

`enrich` carries two columns on purpose. Extracting the claims is **not** a
separate stage — `enrich_agent.run` analyses the reels and then extracts the
claims inside the same step, and the log records one duration covering both.
Giving the claims their own stage would count that duration twice, so they are
counted as a second kind of item inside the stage that does the work. A reel
arriving at `enrich` therefore becomes two items, not one.

### What the estimate does not cover

- **Download is the unreliable one.** Measured between **9 and 77 s/reel** across
  runs, because the cost depends on how many urls Apify pre-filled (a cached CDN
  url is a plain fast fetch) and on whether Instagram starts throttling mid-run,
  in which case the run stops early and the rest waits for the next one. The UI
  says so in as many words rather than presenting one number as a promise.
- **Silent reels skip transcription** (`transcribe_status='skipped'`), so the
  forward-carry counts a few items that will never be transcribed. The estimate
  is slightly pessimistic, which is the right direction to be wrong in.
- **Failed rows are not work.** They stay `failed` by design and are not
  auto-retried, so they are reported next to each stage but never inside the ETA.
- **Blocked rows are not work either.** They are shown as «reel non lavorabili»
  with the reason (senza audio / trascrizione non riuscita). Fixing their states
  (e.g. `transcribe_status=skipped` for reels with no audio) is agent work, not
  done by this page.
- **Only reels.** Blog articles and uploaded interviews are not in this queue.
- **No history, no measurement.** Until the log holds a productive run for a
  stage, a documented default is used and the panel says the number is a
  starting estimate, not a measurement (`measured: false`).

## What the status page reads, and how it stays honest

`core/ops.py` builds the «Stato» page from the machine, not from memory:

- **One run, one bar.** Stage names, order and labels are imported from
  `pipeline/dag.py` (`STAGE_NAMES`, `STAGE_LABELS`). `ops.py` used to keep its own
  copy without `batch`; `run_history()` detects a new run when a stage starts
  *earlier* in the order than the previous one, so `enrich` (position 3 in the
  copy) after `batch` (unknown, position 8) looked like a backward step and every
  nightly run was drawn twice (visible in `pipeline.log` from 2026-11-03, when
  `batch` joined the DAG).
- **A run started from the interface is seen.** `activity()` reads the process
  table; a UI run is `manage.py run_job --job N`, so it looks the `Job` up
  (`kind`, `message`) and reports it with an Italian label (`JOB_KIND_LABELS`).
  Before, the page said «Nessuna elaborazione in corso» while one was running.
- **No bar for work that is not happening.** `reanalysis()` answers only while a
  `reprocess` process runs. It used to compare rows against the current model's
  name: after the switch to `claude-opus-5`, 947 of 1593 analyses were by a
  different (better) model and the page showed «406/1593» for months, with
  `reprocess.log` untouched since 27 July.
- **Schedules in the client's words.** The text comes from the command
  (`--skip-cluster --skip-blogscrape` → «senza raggruppamento e senza blog»),
  not from the crontab comment, which is English and written for whoever edits cron.
- **The last result stays.** `/ops/status/` returns `last_pipeline_job`, so a
  finished or failed UI run is still on the page after it stops being «in corso».

Blog `last_error` (written by `blogscrape_agent`) is a sentence, not a Python
repr: `_human_error()` maps timeout / connection / HTTP errors to Italian
(«il sito non ha risposto in tempo», «sito non raggiungibile», «il sito ha
risposto con errore 503»); the repr stays in the log line.

## The idempotency contract

The pipeline is safe to run on a fixed schedule because **state lives on each row**, not in
the runner. A stage selects only rows in the `pending` state for its column, does its work,
and advances the column. Re-running does no double work. Failures stay `failed` and are *not*
auto-reset — see [01-data-model.md](01-data-model.md#shared-vocabulary).

## Management commands

All under `BEC/core/management/commands/`. Run with `python manage.py <name>`.

| Command | Purpose |
|---|---|
| `run_pipeline` | Run the DAG (cron entrypoint). Flags: `--dry-run`, `--limit`, `--only <stage>`, `--skip-<stage>`. Stages come from `pipeline.dag.build_steps()`, shared with the manual run. |
| `run_job <id>` | Execute a queued `Job` by id, detached. |
| `reprocess` | Re-run stages (`transcribe`, `enrich`, `knowledge`), resumable. Flags: `--stage`, `--scope`, `--limit`, `--only-stale`, `--with-transcript`, `--not-model`. |
| `ingest_blog` | Fetch a specific Medyca blog article (or several). |
| `import_apify` | Fill `video_url`/`caption`/`posted_at`/`duration` from an Apify export. |
| `backfill_meta` | Backfill `posted_at` and other metadata. |
| `autotag` | Generate auto `Tag`s from `primary_topic` (reels + docs). |
| `eval_mcp` | Run the MCP connector eval suite (retrieval, integrity, latency, judge). |
| `graph_check` | Verify the IG Graph token / caller / discoverability. |
| `ig_session` | Import / test Instagram cookies. |
| `progress` | Live pipeline progress bar. |
| `seed_client_user` | Create the client user + token + `ScraperConfig` defaults. |
| `seed_demo` | Create synthetic demo reels. |

## Scheduling

The cron schedule is **not committed inside `BEC/`** — `run_pipeline.py` declares itself the
cron entrypoint and the actual schedule lives on the host (see `deploy/crontab.txt`). The
pipeline is idempotent and self-throttling (blogscrape respects each source's
`crawl_interval_h`), so a fixed nightly run is safe. Background work triggered from the UI
(ideation, drafts, uploads, blog-source discovery) runs as detached `Job` rows via `run_job`,
not through the nightly DAG — **except the pipeline itself**, which the client can now start
from the status page and which runs the same DAG inside a `Job` (see
[Starting a run by hand](#starting-a-run-by-hand)).

Next: [LLM and embeddings](03-llm-and-embeddings.md).
