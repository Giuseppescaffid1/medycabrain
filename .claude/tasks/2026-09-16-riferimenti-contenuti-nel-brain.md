---
id: 2026-09-16-riferimenti-contenuti-nel-brain
titolo: Dai riferimenti dell'MCP (blog:843, reel:199) si deve poter arrivare al contenuto nel brain
stato: sviluppo
ramo: feat/riferimenti-contenuti
pr: ""
ticket: ""
---

## 1. Richiesta          (capo)

Parole del cliente (riportate da Giuseppe, `/goal` 2026-09-16):

> «L'MCP continua a riferirsi ai contenuti con struttura formato:numero, per
> esempio, `blog 2:843` o `reel 2:199`. Ho modo, dal mio frontend del brain, di
> cercare i contenuti in base a questo numero? Se no non riesco a capire a quali
> contenuti si riferisce. Il mio cliente deve capire di che si sta parlando e
> così non capisce.»

In una riga: **quando l'MCP cita `reel:199` / `blog:843`, il cliente non ha modo,
dal frontend del brain, di risalire a QUALE contenuto sia.** Deve poterlo capire.

### Riproduzione / recon del capo (2026-09-16, verificato)

- **Formato dei riferimenti**: l'MCP costruisce l'id in `_hit`
  (`BEC/mcp_bridge/server.py:75`): `id = f"{h['kind']}:{h['id']}"` → `blog:843`,
  `reel:199`. Ogni hit porta già anche `titolo` e `url` (la fonte:
  instagram/youtube/medyca.it), ma il cliente vede citato l'**id** e non sa
  tradurlo. Il «2» in «blog 2:843» non è nel codice: quasi certamente è il numero
  di citazione che il Claude del cliente antepone (es. «[2] blog:843»). **Da
  confermare in disegno** guardando cosa rende davvero il connettore.
- **Il backend SA già risolvere questi id**:
  - `GET /api/v1/reels/<id>/` (`ReelViewSet`, ReadOnly) → un reel per id.
  - `GET /api/v1/knowledge/documents/<id>/` (`KnowledgeDocumentViewSet`, ReadOnly)
    → un documento/blog per id.
- **Il buco è nel frontend del brain** (`FEC/`): le rotte sono `/:scope/library`,
  `/:scope/timeline`, `/knowledge-bank`, `/second-brain`, `/brain-map`,
  `/:scope/clusters/:id`, ecc. **Non esiste** una rotta di dettaglio del singolo
  contenuto né una ricerca «vai all'id `blog:843`». Quindi il cliente non ha
  proprio il gesto per passare dal riferimento al contenuto.

### Cosa deve ottenere la squadra (obiettivo)

Dal riferimento `kind:id` che l'MCP cita, il cliente deve poter arrivare al
contenuto vero (titolo, testo/trascrizione, fonte, link) **dal frontend del
brain**. Approcci da valutare in disegno (non imposti):
1. una **ricerca/vai-all'id** nel brain che accetta `blog:843` / `reel:199` (o il
   solo numero + tipo) e apre il contenuto, riusando gli endpoint REST che già
   esistono;
2. una **pagina di dettaglio del contenuto** (`/content/:kind/:id` o simile) con
   titolo, fonte, link, testo/trascrizione;
3. rendere i **riferimenti dell'MCP auto-esplicativi/cliccabili** — es. un
   deep-link nel brain (`.../content/blog/843`) accanto all'id — così il cliente
   clicca e vede. Questo tocca il **contratto MCP**, quindi va pesato.

Vincoli: è una **feature visibile al cliente** → skill `ui-design` (token del
brand, mobile-first, stati vuoto/caricamento/errore) e **prova da utente vero su
:9093**. Non violare l'invariante `owner_type` binario né mescolare
Medyca/competitor. Se si tocca l'MCP, aggiornare doc + `eval_mcp`.

## 2. Disegno            (architetto)

