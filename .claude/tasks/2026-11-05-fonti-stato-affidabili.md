---
id: 2026-11-05-fonti-stato-affidabili
titolo: Fonti, account e pagina Stato che dicono la verità
stato: pronto
ramo: feat/fonti-stato-affidabili
pr: ""
ticket: ""
---

## 1. Richiesta          (capo)

Parole di Giuseppe: «I'm receiving a lot of complaints from my client, who is saying that these things are not working properly. [...] everything related to uploading links for documentation and stuff like that needs to be done in a better way. It needs to be counterchecked.» Poi, dopo la revisione: «proceed to correct everything».

Il lavoro è diviso in tre rami paralleli, tutti da `main` (062d874):
`feat/upload-link-affidabili`, `feat/fonti-stato-affidabili`, `feat/navigazione-errori`.
Ognuno ha il suo worktree in `/home/giuseppe/projects/medycabrain-wt-<slug>`.
Lavora SOLO nel tuo worktree.

**Confini di questo ramo (per non collidere con gli altri due):** Possiedi: AccountsPanel, BlogSourcesPanel, CustomTopics, manage/parts, ops/*, pages/Status.tsx, Accounts.tsx, e lato BEC serializers Account/BlogSource/CustomTopic, le view relative, ops.py, queue_eta.py, blogscrape_agent.py (solo last_error), custom_topics.py, plan/generate int(n). Il trailing slash di BlogSource (A8 nella lista upload) è tuo. fetchAccounts in endpoints.ts è tuo. NON toccare: JobsContext.tsx e SecondBrain.tsx (li fa feat/navigazione-errori, incluso il punto B9 sulle idee).

Modelli: piano con Fable, esecuzione con Sonnet (regola in arrivo con `feat/regola-modelli`).

Malfunzionamenti da correggere (revisione di sola lettura del 2026-11-05; file:riga si riferiscono al checkout di allora, ricontrolla):

## B. Sources / accounts / topics / Status
1. Accounts list shows 24 of 26 (pagination, endpoints.ts:64-66). Ideas list will hit same at 24.
2. Blog URL with trailing slash / www variant -> 500 instead of "già esiste" (serializers.py:30-55). Duplicates already in DB (lidialamarca, pausetiv).
3. "Rimuovi" (account/blog) only marks inactive, row stays; re-add -> error with English model name (views.py:59-104).
4. Re-enabling a blog via status pill leaves its articles hidden forever (BlogSourcesPanel.tsx:274).
5. Status "7 rimanenti" never drains (queue_eta.py counts unreachable rows).
6. Every nightly run shown as two runs; "batch" missing from STAGE_LABELS (ops.py:35-44).
7. LiveActivity says idle while a UI-started run is running (ops.py:256-260).
8. "Rianalisi 406/1593" shown as in progress, nothing running since 27 Jul (LiveActivity.tsx:76).
9. Generate ideas: no error message, double-click starts several LLM jobs, lost after reload (JobsContext.tsx:108-111, SecondBrain.tsx).
10. Status page skeleton forever if /ops/status/ fails (Status.tsx:88).
11. Toggle/remove/crawl/reactivate/topic remove: no error or success feedback; failed list = "empty" list.
12. Blog last_error shown as raw Python repr (blogscrape_agent.py:77).
13. Instagram username accepts URLs/junk, no lowercase; scraping budget exhausted until 26 Nov and form doesn't say.
14. (Suspected) custom topic create can 500 and leave half-made topic; case duplicates.
15. (Suspected) int(n) 500; finished/failed UI pipeline disappears; raw codes (j.kind, owner_type, English cron comment); tiny tap targets on mobile.

## 2. Disegno            (architetto)

Scritto il 2026-11-05 sul worktree `feat/fonti-stato-affidabili` (base `main` 062d874).
Solo lettura: nessun dato toccato, nessun codice scritto. Tutti i numeri qui sotto
sono misurati sul DB e sui log live (comandi indicati), salvo dove dico «suppongo».

### 2.0 Vincoli misurati

| Fatto | Come l'ho accertato |
|---|---|
| 26 account, 23 attivi; pagina REST = 24 (`core/pagination.py` `page_size = 24`, `max_page_size = 200`). `fetchAccounts` legge solo `data.results` della prima pagina → 2 account spariscono. `fetchBlogSources` passa già `page_size: 100`. | `TrackedAccount.objects.count()`; `FEC/src/api/endpoints.ts:64-66`; `FEC/src/api/blogSources.ts:23` |
| 3 account inattivi (`menopausa_doc`, `faceboost`, `faceboost_`) hanno **0 reel**: sono «rimossi» che restano in lista come «Inattivo». | `TrackedAccount.filter(is_active=False).annotate(Count('reels'))` |
| 33 fonti blog. Stesso dominio più volte: `lidialamarca.it` (#23 inattiva, 0 articoli) vs `www.lidialamarca.it/diario-della-salute` (#31, 19 articoli); `pausetiv.com` (#18, 1 articolo) vs `www.pausetiv.com/it/blog` (#29, 39); `ginecologiafiorillopalese.it` (#19 inattiva, 0) vs `/blog` (#30, 19); `centromedicobuonarroti.it` (#5, 43) vs pagina profonda (#4, 0); `medyca.it` ×3 (#17 homepage 0, #1 /blog 4, #16 /menopausa 18). **Nessuno è un duplicato esatto www/non-www**: tutti hanno percorsi diversi. | `BlogSource.objects.order_by('index_url')` con conteggio documenti |
| Perché la barra finale dà 500: DRF esegue il `UniqueValidator` di `index_url` **prima** di `validate_index_url`, che poi toglie lo `/` finale. Il validator confronta `…/blog/` con `…/blog` (diversi → passa), poi l'INSERT viola `unique` → `IntegrityError` → 500. | lettura `serializers.py:39-56` + ordine di validazione DRF (field validators → `validate_<field>`) |
| «Rimuovi» account = `is_active=False` (riga resta). «Rimuovi» blog = idem + documenti `is_active=False`. Il toggle di stato (pausa) usa **la stessa colonna**: pausa e rimozione sono indistinguibili. Ri-aggiungere → `UniqueValidator` → «tracked account with this username already exists.» (inglese, nome del modello). | `views.py:59-62, 97-104`; `models.py:45` `username unique`, `:409` `index_url unique` |
| Riattivare un blog dal pill fa `PATCH is_active=true` e **non** riattiva i documenti (solo `reactivate/` lo fa). | `BlogSourcesPanel.tsx:273-275` → `updateBlogSource`; `views.py:112-123` |
| Coda «7 rimanenti» = 6 reel di `drgiulianagiudice` con `media_status=skipped` e `transcribe_status=pending` + reel 951 con `transcribe=failed` e `enrich/argument=pending`. Il trascrittore seleziona solo `media_status=DONE` e `audio_file≠''`; l'enrich richiede trascrizione fatta. **Nessun agente li prenderà mai**: sono bloccati, non in coda. | query su `Reel` con `Q(…='pending')`; `transcriber_agent.py:108-109`; `enrich_agent.py:307,330` |
| Ogni esecuzione appare doppia: `ops.STAGE_LABELS` (e anche `dag.STAGE_LABELS`) **non ha `batch`**; in `run_history` `batch` prende posizione 8, poi `enrich` (pos 3) «torna indietro» e apre una seconda esecuzione. Il log mostra `▶ agent: batch` in ogni run dal 2026-11-03. | `ops.py:35-44, 200-204`; `grep "▶ agent:" logs/pipeline.log` |
| Nessun processo `manage.py` in esecuzione ora; `reprocess.log` fermo al **27 luglio**. `reanalysis()` mostra 406/1593 perché conta solo `llm_model ∋ claude-sonnet-5`; 947 analisi sono di `claude-opus-5` (modello **migliore**, non più economico). La barra promette una rianalisi che non esiste. | `ps -eo args \| grep manage.py`; `ls -la logs/reprocess.log`; distribuzione `Enrichment.llm_model` |
| `activity()` riconosce solo `manage.py run_pipeline/reprocess/ingest_blog`; una run dalla UI è `manage.py run_job --job N` → «Nessuna elaborazione in corso» mentre gira. | `ops.py:256-260, 315-321`; `views.py:724` |
| Crontab: 2 righe `medycabrain` con commento **inglese** («nightly full pipeline (off-peak, box is quiet)») mostrato così al cliente; orari 03:30 e 14:15 (server in CET). | `crontab -l`; `date +%Z` |
| Budget Apify: `spent 4.003 / ceiling 4.00`, `available 0.0`, `cycle_end 2026-11-26`. La raccolta reel è ferma fino al 26/11 e il form «Aggiungi account» non lo dice. | `apify_budget.spend()` |
| `blogscrape_agent.py` scrive `repr(exc)[:500]` in `last_error` (righe 78, 83, 87, 173). Oggi in DB gli errori sono già italiani («nessun articolo trovato»): il repr compare solo sul ramo eccezione. | lettura file + `BlogSource.last_error` |
| `CustomTopic.label` è `unique` **case-sensitive** («Tiroide» e «tiroide» passano entrambi). `perform_create` salva la riga, poi `embed_topic` (carica il modello) e `recompute_matches`: se una delle due fallisce, la riga resta senza embedding e la risposta è 500; al secondo tentativo «custom topic with this label already exists.». Oggi 4 temi, 0 inattivi, tutti con embedding. | `models.py:672`; `views.py:1160-1164` |
| `plan`: `int(request.data.get("n", 6))` e `generate`: `int(request.data.get("n", 8))` senza `try` → `"abc"` dà 500. | `views.py:652, 668` |
| Status: `isLoading \|\| !data` → se la prima chiamata fallisce lo skeleton resta per sempre. Pannelli: `!data?.length` → una lista **fallita** è mostrata come **vuota** («Nessun account monitorato»). Nessun componente toast esiste nel FE. | `Status.tsx:88`; `AccountsPanel.tsx:152-155`; `grep -ri toast FEC/src` → 0 |
| Tap target: `RowAction` è `px-1 text-xs` senza altezza minima; `StatusToggle` idem; «✕» del tema `w-8`. La regola UI del progetto chiede **40px**. | `manage/parts.tsx:233-246, 259-266`; `CustomTopics.tsx:151-157`; `.claude/skills/ui-design/references/component-patterns.md:9` |
| Test esistenti: `core/tests/test_endpoints_smoke.py` (APITestCase con token), nessun test su serializer/ops/queue_eta. CI gira su `requirements-ci.txt` (leggero): i test non devono caricare modelli. | `ls BEC/core/tests`; `.github/workflows/ci.yml` |

### 2.1 Le correzioni, in ordine di impatto sul cliente

**D1 — «Rimuovi» che rimuove davvero, e ri-aggiungere che funziona (B3, B4, parte di B13)**

Decisione: **nascondere, non cancellare**. Cancellare un account porta via a cascata tutti i suoi reel, trascrizioni e analisi (`Reel.account` è CASCADE); cancellare un blog lascia orfani i documenti (`source` è SET_NULL) che resterebbero nell'analisi col loro `owner_type` denormalizzato. Entrambi irreversibili con un click. Ma oggi «rimosso» e «in pausa» sono la stessa colonna, e questo è il bug: il cliente rimuove, la riga resta come «Inattivo», e non può più ri-aggiungerla.

- **Migrazione (sì, una):** colonna `removed_at` (DateTime, null) su `TrackedAccount` e `BlogSource`. Nessuna migrazione dati. «In pausa» = `is_active=False, removed_at=NULL`; «Rimosso» = `is_active=False, removed_at=now`.
- `DELETE` → imposta `removed_at` + `is_active=False` (per i blog anche documenti `is_active=False`, come oggi). La lista di default **esclude** i rimossi; `?removed=1` li restituisce (stesso schema di `ReelViewSet ?excluded=1`, `views.py:258-260`: riuso del pattern, non invento). Nuova action `POST …/{id}/restore/` (speculare a `reels/{id}/restore/`): toglie `removed_at`, `is_active=True`, per i blog riattiva i documenti e accoda una scansione (riuso `_queue_crawl`).
- **Ri-aggiungere un rimosso = ripristinarlo.** Nel `create` del serializer/viewset: se esiste una riga con lo stesso username / URL canonico e `removed_at` non nullo → ripristino e risposta 200 con la riga e `"restored": true`; se esiste ed è attiva o in pausa → 400 **in italiano** «Questo account è già monitorato» / «Questo blog è già tra le fonti (nome)». Il messaggio DRF inglese va sostituito dichiarando `extra_kwargs` sul campo con `validators=[]` e facendo il controllo a mano in `validate_*`.
- Il toggle di pausa su un blog, quando passa da `False` a `True`, riattiva i documenti (`perform_update`): copre B4 e le righe «rimosse» col vecchio metodo che oggi hanno documenti nascosti (es. #23, #19).
- **UI** (`AccountsPanel`, `BlogSourcesPanel`): il filtro guadagna «Rimossi» (seconda query `["accounts","removed"]` solo quando selezionato); le righe rimosse mostrano «Ripristina» al posto di «Rimuovi»; «Inattivo» viene rinominato «In pausa» e la conferma di rimozione dice che si ritrova nel filtro «Rimossi». Il conteggio della tab resta quello dei non rimossi.
- **Duplicati esistenti (proposta, non tocco nulla):** dopo il rilascio Giuseppe o il cliente, dalla UI, «Rimuovi» #23 lidialamarca.it (0 articoli, già inattiva) e #19 ginecologiafiorillopalese.it (0, inattiva). Per `pausetiv` #18 (1 articolo) e `Centro Buonarroti` #4 (0) e `Medyca Homepage` #17 (0): da decidere (domanda aperta Q2). Nessuna fusione automatica: i percorsi sono diversi e in un caso (medyca.it ×3) sono voluti.

**D2 — URL blog: varianti riconosciute, mai 500 (B2, A8)**

- `validate_index_url` normalizza prima (strip, `rstrip("/")`, host in minuscolo, via il `#fragment`) e poi cerca gli esistenti con `index_url__in=[8 varianti]` (con/senza `www.`, con/senza `/` finale, `http`/`https`). Trovato attivo → 400 italiano «Questo blog è già tra le fonti: «Nome»»; trovato rimosso → ripristino (D1). Nessuna migrazione: l'URL si salva come lo incolla il cliente (meno lo `/` finale), perché alcuni siti rispondono solo a una delle due forme e il crawler deve colpire quella data.
- Stesso host ma **percorso diverso** resta **permesso** (medyca.it ha 3 sezioni legittime). Se Giuseppe vuole almeno un avviso: Q3.
- Il frontend (`BlogSourcesPanel`) continua a prefissare `https://` e a derivare il nome dall'host; mostra il `detail` del server invece del primo campo a caso.

**D3 — Ogni azione risponde, e un errore non è una lista vuota (B10, B11)**

- `manage/parts.tsx`: tre pezzi nuovi, riusati dai tre pannelli e da `CustomTopics`: `PanelError({message, onRetry})` (lista non caricata: messaggio + «Riprova», mai `PanelEmpty`); `Notice({tone: "ok"|"error", message})` con `role="status"`/`"alert"` sotto la toolbar, che sparisce da sé dopo ~5 s (hook `useNotice`); `apiErrorMessage(e, fallback)` che estrae `detail` o il primo errore di campo (oggi duplicato in due pannelli).
- Ogni mutation (toggle, remove, restore, crawl, reactivate, add, topic add/remove) ha `onError` → `Notice error` con la frase del server, e `onSuccess` → `Notice ok` breve («Scansione avviata», «Rimosso: lo trovi in «Rimossi»», «Ripristinato», «Tema aggiunto: N contenuti trovati»).
- `Status.tsx`: `isError && !data` → riquadro errore con «Riprova» (riuso `PanelError`); `isError && data` → riga sottile «Ultimo aggiornamento non riuscito alle HH:MM, mostro i dati precedenti» (react-query conserva `data`).

**D4 — Lista account completa (B1)**

- `fetchAccounts` segue `next` finché c'è (helper `fetchAllPages<T>(url, params)` in `endpoints.ts`, usato anche da `fetchBlogSources` al posto del `page_size: 100` fisso). Oggi 26 righe = 2 chiamate; con `page_size: 200` sarebbe 1, ma seguire `next` non ha tetto. 
- La lista idee (`SecondBrain.tsx`) ha lo stesso problema a 24 ma è di `feat/navigazione-errori`: lo segnalo, non lo tocco (vedi 2.4).

**D5 — La coda dice «bloccati», non «rimanenti» (B5)**

- `queue_eta.py`: un reel conta come in coda per uno stadio solo se **può arrivarci**: `transcribe` pending richiede `media_status=done` e `audio_file≠''`; `enrich`/`argument` pending richiedono `transcribe_status ∈ {done, skipped}` (stessi filtri degli agenti, citati sopra). Il resto diventa un nuovo numero `blocked` nel payload (totale e per stadio), con la ragione in una riga («senza audio», «trascrizione fallita»). `remaining` scende a 0 con i dati attuali.
- `PipelineQueue.tsx`: se `blocked > 0` mostra «N reel non lavorabili (es. senza audio): non contano nell'attesa», accanto ai falliti. Resta coerente con la regola «i falliti restano failed»: non ritento nulla, dico la verità.
- I 7 reel restano com'è: una sistemazione dei loro stati (`transcribe_status→skipped` per i 6 senza audio) è lavoro degli agenti, non di questo ramo (Q4).

**D6 — Pagina Stato che dice la verità (B6, B7, B8, parte di B15)**

- `ops.py` smette di avere una **sua** lista di stadi: importa `STAGE_NAMES` e `STAGE_LABELS` da `pipeline.dag` (import leggero: `dag.py` rinvia gli import pesanti dentro `build_steps`). In `dag.STAGE_LABELS` si aggiunge `"batch": "Analisi in blocco (consegna entro 24 h)"` — una riga in un file **fuori dall'elenco dei miei** ma non toccato dagli altri due rami (Q1). Effetto: una run = una barra; e anche il messaggio del Job (`pipeline_run.py:75`) smette di dire «batch» nudo. `RunTimeline.STAGE_COLOUR` guadagna `batch` e `blogscrape`.
- `activity()` riconosce `manage.py run_job --job N`: legge il `Job` (`kind`, `message`, `status=running`); `kind="pipeline"` → stessa riga di «Pipeline completa» con lo stadio corrente da `run_history`; gli altri kind → etichetta italiana + `message`. Nuova mappa `JOB_KIND_LABELS` in `ops.py` (ideazione, piano editoriale, scansione blog, trascrizione, bozza, analisi strategica, aggiornamento contenuti) usata anche da `PipelineStatusView` per aggiungere `kind_label` a `jobs` → la UI non mostra più `j.kind`.
- `reanalysis()` restituisce `None` a meno che un processo `reprocess` sia **davvero** in esecuzione (`activity()` lo vede). Niente barra fantasma. Se un giorno si vorrà rifare le analisi opus→sonnet, è una decisione a parte (Q5).
- `schedules()`: il testo mostrato (`what`) viene dal comando, non dal commento crontab: «Aggiornamento completo» / «Aggiornamento di metà giornata (senza raggruppamento e senza blog)». Il commento inglese non arriva più in pagina.
- Ultimo risultato visibile: `PipelineStatusView` aggiunge `last_pipeline_job` (ultimo `Job kind=pipeline`, qualunque stato: `status`, `message`, `error`, `finished_at`). `PipelineQueue` lo mostra sotto il bottone: «Ultimo aggiornamento: completato alle 14:16» / «Completato, ma senza: …» / «Fallito: …». Così una run finita o fallita non sparisce.
- Tabella «Account monitorati» in Status: esclude i rimossi (`removed_at IS NULL`) e mostra «Medyca»/«Competitor» (i18n `scope.*`), non `owner_type` grezzo.

**D7 — Errore del blog leggibile (B12)**

- `blogscrape_agent.py`: funzione `_human_error(exc) -> str` usata nei 4 punti che oggi scrivono `repr`: `requests.Timeout` → «il sito non ha risposto in tempo»; `requests.ConnectionError` → «sito non raggiungibile»; `requests.HTTPError` → «il sito ha risposto con errore NNN»; `RobotsForbidden`/`BudgetSpent` → già italiani; altro → `str(exc)` o il nome della classe. Il `repr` resta nel `logger.warning` per chi manutiene. `last_error` è già nel serializer e già mostrato nel pannello: nessun'altra modifica.

**D8 — Username Instagram pulito e budget dichiarato (B13)**

- `AccountSerializer.validate_username`: accetta anche un link `instagram.com/<user>/…`, toglie `@`, spazi, `/`, mette in **minuscolo**, poi regex `^[a-z0-9._]{1,30}$`; errore italiano «Scrivi solo lo username, per esempio medyca.menopausa». Il `clean()` del frontend fa lo stesso prima di inviare (il server resta la verità). Esistente attivo → «già monitorato»; esistente rimosso → ripristino (D1).
- Budget: la risposta `201` di `POST /accounts/` include `collection_paused_until` (= `cycle_end`) quando `apify_budget.spend()` (già cache 5 min) dice `available_usd <= 0`. Il pannello mostra «Account aggiunto. La raccolta dei suoi reel partirà dal 26 novembre, quando si rinnova il budget». È il momento in cui serve saperlo; non aggiungo un endpoint né interrogo `/ops/status/` dal form (pesante: legge crontab, systemd, log).

**D9 — Temi del cliente senza mezzi fallimenti (B14)**

- `CustomTopicSerializer.validate_label`: strip, spazi collassati, controllo `label__iexact` → 400 «Questo tema esiste già («Tiroide»)». `extra_kwargs` toglie il validator inglese.
- `perform_create` dentro `transaction.atomic()`: se `embed_topic`/`recompute_matches` falliscono, la riga non resta; l'errore diventa `APIException` 503 con «Non sono riuscito a mappare il tema adesso. Riprova tra un minuto» (il `repr` va nel log).
- `CustomTopics.tsx`: stato errore della lista (`PanelError`), `detail` del server al posto di «forse esiste già», `Notice` ok con il numero di contenuti trovati, «✕» a 40×40.

**D10 — Piccole verità (B15)**

- `plan`/`generate`: `n` parsato con `try/except` e clamp (`plan` 3–12, `generate` 3–12), 400 «Il numero di idee deve essere un numero intero». La parte UI del doppio click è di `feat/navigazione-errori`; qui il server rifiuta già un secondo job identico (`_existing_job`).
- Tap target: `RowAction` → `min-h-10 px-3`; `StatusToggle` → `min-h-10`; pill temi come sopra.

### 2.2 File da toccare

**BEC**
- `core/models.py` — `removed_at` su `TrackedAccount` e `BlogSource` (+ docstring che spiega pausa vs rimosso).
- `core/migrations/00XX_removed_at.py` — due colonne nullable, nessun dato.
- `core/serializers.py` — `AccountSerializer.validate_username`, `BlogSourceSerializer.validate_index_url` (varianti), `CustomTopicSerializer.validate_label`, `extra_kwargs` per spegnere i messaggi inglesi, campo `removed_at` in sola lettura.
- `core/views.py` — `AccountViewSet` e `BlogSourceViewSet`: queryset `?removed=1`, `perform_destroy`, action `restore`, `create` con ripristino, `perform_update` (riattiva documenti), `collection_paused_until`; `CustomTopicViewSet.perform_create` atomico; `plan`/`generate` `n`; `PipelineStatusView`: `kind_label`, `last_pipeline_job`, account senza rimossi.
- `core/ops.py` — stadi da `pipeline.dag`, `activity()` con `run_job`, `JOB_KIND_LABELS`, `reanalysis()` solo se in corso, `schedules()` in italiano.
- `core/queue_eta.py` — raggiungibilità per stadio + `blocked`; docstring aggiornato.
- `pipeline/agents/blogscrape_agent.py` — `_human_error`, solo i 4 punti di `last_error`.
- `pipeline/dag.py` — **una riga**: `"batch"` in `STAGE_LABELS` (vedi Q1).
- `core/tests/test_sources_and_status.py` (nuovo) — URL varianti → 400 italiano; rimuovi+riaggiungi → ripristino; username con link/maiuscole; `n="abc"` → 400; `queue_eta` bloccati; `run_history` con `batch` = una sola run; tema `iexact`; `embed_topic` mockato (CI leggera).

**FEC**
- `src/api/endpoints.ts` — `fetchAllPages`, `fetchAccounts(removed?)`, `restoreAccount`.
- `src/api/blogSources.ts` — `fetchBlogSources(removed?)` via `fetchAllPages`, `restoreBlogSource`, campo `removed_at`.
- `src/api/customTopics.ts` — nessuna firma nuova, solo il tipo di errore.
- `src/components/manage/parts.tsx` — `PanelError`, `Notice`, `useNotice`, `apiErrorMessage`, tap target.
- `src/components/sources/AccountsPanel.tsx`, `BlogSourcesPanel.tsx` — filtro «Rimossi», «Ripristina», feedback, `clean()` username, avviso budget.
- `src/components/clusters/CustomTopics.tsx` — stati errore/ok, `detail`, «✕» 40px.
- `src/components/ops/PipelineQueue.tsx` — `blocked`, `last_pipeline_job`; `RunTimeline.tsx` — colori `batch`/`blogscrape`; `LiveActivity.tsx` — nessun cambio di forma (il server ora manda i dati giusti).
- `src/pages/Status.tsx` — stato errore, `kind_label`, etichette proprietà.
- `src/i18n/it.json` — chiavi nuove (`manage.removed`, `manage.restore`, `manage.paused`, `queue.blocked`, `status.lastRun*`, `status.loadError`, `accounts.budgetPaused`, `topics.exists`…).

**Documentazione (regola `.claude/rules/documentation.md`, stesso commit)**
- `documentation/low-level/01-data-model.md` — `removed_at` su `TrackedAccount`/`BlogSource` (voce tabella + ER) e la distinzione pausa/rimosso.
- `documentation/low-level/05-rest-api.md` — righe `accounts`, `blog-sources` (`DELETE` = rimozione reversibile, `?removed=1`, `restore/`, risposta `restored`, `collection_paused_until`, validazioni italiane), `custom-topics` (iexact, atomico), `second-brain/ideas` (`n` validato), `ops/status/` (`queue.blocked`, `jobs[].kind_label`, `last_pipeline_job`, `reanalysis` solo se in corso).
- `documentation/low-level/02-pipeline.md` — sezione «How much is left»: i bloccati; «What the estimate does not cover»; nota su `activity()` che vede le run dalla UI; `last_error` leggibile nel paragrafo blogscrape.
- `documentation/low-level/06-frontend.md` — riga `/accounts` (filtro «Rimossi», ripristino, feedback) e `/stato` (stato errore, ultimo risultato, bloccati).
- Pagina `Documentazione` in app (`FEC/src/i18n/it.json` → `docs.*`): la frase su «Fonti» (riga 355) aggiunge «rimuovere e ripristinare»; `docs.limits.items` aggiunge «alcuni reel senza audio non si possono lavorare e la pagina Stato li chiama “non lavorabili”».
- Docstring in testa a `ops.py`, `queue_eta.py`, `blogscrape_agent.py`.
- `docs/medycabrain-pipeline-cliente.drawio`: **non serve** (nessun passaggio aggiunto o tolto; cambia solo un'etichetta).

### 2.3 Rischi e invarianti

- **`owner_type` binario.** Nessuna correzione aggiunge valori; il ripristino di una fonte rimossa **mantiene** l'`owner_type` originale, non lo rilegge dal form. Attenzione in `create`-con-ripristino: se il cliente ri-aggiunge `@x` scegliendo «Medyca» ma la riga rimossa era «Competitor», il server deve rifiutare o chiedere, non cambiare in silenzio (Q6). Lo stesso per i blog.
- **I falliti restano `failed`.** D5 non ritenta e non cambia stati: li conta a parte. D1 `restore` di un blog azzera `consecutive_failures` solo nel `reactivate/` esistente, non nel `restore/` (sono due gesti diversi).
- **Niente credenziali di terzi.** Nessuna nuova chiamata esterna: `apify_budget.spend()` è già usata e cache-ata.
- **Reel di un account rimosso restano attivi** (decisione precedente in `views.py:60`). Per i blog la scelta è l'opposta. Non la cambio, la segnalo (Q7).
- **Documenti riattivati dal toggle** (D1/B4): un blog messo in pausa e poi riattivato oggi non tocca i documenti; domani li riattiva tutti. È voluto, ma se un documento era stato escluso singolarmente per altro motivo (oggi non esiste un gesto per farlo sui documenti: verificato con `grep -n "is_active" views.py` → solo reel e upload) non c'è perdita.
- **Migrazione** su due tabelle con poche righe (26 + 33): istantanea. La CI controlla il drift (`makemigrations --check`).
- **`pipeline/dag.py`** è fuori dal mio elenco: una riga, zero sovrapposizione con gli altri due rami (verificato: nessuno dei due elenchi lo cita). Serve l'ok del capo (Q1); in alternativa `ops.py` tiene una lista propria con `batch` e il messaggio del Job resta «batch».
- **`fetchAllPages`** aumenta le chiamate a 2 per gli account: trascurabile.
- **Conflitti di merge**: `endpoints.ts` è condiviso; io tocco solo il blocco `Accounts` (righe 63-87) come assegnato. `it.json` lo toccano probabilmente tutti e tre i rami: chiavi nuove in sezioni diverse, conflitto solo testuale.

### 2.4 Cosa resta fuori (dichiarato)

- **B9** (idee: errori, doppio click, perdita al reload) e la lista idee ferma a 24: `JobsContext.tsx`/`SecondBrain.tsx` sono di `feat/navigazione-errori`. Qui solo la parte server di `n`.
- **Correzione dei 7 reel bloccati** nel DB e la regola negli agenti (`transcriber`/`enrich`) che eviterebbe nuovi casi: non è di questo ramo (Q4).
- **Fusione dei duplicati esistenti** e pulizia di `Medyca Homepage`/`Centro Buonarroti` (0 articoli): proposta, nessun dato toccato.
- **Rianalisi opus→sonnet**: la barra sparisce, il lavoro non si fa (Q5).
- **Toast globale**: il feedback è inline per pannello, niente libreria nuova.
- **Avviso budget nel form prima di aggiungere**: solo dopo l'aggiunta (D8).
- **Cancellazione fisica** di account/blog: non prevista; chi la vuole la fa da Django admin.
- **Cambio orari cron o fuso**: la pagina li legge come sono.

### 2.5 Domande aperte per Giuseppe

- **Q1.** Posso aggiungere **una riga** (`"batch"`) in `pipeline/dag.py` `STAGE_LABELS`, fuori dal mio elenco? Senza, `ops.py` deve tenere una copia della lista e il messaggio del Job resta «batch».
- **Q2.** Duplicati esistenti: dopo il rilascio li rimuovi tu dalla UI (#23, #19 sicuri; #18 pausetiv.com con 1 articolo, #4 e #17 con 0) o vuoi un comando `manage.py` una tantum documentato?
- **Q3.** Stesso dominio, percorso diverso (es. `medyca.it/blog` e `medyca.it/menopausa`): resta permesso in silenzio, o vuoi un avviso non bloccante «c'è già una fonte su questo sito»?
- **Q4.** I 6 reel senza audio con trascrizione «in coda»: ti va bene che restino così e la pagina li chiami «non lavorabili», oppure apri un lavoro separato sugli agenti per marcarli `skipped`?
- **Q5.** La barra «Rianalisi 406/1593» sparisce quando nulla gira. Vuoi davvero rifare con Sonnet le 947 analisi fatte da Opus? Se no, la rianalisi è finita e basta.
- **Q6.** Ri-aggiungere una fonte rimossa scegliendo un `owner_type` diverso da quello originale: rifiuto con messaggio («questa fonte era registrata come Competitor: ripristinala dal filtro Rimossi») o lascio che il ripristino mantenga quello vecchio e lo dica?
- **Q7.** Un account rimosso tiene i reel nell'analisi; un blog rimosso toglie gli articoli. Confermi di tenere questa differenza?
- **Q8.** «Inattivo» → «In pausa» nelle etichette: ok per il cliente?

## 3. Sviluppo           (sviluppatore)

Ramo `feat/fonti-stato-affidabili`, un commit. Disegno seguito per intero (D1-D10) con le risposte del Registro (Q1 sì, Q6 rifiuto, Q8 «In pausa»).

**Cosa ho fatto**
- **D1/D2/D8 Rimuovi vero e URL/username puliti.** Colonna `removed_at` su `TrackedAccount` e `BlogSource` (migrazione `0023_removed_at`, due colonne nullable, NON applicata a produzione). `DELETE` = `removed_at` + `is_active=false` (blog: anche documenti nascosti). Lista di default senza rimossi, `?removed=1` solo rimossi, `POST …/restore/`. Riaggiungere un rimosso lo ripristina (200, `restored: true`); con `owner_type` diverso 400 in italiano (Q6). Un blog rimesso `is_active=true` riattiva i documenti (B4). URL blog: normalizzato e confrontato con le 8 varianti (http/https x www x barra) invece dello `UniqueValidator` che causava il 500; stesso host con percorso diverso resta permesso (Q3). Username: link/@/maiuscole puliti, regex, messaggio italiano; `collection_paused_until` nella risposta se il budget Apify è finito. Codice comune nel mixin `_RemovableMixin` in `views.py`.
- **D3/D4 feedback e lista completa.** In `manage/parts.tsx`: `apiErrorMessage`, `useNotice`/`Notice`, `PanelError`; tap target `min-h-10`. Tutte le mutation dei pannelli Account, Blog e Temi hanno messaggio ok/errore; lista fallita = `PanelError` con «Riprova». `fetchAllPages` segue `next` (account 26/26). Filtro «Rimossi» e «Ripristina». «Inattivo» -> «In pausa».
- **D5 coda.** `queue_eta.py`: raggiungibilità per stadio con gli stessi filtri degli agenti; nuovo `blocked` (totale, per stadio, `blocked_reasons`); `remaining` esclude i bloccati. UI: «N reel non lavorabili».
- **D6 Stato.** `ops.py` importa stadi ed etichette da `pipeline.dag` (aggiunta `"batch"` in `dag.STAGE_LABELS`, Q1): una run = una barra. `activity()` riconosce `run_job --job N` leggendo il `Job`; `JOB_KIND_LABELS` e `kind_label`; `reanalysis()` solo se un processo `reprocess` gira (Q5); `schedules()` in italiano dal comando; `last_pipeline_job` mostrato sotto il bottone; tabella account senza rimossi e con Medyca/Competitor; `Status.tsx` con stato errore (primo caricamento) e avviso «dati delle HH:MM» (dopo).
- **D7** `_human_error` in `blogscrape_agent.py` (3 punti + il dettaglio del job; il repr resta nel log).
- **D9** `validate_label` (iexact, spazi), `perform_create` atomico con 503 italiano; la risposta 201 porta i conteggi per il messaggio «N contenuti trovati».
- **D10** `_idea_count` (`ParseError` 400) per `plan`/`generate`.
- **Documentazione nello stesso commit:** `01-data-model.md` (voci tabella; il diagramma ER mostra solo relazioni, nessuna riga cambia), `02-pipeline.md` (bloccati + nuova sezione «What the status page reads»), `05-rest-api.md`, `06-frontend.md`, pagina `Documentazione` in app (`docs.outputs`, `docs.limits` x3), docstring di `ops.py`, `queue_eta.py`, `blogscrape_agent.py`, commento in `dag.py`. Drawio non toccato (nessun passaggio aggiunto o tolto).

**Scelte da sapere**
- `fetchAccounts`/`fetchBlogSources` restano SENZA parametri e il «Rimossi» ha funzioni separate (`fetchRemovedAccounts`, `fetchRemovedBlogSources`): `queryFn: fetchAccounts` riceve il contesto di react-query e un flag `removed` sarebbe risultato sempre vero (la `FilterBar` lo usa così).
- Errori di dominio del mixin con `ParseError` (400, `detail` stringa), non `ValidationError({"detail": …})` che darebbe una lista.
- `restore/` di un blog NON azzera `consecutive_failures` (lo fa solo `reactivate/`, come da disegno); `reactivate/` però toglie anche `removed_at`.
- `reanalysis(running=None)` accetta l'elenco già calcolato da `snapshot()` per non leggere due volte la tabella dei processi.

**Cosa è rimasto fuori (dichiarato nel disegno 2.4)**
- B9 (idee: errori, doppio click, persi al reload, lista idee a 24): `JobsContext.tsx`/`SecondBrain.tsx` sono di `feat/navigazione-errori`. Qui solo la parte server di `n`.
- I 7 reel bloccati non sono stati toccati nel DB (Q4); duplicati blog e pulizia #23/#19/#18/#4/#17: li rimuove Giuseppe dalla UI dopo il rilascio (Q2). Nessun dato di produzione toccato, migrazione non applicata.
- Nessuna fusione automatica, nessun toast globale, nessuna cancellazione fisica.
- Il messaggio inglese «Enter a valid URL.» del campo URL di DRF (URL del tutto malformato) non è tradotto lato server: il frontend lo intercetta prima (`sources.urlInvalid`).
- Non ho provato la UI nel browser (nessun servizio riavviato, `dist` non servito): verifica visiva su mobile e desktop da fare al collaudo, dopo `migrate` e rebuild.

**Comandi eseguiti (esito reale)**
- Venv e `.env` presi dal checkout principale (il worktree non ne ha); DB di test creato da Django (`test_…`), nessuna scrittura su quello di produzione.
- `manage.py makemigrations core -n removed_at` -> `0023_removed_at.py` (due AddField). `makemigrations --check --dry-run` -> «No changes detected».
- `manage.py test core.tests.test_sources_and_status --noinput` -> prima 1 fallimento (il mio test non sapeva che una migrazione semina già una fonte blog), corretto il test.
- `manage.py test core --noinput` -> **Ran 75 tests, OK** (26 nuovi, `embed_topic`/`recompute_matches`/`apify_budget.spend` mockati).
- `npm run build` in `FEC` (node_modules collegato temporaneamente dal checkout principale, poi scollegato) -> tsc + vite **built in 14.11s**, nessun errore di tipo.
- Prima del merge servono: `manage.py migrate` (0023) e `npm run build` + riavvio backend, da fare al rilascio.

**Secondo giro** (dopo revisione e collaudo, un secondo commit sul ramo)
- `serializers.py`: un PATCH che porta `username` o `index_url` su una riga rimossa ora dà 400 «Questa fonte esiste già tra le rimosse: ripristinala dal filtro «Rimossi».» (prima 500 per il vincolo UNIQUE). 2 test nuovi (account e blog).
- `mcp_bridge/server.py` `fonti_blog`: solo `removed_at__isnull=True` (nient'altro toccato); `04-mcp-connector.md` aggiornato; 1 test nuovo in `test_mcp_tools.py`.
- Mobile: `TableFrame` ha l'opzione `stacked` (usata da account e blog): sotto 768 px ogni riga e' una scheda (prima cella in alto, le altre con didascalia `data-label`, azioni in fondo), niente scroll laterale. La tabella dei caricamenti NON e' convertita (e' del ramo upload). Verificato solo che il CSS generato contiene le regole; **non provato nel browser a 380px**: da guardare al collaudo.
- `queue_eta.py`: docstring di `snapshot()` riportata sotto gli 80 caratteri.
- Data del budget: `formatResumeDate` (`lib/utils.ts`) la scrive in Europe/Rome, «27 novembre»; testi «La raccolta riparte il 27 novembre» in avviso account, barra budget e tetto raggiunto. Coerente con la documentazione (ciclo 27 ago -> 26 set: ultimo giorno il 26, si riparte il 27). Aggiornati `05-rest-api.md` e `06-frontend.md`.
- Esiti: `manage.py test core --noinput` -> **Ran 78 tests, OK** (75 + 3 nuovi); `npm run build` -> tsc + vite **built in 16.08s**. Symlink a `.env` e `node_modules` tolti. Produzione non toccata, nessun push.

## 4. Revisione          (revisore)

**Verdetto: PASSA** (nessun rilievo bloccante). Letti il file di lavoro e `git diff origin/main...HEAD` (un commit, nessun commit su main).

Invarianti: `owner_type` resta binario; il ripristino con `owner_type` diverso e' rifiutato (serializers.py `validate`, account e blog); il ripristino di un blog riattiva solo i documenti dello stesso blog (stesso owner). `failed` mai toccato (queue_eta conta `blocked` a parte, non cambia stati). Nessuna credenziale, nessun segreto nel diff. Migrazione 0023: due `AddField` nullable, nessun dato; `makemigrations --check` pulito; il DB reale e' a 0022 (33 fonti): sicura. 8 varianti URL (http/https x www x barra) corrette. Filtri `queue_eta` uguali a transcriber_agent.py:108-109 e enrich_agent.py:307,330. `ops.py` importa solo `STAGE_NAMES/STAGE_LABELS` da `pipeline.dag` (import leggero). Creazione tema atomica. Documentazione aggiornata (01, 02, 05, 06, pagina Documentazione); drawio non serve.
Non verificato: i test nuovi non si sono potuti eseguire (il worktree non ha le credenziali DB).

Rilievi non bloccanti, per gravita':
1. `serializers.py` (`validate_index_url`, `validate_username`): su PATCH/PUT che cambia URL o username in uno gia' usato da una riga *rimossa*, `restorable` viene impostato ma ignorato dall'update; il salvataggio viola `unique` e rispondera' 500 (il `UniqueValidator` e' stato tolto). Il create e' coperto, l'update no. Poco probabile dalla UI.
2. `mcp_bridge/server.py:487-504` (`fonti_blog`): elenca anche le fonti rimosse, con `attiva: false`, indistinguibili da quelle in pausa. Il cliente le rivede in Claude dopo averle tolte. Filtrare `removed_at__isnull=True` (e aggiornare `04-mcp-connector.md`).
3. `queue_eta.py` docstring di `snapshot()`: riga troppo lunga dopo la modifica (solo forma).
## 5. Collaudo           (collaudatore)

**Verdetto: PASSA** (con 3 osservazioni minori, nessuna blocca).

**Comandi eseguiti (worktree, venv e .env del checkout principale; DB di test creato da Django)**
- `makemigrations --check --dry-run` -> `No changes detected`
- `manage.py check` -> `System check identified no issues (0 silenced).`
- `manage.py test core --noinput` -> `Ran 75 tests in 9.733s` / `OK`
- `npm run build` in FEC (node_modules via symlink temporaneo, tolto) -> `tsc -b` + vite: `built in 18.68s`, nessun errore di tipo.

**Prova dal vivo (ramo, mai produzione)**
- Backend del ramo su 127.0.0.1:8110 contro un DB temporaneo `collaudo_fonti`, copia (pg_dump, sola lettura) di quello vero, con `migrate` (0023) applicata solo alla copia. Frontend `vite preview` del ramo su 127.0.0.1:5199 con proxy verso 8110. Browser: Chromium headless (Playwright), 380px e 1280px. Il server :9093 non e stato toccato: nessun POST, nessun riavvio. Dopo il collaudo copia, server e symlink eliminati; produzione verificata: `0023` non applicata, 26 account.
- Lista account: `GET /accounts/` (pagina da 24) -> count 28 (26 + 2 creati), 24 nel primo blocco; la UI mostra «28 di 28» e le 3 righe «In pausa» (menopausa_doc, faceboost, faceboost_). La UI chiede `page_size=100`: il ciclo su `next` non e stato esercitato dalla UI (una sola pagina).
- Account: `Collaudo.Test` -> 201, salvato `collaudo.test`; di nuovo -> 400 `Questo account è già monitorato.`; URL `https://www.instagram.com/Collaudo.Due/` -> 201 `collaudo.due`; `a b!!` -> 400 `Scrivi solo lo username, per esempio medyca.menopausa.`; la 201 contiene `collection_paused_until: 2026-11-26T23:59:59.999Z`.
- Rimuovi/ripristina account: DELETE -> 204; `?removed=1` -> la riga con `removed_at`; riaggiunta con owner `owned` -> 400 `Questo account era registrato come Competitor: ripristinalo dal filtro «Rimossi».`; riaggiunta con owner giusto -> 200 ripristinato; `POST /33/restore/` -> 200.
- Blog: `https://www.lidialamarca.it/diario-della-salute/`, `https://lidialamarca.it/diario-della-salute`, `http://PAUSETIV.com/it/blog/` -> tutti 400 `Questo blog è già tra le fonti: «Lidia La Marca»` / `«Pausetiv»` (nessun 500). Host inesistente -> 400 `Nome host non risolvibile`. Nuovo blog con www e barra finale -> 201, salvato senza barra; variante senza www -> 400; DELETE -> 204; riaggiunta con owner diverso -> 400 italiano; con owner giusto -> ripristino; `restore/` -> 200.
- B4: documenti di Pausetiv messi `is_active=False` a mano nella copia (stato «vecchia rimozione»), poi `PATCH is_active:true` -> `True 39 39` (documenti attivi 0 -> 39).
- Temi: `Collaudo Tema` -> 201; `  collaudo   TEMA ` -> 400 `Questo tema esiste già («Collaudo Tema»).`
- `n="abc"` su `ideas/generate/` e `ideas/plan/` -> 400 `Il numero di idee deve essere un numero intero.`
- `/ops/status/`: `queue` = `remaining: 0, blocked: 7` con ragioni «senza audio da trascrivere» e «trascrizione non riuscita o mancante». `history` con il pipeline.log vero (copiato nella copia): 6 run, una per notte/orario, ognuna con la sequenza `scrape, download, transcribe, batch, enrich, embed, [blogscrape], knowledge, [cluster]` (prima: due run). `reanalysis: null`, `activity: []`, `schedules` in italiano («Aggiornamento completo», 03:30; «Aggiornamento di metà giornata…», 14:15), `last_pipeline_job` presente, tabella account senza rimossi.
- UI mobile 380px / desktop 1280px: nessuno scroll orizzontale della pagina; Stato mostra «7 reel non lavorabili…», «Ultimo aggiornamento (12 set, 20:12)»; bottoni sotto i 36px: nessuno a 380px (a desktop solo i due filtri «Medyca/Competitor» a 28px). Gesti: Rimuovi account -> conferma italiana, avviso verde «Account rimosso. Lo trovi nel filtro «Rimossi».», la riga sparisce; filtro «Rimossi» -> riga con «Ripristina» -> avviso «Ripristinato.»; Aggiungi con `https://instagram.com/Collaudo.Tre/` -> avviso «Account aggiunto. La raccolta dei suoi reel partirà dal 27 nov 2026, quando si rinnova il budget.»; Blog: aggiungere `www.pausetiv.com/it/blog/` -> avviso `⚠ Questo blog è già tra le fonti: «Pausetiv».`
- Stati di errore (richiesta bloccata con 500): `/stato` -> «Non riesco a leggere lo stato della pipeline. Controlla la connessione e riprova.» + «Riprova» (niente skeleton eterno); `/accounts` -> «Non riesco a caricare gli account. Non è vuoto: è un problema di collegamento.» + «Riprova».

**Osservazioni (non bloccanti)**
1. Data del budget: l'API dice `cycle_end 2026-11-26T23:59:59Z`, il disegno prometteva «dal 26 novembre»; la UI scrive «27 nov 2026» (converte in ora locale: 00:59 del 27). E coerente con la realta, ma non con il testo del disegno. Da guardare a occhio.
2. Su 380px la tabella account e larga 1007px in un contenitore di 346px: la colonna «Rimuovi» e fuori schermo e si raggiunge scorrendo di lato. Il layout della tabella non e cambiato dal ramo (preesistente), ma il tap target ora c'e solo dopo lo scroll.
3. Console: 403 dalle foto profilo `cdninstagram.com` (immagini scadute): preesistente, non legato al ramo.

**Non provato**
- `activity()` con una run avviata dalla UI (`run_job`): non ho avviato job reali; coperto solo dai test automatici. `/ops/status/` ha mostrato `activity: []`, corretto perche nulla girava.
- Il ciclo `next` di `fetchAllPages` con piu pagine (la UI chiede page_size 100).
- Scansione blog dopo aggiunta/ripristino (i job in coda sono finiti solo nella copia); il toggle di stato dalla UI per i blog (provato via API); sezione Temi dalla UI (provata via API); tap target di `CustomTopics`.
- Il verde dei test non prova la correttezza di tutto: la rete di test e sottile.
- La prova visiva da occhio umano (colori, spaziature): screenshot fatti ma guardati solo a campione. Giuseppe: dopo `migrate` + build, aprire `/accounts` e `/stato` a 380px.

**Secondo giro** (collaudatore) - **Verdetto: PASSA** (nessun problema bloccante).
- Ambiente: copia temporanea del DB di produzione con `migrate` (0023 solo sulla copia), backend del ramo su 127.0.0.1:8110, `vite preview` del ramo su 5199 (proxy verso 8110), Chromium headless. Nessun POST su :9093; copia, server e symlink eliminati; produzione ancora a `0022_link_media`, :9093 risponde 200.
- (1) Mobile. A 380px `/accounts` (account e Blog): `scrollWidth 380 = clientWidth 380`, tabella 346px in contenitore 346px (nessuno scroll laterale), ogni riga e' una scheda (prima cella in alto, didascalie Proprieta'/Reel/Follower/Stato, azioni in fondo). «Rimuovi» visibile, box 68x40 px; cliccato davvero su account (27 -> 26 bottoni) e su blog (35 -> 34). A 1280px restano tabelle (righe `table-row`).
- (2) PATCH su riga rimossa: account `PATCH {"username":"coll.uno"}` -> `{"username":["Questa fonte esiste già tra le rimosse: ripristinala dal filtro «Rimossi»."]} [400]`; blog `PATCH {"index_url":"https://example.com/blog-a"}` -> stesso messaggio su `index_url` [400], e anche la variante `https://www.example.com/blog-a/` -> 400. PATCH valido (`coll.tre`) -> 200. Nessun `Traceback` nel log del backend.
- (3) Testo: aggiungendo un account dalla UI, avviso «Account aggiunto. La raccolta dei suoi reel riparte il 27 novembre, quando si rinnova il budget.» (380 e 1280px); `/stato` mostra «La raccolta riparte il 27 novembre» (380 e 1280px, nessuno scroll laterale).
- (4) `manage.py test core --noinput` -> `Ran 78 tests in 11.488s` / `OK`. `npm run build` -> `✓ built in 16.16s` (tsc + vite, nessun errore).
- Osservazione (preesistente, non bloccante): a 1280px la tabella account e' larga 1007px in un contenitore di 974px, quindi «Rimuovi» e' tagliato sul bordo destro e si raggiunge scorrendo dentro la tabella; la pagina in se' non scorre. Screenshot letti: account 380/1280, blog 380, stato 380.
- Non provato: la tabella dei caricamenti (fuori ramo), `fonti_blog` MCP (solo test automatico), ciclo `next` con piu' pagine.

## 6. Rilascio           (rilasciatore)
## Registro delle decisioni

- 2026-11-05 (capo, su mandato di Giuseppe: «once it finished trigger everything manually» = approvare e procedere con le scelte raccomandate):
  - Q1: sì, aggiungere `"batch"` in `pipeline/dag.py`.
  - Q2: i duplicati esistenti li rimuove Giuseppe dalla UI dopo il rilascio; nessun comando sui dati.
  - Q3: stesso dominio con percorso diverso: nessun avviso.
  - Q4: i 6 reel senza audio restano «non lavorabili»; nessun lavoro sugli agenti ora.
  - Q5: niente rianalisi Opus→Sonnet; la barra «Rianalisi» sparisce quando nulla gira.
  - Q6: ri-aggiungere una fonte rimossa con `owner_type` diverso viene **rifiutato** con messaggio italiano (invariante owned/competitor).
  - Q7: confermato: account rimosso tiene i reel, blog rimosso toglie gli articoli.
  - Q8: sì, «Inattivo» → «In pausa».

- 2026-11-05 (capo): revisione PASSA, collaudo PASSA (due giri, mobile 380px verificato). Secondo giro sui rilievi (20679aa, 78 test OK). Resta fuori: a 1280px la tabella account è 1007px in 974px (preesistente, «Rimuovi» si raggiunge scorrendo dentro la tabella). stato: pronto.
