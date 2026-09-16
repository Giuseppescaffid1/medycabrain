---
id: 2026-09-16-mcp-search-affidabile
titolo: La ricerca MCP deve essere affidabile su ogni strumento, interviste comprese
stato: revisione
ramo: feat/mcp
pr: ""
ticket: ""
---

## 1. Richiesta          (capo)

Parole di Giuseppe (dal `/goal`, 2026-09-16):

> «La MCP ancora non fa girare la ricerca "nella mappa", il cliente si è
> lamentato. Non guarda nemmeno le interviste che abbiamo. Usa l'agente
> architetto e tutto il flusso per arrivare al risultato in cui **ogni
> componente della MCP funziona**. Testa tutti i componenti contro un **test di
> base per la MCP** e se è tutto verde allora facciamo la pull request. Apri un
> nuovo ramo `feat/mcp`, disegna la spec del fix, scrivi il fix, rivedilo,
> disegna il test del fix, includi su GitHub un test per la MR che possa essere
> approvata **solo se il test sulla MCP passa**.»

Nota sul ramo: Giuseppe ha scritto `feature/mcp`; uso `feat/mcp` perché è la
convenzione che tutta la squadra e il guard in `.claude/settings.json`
(`git push -u origin feat/:*`) e il ruleset di GitHub si aspettano. Se voleva
davvero `feature/mcp`, si cambia in un minuto.

### Contesto: il fix precedente (PR #5, già in `main`)

Il 2026-09-15 la PR #5 ha tolto il blocco da 30-40s del reranker MCP
(`max_tokens` 1000→2000, `retries=0`). È **fusa in `main`**. Il cliente però si
lamenta ancora: quindi resta un problema, ed è di **latenza/affidabilità**, non
più di blocco totale.

### Riproduzione del capo (2026-09-16, misurata, servizio live `medycabrain-mcp`)

Test grezzo dei 10 strumenti, chiamati diretti sul servizio (curl, `--max-time 90`):

| strumento | http | tempo | esito |
|---|---|---|---|
| panoramica | 200 | 0.4s | ok |
| cerca_reel | 200 | **11.1s** | ok ma lento |
| cerca_articoli | 200 | **14.2s** | ok ma lento |
| cerca_tutto | 200 | 2.3s | ok |
| cerca_riferimenti | 200 | 3.5s | ok (diretto) |
| leggi_reel | 200 | 0.04s | ok |
| leggi_articolo | 200 | 0.05s | ok |
| leggi | 200 | 0.04s | ok |
| fonti_blog | 200 | 0.03s | ok |
| temi | 200 | 1.0s | ok |

**Attraverso il connettore claude.ai** (non diretto), nello stesso giro:
`cerca_riferimenti` è andato in **timeout**, mentre `cerca_tutto` ha risposto in
2.3s. Quindi il connettore ha un tetto di tempo e le chiamate lente lo sfondano
a intermittenza → il cliente legge "la ricerca non funziona".

Causa della lentezza, misurata in shell (`semantic_search` diretto, indice caldo):

- `cerca_reel`/`cerca_articoli` fanno un **over-fetch 3×**: `_search` chiama
  `semantic_search(top_k=limite*3)` = 24, poi filtra al tipo e taglia a 8. Quindi
  passaggio+rerank si pagano su **24** elementi per restituirne 8.
  - `semantic_search(top_k=24, rerank=True)` = **17.3s**
  - `semantic_search(top_k=24, rerank=False)` = **9.3s**  ← il rerank aggiunge ~8s
  - `semantic_search(top_k=8, rerank=True)` (cerca_tutto) = **2.6s**
  - `semantic_search(top_k=5, only_inspiration, rerank=True)` = **3.5s**
- Il costo cresce con la dimensione del pool: il rerank manda al modello un pool
  di 24 estratti lunghi; e `_best_passage` seleziona il chunk per tutti e 24.

### Le interviste ("non le guarda")

Le "interviste" sono il **materiale di riferimento** (`is_inspiration=True`,
`source_type="video"`): 14 puntate "Canale Salute" (salute metabolica,
sovrappeso, pressione). Stato dati verificato:

