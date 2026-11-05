---
id: 2026-11-05-navigazione-errori
titolo: Pagine di consultazione: niente schermi bianchi, liste complete, scope separati
stato: revisione
ramo: feat/navigazione-errori
pr: ""
ticket: ""
---

## 1. Richiesta          (capo)

Parole di Giuseppe: «I'm receiving a lot of complaints from my client, who is saying that these things are not working properly. [...] everything related to uploading links for documentation and stuff like that needs to be done in a better way. It needs to be counterchecked.» Poi, dopo la revisione: «proceed to correct everything».

Il lavoro è diviso in tre rami paralleli, tutti da `main` (062d874):
`feat/upload-link-affidabili`, `feat/fonti-stato-affidabili`, `feat/navigazione-errori`.
Ognuno ha il suo worktree in `/home/giuseppe/projects/medycabrain-wt-<slug>`.
Lavora SOLO nel tuo worktree.

**Confini di questo ramo (per non collidere con gli altri due):** Possiedi: App.tsx, api/* (tranne fetchAccounts), JobsContext.tsx, pages di consultazione (Library, Timeline, Clusters, ClusterDetail, Workspace, Analytics, SecondBrain, KnowledgeBank, Home, ContentDetail, Login), components knowledge/reels/articles/graph/filters/layout/ui/docs, lazyPage, e lato BEC: serializers blog-drafts, ReelViewSet retrieve, analytics.py, paginazione, prestazioni ricerca/cluster/grafo. NON toccare: UploadPanel e i file upload, AccountsPanel/BlogSources/Status/ops.

Modelli: piano con Fable, esecuzione con Sonnet (regola in arrivo con `feat/regola-modelli`).

Malfunzionamenti da correggere (revisione di sola lettura del 2026-11-05; file:riga si riferiscono al checkout di allora, ricontrolla):

## C. Browsing pages / shared frontend
1. /second-brain/blog-drafts/ always 500: missing comma serializers.py:191-192 ("created_at" "llm_model"). No page shows drafts though UI points to them.
2. MCP link opened while logged out -> after login lands on Home (App.tsx:73,82).
3. No error boundary -> white screen on any render error.
4. Errors look like empty lists or endless spinners (ReelDetailDrawer:73, ArticleDetailDrawer:68, BrainMap:33, Library, Clusters, Timeline, Workspace, Analytics, ClusterDetail).
5. Excluded reel can't be restored; 404 on its page (ReelViewSet filters is_active on retrieve).
6. Lists cut silently: articles 100 of 903; Timeline oldest 200 of 1548 (page_size 400 > max 200); clusters capped 60 reels/30 articles.
7. Scope switch keeps filters/ids; /competitor/clusters/123 -> /medyca/clusters/123 shows competitor under Medyca (Sidebar.tsx:23-24) — breaks owned/competitor rule.
8. Jobs: no poll on mount; start* errors uncaught; editorial job shown as "Pipeline".
9. Competitor reference docs labelled "Medyca" (ArticleDetailDrawer.tsx:89), incl. doc 843.
10. "Vai al contenuto" wipes chat; rejects the MCP's own http link format (GoToContent.tsx:17).
11. Stale caches after favourite/exclude/tag (ReelDetailDrawer.tsx:38-41).
12. Format filter shows raw English codes (FilterBar.tsx:58).
13. Login always says "Credenziali non valide" for any error (Login.tsx:22).
14. Slow: reel search 7.5s/keystroke, competitor clusters 5.3s, graph 8.8s; 307 graph nodes overlap.
15. Analytics: 233-bar chart ~7.9k px tall; top content only from last 400 reels.
16. (Suspected) status bar covers chat input/buttons; chat answers >180s -> 504; reel note lost on Esc; dead [n] buttons in articles.


In più dalla lista B: punto 9 (genera idee: errori, doppio click, poll dopo reload) e fetchIdeas paginato. Dalla lista A: punto 10 (job di upload/link nella barra di stato: aggiungi i kind in JobsContext/api/jobs.ts/it.json).

## 2. Disegno            (architetto)

Letto tutto il file di lavoro, `CLAUDE.md`, `.claude/architecture-summary.md`,
`documentation/low-level/05-rest-api.md` e `06-frontend.md`, la skill
`.claude/skills/ui-design/`. Il registro delle decisioni è vuoto; l'unica
decisione precedente che questo lavoro riapre è segnalata al punto 11.
Codice studiato SOLO nel worktree `medycabrain-wt-navigazione-errori`
(ramo `feat/navigazione-errori`, su `main` 062d874). Le misure sono state fatte
sul database vivo (sola lettura, nessuna scrittura).

### 2.1 Vincoli misurati

| Fatto | Numero | Come l'ho accertato |
|---|---|---|
| Nessun error boundary nel frontend | 0 occorrenze | `grep -rn "ErrorBoundary\|componentDidCatch\|getDerivedStateFromError" FEC/src` |
| Pagine/componenti che chiamano `useQuery` ma non guardano mai `isError` | 19 su 21 (solo `ContentDetail` e `CustomTopics` lo fanno) | `grep -c useQuery` + `grep -rln isError` |
| Ricerca reel: `to_tsvector` calcolato al volo su caption + trascrizione, nessun indice GIN | 3.0–3.2 s per la query SQL pura; **6.6 s** nel percorso della vista (conteggio della paginazione + pagina = due passaggi) | `manage.py shell`, query identica a `ReelViewSet.get_queryset`; `pg_indexes` su `reels`/`transcripts`: solo btree |
| Dati: reel attivi 1618 (70 Medyca, 1548 competitor), trascrizioni 1473 (13 MB), articoli attivi 2049 (in tema: 903 competitor, 20 Medyca) | — | `manage.py shell`, `count()` |
| Lista cluster competitor | 307 cluster, **1230 query SQL**, 3.2 s (4 query per cluster nel `ClusterSerializer`) | `connection.queries` con `DEBUG=True` |
| Grafo `/second-brain/graph/` | 1681 nodi, 2186 archi, **1221 query**, 8.9 s; a riposo la mappa disegna 3 hub + 11 + 307 temi + 254 opportunità sullo stesso arco | idem; `layout.ts` mette fino a 307 figli su un arco di raggio ~756 px, quindi ~8 px l'uno |
| `cluster_performance('competitor')` (Analytics) | 233 righe, 310 query, 2.6 s, chiamata **due volte** per pagina (anche dentro `overview`) → grafico alto 233×34 = 7922 px | idem; `Analytics.tsx:92` |
| `top_content` su tutti i 1548 reel competitor invece dei primi 400 | 0.53 s | cronometrato nella shell: togliere il tetto costa nulla |
| Cluster competitor più grandi del tetto della pagina | 3 cluster con più di 60 reel (max 146), 3 con più di 30 articoli (max 60); lato Medyca nessuno | `annotate(Count(...))` |
| Documento 843 | `owner_type=competitor`, **senza `source`**, quindi il drawer mostra «Medyca» per il fallback `doc.source?.name || "Medyca"`; sono 14 articoli competitor senza fonte | `KnowledgeDocument.objects.get(id=843)` |
| Link MCP | `server.py:94` emette `{BRAIN_BASE_URL}/content/{kind}/{pk}`; `parseRef` in `GoToContent.tsx:17` esige `kind … : id` e lo rifiuta | lettura di entrambi i file |
| Bozze blog | 1 riga in DB; `fetchBlogDrafts` esiste in `api/secondBrain.ts` ma **nessun componente la usa**; le chiavi `blog.readAll/collapse/copy` in `it.json` sono orfane | `grep -rn fetchBlogDrafts\|BlogDraft FEC/src --include=*.tsx` → 0 |
| Perché lo smoke test non ha visto la virgola mancante | `BlogDraftSerializer` costruisce i campi solo quando serializza una riga; in CI la tabella è vuota | lettura `test_endpoints_smoke.py` + DRF |
| Job kinds già in uso nel DB ma non tradotti | `blogsource_discover`, `link_transcribe`, `upload_transcribe`, `editorial` → in barra di stato appaiono tutti come «Pipeline» (`StatusBar.tsx:36` fallback) | `Job.objects.values_list('kind')` + `it.json` sezione `jobs` |
| Timeout | nginx `location /api/` 180 s; frontend `askKnowledge` 300 s; gunicorn 300 s → una risposta tra 180 e 300 s diventa 504 | `/etc/nginx/sites-enabled/medycabrain-port:62`, `deploy/nginx-medycabrain.conf`, `api/knowledge.ts:97`, unit systemd |
| Paginazione | default 24, `max_page_size` 200: `Timeline` chiede 400 e riceve i **200 più vecchi** (`ordering: "posted_at"`); `fetchKnowledgeDocs` chiede 100 | `core/pagination.py`, `Timeline.tsx:24`, `api/knowledge.ts:63` |
| Idee | 21 non scartate oggi (sotto il 24 della pagina): la lista non è ancora tagliata ma lo sarà | `ContentIdea.objects.exclude(status='dismissed').count()` |

**Non misurato (stima):** il guadagno dell'indice GIN sulla ricerca. Ho provato a
crearlo in una transazione poi annullata per cronometrarlo, ma il sistema dei
permessi ha bloccato il comando (modifica di risorsa condivisa). Su 13 MB di
testo mi aspetto da 3 s a decine di millisecondi: lo sviluppatore deve
confermarlo con `EXPLAIN ANALYZE` prima di chiudere.

### 2.2 Fondamenta condivise (si costruiscono una volta, si usano ovunque)

Senza queste, la stessa correzione andrebbe ripetuta in dieci pagine.

- **A. `components/ui/ErrorBoundary.tsx`** (nuovo, l'unico componente a classe
  del progetto: React non offre altro modo). Due livelli: uno attorno a tutta
  l'app in `main.tsx` (ultima rete: «La piattaforma ha avuto un problema» +
  «Ricarica»), uno attorno a `<main>` in `Shell` (`App.tsx`) con `key` sul
  percorso, così un errore resta nella pagina che l'ha causato: menu laterale
  e barra di stato restano vivi, il testo dice «Questa pagina ha avuto un
  problema» con «Riprova» (azzera lo stato) e «Torna alla Home». Testo con icona
  e parole, mai solo colore (il rosso del brand è anche il rosso dell'errore,
  regola della skill).
- **B. `ErrorState` in `components/ui/primitives.tsx`** (nuovo, accanto a
  `EmptyState`): icona + frase chiara + pulsante «Riprova» (`onRetry`,
  `loading`) + eventuale azione secondaria. È la versione generica dei tre
  stati che `ContentDetail.tsx` già fa bene (caricamento / non trovato /
  errore con Riprova): quel pattern si estende, non si reinventa. Chiavi
  `common.loadError` («Non riesco a caricare questi dati adesso. Riprova tra
  poco.»), `common.retry`, `common.notFound`.
  Regola d'uso in ogni pagina: `isLoading → Skeleton`, `isError → ErrorState`,
  `vuoto → EmptyState`, altrimenti dati. Mai più «lista vuota» per un errore.
- **C. `components/ui/LoadMore.tsx`** (nuovo): riga «n / totale» + «Carica
  altri» — estratta dalle righe 146-159 di `Library.tsx`, dove esiste già.
  Serve a reel e articoli in Libreria, ai reel e articoli del cluster, alla
  Timeline, al Workspace.
- **D. `lib/queryKeys.ts`** (nuovo): le chiavi react-query come costanti e
  una funzione `invalidateReelViews(qc, reelId)` che invalida **tutte** le
  viste che mostrano reel (`reel`, `reels`, `workspace`, `timeline`,
  `cluster-reels`, `topic-matches`, `tags`, `stats`, `an-top`, `an-overview`).
  Oggi `ReelDetailDrawer.tsx:38-41` ne invalida due.
- **E. Rimontaggio per scope in `App.tsx`**: un piccolo wrapper `Scoped` che
  legge `:scope` e rende i figli con `key={scope}`. React Router tiene montata
  la stessa pagina quando cambia solo il parametro, quindi oggi filtri, mese
  selezionato e drawer aperto **sopravvivono al cambio Medyca↔Competitor**.
- **F. `retry` globale in `main.tsx`**: oggi `retry: 1` ritenta anche i 404;
  ritentare solo errori di rete/5xx. Una riga, vale per tutte le query.
- **G. `fetchAllPages` in `api/client.ts`**: segue `next` della paginazione
  (tetto 10 pagine). Per liste piatte che l'interfaccia tratta per intero
  (idee, bozze).

### 2.3 Correzioni, in ordine di impatto sul cliente

**1. CRITICO — scope mescolato (punto 7).** Invariante del progetto.
*Causa verificata:* `Sidebar.tsx:23-24` cambia solo il primo segmento
dell'URL e tiene il resto: `/competitor/clusters/123` → `/medyca/clusters/123`,
e `ClusterViewSet.retrieve` serve qualunque id senza guardare lo scope. In più
la pagina non si rimonta (fondamento E), quindi il filtro «cluster» o «account»
di Libreria resta impostato su un id dell'altra parte.
*Correzione:* (a) `useScope.set` tiene solo la **sezione** (`library |
analytics | timeline | clusters`), mai l'id: dal dettaglio di un cluster si
torna alla lista dell'altro lato; la query string (`?type=article`) può
restare. (b) Difesa in profondità per link incollati o segnalibri:
`ClusterSerializer` espone `scope` (`"medyca"` se `run.scope == "owned"`,
altrimenti `"competitor"` — così un eventuale terzo valore cade dal lato
competitor, non da quello di Medyca) con `select_related("run")`;
`ClusterDetail.tsx` confronta `cluster.scope` con il parametro di rotta e, se
diversi, fa `Navigate replace` all'URL giusto, mostrando il `ScopeBadge` del
lato reale. (c) Fondamento E azzera i filtri al cambio di lato.
*File:* `Sidebar.tsx`, `App.tsx`, `ClusterDetail.tsx`, `BEC/core/serializers.py`,
`BEC/core/views.py` (`ClusterViewSet.get_queryset`). *Rischi:* nessuna
migrazione; `owner_type` resta binario, il mapping è esplicito.

**2. CRITICO — articolo competitor etichettato «Medyca» (punto 9).**
*Causa verificata:* `ArticleDetailDrawer.tsx:89` fa `doc.source?.name ||
"Medyca"`; 14 articoli competitor non hanno `source` (tra cui il doc 843).
*Correzione:* il badge dice **sempre** di chi è, leggendo `doc.owner_type`
(che è autoritativo, regola dell'architettura): «Medyca» o «Competitor» con i
colori di `ScopeBadge` (blu/ambra), e il nome della fonte come secondo badge
solo se c'è. Stesso controllo su `ArticleCard.tsx` se usa lo stesso fallback.
*File:* `ArticleDetailDrawer.tsx`, `ArticleCard.tsx`. *Rischi:* nessuno
lato dati.

**3. Schermo bianco e errori travestiti da liste vuote o spinner infiniti
(punti 3 e 4).** Fondamenti A, B, F. Pagine da adeguare (ognuna poche righe):
`Library` (2 query), `Timeline`, `Clusters`, `ClusterDetail` (4 query; oggi
`cluster`/`args`/`docs` non hanno nemmeno lo stato di caricamento),
`Workspace`, `Analytics` (una `ErrorState` compatta per scheda, così un
grafico rotto non spegne gli altri), `BrainMap`, `SecondBrain` (coverage e
idee), `StatBar` (resta muto: mostra «—», va bene). I due drawer
(`ReelDetailDrawer:73`, `ArticleDetailDrawer:68`) prendono i tre stati di
`ContentDetail`: caricamento, «non trovato» (404), errore con Riprova; oggi
`isLoading || !reel` gira per sempre su un 404.
*File:* i citati + `primitives.tsx`, `main.tsx`, `App.tsx`, `it.json`.

**4. Liste tagliate in silenzio (punto 6).**
- *Articoli in Libreria:* 100 di 903. `fetchKnowledgeDocs` restituisce la
  pagina intera (`Paginated`), `Library` passa a `useInfiniteQuery` + `LoadMore`
  (page_size 48), come già fa per i reel.
- *Timeline:* oggi mostra i **200 reel più vecchi** e l'istogramma è sbagliato
  da sempre. Niente endpoint nuovo: l'istogramma usa
  `fetchEngagementOverTime(scope)` (`/analytics/?metric=engagement-over-time`,
  già per mese, già per scope e `is_active`; chiave `an-time` condivisa con
  Analytics, zero richieste in più); la griglia usa `fetchReels` con i filtri
  `posted_after`/`posted_before` che `ReelFilter` già offre, `ordering:
  "-posted_at"`, infinita + `LoadMore`. Senza mese selezionato: i più recenti.
- *Cluster:* reel (oggi 60, max reale 146) e articoli (oggi 30, max reale 60)
  diventano query infinite + `LoadMore`, con il totale visibile.
- *Workspace:* idem (preferiti potrebbero superare 60).
- *Idee e bozze:* `fetchIdeas`/`fetchBlogDrafts` usano `fetchAllPages`
  (fondamento G): la pagina le tratta come lista unica con aggiornamenti
  ottimistici, un'infinita qui complicherebbe senza beneficio.
*File:* `api/knowledge.ts`, `api/secondBrain.ts`, `api/client.ts`, `Library`,
`Timeline`, `ClusterDetail`, `Workspace`, `LoadMore.tsx`. *Rischi:* nessuna
modifica backend.

**5. Prestazioni (punto 14) — la correzione più piccola e sicura per ognuna.**
- *Ricerca reel (6.6 s):* **serve una migrazione**, la sola di questo lavoro:
  due indici GIN su espressione, `GinIndex(SearchVector("text",
  config="italian"))` su `Transcript` e `GinIndex(SearchVector("caption",
  config="italian"))` su `Reel` (Django 4.2 li supporta nel `Meta.indexes`,
  niente colonne nuove, niente trigger; ~13 MB, costruzione di pochi secondi).
  E il filtro in `ReelViewSet.get_queryset` passa da **un vettore
  concatenato** (`caption + transcript__text`, che nessun indice può servire) a
  **due condizioni in OR** (`Q(sv_caption=q) | Q(sv_transcript=q)`), ognuna
  sul proprio indice. Verifica obbligatoria con `EXPLAIN ANALYZE` che il piano
  usi gli indici (vedi 2.1, stima non misurata). Piano B se non li usa: una
  colonna `SearchVectorField` su `Transcript` aggiornata dallo stadio
  `transcribe` — più invasiva, solo se serve. Lato frontend
  `placeholderData: keepPreviousData` sulla query dei reel, così scrivendo
  non lampeggiano gli skeleton.
- *Lista cluster (1230 query):* `ClusterViewSet.get_queryset` annota
  `reel_count`, `doc_count`, `has_blog` (`Count(distinct)`, `Exists`), e le
  miniature arrivano con **una** query su `ReelClusterAssignment` per tutti i
  cluster della run, raggruppate in Python prendendone 3 — passate nel
  `context` del serializer come già fa `_current_cluster_labels()`. Da 1230 a
  ~4 query. Nessuna migrazione.
- *Grafo (1221 query, 8.9 s):* stessa cura in `SecondBrainGraphView`: una
  query per i cluster delle due run con il conteggio annotato, una per le
  assegnazioni reel ordinate per `-reel__view_count` (si prendono i primi 5
  per cluster in Python), una per le assegnazioni articolo (primi 3). Da 1221
  a ~8 query. Per i **307 nodi sovrapposti**: `layout.ts` dispone i figli di
  un hub in **anelli concentrici** (24 nel primo, +8 per anello, raggio +90 px)
  invece di un solo arco; la mappa resta deterministica. Nessuna migrazione.
- *Analytics (`cluster_performance` 310 query ×2):* una query sulle
  assegnazioni della run con `view_count`/`like_count`, raggruppata in Python;
  `overview` riusa il risultato. Nessuna migrazione.
*File:* `BEC/core/views.py`, `BEC/core/serializers.py`, `BEC/core/models.py` +
migrazione, `BEC/core/analytics.py`, `FEC/src/components/graph/layout.ts`,
`Library.tsx`. *Rischi:* la migrazione va coordinata con gli altri due rami
(domanda aperta 6); i conteggi annotati devono dare gli stessi numeri di
oggi (test di confronto).

**6. `/second-brain/blog-drafts/` sempre 500 e bozze invisibili (punto 1).**
*Correzione:* la virgola in `serializers.py:191`; lo smoke test crea **una
riga** di `BlogDraft` (e di `ContentIdea`, `StrategyBrief`) prima delle GET,
così il test copre davvero i campi. Poi la pagina: una sezione «Bozze del
blog» in `SecondBrain.tsx` con un nuovo `components/plan/BlogDraftCard.tsx`
(titolo, tema, badge «espansione/bozza», corpo richiudibile reso con
`AnswerBody` senza citazioni, Copia / Tieni / Scarta): riusa `ActionButton` di
`IdeaCard.tsx` (da esportare) e le chiavi `blog.readAll/collapse/copy` già in
`it.json`. `JobsContext` invalida già `blog-drafts` a fine job.
*File:* `BEC/core/serializers.py`, `BEC/core/tests/test_endpoints_smoke.py`,
`SecondBrain.tsx`, `IdeaCard.tsx`, `BlogDraftCard.tsx`, `it.json`.

**7. Barra dei lavori (punto 8, lista B punto 9, lista A punto 10).**
*Cause verificate:* `JobsContext` non chiama mai `poll()` al montaggio (dopo un
reload un lavoro in corso sparisce); i `start*` non catturano errori (rifiuto
non gestito, il pulsante non dice nulla); doppio click prima della risposta
POST = due lavori; i kind nuovi non hanno traduzione.
*Correzione:* `poll()` una volta al montaggio; stato `starting` nel context
(disabilita il pulsante all'istante); `try/catch` nei `start*` che espone
`lastError` → `StatusBar` mostra una riga rossa chiudibile «Non sono riuscito ad
avviare: …»; `api/jobs.ts` allarga l'unione `kind` e `it.json` aggiunge
`jobs.editorial` («Piano editoriale»), `jobs.blogsource_discover`,
`jobs.upload_transcribe`, `jobs.link_transcribe`; a fine job si invalidano
`uploads` (per i due transcribe) e `blog-sources` (per discover) — chiavi lette
nei pannelli degli altri rami, che non tocco (domanda aperta 8). Inoltre
`StatusBar` esce da `fixed bottom-0` e si mette **in flusso** sotto `<main>`
in `Shell`: le pagine si accorciano invece di essere coperte (sistema il
sospetto 16a: oggi copre la riga d'invio della chat).
*File:* `JobsContext.tsx`, `api/jobs.ts`, `StatusBar.tsx`, `App.tsx`, `it.json`.

**8. Reel escluso non ripristinabile (punto 5).**
*Causa verificata:* `ReelViewSet.get_queryset:262` filtra `is_active=True` anche
per `retrieve`, quindi il drawer riceve 404 e il pulsante «Ripristina» non si
vede mai. *Correzione:* il filtro `is_active` si applica solo a `list`
(`retrieve`, `annotation`, `tags` lavorano per id, come già fanno cluster e
documenti); il drawer mostra già il badge «Escluso» e «Ripristina». In
`FilterBar` un chip «Mostra esclusi» (`excluded: true`, parametro che il
backend accetta già) per ritrovarli. Il commento di `ContentDetail.tsx` che
dice «un 404 = contenuto rimosso» va aggiornato: ora un escluso si apre e si
dichiara tale, il 404 resta per id inesistenti.
*File:* `BEC/core/views.py`, `FilterBar.tsx`, `ContentDetail.tsx`, `it.json`.

**9. «Vai al contenuto» cancella la chat e rifiuta il link dell'MCP (punto 10).**
*Correzione:* `parseRef` accetta anche l'URL `…/content/(reel|blog)/<id>`;
`GoToContent` riceve un `onOpen(ref)` e `KnowledgeBank` apre **in loco** il
drawer giusto (`ReelDetailDrawer`/`ArticleDetailDrawer`, già tre stati dopo la
correzione 3) senza navigare: i messaggi restano. La rotta `/content/:kind/:id`
resta per i link esterni dell'MCP. *File:* `GoToContent.tsx`, `KnowledgeBank.tsx`.

**10. Cache stantie dopo preferito/escludi/tag (punto 11).** Fondamento D:
`ReelDetailDrawer` chiama `invalidateReelViews`. *File:* `ReelDetailDrawer.tsx`,
`lib/queryKeys.ts`.

**11. Link MCP da scollegato → dopo il login si finisce in Home (punto 2).**
*Correzione:* in `App.tsx` il `Navigate` verso `/login` porta `state.from`; un
piccolo `AfterLogin` sulla rotta `/login` autenticata torna a `from` (solo
percorsi interni, altrimenti `/`). `Login.tsx` non cambia.
**Attenzione:** `06-frontend.md` registra l'opposto come decisione («no
return-to-content after login, by decision»). La riapro perché il reclamo del
cliente viene da qui; va confermata (domanda aperta 1) e la riga del documento
va riscritta.

**12. Analytics (punto 15).** Grafico cluster: i **primi 20** per peso con
toggle «Mostra tutti (233)» che apre un contenitore scorrevole a altezza
fissa, mai 7922 px. `top_content`: via il tetto `[:400]` (misurato 0.53 s su
tutti i reel). *File:* `Analytics.tsx`, `BEC/core/analytics.py`, `it.json`.

**13. Testi (punti 12 e 13).** `FilterBar.tsx:58`: `t("reel.${f}")` cerca
chiavi che non esistono → usare `formatLabel` di `lib/utils.ts`, che ha già le
etichette italiane. `Login.tsx:22`: distinguere con `isAxiosError` credenziali
sbagliate (400/401/403), server irraggiungibile (nessuna risposta: «Il server
non risponde: controlla la connessione e riprova») e altri errori («Errore del
server (codice N). Riprova tra poco.»). *File:* `FilterBar.tsx`, `Login.tsx`,
`it.json`.

**14. Sospetti (punto 16), verificati nel codice.**
- *Barra di stato copre la chat:* vero (`fixed bottom-0 z-40`); risolto al
  punto 7.
- *Risposte > 180 s → 504:* vero (nginx 180 s < frontend 300 s). Lato frontend:
  su 504/timeout la chat dice «La risposta ha superato il tempo massimo (3
  minuti). Prova una domanda più breve o un ambito più stretto» invece di
  `common.error`. Lato nginx: alzare `/api/v1/knowledge/ask/` a 300 s in
  `deploy/nginx-medycabrain.conf` è una modifica di rilascio (domanda aperta 2).
- *Nota del reel persa con Esc:* vero: `AnnotationPanel` salva `onBlur`, Esc
  smonta il drawer prima del blur. Correzione: salvataggio in uscita
  (`useEffect` cleanup con ref alla nota «sporca») + autosalvataggio dopo 800 ms
  di pausa.
- *Pulsanti `[n]` morti negli articoli:* vero: `AnswerBody.linkCitations`
  trasforma ogni `[n]` del markdown in pulsante anche quando `onCite` manca
  (`ArticleDetailDrawer:148`). Correzione: le citazioni diventano pulsanti
  **solo se** `onCite` è passato; altrimenti il testo resta testo.
*File:* `KnowledgeBank.tsx`, `ReelDetailDrawer.tsx`, `AnswerBody.tsx`, `it.json`.

### 2.4 Documentazione da aggiornare (stesso commit, regola `documentation.md`)

- `documentation/low-level/06-frontend.md`: fondamenti A–G (error boundary,
  `ErrorState`, `LoadMore`, chiavi, rimontaggio per scope), Timeline costruita
  da `engagement-over-time`, sezione «Bozze del blog», `GoToContent` che accetta
  l'URL e apre in loco, chip «Mostra esclusi», **riga sul ritorno dopo il
  login riscritta** (punto 11), barra di stato in flusso.
- `documentation/low-level/05-rest-api.md`: `reels/<id>/` non filtra più
  `is_active`; ricerca su due indici GIN in OR; `clusters` con campo `scope` e
  conteggi annotati; grafo e analytics in blocco; `blog-drafts` con
  `llm_model`.
- `documentation/low-level/01-data-model.md`: i due indici GIN su `Reel.caption`
  e `Transcript.text` (voce tabella; l'ER non cambia).
- `FEC/src/i18n/it.json` → pagina `Documentazione` del cliente: una riga in
  `docs.limits.items` o nel flusso: «Se una pagina non riesce a caricare i dati
  vedi un messaggio chiaro e un pulsante Riprova»; le bozze del blog dove si
  trovano; nella mappa i temi oltre il primo anello stanno negli anelli esterni.
- Commenti in testa ai moduli: `ReelViewSet` (perché due OR e non un vettore
  concatenato), `SecondBrainGraphView` e `ClusterSerializer` (perché in
  blocco), `layout.ts` (anelli).
- `docs/medycabrain-pipeline-cliente.drawio`: **non cambia** (nessuno stadio
  della pipeline tocca questo lavoro). `.claude/architecture-summary.md`: non
  cambia la forma del sistema.

### 2.5 Verifiche attese (per revisore e collaudatore)

- Backend: smoke test con una riga per modello (`BlogDraft`, `ContentIdea`,
  `StrategyBrief`); test `reels/<id>/` su reel `is_active=False` → 200 con
  `is_active: false`; test che `clusters/?scope=` espone `scope` coerente e che
  `reel_count/doc_count/has_blog` annotati coincidano con i valori calcolati
  riga per riga; test che la ricerca con due OR restituisce gli stessi id di
  prima (richiede Postgres: controllare che il job CI non giri su SQLite, dove
  `SearchVector` non esiste). `EXPLAIN ANALYZE` della ricerca con gli indici,
  numeri scritti nel file di lavoro.
- Frontend: `npm run build` (è anche il type check). Collaudo da utente reale,
  mobile 380 px e desktop: staccare il backend e vedere `ErrorState` + Riprova
  su ogni pagina; `/competitor/clusters/<id>` poi switch → lista Medyca;
  `/medyca/clusters/<id competitor>` incollato → redirect; doc 843 → badge
  «Competitor»; Libreria articoli competitor → 903 raggiungibili; Timeline →
  mesi recenti; cluster da 146 reel → tutti caricabili; reel escluso → si apre
  e si ripristina; link MCP incollato in «Vai al contenuto» → drawer, chat
  intatta; reload con un job in corso → barra visibile; `[n]` negli articoli
  non più pulsanti.

### 2.6 Cosa resta fuori (dichiarato)

- Lo stato filtri di Libreria nell'URL (oggi in memoria): al cambio di lato si
  azzera, non si conserva per lato.
- Elenco dedicato dei reel esclusi: solo il chip in Libreria.
- Streaming della chat o rifattorizzazione del tempo di risposta del RAG: qui
  si corregge solo il messaggio e si propone il timeout nginx.
- Riferimenti a temi/cluster in «Vai al contenuto» (limite già documentato).
- Analisi dedicata ai blog in Analytics (limite già documentato).
- Tutto ciò che è degli altri due rami: `UploadPanel`, `AccountsPanel`,
  `BlogSourcesPanel`, `Status`, `components/ops/*`, `fetchAccounts`.
- Nessun cambio a `owner_type`, alla pipeline, all'MCP, ai modelli LLM.

### 2.7 Domande aperte per Giuseppe

1. **Ritorno alla pagina dopo il login** (punto 11) riapre una decisione
   scritta in `06-frontend.md`. Confermi che ora vogliamo tornare al link
   dell'MCP dopo l'accesso?
2. **Timeout nginx** per `/api/v1/knowledge/ask/` a 300 s: lo tocco io in
   `deploy/nginx-medycabrain.conf` in questo ramo, o lo lasciamo al
   rilasciatore / al ramo `fonti-stato-affidabili`? Finché resta 180 s, le
   risposte lunghe falliranno comunque (con un messaggio onesto).
3. **Bozze del blog**: le mostro in una sezione del Second Brain (proposta) o
   dentro la pagina del cluster da cui nascono? Oppure entrambe?
4. **Reel esclusi**: basta il chip «Mostra esclusi» in Libreria, o vuoi una
   pagina/tab dedicata?
5. **Mappa**: anelli concentrici per i 307 temi (proposta, deterministica) o
   mostrare a riposo solo i primi N temi per dimensione con un «mostra tutti»?
6. **Migrazione** degli indici GIN: è l'unica migrazione del lavoro; gli altri
   due rami ne aggiungono? Se sì, chi merge per primo e come numeriamo
   (`0XXX_search_indexes`) per evitare conflitti.
7. **Chiavi di cache degli altri rami** (`uploads`, `blog-sources`): le
   invalido a fine job dai `JobsContext`. Se quei rami rinominano le chiavi,
   l'invalidazione smette in silenzio: confermi i nomi o preferisci che ogni
   pannello si ricarichi da solo?
8. **Cluster `scope` dal serializer**: va bene che un eventuale valore non
   previsto di `run.scope` cada dal lato *competitor*? È la scelta sicura per
   l'invariante, ma la metto per iscritto.

## 3. Sviluppo           (sviluppatore)

Ramo `feat/navigazione-errori`, un commit (`0e1fe31`). Tutto il disegno 2.3 è
implementato; le decisioni del Registro sono seguite (Q1 ritorno dopo login,
Q2 nginx 300 s, Q3 bozze in Second Brain, Q4 solo chip, Q5 anelli, Q7 chiavi
verificate, Q8 scope inatteso = competitor).

**Backend** (`BEC/core/`)
- `serializers.py`: virgola mancante in `BlogDraftSerializer` (+ `llm_model` read-only); `ReelDetailSerializer` espone `is_active` (il test ha mostrato che mancava: il drawer non poteva sapere che il reel era escluso); `ClusterSerializer` con `scope` e conteggi/miniature da annotazioni/contesto.
- `views.py`: `ReelViewSet` filtra `is_active` solo su `list`; ricerca = due sottoquery in OR (`id IN caption` OR `id IN transcript`); `ClusterViewSet` con sottoquery annotate + miniature in batch; `SecondBrainGraphView` in blocco.
- `analytics.py`: `cluster_performance` in una query; `top_content` senza tetto 400.
- `models.py` + `migrations/0023_search_indexes.py`: due `GinIndex(SearchVector(..., config="italian"))`. **Non applicata alla produzione.**
- Test: `test_endpoints_smoke.py` crea una riga di `BlogDraft`/`ContentIdea`/`StrategyBrief`; nuovo `test_navigation.py` (reel escluso 200/lista/404/restore, ricerca stessi id e senza duplicati, scope del cluster incl. valore strano, conteggi annotati = conteggi riga per riga, miniature max 3 senza vuote, costo query costante all'aumentare dei cluster per lista e grafo, grafo, cluster_performance, top_content oltre i 400).
- `deploy/nginx-medycabrain.conf`: `location = /api/v1/knowledge/ask/` a 300 s. Il file live lo copia il rilasciatore (+ `nginx -t` e reload).

**Frontend** (`FEC/src/`)
- Nuovi: `ui/ErrorBoundary.tsx`, `ErrorState` (in `primitives.tsx`), `ui/LoadMore.tsx`, `lib/queryKeys.ts`, `plan/BlogDraftCard.tsx`, `fetchAllPages`/`errorStatus` in `api/client.ts`.
- `main.tsx` (boundary + retry solo rete/5xx), `App.tsx` (boundary di pagina con `key`, `Scoped`, `from` dopo login, barra in flusso), `Sidebar` (tiene solo la sezione).
- Pagine: Library (articoli e reel infiniti, keepPreviousData), Timeline (istogramma da `an-time`, griglia per mese), Clusters, ClusterDetail (redirect per scope, reel/articoli infiniti, 4 stati), Workspace, Analytics (errore per scheda, primi 20 + «Mostra tutti» in box scorrevole), BrainMap, SecondBrain (errori, sezione bozze), Login (3 messaggi), KnowledgeBank (drawer in loco, messaggio 504), ContentDetail (solo commento).
- Componenti: drawer reel/articolo (tre stati, invalidazione completa, nota con autosalvataggio 800 ms + salvataggio in uscita, badge da `owner_type`), `ArticleCard`, `FilterBar` (etichette italiane + chip «Mostra esclusi»), `GoToContent` (accetta il link MCP, `onOpen`), `AnswerBody` (`[n]` pulsante solo con `onCite`), `StatusBar` (in flusso, `floating` per la Home, riga errore), `layout.ts` (anelli), `JobsContext`/`api/jobs.ts` (poll al mount, `starting`, `lastError`, kind nuovi, invalidazione `uploads`/`blog-sources`/`knowledge-docs`).
- `it.json`: chiavi nuove + pagina Documentazione (limiti, bozze, link MCP, ritorno dopo login).
- Documentazione: `01-data-model.md`, `05-rest-api.md`, `06-frontend.md` (inclusa la riga «no return-to-content» riscritta e segnata come decisione ribaltata). Drawio e architecture-summary non cambiano (nessuno stadio toccato).

**Misure (EXPLAIN ANALYZE).** Non potendo creare gli indici in produzione ho copiato `reels(id, caption, is_active)` e `transcripts(reel_id, text)` (1618 e 1473 righe, sola lettura da prod) in un database di prova (poi eliminato) e ho confrontato:
- vista di prima (left join + `to_tsvector` al volo, senza indici): **1460 ms**;
- stessa OR dopo il join, **con** gli indici: **1432 ms** (non li usa: la OR attraversa due tabelle) — per questo il disegno «due OR» non bastava;
- due sottoquery `id IN (...) OR id IN (...)` con gli indici (espressione identica a quella che genera Django, `COALESCE` incluso): **4.6–5.1 ms**, due `Bitmap Index Scan`; con parola rara (`tibolone`) 4.1 ms.
Il disegno 2.3 punto 5 («due condizioni in OR sul join») è stato quindi cambiato in due sottoquery; è l'unica deviazione dal disegno. La ricerca parte da 940 risultati per «menopausa»: il costo ora è dominato dalla paginazione, non dal testo.
Query contate nei test: lista cluster e grafo hanno costo costante al crescere dei cluster (assert nei test); i numeri 1230/1221/310 → ~4/~8/2 sono quelli attesi dal disegno, non rimisurati sul DB vivo (non ho toccato i servizi).

**Comandi eseguiti**
- `manage.py test core --noinput` (DB di test separato `test_medycabrain_nav`, perché `test_medycabrain` esisteva già, probabilmente di un altro ramo): **72 test OK** (test nuovi in `test_navigation.py`; `AnalyticsTests` eredita i test di `ClusterScopeTests` per riusare i dati, quindi quelli girano due volte).
- `manage.py makemigrations --check --dry-run`: nessuna deriva. `manage.py check`: nessun problema.
- `npm run build` in `FEC` (usa `node_modules` della copia principale tramite link temporaneo, rimosso prima del commit): `tsc -b` e `vite build` OK.
- `makemigrations core -n search_indexes` per generare la 0023. **Mai eseguito `migrate`**, nessun servizio riavviato, nessun push.

**Rimasto fuori / da sapere**
- **Collaudo da utente reale non fatto da me**: nessun gesto sulla UI viva (il frontend live non è stato ricostruito né il backend riavviato). Da fare nel collaudo: mobile 380 px e desktop, backend staccato → `ErrorState`, switch di scope dal dettaglio, link incollato col lato sbagliato, doc 843, 903 articoli raggiungibili, cluster da 146 reel, reel escluso (chip → drawer → Ripristina), link MCP in «Vai al contenuto» con chat intatta, reload con job in corso, `[n]` non più pulsanti, anelli della mappa a occhio (non verificati visivamente: solo la matematica).
- **Migrazioni**: la 0023 dipende da `0022_link_media`. Gli altri due rami aggiungono la loro dalla stessa base: chi arriva dopo deve fare `makemigrations --merge` (Q6). Il rilascio applica 0023 (creazione indice su ~13 MB: pochi secondi, blocca le scritture su `reels`/`transcripts` per quel tempo).
- **nginx**: il file del repo è cambiato, quello live (`/etc/nginx/sites-enabled/medycabrain-port`) no.
- `generateIdeas` (POST sincrono di 300 s in `api/secondBrain.ts`) è codice morto che nessuna pagina chiama; non toccato. Il «genera idee» di fatto passa da `startIdeation`/`startPlan`, ora protetti.
- Non fatto: `StatBar` resta muto su errore (come da disegno); `FilterBar` e `CustomTopics` non hanno stato di errore proprio (i filtri restano vuoti, `CustomTopics` è nell'area di Clusters ma non è stato toccato); la Home mostra «–» se le statistiche falliscono.
- Non fatto: stato filtri Libreria nell'URL, pagina dedicata agli esclusi (fuori per decisione).
- Il polling dei job alla mount mostra solo i job ancora attivi; uno finito mentre la pagina era chiusa non compare.
- Rischio noto: l'invalidazione a fine job dipende dai nomi `uploads` e `blog-sources` letti nel codice di oggi; se gli altri rami li rinominano, smette in silenzio.

### Secondo giro (sviluppatore)

Dopo revisione e collaudo, tre correzioni. Misure su una copia temporanea del DB di produzione (`pg_dump` in `nav2_copy`, 0023 applicata solo lì, poi eliminata). Produzione non toccata, niente push.

1. **Ricerca reel con più parole** (`ReelViewSet.get_queryset`). Ora, per ogni parola, `id IN (didascalia) OR id IN (trascrizione)`, e AND tra le parole: stesso significato di prima (ogni parola ovunque tra didascalia e trascrizione) e indici GIN usati. Le parole che la config italiana scarta («di», «per») vengono tolte prima (una query vuota non trova nulla e avrebbe azzerato la ricerca; una ricerca fatta solo di quelle non trova nulla, come prima). Le frasi tra virgolette non erano gestite nemmeno prima (query «plain»): invariato. Test nuovo `test_search_words_may_sit_in_different_fields` (una parola in didascalia, una in trascrizione → trovato; solo una delle due → no; parola vuota in mezzo ignorata). Sulla copia, stessi id della vista vecchia (vettore concatenato): «menopausa» 940, «tibolone dosaggio» 25, «menopausa terapia ormonale» 273. Tempo della sola query degli id: vecchia 3.2–3.4 s → nuova 8–11 ms; `EXPLAIN ANALYZE` 17–23 ms con `Bitmap Index Scan` su `reels_caption_fts_gin` e `transcripts_text_fts_gin`; API 0.04–0.2 s, 5 query. Aggiornato `05-rest-api.md`.
2. **Grafo** (`SecondBrainGraphView.add_world`). `.only()` sulle tre query (cluster: `run`, `label_it`, `description_it`, `centroid`, `size`; assegnazioni reel con reel/account/enrichment; assegnazioni documenti con documento/fonte): niente più embedding, `chunk_vectors`, `raw_response`, `keywords`, `content_*`. Prima: **5.5–6.3 s, 17 query**. Dopo: **0.57–0.9 s, 17 query**, risposta identica (hash MD5 uguale, 1681 nodi, 2186 archi). Primo tentativo senza `run` nell'elenco: 335 query (il campo differito veniva riletto una riga alla volta); annotato in `05-rest-api.md`.
3. **Mappa** (`BrainGraph.tsx`, `it.json`). A riposo le etichette restano su hub e temi; Opportunità e temi del cliente mostrano il nome al passaggio (hover) o al tocco (selezionato). Sotto 640 px non si disegnano gli archi tratteggiati delle opportunità (il nodo ciuffo rosso) e una riga in basso spiega la vista ridotta (`map.hintCompact`); sopra, tutto come prima. **Non verificato a occhio in un browser**: solo `tsc` + build. Da guardare a 380 px e desktop nel collaudo.

Comandi: `manage.py test core --noinput` → 73 test OK; `makemigrations --check --dry-run` → nessuna deriva; `npm run build` OK (link a `node_modules` rimosso). Il DB di prova `nav2_copy` è stato eliminato.

## 4. Revisione          (revisore)

**Verdetto: PASSA** (nessun rilievo bloccante; un rilievo medio da annotare nella documentazione).

Controllato su `origin/main...HEAD` (3 commit, solo sul ramo). Nessun segreto nel diff.

**Invarianti: tutti rispettati**
- `owner_type` resta binario. `ClusterSerializer.get_scope` (serializers.py, `get_scope`) mappa `owned` -> `medyca`, ogni altro valore -> `competitor`. Nessun terzo valore introdotto.
- `ClusterDetail.tsx`: le query di reel, articoli e argomenti hanno `enabled: sameSide`, quindi con link sul lato sbagliato non parte nessuna richiesta di contenuti; poi `Navigate replace` al lato vero. `Sidebar.useScope` tiene solo la sezione. `Scoped` rimonta per scope. Badge articoli letto da `owner_type`.
- Nessun `failed` azzerato; nessuna credenziale di terzi. Documentazione nello stesso commit (01, 05, 06, it.json); drawio non serve (nessuno stadio toccato).
- Redirect dopo login (App.tsx `afterLoginTarget`): accetta solo stringhe che iniziano con `/` e non `//`; `from` viene dallo state di router scritto da `ToLogin`, non dall'URL. Nessun open redirect.
- Reel escluso: `get_queryset` filtra `is_active` solo per `list`. Le azioni non-lista (`retrieve`, `annotation`, `tags`) lavorano per id; `exclude`/`restore` usavano gia `Reel.objects`. Le liste non fanno ricomparire gli esclusi. Nessun'altra azione di ReelViewSet restituisce liste.

**Rilievo medio (non bloccante) - views.py, ricerca reel (`ReelViewSet.get_queryset`, blocco `search`)**
I risultati NON sono identici a prima per le ricerche con piu parole. `SearchQuery` e di tipo "plain" (AND dei termini). Prima il vettore era `caption + transcript` concatenato: «tibolone dosaggio» trovava un reel con «tibolone» nella didascalia e «dosaggio» solo nella trascrizione. Ora serve che tutti i termini stiano nello stesso campo (due sottoquery OR). I test (`test_search_matches_caption_and_transcript_only`) usano una sola parola, quindi non lo vedono, e la frase «stessi id di prima» in lavagna/docs e valida solo per una parola. Con una parola e identico, senza duplicati (Transcript e OneToOne). Il compromesso (1460 ms -> 4.6 ms) e ragionevole e un indice su un vettore concatenato tra due tabelle non e possibile; ma va scritto in `documentation/low-level/05-rest-api.md` (riga `reels`) e, meglio, coperto da un test a due parole che fissi il comportamento voluto.

**Migrazione 0023_search_indexes**: `AddIndex` normale (non CONCURRENTLY). Tabelle reali: `reels` 1618 righe, `transcripts` 1473 righe / 13 MB: creazione di pochi secondi, scritture bloccate solo per quel tempo. Accettabile, niente `atomic=False`. Il rilascio la applichi in finestra tranquilla (la pipeline notturna scrive su queste tabelle). Dipende da `0022_link_media`; gli altri due rami hanno una 0023 (merge noto, non e un rilievo).

**Query in blocco: stessi numeri**
- `cluster_performance`: stessa formula di `normalized_engagement` (`views + LIKE_BLEND*likes` / mediana, `1.0` se mediana <= 0, arrotondata a 3), stessi filtri (`is_active`, cluster della run). Corretta.
- Lista cluster: `reel_count`/`doc_count` come sottoquery `Count` (come prima: contano tutte le assegnazioni, anche reel disattivati), `has_blog` con `Exists`. Le miniature ora sono ordinate per visualizzazioni (prima senza ordine, [:3]): differenza innocua.
- Grafo: `n_reels` = `Count(distinct)` uguale al vecchio `.count()`; top 5 reel per `-view_count` con `is_active`, top 3 articoli (ora ordinati per id, prima senza ordine). `n_reels` usato anche nelle opportunita, che usano la stessa lista restituita da `add_world`. Corretto.
- `top_content` senza tetto 400: piu corretto, costo misurato 0.53 s.

**nginx**: `location = /api/v1/knowledge/ask/` a 300 s, uguale a frontend e gunicorn, stesse intestazioni del blocco generico. Il file live non e cambiato (compito del rilasciatore, `nginx -t` + reload).

**Note minori (non rilievi)**: `generateIdeas` resta codice morto; l'invalidazione a fine job dipende dai nomi `uploads`/`blog-sources` degli altri rami. Il collaudo da utente reale resta da fare (non fatto dallo sviluppatore).

## 5. Collaudo           (collaudatore)

**Verdetto: PASSA** (con tre riserve non bloccanti, in fondo). Collaudo del 2026-11-05 sul ramo `feat/navigazione-errori` (1e2104f).

**Ambiente.** Produzione (:9093, `main`) non toccata: nessuna migrazione, nessun riavvio, nessun POST. Ho clonato il DB (`pg_dump` in `collaudo_nav`, poi eliminato), applicato la 0023 solo sulla copia, avviato gunicorn del ramo su :9193 e servito `FEC/dist` del ramo su :9194 (piccolo server node nello scratchpad, proxy `/api` verso :9193). Utente di prova creato solo nella copia. Browser: Chromium headless (Playwright), desktop 1366x850 e telefono 380x800. `node_modules` linkato e rimosso; DB e processi rimossi.

**Comandi**
```
makemigrations --check --dry-run  -> No changes detected
manage.py check                   -> System check identified no issues (0 silenced).
manage.py test core --noinput     -> Ran 72 tests in 12.191s  OK
npm run build (tsc -b + vite)     -> ✓ built in 19.28s
migrate (solo sulla copia)        -> Applying core.0023_search_indexes... OK
```

**Prova da utente vero (desktop e 380 px, stessi risultati)**
- `/second-brain/blog-drafts/` -> `200 0.15s`, `count:1`; la pagina Second Brain mostra la sezione bozze con la bozza «Espansione: Tutti gli uomini vanno in andropausa…».
- Link `/content/blog/843` da sloggato -> `/login`; dopo il login -> `http://127.0.0.1:9194/content/blog/843`. Il badge in testa al documento dice «Competitor» (ambra) più il tema; fonte «YouTVRS» (nella copia il doc 843 ha una fonte).
- Cambio scope da `/competitor/clusters/21020` -> `/medyca/clusters` (lista, nessun «Proteine personalizzate»). Link incollato `/medyca/clusters/21020` -> redirect a `/competitor/clusters/21020`.
- Libreria articoli competitor: `48 / 903` -> dopo i «Carica altri» `903 / 903`, nessun pulsante rimasto.
- Cluster 21020 (154 reel): `154 / 154` raggiunto con «Carica altri».
- Timeline competitor: «1436 pubblicati · maggio 2021 – novembre 2026», griglia «Tutti (dai più recenti)»; istogramma scorre in orizzontale.
- Reel escluso (id 14): Escludi -> badge «Escluso dal dataset»; reload della pagina -> si apre (non 404) con «Ripristina»; Ripristina -> torna normale. DB: `is_active = t`. Reel inesistente 999999 -> messaggio «non esiste più», non schermo bianco.
- Backend spento (12 pagine, desktop+telefono): Libreria, Timeline, Clusters, ClusterDetail, Workspace, Brain-map, ContentDetail reel/blog -> 1 «Riprova» + «Non riesco a caricare questi dati adesso»; Analytics -> 5 «Riprova» (uno per scheda); Second Brain -> 4. Nessuno spinner (`.animate-spin` = 0), nessun errore JS (`pageerrors: []`). Backend riacceso + clic «Riprova» sulla Libreria -> `24 / 1548`, errore sparito. Eccezioni: `/knowledge-bank` (nessun caricamento all'apertura) e Home (mostra «–», dichiarato).
- Nessun overflow orizzontale a 380 px su 7 pagine (`scrollWidth 380`).

**Tempi (copia del DB, con gli indici 0023)**
| Cosa | Dichiarato prima | Misurato ora |
|---|---|---|
| Ricerca reel «menopausa» (API) | 6.6 s | 0.07–0.09 s, 4 query |
| Ricerca nella UI (digitazione -> risposta) | 7.5 s | 0.5–0.9 s |
| `EXPLAIN ANALYZE` stessa ricerca | 3 s | 203 ms, due Bitmap Index Scan su `transcripts_text_fts_gin` |
| Cluster competitor | 5.3 s, 1230 query | 0.23–0.24 s, 5 query |
| Analytics cluster-performance | 2.6 s, 310 query | 0.32–0.36 s, 4 query |
| Grafo `/second-brain/graph/` | 8.9 s, 1221 query | **5.2–6.4 s, 17 query** |

**Riserve (non bloccanti, da leggere)**
1. **Il grafo resta lento: 5–6 s.** Le query sono scese da 1221 a 17, ma il tempo no. Profilo: 2.64 s su 5.2 s sono `json.decoder.raw_decode` (9722 chiamate), cioè si decodifica una colonna JSON per riga, probabilmente il vettore `embedding` dei documenti caricato dalla query sulle assegnazioni (`views.py` ~1118, `add_world`); quella query da sola 1.3 s. Un `.only()`/`defer()` sulle colonne pesanti dovrebbe bastare. Il disegno prometteva «da 8.9 s a ~8 query»: le query ci sono, il tempo no.
2. **Mappa, controllo visivo (serve un occhio umano).** Aprire `http://81.17.96.27:9093/brain-map` dopo il rilascio (o il mio screenshot non basta): a riposo i 307 temi non si sovrappongono più nell'arco unico, ma in basso le Opportunità sono ancora fitte con etichette sovrapposte e un ventaglio rosso denso di archi. A 380 px la mappa mostra un ciuffo di linee illeggibile. Giudizio di Giuseppe.
3. Le miniature dei reel sono immagini rotte nella mia copia (i file `/media` non sono nel DB clonato): non è un difetto del ramo, ma non ho potuto vedere le miniature vere.

**Non provato**
- Link MCP incollato in «Vai al contenuto» con chat intatta (serve una chat con risposta LLM; non ho chiamato il modello). Coperto solo dal build.
- Reload con un job in corso (barra di stato) e errore di avvio job: non ho avviato job (scriverebbero e userebbero LLM).
- Nota del reel (autosalvataggio/Esc), `[n]` non cliccabili negli articoli, messaggio 504 della chat, badge «Medyca» di un articolo senza fonte (nella copia il doc 843 ha una fonte), etichette formato in `FilterBar`, messaggi di Login (3 casi): non provati a mano.
- Il test `AnalyticsTests` che gira due volte è dichiarato dallo sviluppatore; non verificato. Il timeout nginx a 300 s non è provabile qui (file live non cambiato).
- Un verde dei 72 test non prova che le funzioni siano giuste: la copertura è sottile; i gesti sopra sono la prova vera.
## 6. Rilascio           (rilasciatore)
## Registro delle decisioni

- 2026-11-05 (capo, su mandato di Giuseppe: «once it finished trigger everything manually» = approvare e procedere con le scelte raccomandate):
  - Q1: sì, dopo il login si torna alla pagina richiesta; aggiornare la decisione in 06-frontend.md.
  - Q2: sì, il timeout nginx di `/knowledge/ask/` passa a 300 s in `deploy/nginx-medycabrain.conf` in questo ramo (gli altri due rami non toccano nginx). Il file live lo copia il rilasciatore.
  - Q3: bozze del blog in una sezione del Second Brain.
  - Q4: basta il chip «Mostra esclusi» in Libreria.
  - Q5: anelli concentrici.
  - Q6: anche gli altri due rami aggiungono una migrazione in `core` (unicità `source_url` upload; `removed_at` fonti). Ognuno parte da main. Ordine di merge previsto: fonti → upload → navigazione; chi arriva dopo aggiunge una migrazione di merge (`makemigrations --merge`) con un commit nuovo, mai rebase.
  - Q7: sì, ma verifica nel codice i nomi reali delle chiavi di cache (`uploads`, `blog-sources`) prima di usarli.
  - Q8: sì, uno scope imprevisto cade dal lato competitor.