In una riga: **aggiungere al brain un gesto "vai al contenuto" che accetta
`blog:843` / `reel:199` e apre la scheda di dettaglio già esistente**, montato su
una rotta `/content/:kind/:id` così lo stesso gesto vale anche come link diretto.
Nessuna modifica al backend, nessuna modifica all'MCP. Riuso puro di componenti
già in casa.

### Vincoli misurati (con il comando che li accerta)

1. **Il formato del riferimento è solo `blog:<id>` / `reel:<id>`.** L'unica
   stringa-id che l'MCP produce è a `server.py:75`
   (`grep -n "kind']}:" BEC/mcp_bridge/server.py` → una sola riga:
   `"id": f"{h['kind']}:{h['id']}"`). Il **«2»** che il cliente vede in
   «blog 2:843» **non nasce da noi**: nessun punto del codice antepone un numero
   all'id (verificato: `grep -rniE "cit" BEC/mcp_bridge/server.py` trova solo
   `citazione` dentro le affermazioni). È il numero di citazione che il Claude del
   cliente mette davanti (`[2] blog:843`). → il parser del campo deve **buttare
   via qualunque numero/prefisso davanti** e tenere `blog:843`.
2. **Il backend risolve già questi id, senza sapere di che "lato" sono.**
   - `sed -n '523,528p' BEC/core/views.py`: `KnowledgeDocumentViewSet` in
     `retrieve` restituisce il queryset filtrato solo per `is_active=True`
     (commento nel codice: «Detail by id stays unrestricted») → `GET
     /api/v1/knowledge/documents/843/` funziona per id, a prescindere da
     scope/on-topic.
   - `sed -n '256,269p' BEC/core/views.py`: `ReelViewSet` in dettaglio filtra
     `is_active=True` → `GET /api/v1/reels/199/` funziona per id.
   - **Conseguenza: non serve toccare né endpoint né serializer.** Prova: oggi
     `Library.tsx` già chiama `fetchReel(id)` e `fetchKnowledgeDoc(id)` e li dà in
     pasto agli stessi drawer che riuserei — quindi restituiscono già abbastanza
     (titolo, testo/trascrizione, fonte, link, affermazioni).
3. **La scheda di dettaglio esiste già ed è usata da 5 pagine.**
   `grep -rn "DetailDrawer" FEC/src` → `ReelDetailDrawer` e `ArticleDetailDrawer`
   sono importati/usati in `Library.tsx`, `ClusterDetail.tsx`, `Timeline.tsx`,
   `Workspace.tsx`, `CustomTopics.tsx`. Si aprono con un id numerico
   (`reelId` / `docId`) e non dipendono dallo scope. **Questo è il ~70% già
   pronto.**
4. **Non esiste oggi nessuna rotta di dettaglio del contenuto né un "vai
   all'id".** `grep -rn "content/" FEC/src` → nessuna rotta; le rotte in
   `App.tsx` sono tutte scoped o strumenti. È esattamente il buco descritto.
5. **Il brain FEC è servito su `81.17.96.27:9093`** (`grep -iE "listen|root"
   deploy/nginx-medycabrain.conf` → `listen 9093`, `root .../FEC/dist`) ed è
   **dietro login** (`App.tsx`: se non autenticato → `/login`). Conta per il
   deep-link (vedi opzione C e domande aperte).

### La soluzione proposta (la più semplice che chiude il buco)

**Opzione (a) "vai all'id" + opzione (b) rotta, uniti; opzione (c) MCP fuori.**
Un campo dove il cliente incolla `blog:843` (o `reel 2:199`, o solo il numero con
un selettore di tipo), che lo porta alla scheda del contenuto vero. La scheda è il
drawer già esistente. Montando il drawer anche su una rotta `/content/:kind/:id`,
lo stesso lavoro serve sia come gesto sia come indirizzo condivisibile — senza
costo aggiuntivo.

### File da toccare e perché