- 14 attive, **tutte con embedding**, tutte con `chunk_vectors`, tutte con
  `content_text` → **tutte e 14 sono nell'indice di ricerca**.
- `cerca_tutto("sindrome metabolica")` le trova (blog:890 in cima, pertinenza
  0.743). Quindi il recupero le raggiunge.
- Due sospetti aperti, da verificare in disegno:
  1. **Latenza**: `cerca_riferimenti` va in timeout dal connettore (come sopra),
     e allora "non le guarda" = non fa in tempo a leggerle.
  2. **Etichetta**: le interviste hanno `owner_type="competitor"` e
     `account="YouTVRS"`, quindi `_hit()` le marca **"competitor: YouTVRS"**. Se
     il Claude del cliente chiede "guarda le nostre interviste" e poi scarta il
     materiale competitor, le interviste vengono buttate anche se recuperate.
     Da CLAUDE.md il materiale di ispirazione è esente dalla regola
     owned/competitor: l'etichetta attuale potrebbe tradire questa esenzione.

### Vincolo sulla CI (importante per il "test che blocca la MR")

`.github/workflows/ci.yml` gira il backend con `requirements-ci.txt`: **niente
torch, niente sentence-transformers, niente chiavi LLM, niente Ollama**. I
modelli pesanti sono importati in modo pigro. Quindi il "test di base MCP" che
gira in CI **non può** chiamare l'embedder vero né il reranker vero: deve
provare il **contratto/cablaggio** dei 10 strumenti (con embedder e LLM finti su
un DB piccolo seminato), non il recupero live. Il test live "vero" può esistere,
ma gira sul VPS, non nel cancello della MR.

### Cosa deve produrre la squadra (obiettivo)

1. Ogni strumento MCP risponde entro un budget di tempo che non fa scattare il
   timeout del connettore (le ricerche tipizzate oggi a 11-14s vanno abbassate).
2. Le interviste sono effettivamente usabili dal cliente (latenza + etichetta).
3. Un **test di base MCP** che esercita tutti i 10 strumenti.
4. Un **job CI** che fa quel test e che il ruleset di `main` richiede: la MR
   passa solo se il test MCP è verde.

## 2. Disegno            (architetto)

L'idea guida è una sola: la lentezza NON è del recupero, è del **rerank LLM**
che oggi lavora su un pool di 24 elementi invece che sul minimo necessario. Chi
cerca "solo reel" o "solo articoli" paga il rerank su 24 elementi misti per poi
buttarne la maggior parte. La cura è far arrivare al rerank solo gli elementi del
tipo giusto, già del numero giusto. Lo stesso taglio elimina anche lo starvation.
Poi due ritocchi mirati: l'etichetta delle interviste e un test-cancello in CI.

### Vincoli misurati (con il comando che li accerta)

1. **Le 10 funzioni-strumento sono chiamabili in-process**, quindi il
   test-cancello può importarle e chiamarle senza far partire il server HTTP.
   Il decoratore `@server.tool` restituisce la funzione invariata.
   `venv/bin/python -c "import inspect; from mcp.server.mcpserver import MCPServer;
   print('return fn' in inspect.getsource(MCPServer.tool))"` → `True`.
   `grep -c "@server.tool" mcp_bridge/server.py` → `10`.

2. **Il pacchetto `mcp` NON è in nessun requirements** (è installato ad-hoc in
   prod come 2.0.0) e le sue dipendenze **non includono torch**.
   `grep -in mcp BEC/requirements*.txt` → vuoto.
   `venv/bin/python -c "import importlib.metadata as m; print(m.version('mcp'));
   print(m.requires('mcp'))"` → `2.0.0`, deps = anyio, httpx2, jsonschema,
   mcp-types, opentelemetry-api, pydantic, pyjwt[crypto], starlette, uvicorn…
   (tutte leggere, nessuna pesante). **Conseguenza dura**: il test-cancello
   importa `mcp_bridge.server`, che importa `mcp`; quindi `requirements-ci.txt`
   deve guadagnare `mcp==2.0.0`, altrimenti la CI fallisce con
   `ModuleNotFoundError: mcp`.