- **`FEC/src/pages/ContentDetail.tsx`** (nuovo, piccolo): legge `:kind` e `:id`
  dalla URL; se `kind=reel` monta `ReelDetailDrawer` con `reelId=id` già aperto,
  se `kind=blog` monta `ArticleDetailDrawer` con `docId=id`; `onClose` →
  `navigate` indietro (o alla Libreria). Gestisce lo stato **non trovato** (id
  rimosso/errato) con un messaggio pulito. È l'unico pezzo di logica nuova.
- **`FEC/src/App.tsx`**: una riga di rotta `/content/:kind/:id` + l'import
  `lazyPage`. È il bersaglio del deep-link e l'atterraggio del gesto.
- **`FEC/src/components/knowledge/GoToContent.tsx`** (nuovo, piccolo): il campo
  "vai al contenuto". Fa il parsing tollerante (`blog:843`, `blog 2:843`,
  `reel:199`, o numero + toggle tipo), poi `navigate(/content/{kind}/{id})`.
  Mostra un errore inline se l'input non è riconoscibile.
- **`FEC/src/pages/KnowledgeBank.tsx`**: ospita `GoToContent` nell'intestazione
  (è la pagina "sui contenuti", il posto mentalmente più vicino). *Posizione da
  confermare — vedi domande aperte.*
- **`FEC/src/i18n/it.json`**: nuovo gruppo `content.*` (etichetta campo,
  placeholder d'esempio con un `blog:` e un `reel:`, stati vuoto/errore/non
  trovato). Tutte le stringhe stanno qui, come da convenzione.
- **`documentation/low-level/06-frontend.md`** + **`FEC/src/pages/Documentation.tsx`**:
  la regola `documentation.md` impone di documentare una feature visibile al
  cliente **nello stesso commit** (pagina/flow lato manutentore + pagina in-app
  lato cliente, in italiano semplice).

### Cosa riuso (percorso + nome esatti)

- `FEC/src/components/reels/ReelDetailDrawer.tsx` → `ReelDetailDrawer({reelId, onClose})`
- `FEC/src/components/articles/ArticleDetailDrawer.tsx` → `ArticleDetailDrawer({docId, onClose})`
- `FEC/src/api/endpoints.ts` → `fetchReel(id)` · `FEC/src/api/knowledge.ts` → `fetchKnowledgeDoc(id)`
  (già chiamati dai drawer stessi via react-query — nessun nuovo client API)
- `FEC/src/components/ui/primitives.tsx` → `fieldCls`, `Button`, `EmptyState`, `Spinner`
- `FEC/src/lib/lazyPage.ts` → `lazyPage`

### Backend e MCP

- **Backend: nessuna modifica.** Gli endpoint `GET /api/v1/reels/<id>/` e
  `GET /api/v1/knowledge/documents/<id>/` e i loro serializer restituiscono già
  quanto basta (prova: la Libreria li usa oggi per gli stessi drawer).
- **MCP: non si tocca** in questo MVP. L'opzione (c) — mettere un link cliccabile
  dentro l'output dell'MCP (`_hit`/`leggi_*`) — **cambia il contratto MCP**, quindi
  obbligherebbe ad aggiornare `documentation/low-level/04-mcp-connector.md` e
  `eval_mcp` nello stesso commit, e **rischia conflitto con la PR #7** (che tocca
  proprio `eval_mcp`, e non è ancora in `main`). Inoltre il deep-link sarebbe
  `http://81.17.96.27:9093/content/{kind}/{id}`: IP nudo e **dietro login**. Due
  motivi per rimandarla. Nota utile: `_hit` **già restituisce `url`** (il link
  originale su instagram/youtube/medyca.it), quindi il Claude del cliente ha già
  un link esterno; quello che manca — e che questo disegno dà — è la **vista dentro
  il brain**, con la nostra analisi. Se in futuro Giuseppe vorrà l'opzione (c), la
  rotta `/content/:kind/:id` è già il bersaglio pronto: si aggiunge un solo campo
  all'output MCP.

### Rischi e invarianti

- **`owner_type` binario / niente mescolanza Medyca–competitor**: il gesto apre
  per id, è cieco allo scope, **non scrive mai** `owner_type` e non mescola i due
  lati; il drawer mostra il contenuto con il suo badge Medyca/competitor già
  esistente. Invariante non sfiorata.
- **I `failed` restano `failed`**: feature di sola lettura, nessuna mutazione di
  stato pipeline.
- **Niente credenziali di terzi**: non coinvolte.
- **Contenuto rimosso/id errato**: un reel escluso (`is_active=False`) fa 404 su
  `GET /reels/<id>/` (il dettaglio filtra `is_active=True`). L'MCP cita solo
  contenuti attivi, ma un riferimento vecchio potrebbe puntare a un id sparito →
  `ContentDetail` **deve** mostrare uno stato "contenuto non trovato (potrebbe
  essere stato rimosso)", non un errore grezzo.
- **Login**: aprendo un deep-link da sloggati, `App.tsx` manda a `/login` e
  perde il bersaglio. Per l'MVP il cliente è già loggato quando usa il brain;
  preservare il path dopo il login è un nice-to-have (vedi domande aperte).

### Prova richiesta allo sviluppatore

Feature visibile al cliente → lo sviluppatore usa la skill **`ui-design`** (token
del brand, mobile-first, stati **vuoto / caricamento / errore/non-trovato**
sempre presenti) e porta la **prova da utente vero su `:9093`**: incollare
`blog:<id>` e `reel:<id>` reali, su **mobile e desktop**, e vedere aprirsi la
scheda giusta; provare anche un id inesistente e vedere lo stato "non trovato".

### Cosa resta fuori (dichiarato)