3. **Over-fetch 3× + post-filtro = starvation possibile**, verificato per logica
   sul codice: `mcp_bridge/server.py:159-164` fa
   `semantic_search(top_k=limite*3)` → `hits=[h for h in hits if h["kind"]==only]`
   → `hits[:limite]`. Se tra i 24 elementi del pool i blog sono meno di `limite`
   (corpus dominato dai reel, ~900 vs ~30 articoli), `cerca_articoli` restituisce
   **meno di `limite`** risultati. È lo stesso caso che la doc del capo cita
   ("returns two"). Confermato dal capo: `top_k=24 rerank=True` = 17.3s vs
   `top_k=8 rerank=True` = 2.6s → il costo è nel pool grande, non nel recupero.

4. **`want = max(top_k, RERANK_POOL=15)`** (`core/knowledge.py:284`): oggi i
   tipizzati chiamano con `top_k=24`, quindi il pool effettivo che paga
   `_best_passage` + `_rerank` è **24**; `cerca_tutto` chiama con `top_k=8` →
   pool 15 → 2.6s. Portare i tipizzati a `top_k=limite` (=8) li riporta a
   `want=15`, cioè nel regime di `cerca_tutto`.

5. **`is_inspiration` è, per scelta esplicita, NON un terzo `owner_type`**
   (`core/models.py:485-490`: «26 call sites read that field as a binary and ten
   of them would silently file a third value under Medyca»). Quindi l'etichetta
   sbagliata delle interviste va corretta **solo nel layer di presentazione**,
   mai toccando `owner_type`.

### Pezzo 1 — Latenza dei tipizzati (e starvation, stessa cura)

**Cosa fare.** Aggiungere a `semantic_search` un parametro `kind` (`"reel"` /
`"blog"` / `None`) che filtra l'indice **subito dopo `_load_index`**, esattamente
come fa già `only_inspiration` (`core/knowledge.py:274-279`). In
`mcp_bridge/server.py::_search` passare `kind=only`, chiamare con
`top_k=limite` (via il param nuovo), e **togliere** sia l'over-fetch `*3` sia il
post-filtro `[h for h in hits if h["kind"]==only]` e il `hits[:limite]`.

**Perché funziona.** Con il filtro-tipo a monte, il pool che arriva a
`_best_passage` e a `_rerank` è di soli elementi del tipo giusto e di dimensione
`want=max(limite,15)=15` invece di 24. `cerca_reel`/`cerca_articoli` scendono nel
regime di `cerca_tutto` (~2.6s). E lo **starvation sparisce alla radice**: non si
filtra più *dopo* il rerank, quindi tutti i 15 candidati sono già del tipo giusto
e se ne restituiscono `limite`.

**Attenzione — è un cambiamento di risultato, va misurato.** Oggi `cerca_articoli`
restituisce «i blog che sopravvivono tra i primi 24 misti»; dopo restituisce «i
migliori blog rankati tra loro» (con la stessa quota owned/competitor, ora
applicata dentro il tipo). È quasi certamente un **miglioramento** (più pertinenti,
niente starvation), ma NON è "identico". Il vincolo del capo — «stessi risultati,
stesso ordine riordinato» — si onora così: **prima del merge si esegue
`python manage.py eval_mcp` e si verifica che l'hit-rate del golden set non cali**
(i casi `marion_gluck_blog`, `bijuva_medyca`, `crosslang_xerostomia` toccano
proprio reel-vs-articoli). Questa è la misura da fare in sviluppo/collaudo, non
un'ipotesi da chiudere ora.

**File da toccare**
- `BEC/core/knowledge.py` — nuovo param `kind` in `semantic_search` (motore
  condiviso da chat e MCP): il filtro sull'indice + aggiornare la docstring.
- `BEC/mcp_bridge/server.py` — `_search`: `kind=only`, `top_k=limite`, via
  l'over-fetch e il post-filtro.

**Cosa riuso** (percorso + nome esatti)
- Il pattern del filtro già presente: `core/knowledge.py:274-279`
  (`if only_inspiration: index = [i for i in index if i.get("inspiration")]`).
  `kind` è la stessa identica forma, un filtro in più sull'indice.

### Pezzo 2 — Le interviste