- Nessuna modifica al contratto MCP (niente link cliccabile nell'output MCP).
- Nessun nuovo endpoint o serializer nel backend.
- Nessuna scheda di dettaglio "nuova" disegnata da zero: si riusa il drawer.
- I riferimenti ai **temi/cluster** (`temi` restituisce un `id` di cluster, spazio
  di id diverso): fuori portata, la feature copre solo `reel:`/`blog:`.
- La ricerca per parola chiave: già coperta da Libreria e Chat sui contenuti;
  qui si fa solo il "vai a un id noto".

### Domande aperte

1. **Dove mettere il campo "vai al contenuto"?** Proposta: intestazione di
   `KnowledgeBank` (la pagina "sui contenuti"). Alternative: un campo globale
   nella Sidebar, o nella Home. Quale preferisci?
2. **Serve il link cliccabile dentro l'MCP (opzione c)?** Consiglio: no per ora
   (cambia il contratto, tocca `eval_mcp`/`04-mcp-connector.md`, rischia conflitto
   con la PR #7, e la URL sarebbe `IP:9093` dietro login). Confermi il rinvio?
3. **Deep-link da sloggati**: va bene per l'MVP richiedere che il cliente sia già
   loggato nel brain, o vuoi che dopo il login si torni al contenuto puntato?
4. **Input**: basta accettare `blog:843`/`reel:199` (con lo strip del numero di
   citazione), o vuoi anche il solo numero + un selettore reel/articolo?

## 3. Sviluppo           (sviluppatore)

### Cosa ho fatto — FASE 1 (solo frontend)

Il gesto "vai al contenuto" nel brain: il cliente incolla un riferimento che
l'MCP ha citato (`blog:843` / `reel:199`) e arriva alla scheda del contenuto
dentro il brain. Nessuna modifica a backend o MCP: riuso puro dei drawer di
dettaglio già usati dalla Libreria e degli endpoint REST che risolvono già per id.

### File toccati

- **`FEC/src/components/knowledge/GoToContent.tsx`** (nuovo) — il campo, montato
  nell'header di KnowledgeBank. `parseRef()` fa il parsing tollerante: tiene la
  parola del tipo e il numero dopo i due punti e butta via qualunque cosa in
  mezzo, perché il Claude del cliente antepone il numero di citazione
  (`[2] blog:843`, `blog 2:843`). Accetta anche `articolo`/`article` come sinonimi
  di `blog`. Input non riconoscibile → errore inline (⚠ + testo, mai solo colore,
  perché il rosso del brand è anche il colore d'errore) e **nessuna** navigazione.
  Input valido → `navigate('/content/{kind}/{id}')`.
- **`FEC/src/pages/ContentDetail.tsx`** (nuovo) — la rotta `/content/:kind/:id`.
  `reel` → `ReelDetailDrawer(reelId)`, `blog` → `ArticleDetailDrawer(docId)`.
  L'unico pezzo di logica nuova: distingue "sto caricando" da "non c'è più".
  Risolve prima il contenuto con la **stessa query key dei drawer** (così non fa
  una seconda richiesta) e monta il drawer solo quando il dato è in cache; se
  l'endpoint fa 404 (id rimosso: il dettaglio filtra `is_active=True`) mostra uno
  stato "contenuto non trovato" pulito con un bottone di ritorno, invece dello
  spinner infinito che darebbe il drawer da solo. `retry: false` per far comparire
  subito il "non trovato". Chiusura → indietro nella storia, con fallback a
  `/knowledge-bank` (dove vive il campo) sui deep-link a freddo.
- **`FEC/src/App.tsx`** — rotta `/content/:kind/:id` con `lazyPage`, dentro le
  rotte autenticate (da sloggato `App.tsx` manda già a `/login`, come per ogni
  rotta; nessun ritorno-al-contenuto dopo il login, per decisione di Giuseppe).
- **`FEC/src/pages/KnowledgeBank.tsx`** — monta `GoToContent` nell'intestazione
  (posizione confermata da Giuseppe). Ho solo aggiunto un livello di colonna
  all'header per ospitare il campo sotto la riga titolo+filtri, senza toccare il
  layout esistente.
- **`FEC/src/i18n/it.json`** — nuovo gruppo `content.*` (etichetta, placeholder con
  un esempio `blog:` e uno `reel:`, stati errore e non-trovato, bottone di ritorno)
  e `docs.goto.*` per la pagina Documentazione in-app.
- **`documentation/low-level/06-frontend.md`** — nuova sezione "From a reference to
  the content" (flow, il perché del 404, il limite: copre solo `reel:`/`blog:`) +
  riga nella tabella delle rotte.
- **`FEC/src/pages/Documentation.tsx`** — nuova sezione client-facing "Aprire un
  contenuto da un riferimento", in italiano semplice.

### Riuso (come da disegno)

`ReelDetailDrawer` (`reelId`), `ArticleDetailDrawer` (`docId`), `fetchReel`,
`fetchKnowledgeDoc`, le primitive `fieldCls`/`Button`/`EmptyState`/`Spinner`,
`lazyPage`, `PageTransition`. Nessun nuovo client API, nessun nuovo endpoint.

### Verifica: `cd FEC && npm run build` (tsc -b + vite) — PASSA

```
> tsc -b && vite build
✓ built in 16.01s
```
(Un solo intoppo di tipi, risolto: la query in ContentDetail restituisce un tipo
unione, tipizzata come `useQuery<unknown, Error>` perché a questa pagina serve solo
sapere se l'id si risolve, il resto lo fa il drawer.)

### Prova da utente vero su :9093 (Playwright headless, loggato via token)

Id reali presi dal DB: **reel 879**, **blog/articolo 896** (id max: reel 1282,
doc 954 → `99999` è sicuramente inesistente). Testato a **desktop 1280px** e
**mobile 380px**:

- `reel:879` → va a `/content/reel/879`, si apre il drawer del reel (thumbnail,
  numeri reali 10.6k views, gancio, riassunto, argomenti, "Apri su Instagram"). ✓
- `blog 2:896` (col numero di citazione davanti) → va a `/content/blog/896`, si
  apre il drawer dell'articolo con titolo "Canale Salute…". Lo strip del numero
  di citazione funziona. ✓
- `blog:99999` (id inesistente) → stato "Questo contenuto non esiste più o
  l'indirizzo non è valido. Potrebbe essere stato rimosso." con bottone di
  ritorno, non un errore grezzo. ✓
- `ciao` (input non valido) → errore inline "⚠ Non riconosco questo riferimento…"
  e resta sulla pagina, nessuna navigazione. ✓
- Mobile 380px: header impilato pulito, campo e bottone a tutta larghezza; il
  gesto `reel:879` apre il drawer. ✓

A livello HTTP ho anche verificato: le rotte SPA `/content/...` servono
`index.html` (200 via nginx try_files), gli endpoint di dettaglio rispondono 200
per 879/896 e **404** per gli id inesistenti (è la condizione su cui poggia lo
stato "non trovato").

### FASE 2 — RIMANDATA AL CAPO (dopo il merge della PR #7)

Questa è **solo la fase 1 (frontend)**. La **fase 2 (MCP)** è **rimandata al capo**
dopo che la PR #7 sarà fusa in `main` (la #7 tocca `eval_mcp` e non è ancora in
main → conflitto di file). La fase 2 comprende, e **non è stata toccata qui**:
- rendere i riferimenti dell'MCP auto-esplicativi: **titolo + fonte leggibili**
  (es. «Metodo Marion Gluck — Medyca») e un **link cliccabile** al contenuto nel
  brain (`/content/{kind}/{id}` — bersaglio già pronto grazie a questa fase);
- `BEC/mcp_bridge/server.py`, `documentation/low-level/04-mcp-connector.md`,
  `BEC/core/management/commands/eval_mcp.py` — **non toccati** per istruzione
  esplicita.

### Cosa resta fuori (oltre alla fase 2)

- Solo `reel:`/`blog:`; i riferimenti a temi/cluster (spazio di id diverso) sono
  fuori portata, come da disegno.
- Nessun ritorno-al-contenuto dopo il login (decisione di Giuseppe: basta essere
  loggati).

## 4. Revisione          (revisore)

## 5. Collaudo           (collaudatore)

## 6. Rilascio           (rilasciatore)

## Registro delle decisioni

- 2026-09-16 — Ramo `feat/riferimenti-contenuti` off `main` (convenzione `feat/`).
  Nota: `main` non ha ancora la PR #7 (fix eval_mcp); file diversi, nessun
  conflitto atteso. (capo)

- 2026-09-16 — Decisioni di Giuseppe sul disegno:
  1. Approvato. Campo "vai al contenuto" nell'**header di KnowledgeBank** (Chat contenuti).
  2. **MCP ora IN scope**: oltre al gesto nel brain, i riferimenti dell'MCP devono
     portare un **link cliccabile** al contenuto nel brain (opzione c, non più rimandata).
  3. Input/riferimenti: Giuseppe vuole che si veda anche un **titolo leggibile** così il
     cliente capisce di che contenuto si tratta, non solo il numero (risposta arrivata
     garbled — DA CONFERMARE con Giuseppe l'esatta interpretazione).
  4. Deep-link da sloggato: **basta essere loggati** (no ritorno-al-contenuto dopo login).
  Conseguenze: cambia il **contratto MCP** → aggiornare `04-mcp-connector.md` + `eval_mcp`
  nello stesso commit; **condivide file con la PR #7** (aperta, non ancora in main) →
  coordinare l'ordine di merge. (capo)

- 2026-09-16 — Chiarimenti: (3) confermato **titolo + fonte leggibili** nei
  riferimenti (es. «Metodo Marion Gluck — Medyca»), non solo il numero, più il
  link cliccabile. (ordine) Giuseppe **fonde la PR #7 per prima**, poi il capo
  ribasa `feat/riferimenti-contenuti` sul main aggiornato e sviluppa tutto pulito. (capo)