**(a) Latenza di `cerca_riferimenti`.** Gira già nel regime piccolo: il subset
ispirazione è di 14 elementi, quindi `_rerank` lavora su ≤14 → i 3.5s misurati
sono in pratica **il costo di una singola chiamata LLM di rerank**, non del pool.
Il filtro `kind` qui non aiuta (è già ristretto all'ispirazione). Se 3.5s sfonda
ancora il connettore, l'unica leva è ridurre quel rerank: saltarlo quando il pool
è ≤ `limite`, oppure abbassare `RERANK_POOL` solo per questo caso. **Non lo decido
ora**: dipende dal vero tetto del connettore, che non conosciamo (vedi domande
aperte). Piano minimo: dopo il Pezzo 1 tutte le ricerche stanno a ~2.6-3.5s
contro gli 11-14s di oggi; se serve limare gli ultimi decimi, si misura.

**(b) Etichetta.** In `_hit` (`server.py:72-87`) e in `_leggi_articolo`
(`server.py:263-313`), quando l'elemento è `inspiration`, il campo `di` deve dire
**`"riferimento: YouTVRS"`** — non `"competitor: YouTVRS"` e **non** `"Medyca"`.
Così `owner_type` resta binario nel DB, il materiale non finisce dalla parte di
Medyca, e il Claude del cliente smette di scartarlo come "roba dei competitor".
Il `tipo` è già corretto (`_hit` mette già "materiale di riferimento" per
l'ispirazione): si corregge **solo** `di`.

**Questo è un cambiamento di contratto MCP → va pesato.** Due conseguenze:
- La doc `04-mcp-connector.md` (tabella dei campi di `_hit`) va aggiornata.
- **Rompe il check di proprietà in `eval_mcp`**: `_call`/golden contano
  `"competitor" in h["di"].lower()` e lo confrontano con `owner_type` del DB
  (`eval_mcp.py:147-153, 262-275`). Un hit ispirazione ha `owner_type="competitor"`
  ma d'ora in poi `di` non conterrà "competitor" → falso negativo. Quindi
  `eval_mcp` va insegnato l'**esenzione**: per gli hit con
  `ispirazione=True` salta il controllo owned/competitor.

**File da toccare**
- `BEC/mcp_bridge/server.py` — `_hit` e `_leggi_articolo` (etichetta `di`).
- `BEC/core/management/commands/eval_mcp.py` — esenzione ispirazione nel check di
  proprietà; opzionale: un caso golden dedicato alle interviste + una soglia di
  latenza per i tipizzati (ora che devono stare bassi).

### Pezzo 3 — Test-cancello MCP + gate sulla MR

**Test-cancello leggero (CI), nuovo file `BEC/core/tests/test_mcp_tools.py`**
(Django `TestCase`, così ha un DB transazionale). Prova il **contratto e il
cablaggio** dei 10 strumenti, non la qualità del recupero.

- **Semina** un mini-corpus con l'ORM: `TrackedAccount(owned)` + `Reel` +
  `Enrichment` + `Transcript` + `ReelEmbedding(vector, chunk_vectors)`; un reel
  `competitor`; `BlogSource(owned)` + `KnowledgeDocument(owned, embedding,
  chunk_vectors, is_on_topic=True)` + `DocumentArgument`; un `KnowledgeDocument`
  competitor; **un `KnowledgeDocument` ispirazione** (`owner_type="competitor"`,
  `is_inspiration=True`, `source_type="video"`, fonte "YouTVRS"); un `ClusterRun`
  + `TopicCluster` + `Argument`/`ArgumentAssignment` per `temi`.
- **Stub dei modelli pesanti** (rispetta `requirements-ci.txt`: niente torch, né
  chiavi):
  - `core.knowledge._get_embedder` → oggetto finto con `.encode(list, ...)` che
    ritorna vettori a dimensione fissa (es. 16) normalizzati. È l'unico posto
    dove serve l'embedder in ricerca, perché i vettori dei documenti vengono
    letti dal DB. **Trucco**: seminare testi < 700 caratteri fa sì che
    `_best_passage` ritorni `parts[0]` senza chiamare l'embedder
    (`core/knowledge.py:420` — short-circuit `len(parts)==1`), quindi l'embedder
    finto serve solo per `_embed_query`.
  - `core.knowledge.client.chat_json` (usato da `_rerank`) → ritorna un dict
    (`{}` fa cadere il rerank sull'ordine del blend, esercitando comunque il
    cablaggio; oppure `{"ordine":[...]}` per esercitare il ramo di riordino).
    Necessario perché `_rerank` altrimenti chiamerebbe la rete.
- **Cosa verifica**: (1) tutte e 10 le funzioni rispondono con la forma giusta
  (`_hit` → chiavi `id/tipo/di/titolo/estratto/url/ispirazione/pertinenza`;
  `leggi_*` → i campi documentati; `panoramica`/`temi`/`fonti_blog` → le loro
  chiavi); (2) `cerca_reel` ritorna solo reel, `cerca_articoli` solo articoli,
  `cerca_riferimenti` solo ispirazione; (3) **etichette**: reel competitor →
  `di` contiene "competitor"; owned → "Medyca"; ispirazione → **né "competitor"
  né "Medyca" nudo**, ma "riferimento"; (4) **niente starvation**: con un pool
  seminato a maggioranza reel, `cerca_articoli` restituisce comunque gli articoli
  seminati; (5) i **10 strumenti sono registrati** sull'`MCPServer` (barriera
  contro uno strumento perso o rinominato — regressione di contratto).
- **Cosa riuso** (percorso + nome esatti): i pattern di
  `BEC/core/tests/test_link_ingest.py` (`unittest.mock.patch`, `APITestCase`,
  stub delle parti di rete) e `BEC/core/tests/test_endpoints_smoke.py`
  (`setUpTestData`). Le attese e la forma degli hit ricalcano `GOLDEN` e i
  matcher di `BEC/core/management/commands/eval_mcp.py`.

**Gate sulla MR.**
- Aggiungere `mcp==2.0.0` a `BEC/requirements-ci.txt` (vincolo #2).
- In `.github/workflows/ci.yml`, nel job **backend** (che è già un check
  richiesto dal ruleset di `main`), aggiungere uno step leggibile:
  `python manage.py test core.tests.test_mcp_tools -v 2`. Uno step che fallisce fa
  fallire il job → la MR è bloccata finché il test MCP non è verde, che è
  esattamente ciò che chiede il capo. **Non serve un job nuovo**: un job separato
  andrebbe aggiunto alla lista dei check obbligatori nel ruleset lato GitHub, cosa
  che fa Giuseppe, non un agente (vedi "fuori scope").
  - Nota: il test sta in `core/tests/`, quindi lo step esistente `manage.py test
    core` lo eseguirebbe già; lo step dedicato serve a renderlo **leggibile** come
    "cancello MCP" nella lista dei check.

**Test live (VPS, non in CI).** Resta `python manage.py eval_mcp` (embedder e LLM
veri, via HTTPS attraverso nginx, `eval_mcp.py`): lo esegue il collaudatore sul
VPS per confermare che i tipizzati sono davvero scesi a ~2.6s e che il golden non
è regredito. Non entra nel cancello della MR perché richiede i modelli pesanti e
il segreto.

### Riepilogo file da toccare

| File | Perché |
|---|---|
| `BEC/core/knowledge.py` | param `kind` in `semantic_search` (latenza + starvation) |
| `BEC/mcp_bridge/server.py` | `_search` (kind, no over-fetch/post-filtro) + `_hit`/`_leggi_articolo` (etichetta riferimento) |
| `BEC/core/tests/test_mcp_tools.py` | **nuovo** test-cancello dei 10 strumenti |
| `BEC/requirements-ci.txt` | aggiungere `mcp==2.0.0` (import del server nel test) |
| `.github/workflows/ci.yml` | step "test MCP" nel job backend (gate leggibile) |
| `BEC/core/management/commands/eval_mcp.py` | esenzione ispirazione nel check proprietà; opz. golden interviste + soglia latenza |
| `documentation/low-level/04-mcp-connector.md`, `03-llm-and-embeddings.md` | param `kind`, rimozione over-fetch, nuova etichetta, nota starvation (regola: doc nello stesso commit) |

### Rischi e invarianti

- **`owner_type` binario**: mai un terzo valore; l'etichetta interviste cambia
  **solo** in presentazione (`_hit`/`_leggi_articolo`). Vietato da
  `core/models.py:485-490`.
- **Contratto MCP**: cambiano due cose osservabili dal client — il campo `di`
  per l'ispirazione, e il *set* di risultati dei tipizzati (kind-filter). Vanno
  misurati con `eval_mcp` e documentati in `04-mcp-connector.md` nello stesso
  commit.
- **Niente credenziali di terzi / niente modelli pesanti in CI**: il test-cancello
  usa embedder e LLM finti; nessuna chiave, nessun torch. Rispetta
  `requirements-ci.txt`.
- **I falliti restano `failed`**: nulla in questo disegno li tocca.
- **Regressione di qualità**: il rischio principale è che il kind-filter cambi in
  peggio i risultati dei tipizzati. Mitigazione: cancello = `eval_mcp` golden
  verde prima del merge.

### Cosa resta fuori (dichiarato)

- **Job CI separato + modifica del ruleset di `main`** su GitHub: lo fa Giuseppe.
  Qui si aggiunge solo uno step dentro un job già obbligatorio.
- **Pinnare `mcp` in `requirements.txt` di produzione**: oggi è installato ad-hoc
  e non pinnato (debito latente, segnalato); non necessario per questo fix, ma
  andrebbe fatto.
- **Abbassare `RERANK_POOL` globale** (toccherebbe anche la chat): solo piano B da
  misurare se `cerca_riferimenti` resta sopra il tetto.
- **OAuth / trasporto / altre parti dell'MCP**: non toccati.

### Domande aperte (cambiano il lavoro secondo la risposta)

1. **Qual è il vero tetto di tempo del connettore claude.ai?** Il capo ha visto
   2.6s passare e 3.5s andare in timeout, ma in modo intermittente. Se il tetto è
   ~5s, il Pezzo 1 basta; se è più stretto, `cerca_riferimenti` va limato (leva
   del rerank).
2. **Il kind-filter mantiene l'hit-rate del golden?** Da misurare con `eval_mcp`
   prima del merge. Se cala, si rivede la quota owned/competitor dentro il tipo.
3. **Etichetta esatta per l'ispirazione**: propongo `"riferimento: YouTVRS"`.
   È wording di contratto → conferma di Giuseppe.
4. **Versione di `mcp` da pinnare in CI**: uso 2.0.0 (quella in prod). Da
   confermare che è quella deployata sul VPS.

## 3. Sviluppo           (sviluppatore)

Costruiti i tre pezzi del disegno, senza scostamenti. Un solo commit sul ramo
`feat/mcp`, doc nella stessa modifica.

### File toccati

| File | Cosa |
|---|---|
| `BEC/core/knowledge.py` | nuovo param `kind` (`"reel"`/`"blog"`/`None`) in `semantic_search`, filtra l'indice subito dopo `_load_index` (stessa forma di `only_inspiration`) + docstring |
| `BEC/mcp_bridge/server.py` | `_search`: `kind=only`, `top_k=limite`, tolti over-fetch `*3`, post-filtro e taglio finale. `_hit` e `_leggi_articolo`: etichetta `di` = `"riferimento: <fonte>"` per l'ispirazione (owner_type non toccato) |
| `BEC/core/management/commands/eval_mcp.py` | check proprietà: `continue` sugli hit `ispirazione=True` (altrimenti falso negativo) |
| `BEC/core/tests/test_mcp_tools.py` | **nuovo** test-cancello: 14 test, 10 strumenti, embedder+LLM finti, mini-corpus via ORM |
| `BEC/requirements-ci.txt` | `mcp==2.0.0` (il test importa `mcp_bridge.server` → `mcp`) |
| `.github/workflows/ci.yml` | step "Test cancello MCP" nel job `backend` già obbligatorio |
| `documentation/low-level/04-mcp-connector.md`, `03-llm-and-embeddings.md` | param `kind`, rimozione over-fetch, etichetta `riferimento:`, starvation risolto, test-cancello + gate CI |

### Scelte fatte

- **Latenza**: il filtro-tipo è spinto dentro `semantic_search` (`kind=`), non
  applicato dopo. `_search` chiama `top_k=limite` e restituisce direttamente
  `[_hit(h) for h in hits]`. Il param `kind` ha default `None`, quindi i tre
  altri chiamanti (`_prepare`, `ideation`, `views`) non cambiano — retrocompatibile.
- **Etichetta**: `di` diventa `"riferimento: <fonte>"` per l'ispirazione, in
  `_hit` e `_leggi_articolo`. `owner_type` resta binario nel DB (vietato terzo
  valore, `models.py:485-490`): cambia solo la presentazione. `<fonte>` è
  `account`/`source.name`/`author`, cioè "YouTVRS" per le puntate reali.
- **Test finti senza torch**: `_get_embedder` stubbato con un finto `.encode()`
  che ritorna vettori a 16 dim normalizzati (crc32, deterministico anche fuori
  processo); testi seminati < 700 char → `_best_passage` corto-circuita a
  `parts[0]` senza embedder; `client.chat_json` stubbato a `{}` → `_rerank`
  tiene l'ordine del blend. Nessun import pesante nel percorso del test.
- **10 strumenti registrati**: verificati via
  `server.server._tool_manager.list_tools()` (API sincrona di `mcp` 2.0.0).

### Verifica (output reale, venv del backend)

```
$ venv/bin/python manage.py test core.tests.test_mcp_tools -v 2
...  (14 test)
Ran 14 tests in 0.933s
OK

$ venv/bin/python manage.py makemigrations --check --dry-run
No changes detected                       # nessuna migrazione nuova (atteso)

$ venv/bin/python manage.py check
System check identified no issues (0 silenced).

$ venv/bin/python manage.py test core     # suite intera, niente regressioni
Ran 44 tests in 6.731s
OK
```

### Numeri di latenza

Non misurabili in-process qui: senza chiavi LLM il `_rerank` (la leva della
latenza) non gira, e l'embedder finto azzera i tempi. Restano quindi le misure
del disegno (capo, servizio live): `cerca_reel`/`cerca_articoli` **11–14s →
~2.6s**, `cerca_tutto` 2.3s, `cerca_riferimenti` 3.5s. Il meccanismo è
verificabile: il pool che arriva a `_rerank`+`_best_passage` scende da 24 misti a
15 di un solo tipo. La conferma coi modelli veri è compito del collaudatore via
`manage.py eval_mcp` sul VPS.

### Cosa è rimasto fuori (dichiarato)

- **`cerca_riferimenti` sotto il tetto del connettore**: il Pezzo 1 non lo tocca
  (è già ristretto all'ispirazione, ~3.5s). Se 3.5s sfonda ancora, la leva è il
  rerank (saltarlo con pool ≤ limite, o `RERANK_POOL` più basso solo lì). Non
  fatto: dipende dal vero tetto del connettore, ancora ignoto (domanda aperta #1).
- **Caso golden dedicato alle interviste + soglia di latenza in `eval_mcp`**:
  opzionale nel disegno, non fatto per restare conservativi. Solo l'esenzione
  proprietà è stata aggiunta (necessaria).
- **Pin di `mcp` in `requirements.txt` di produzione** e **job CI separato +
  ruleset GitHub**: fuori scope per decisione di Giuseppe, restano al capo.
- **`cerca_articoli` e il materiale di riferimento**: un doc `is_inspiration`
  ha `kind="blog"`, quindi `cerca_articoli` può includerlo (etichettato
  "materiale di riferimento") — comportamento invariato rispetto a prima (anche
  il vecchio post-filtro `kind=="blog"` lo teneva). Lo strumento dedicato resta
  `cerca_riferimenti`.

## 4. Revisione          (revisore)

## 5. Collaudo           (collaudatore)

## 6. Rilascio           (rilasciatore)

## Registro delle decisioni

- 2026-09-16 — Ramo `feat/mcp` (non `feature/mcp`) per stare nella convenzione
  della squadra e nel guard dei permessi. (capo)

- 2026-09-16 — Disegno approvato da Giuseppe. Decisioni: (1) etichetta interviste
  = `"riferimento: YouTVRS"` (solo presentazione, `owner_type` intatto); (2)
  cancello CI = step dentro il job `backend` già obbligatorio, niente modifica al
  ruleset GitHub; (3) `mcp==2.0.0` confermato sul VPS (venv) dal capo → è la
  versione da pinnare in `requirements-ci.txt`. (capo)
