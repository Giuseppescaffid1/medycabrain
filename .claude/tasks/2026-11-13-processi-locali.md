---
id: 2026-11-13-processi-locali
titolo: Pagina "Processi locali" - cosa fa l'LLM locale e quanto costa in tempo
stato: pronto
ramo: feat/processi-locali
pr: ""
ticket: ""
---

## 1. Richiesta          (capo)

Parole di Giuseppe (13/11/2026, appena passati al nuovo VDS):

> now we have IProyal and a new VDS which is superpowerful despite it's only CPU,
> who cares we can find optimization to run our LLM there even though the token
> per second are slow. [...] I don't want to use the Anthropic API call and the
> Apify stuff because I have a powerful machine that I can run my process on.
> The only problem here is that I want accountability for what is running in
> terms of how much it takes to run a certain process. I need to develop a page
> in the Medyca UI that gives me the state of updates for every process that is
> running on the LLM locally. It needs to be a very simple one.

Contesto raccolto dal capo:

- Nuovo VDS: 18 core CPU, 94 GB RAM, niente GPU. Ollama attivo come servizio
  systemd con `qwen2.5:7b-instruct-q4_K_M`.
- Ollama è già integrato in `BEC/llm/client.py` (`_ollama_chat`, `_ollama_slot`),
  con un lock file che serializza le generazioni (`OLLAMA_LOCK_PATH`,
  `OLLAMA_LOCK_WAIT` in `BEC/config/settings/base.py`). Oggi è solo la riserva:
  `LLM_PROVIDER_ORDER` di default è `fast,ollama`.
- Esiste già la tabella `Job` (`BEC/core/models.py`) con stato/progresso/messaggio.
- Lasciare Anthropic API e Apify è un lavoro **separato e successivo**: qui non
  si tocca.

Cosa deve mostrare la pagina, per ogni processo che usa l'LLM locale:
cosa è (stadio pipeline o Job), stato (in attesa del lock / in corso / finito /
fallito), inizio, durata, token in/out, token al secondo, tempo rimanente
stimato. In più un totale giornaliero di ore-macchina per tipo di processo:
è il "costo" ora che non si paga in euro. Molto semplice, mobile first,
`ui-design`.

Idea di partenza del capo (da confermare o smontare nel disegno): registrare
ogni chiamata LLM (provider, modello, token, secondi, attesa del lock, job o
stadio di appartenenza) in una tabella nuova, e costruire la pagina su quella
più la tabella `Job`.

### Aggiunta di Giuseppe (13/11/2026, dopo il primo disegno)

> ok adesso dove posso monitorare nella content intelligence quali video stanno
> runnando cioè, quello che voglio vedere sulla Medyca Intelligence è, nel menu
> drop-down a sinistra, dove c'è anche lo stato di valutazione di alcuni
> processi: voglio vedere in stile TQDM tipo Python, come questi video vengono
> processati da questi LLM locali. Voglio vedere lo stato in cui si muovono le
> cose. Ogni volta che riattiviamo tutto e ingestiamo nuovi Instagram e nuove
> fonti, tipo blog, eccetera, ovviamente questo deve essere riflesso anche lì,
> se no non ho consciousness di quello che sta succedendo.

Cosa cambia rispetto al primo disegno (letto dal capo):

- Vuole vedere **l'avanzamento stadio per stadio in stile tqdm**: una barra per
  ogni stadio con fatti/totale, velocità (elementi al minuto o token al
  secondo), tempo passato e tempo rimanente. Il primo disegno lasciava la
  vista "stadio intero" alla pagina Stato e non la duplicava: ora è il cuore.
- Deve coprire **ogni ingestione**: reel Instagram nuovi, fonti blog nuove,
  upload. Non solo le chiamate al modello.
- La voce sta **nel menu a sinistra, vicino a Stato**.
- Dice "LLM locali", ma oggi il lavoro lo fanno i modelli remoti e il Batch
  (`LLM_PROVIDER_ORDER=fast,ollama`, `BATCH_ENABLED=1`). La pagina deve dire
  chiaramente **chi** sta lavorando ogni elemento (locale o remoto).
- Da oggi Ollama usa 6 thread (PR #19 fusa): 7b a 3,8-4,0 tok/s.

## 2. Disegno            (architetto)

### In due righe

Ogni volta che il programma chiede qualcosa a un modello, scrive una riga in
una tabella nuova: chi l'ha chiesto, a quale modello, quando, quanto ha
aspettato, quanti token, quanti secondi. La pagina "Processi locali" legge
quella tabella (più `Job`) e la mostra. L'idea del capo è confermata, con tre
aggiunte: la riga nasce **prima** della chiamata (così si vede "in attesa" e
"in corso"), si registrano **anche i modelli remoti** (solo a fine chiamata),
e nessun testo viene salvato, solo numeri.

### Fatti misurati (13/11/2026, su questo VDS)

Verificato, con il comando usato:

1. **Il modello locale oggi è lentissimo: 0,4-0,6 token al secondo.** Due
   prove dirette su Ollama con `qwen2.5:7b-instruct-q4_K_M`
   (`curl http://127.0.0.1:11434/api/chat`): a freddo 44 token in 117 s
   (0,38 tok/s) più 22,8 s per caricare il modello; a caldo 24 token in 38 s
   (0,63 tok/s). Anche la lettura del prompt è lenta: 35 token in 12,9 s.
   Durante la prova i 18 core erano tutti occupati (`top`: 97,8% CPU,
   `llama-server` al 1273%). Attenzione: la seconda prova si è sovrapposta al
   giro delle 14:15 della pipeline (che però usava solo il 20% di un core).
   Sono due campioni soli: il numero va rimisurato a macchina ferma. Ma se è
   confermato, un'analisi da 400 token dura 10-17 minuti, e una CPU così
   dovrebbe fare almeno dieci volte meglio. **La causa non è nota e non è
   lavoro di questo disegno**, ma è la prima cosa che la pagina farà vedere.
2. **Ollama dice già tutto quello che serve**, nell'ultima riga della
   risposta: `prompt_eval_count` (token letti), `eval_count` (token scritti),
   `prompt_eval_duration`, `eval_duration`, `load_duration`, `total_duration`
   (in nanosecondi), `done_reason`. Oggi `_ollama_chat` (`BEC/llm/client.py`
   righe 123-140) butta via quella riga: tiene solo il testo.
3. **Mentre scrive, Ollama manda un pezzo per token**: 43 pezzi di testo per
   44 token (`wc -l` sul flusso salvato). Quindi contare i pezzi dà i "token
   finora" in diretta. Verificato su un solo campione: a fine chiamata il
   conteggio viene comunque sostituito dal numero vero.
4. **Una generazione occupa tutta la macchina** (punto 1). Quindi
   "ore-macchina" = tempo in cui il lucchetto è tenuto, senza moltiplicare
   per 18.
5. **Il file `.env` dice `OLLAMA_MODEL=qwen2.5:3b-instruct-q4_K_M`**, non il
   7b scritto nella richiesta (`grep OLLAMA BEC/.env`). Entrambi i modelli
   sono installati (`/api/tags`). Oggi l'app userebbe il 3b.
6. **Oggi il locale non lavora quasi mai**: `LLM_PROVIDER_ORDER=fast,ollama`,
   il file del lucchetto non esiste (`ls /tmp/medycabrain-ollama.lock*`), e
   solo 13 analisi su 1617 portano la firma `ollama:` (shell Django).
7. **Ollama carica il modello con una finestra di 4096 token**
   (`/api/ps`: `context_length: 4096`); `client.py` non imposta `num_ctx`.
   Un prompt più lungo viene tagliato in silenzio.
8. **I punti che chiamano il modello sono 16, in 10 file**
   (`grep -rnE "chat_json\(|client\.chat\("`). Passano tutti da `chat()`:
   si registra lì, in un punto solo, e i 16 non si toccano.
9. **I punti dove nasce un processo sono 2**: `DAG.run` in
   `BEC/pipeline/dag.py` (riga 96, `step.fn(ctx)`: copre cron e pipeline
   lanciata a mano, 9 stadi) e `run_job.handle` (`_dispatch`, 9 tipi di Job).
   Restano fuori da questi due: la chat del Second Brain (gira dentro il
   server web, `KnowledgeAskView`), la ricerca MCP con riordino
   (`mcp_bridge/server.py` riga 209) e i comandi a mano (`reprocess`,
   `eval_mcp`).
10. **`enrich` usa 5 thread** (`ENRICH_WORKERS=5`, `ThreadPoolExecutor` in
    `enrich_agent.py` riga 83). Una contextvar (l'etichetta "chi sta
    chiamando" legata al filo di esecuzione) **non passa** ai thread di un
    pool: da sola perderebbe lo stadio proprio su `enrich`.
11. **Nessuna chiamata al modello sta dentro una transazione**
    (`grep atomic`: 4 blocchi, nessuno contiene `chat`; niente
    `ATOMIC_REQUESTS`). Quindi le righe "in attesa" e "in corso" sono visibili
    subito dalla pagina.
12. **Volumi**: 1618 reel, 2211 documenti, 85 Job in tutto, picco di 141
    analisi in un giorno negli ultimi 30. Con due chiamate per reel sono poche
    centinaia di righe al giorno nei giorni pieni: la tabella resta piccola.
13. `timeout` scaduto in `_ollama_chat` **non è un errore**: restituisce il
    testo parziale (riga 139). Oggi nessuno lo sa.

Supposto, non verificato: che i provider remoti restituiscano sempre il campo
`usage` (lo standard OpenAI e l'SDK Anthropic lo prevedono; se manca, i token
restano vuoti e la riga si scrive lo stesso).

### La tabella nuova: `LLMCall` (`llm_calls`, migrazione `0026`)

Una riga per ogni tentativo di chiamata. Solo numeri ed etichette:
**niente prompt, niente risposta**.

- Chi: `process` (etichetta, es. `pipeline:enrich`, `job:strategy`,
  `web:chat`, `mcp:cerca`, `cmd:reprocess`, `altro`), `stage`, `job`
  (collegamento a `Job`, facoltativo, `SET_NULL`), `run_id` (un codice uguale
  per tutte le chiamate dello stesso processo: serve a raggrupparle), `pid`.
- Con cosa: `provider` (`ollama` o il nome del provider remoto), `is_local`,
  `model`.
- Stato: `waiting` (in attesa del lucchetto) / `running` / `done` / `failed`,
  più `truncated` (risposta tagliata dal timeout o dal tetto di token) ed
  `error` (frase corta).
- Tempi: `created_at` (entrata in coda), `started_at` (lucchetto preso),
  `finished_at`, `wait_seconds`, `duration_seconds`, `load_seconds`,
  `prompt_seconds`, `eval_seconds`.
- Token: `prompt_tokens`, `output_tokens`, `tokens_so_far` (in diretta),
  `max_tokens` (il tetto chiesto, serve per la stima), `prompt_chars`.
- Indici: `status`, `created_at`, (`process`, `created_at`).

### Dove si registra

File nuovo `BEC/llm/usage.py` (il "registratore"), usato da `client.py`.

- **Chi sta chiamando.** `usage.scope(process, stage, job_id)` è un blocco
  `with` messo nei 2 punti del fatto 9. L'etichetta sta in una contextvar
  **e**, come riserva, in una variabile di processo: pipeline e Job sono
  ognuno un processo a sé che fa uno stadio alla volta, quindi la riserva è
  sempre giusta e risolve i 5 thread di `enrich` senza toccare l'agente.
  Chat web e MCP aprono il loro blocco in `core/knowledge.py` (`answer` e il
  riordino). Senza blocco: `cmd:<nome comando>` da `sys.argv`, altrimenti
  `altro`. Una pipeline lanciata da Job porta sia `job` sia `stage`.
- **Ollama, in diretta** (ramo locale di `chat()._call`, riga 484):
  1. riga `waiting` creata **prima** di `_ollama_slot`;
  2. prima istruzione dentro il `with`: `running`, `started_at`,
     `wait_seconds`. Il lucchetto non si tocca;
  3. durante lo stream: `tokens_so_far` aggiornato al massimo ogni 5 secondi;
  4. alla riga `done`: i numeri veri del fatto 2, stato `done`;
  5. uscita per timeout (fatto 13): `done` con `truncated`;
  6. errore, compreso "nessun posto libero dopo 900 s": `failed` con la frase.
  `_ollama_chat` continua a restituire una stringa: riceve il registratore
  come parametro facoltativo.
- **Remoti** (`_fast_chat`, `_anthropic_chat`, `_hf_chat`): una sola
  scrittura a fine tentativo, con i token letti da `usage`.
- **La registrazione non può mai rompere una chiamata**: ogni scrittura è
  protetta; se il database non risponde si scrive un avviso nel log e la
  generazione prosegue.
- **Righe fantasma.** Un processo ucciso lascia una riga `waiting`/`running`.
  Chi legge la pagina le chiude come `failed` ("processo interrotto") quando
  il `pid` non esiste più (`/proc/<pid>`, stessa macchina) o dopo 3 ore. Mai
  rimesse in coda. Stesso schema di `_reap_stale_jobs` (`views.py` riga 994).

### Anche i remoti? Sì

Motivo: oggi il locale non lavora quasi mai (fatto 6), quindi una pagina solo
Ollama resterebbe vuota fino al passaggio. Registrando anche i remoti si sa
da subito **quante chiamate e quanti token fa ogni processo in un giorno**.
Quel numero, diviso per la velocità locale misurata, dà le ore che il VDS
impiegherebbe: è il conto che il registro delle decisioni chiede di fare
prima di lasciare Anthropic. Costo: una scrittura in più per chiamata.
Sulla pagina i remoti stanno in una sola riga di confronto nei totali, non
nell'elenco in diretta: la pagina resta "locale".

### Endpoint REST

`GET /api/v1/ops/llm/?day=AAAA-MM-GG` (`IsAuthenticated`, sola lettura),
logica in un file nuovo `BEC/core/llm_report.py`. Restituisce:

- `active`: i processi con chiamate aperte, raggruppati per `run_id`: nome,
  stato, inizio, durata, chiamate fatte, token in/out, token al secondo,
  stima. Per i Job anche `progress` e `message` già presenti su `Job`.
- `recent`: gli ultimi 20 processi finiti o falliti.
- `daily`: per il giorno scelto (ora di Roma) e per tipo di processo:
  chiamate, ore-macchina, ore di attesa, token, fallite; più la riga "remoto".
- `speed`: velocità mediana locale delle ultime 24 ore e modello usato.

### La pagina

`/processi`, voce "Processi locali" nel menu sotto "Stato". File nuovo
`FEC/src/pages/LocalProcesses.tsx`, pezzi in `FEC/src/components/ops/`.
Pagina a parte e non un sesto riquadro in `Status.tsx` (308 righe, già 5
riquadri). Pensata a 380 px, tre blocchi in colonna:

1. **Adesso**: una scheda per processo. Nome in chiaro (le etichette di
   `STAGE_LABELS` e dei tipi di Job), stato con icona e parola, "iniziato
   alle", durata che scorre, token letti/scritti, token al secondo, "manca".
   Vuoto: "Nessun processo sta usando il modello locale. L'ultimo è finito
   alle 03:52."
2. **Oggi**: una riga per tipo di processo con le ore-macchina e una barra;
   frecce per cambiare giorno; in fondo la riga di confronto "modelli remoti".
3. **Ultimi processi**: elenco corto, "Mostra altri".

Aggiornamento ogni 5 s se c'è qualcosa in corso, ogni 30 s altrimenti.
Stati di caricamento ed errore come in Stato. Nessun elemento rosso: non c'è
un'azione principale, e un fallimento si dice con icona e testo.

### Stima del tempo rimanente, senza inventare

- **In attesa**: nessun numero. Si mostra "in coda da 4 min, 2 davanti".
- **Sta leggendo il prompt** (nessun token ancora): stima dalla lunghezza del
  prompt e dalla velocità di lettura delle ultime chiamate. Senza storico:
  "non ancora stimabile".
- **Sta scrivendo**: due numeri, dichiarati per quello che sono. "Di solito
  ancora ~6 min" (lunghezza mediana delle ultime risposte dello stesso
  processo, servono almeno 5 esempi) e "al massimo 40 min" (tetto di token
  diviso velocità attuale). Superata la mediana: "più lunga del solito".
- **Il processo intero**: per i Job la percentuale che `Job` ha già; per gli
  stadi della pipeline resta la stima di `core/queue_eta.py` sulla pagina
  Stato. Non se ne fa una seconda.

### Pulizia

Dettaglio tenuto 90 giorni (`LLM_CALL_RETENTION_DAYS`, in `base.py` e
`.env.example`). Comando nuovo `prune_llm_calls`, una riga nel crontab (la
aggiunge il rilasciatore, chiedendo conferma). Mai cancellare dentro
l'endpoint di lettura. In v1 i totali oltre i 90 giorni si perdono.

### File da toccare

| File | Perché |
|---|---|
| `BEC/core/models.py` + `migrations/0026_llmcall.py` | la tabella |
| `BEC/llm/usage.py` (nuovo) | registratore ed etichetta del processo |
| `BEC/llm/client.py` | registrare nei 4 punti dove parte una chiamata; tenere l'ultima riga di Ollama |
| `BEC/pipeline/dag.py` | blocco `scope` attorno a `step.fn(ctx)` |
| `BEC/core/management/commands/run_job.py` | blocco `scope` attorno a `_dispatch` |
| `BEC/core/knowledge.py` | etichetta per chat web e riordino MCP |
| `BEC/core/llm_report.py` (nuovo), `views.py`, `urls.py` | endpoint |
| `BEC/core/management/commands/prune_llm_calls.py` (nuovo) | pulizia |
| `BEC/config/settings/base.py`, `BEC/.env.example` | giorni di conservazione |
| `BEC/core/tests/test_llm_usage.py` (nuovo) | prove con Ollama finto: in CI Ollama non c'è |
| `FEC/src/pages/LocalProcesses.tsx` (nuovo), `components/ops/*`, `App.tsx`, `Sidebar.tsx`, `api/`, `i18n/it.json` | pagina |

### Cosa si riusa

- `Job` e `Job.progress/message`; `_reap_stale_jobs` come schema per i fantasmi.
- `STAGE_LABELS` in `pipeline/dag.py` per i nomi in chiaro.
- `_last_model` in `client.py`: stesso meccanismo (contextvar) già in uso.
- `core/queue_eta.py` per la stima a livello di stadio (non duplicata).
- Frontend: `components/ops/live.ts` (`fmtDuration`, `useTicker`,
  `elapsedNow`), `Badge`, `Skeleton`, `PanelError`, `LoadMore`,
  `PageTransition`, la voce `Item` della sidebar.

### Documentazione, nello stesso commit

`01-data-model.md` (tabella e diagramma ER), `03-llm-and-embeddings.md`
(cosa si registra, i fatti misurati 1-7), `05-rest-api.md`, `06-frontend.md`,
`02-pipeline.md` (due righe: ogni stadio etichetta le sue chiamate, più il
comando di pulizia), `.claude/architecture-summary.md` (una riga), la pagina
`Documentazione` dell'app in parole del cliente, i commenti in testa ai
moduli. Il drawio **non** cambia: non c'è uno stadio nuovo né uno che si
comporta diversamente. Se il revisore la pensa diversamente, pagina 2.

### Rischi

- **`owner_type`**: la tabella non contiene né contenuti né proprietario.
  Nessun terzo valore, nessuna mescolanza possibile. Gli strumenti MCP non
  cambiano.
- **I falliti restano `failed`**: le righe fantasma si chiudono come fallite e
  basta. Nessun ritento nasce da questa tabella.
- **Credenziali**: nessuna nuova. Non si salvano chiavi né indirizzi con chiave.
- **Punto caldo**: `client.py` è il file da cui passa tutto. Una scrittura che
  solleva un errore fermerebbe le analisi: per questo ogni scrittura è
  protetta, e va provata con il database spento.
- **5 thread su un lucchetto solo**: quando `enrich` cadrà sul locale, 4
  chiamate su 5 aspetteranno, e a 10-17 minuti l'una supereranno i 900 s di
  attesa e falliranno. Non è un difetto di questo lavoro, ma la pagina lo
  mostrerà come una fila di fallimenti: va saputo prima.
- **`pid` riusato** da un altro processo: una riga fantasma resta aperta fino
  al tetto delle 3 ore. Accettato.
- **Token in diretta = pezzi contati**: verificato su un campione (fatto 3).
- **Lettura di prompt lunghi**: per minuti non arriva nessun token; la scheda
  dice "sta leggendo il prompt", non sembra bloccata.

### Alternative scartate

- **Leggere i log** (come fa `queue_eta.py` con `pipeline.log`): i log non
  hanno i token e non hanno lo stato "in attesa".
- **Aggiungere colonne a `Job`**: un Job fa molte chiamate, e il cron della
  notte non ha nessun Job.
- **Seconda tabella per i processi** (`LLMRun`): il raggruppamento per
  `run_id` basta. Si aggiunge se serve.
- **Solo contextvar**: perde lo stadio su `enrich` (fatto 10).
- **Passare `job=` a mano nei 16 punti**: 16 modifiche al posto di 2.
- **Salvare prompt e risposta**: più peso, dati del cliente copiati in un
  altro posto, e nessuna utilità per il conto del tempo.
- **Chiedere lo stato a Ollama** (`/api/ps`): dice quale modello è caricato,
  non chi lo sta usando né quanti token ha fatto.
- **Tabella di totali giornalieri**: rimandata, vedi domanda 4.

### Cosa resta fuori

- Rendere il modello locale più veloce (fatto 1) e alzare la finestra di 4096
  token (fatto 7). Sono lavori a sé, e vengono prima del passaggio al locale.
- Lasciare Anthropic e Apify (registro delle decisioni).
- La trascrizione (Whisper, remoto o locale) e gli embedding: non passano da
  `chat()`. Vedi domanda 2.
- Il Batch API di Anthropic (`llm/batch.py`): non è una chiamata in diretta.
- Fermare o riavviare un processo dalla pagina: è sola lettura.
- Stima del tempo per l'intero stadio: resta su Stato.
- Avvisi (mail, notifiche) quando qualcosa fallisce o è lento.

### Domande aperte per Giuseppe

1. **Quale modello locale?** Il `.env` dice 3b, la richiesta dice 7b. Lo
   cambiamo qui o resta com'è finché non si decide il passaggio?
2. **La trascrizione locale (Whisper) conta come "processo locale"?** Occupa
   la stessa CPU ma non è un LLM e non usa il lucchetto. Farla entrare
   allarga il lavoro (un secondo punto di registrazione, niente token).
3. **Chi vede la pagina?** Oggi ogni utente vede tutto, cliente compreso, e
   non esiste una distinzione di ruolo nell'app. Va bene così o solo tu?
4. **90 giorni di dettaglio bastano?** Se i totali giornalieri devono restare
   per sempre serve una piccola tabella di riepilogo in più.
5. **La lentezza misurata (0,4-0,6 token/s)** la indaghiamo subito con un
   lavoro separato, prima o in parallelo a questo? Con quei numeri la pagina
   mostrerà chiamate da decine di minuti.
6. **Va bene registrare anche i modelli remoti** (una riga di confronto sulla
   pagina), o vuoi la tabella solo per Ollama?
### Revisione del disegno (tqdm)

Aggiunta dopo la richiesta di Giuseppe del 13/11 ("Aggiunta di Giuseppe",
sezione 1). Il testo sopra non è stato riscritto: qui c'è scritto cosa resta,
cosa cambia e cosa si aggiunge.

#### In tre righe

La pagina non è più "le chiamate al modello locale": è **"cosa sta girando
adesso, stadio per stadio"**, con una barra per stadio e i quattro numeri di
tqdm (fatti/totale, velocità, tempo passato, tempo rimanente). Sotto la barra
c'è scritto quale reel o articolo è in lavorazione e chi lo lavora (modello
locale, remoto, o consegna in blocco). Per avere il fatti/totale in diretta
serve una seconda tabella piccola, `StageRun`, accanto a `LLMCall`.

#### Fatti nuovi misurati (13/11/2026)

14. **Nessuno oggi conosce il fatti/totale di un giro, tranne l'agente stesso.**
    Ogni agente costruisce la sua lista all'inizio (`batch = list(qs)`,
    `_parallel(list(qs), ...)`) e la scorre: il totale esiste solo in memoria
    e non viene scritto da nessuna parte (lettura dei 9 agenti in
    `BEC/pipeline/agents/`). Il log scrive solo "inizio stadio" e "fine
    stadio" (`dag.py` righe 89 e 99).
15. **Contare le righe non basta per ricostruirlo.** Il download prende solo
    una parte della coda (`download_max_per_run`, `ctx.limit`,
    `downloader_agent.py` righe 366-371), può fermarsi prima per la quota di
    Instagram, e a fine giro rimette in coda i falliti con tentativi rimasti
    (riga 441): il conteggio "in attesa" andrebbe all'indietro. `Reel` e
    `KnowledgeDocument` non hanno una data per colonna di stato, solo
    `updated_at`.
16. **`/ops/status/` è troppo pesante per essere chiesto più spesso.**
    Cronometrato nella shell Django: `ops.snapshot()` 303-566 ms (lancia 6
    comandi di sistema e rilegge il log), `queue_eta.snapshot()` 52-147 ms
    con 4 query. Due query semplici su colonne indicizzate (`Job` attivi,
    `BatchRun` aperti): 18,7 ms in tutto, compresa l'apertura della
    connessione.
17. **Esiste già un tqdm, ma da terminale**: `manage.py progress`
    (`core/management/commands/progress.py`). Conta le righe di 4 colonne dei
    reel, su tutto lo storico. Non copre articoli, upload, né "questo giro".
18. **Uno stadio fallito oggi può sembrare "in corso".** `ops.run_history`
    chiude uno stadio solo sulla riga `✓` (`ops.py` righe 232-269); le righe
    `✗` non vengono lette, e nel log ce ne sono 11 (`grep -c "✗"
    logs/pipeline.log`). Letto nel codice, **non riprodotto**.
19. **Lo stadio `batch` non è in diretta per natura**: consegna e ritira. Lo
    stato vero sta in `BatchRun` (26 righe, tutte `collected` oggi) e viene
    aggiornato solo quando gira la pipeline.
20. **La trascrizione decide chi lavora elemento per elemento**: prima il
    remoto (`whisper-large-v3`, `USE_REMOTE_STT=True`), poi il locale di
    riserva (`transcriber_agent.py` righe 44-60). Non passa da `chat()`.
21. **I Job conoscono solo una percentuale**, non un fatti/totale
    (`Job.progress` 0-100 e `Job.message`; 11 punti chiamano `set_progress`).
    La percentuale dei Job si vede già in tre posti: la barra globale in
    fondo (`StatusBar`), il riquadro "Job in corso" di Stato e il riquadro
    della coda.
22. `enrich` e `knowledge` usano lo stesso aiuto `_parallel`
    (`knowledge_agent.py` riga 199): un punto solo serve entrambi.
23. Volumi di oggi: 23 account attivi, 30 fonti blog attive, 20 upload, 0 Job
    attivi, 1 reel in attesa di analisi su 1618.

Il **fatto 1 è superato**: il registro delle decisioni ha trovato la causa (i
thread) e con 6 thread il 7b fa 3,8-4,0 token al secondo (PR #19). Un'analisi
da 400 token dura circa 100 secondi, non 10-17 minuti. Il rischio "5 thread
su un lucchetto solo" si riduce: il quinto aspetta circa 400 s, sotto i 900.

#### Cosa resta valido

- La tabella `LLMCall`, il registratore `BEC/llm/usage.py`, il blocco `scope`
  nei 2 punti, la regola "la registrazione non rompe mai una chiamata", le
  righe fantasma, la pulizia a 90 giorni, i totali "Oggi" in ore-macchina.
- Le stime per la singola chiamata ("di solito ancora", "al massimo").
- Tutte le alternative scartate.

#### Cosa cambia

1. **Una pagina sola, con un altro nome.** Non "Processi locali" su
   `/processi`, ma **"Avanzamento"** su `/avanzamento`, voce di menu subito
   sotto "Stato pipeline". Contiene tutto: le barre, chi lavora, i totali del
   giorno. Due pagine per la stessa domanda sarebbero una di troppo.
2. **Lo stadio intero non resta più su Stato**: la riga "Stima del tempo per
   l'intero stadio: resta su Stato" (in "Cosa resta fuori") è annullata.
3. **I modelli remoti si registrano anche all'inizio**, non solo alla fine.
   Altrimenti mentre un remoto lavora non si saprebbe dire chi sta lavorando.
   Costo: due scritture per chiamata invece di una. Per i remoti non ci sono
   "token finora" (rispondono tutto insieme): si mostra solo il tempo.
4. **`LLMCall` prende quattro colonne in più**: `item_kind` (reel / articolo
   / upload), `item_id`, `item_label` (testo corto, es. "@account · codice" o
   il titolo dell'articolo, massimo 80 caratteri) e `stage_run` (collegamento
   alla barra, facoltativo, `SET_NULL`). Prima il disegno diceva "solo numeri
   ed etichette": resta vero, ma ora c'è anche il nome dell'elemento. Niente
   prompt e niente risposta, come prima.
5. **"Token finora" si aggiorna ogni 2 secondi**, non ogni 5: a 4 token al
   secondo, 5 secondi sono salti da 20.
6. **Il blocco "Ultimi processi" diventa "Ultimo giro"**: gli stadi
   dell'ultimo giro con i numeri finali. La storia dei giri passati con le
   durate resta su Stato (`RunTimeline`) e non si copia.
7. **Endpoint**: quello veloce è nuovo, `GET /api/v1/ops/progress/`. I totali
   del giorno restano su `GET /api/v1/ops/llm/?day=`, chiesto una volta e poi
   ogni 60 s. La logica di lettura sta in un file solo,
   `BEC/core/progress_report.py` (prende il posto di `llm_report.py`).

#### (a) Pagina nuova, e cosa si toglie da Stato

Pagina nuova, perché Giuseppe ha chiesto una voce di menu e perché Stato ha
già 8 blocchi. Regola per non avere lo stesso numero in due posti:

- **Stato = il quadro.** Quanto manca in tutto (anche per i giri futuri),
  totali storici, durata dei giri passati, servizi, account.
- **Avanzamento = adesso.** Questo giro, questo stadio, questo elemento.

Di conseguenza su Stato:

- il riquadro **"Job in corso"** (righe 241-261 di `Status.tsx`) si toglie:
  la stessa percentuale passa su Avanzamento. La barra globale in fondo resta:
  è un avviso, non una pagina;
- il riquadro **"In questo momento"** (`LiveActivity`) si riduce a una riga
  con il collegamento "Segui l'avanzamento". Resta lì solo la barra della
  rianalisi, che Avanzamento non copre;
- le barre "Avanzamento per stadio" di Stato restano: sono su tutto lo
  storico (1617 su 1618), un numero diverso da "37 su 120 in questo giro".
  Il titolo va cambiato in "Totale storico per stadio" per non confonderli;
- la stima "quanto manca" del riquadro coda resta: riguarda tutta la coda,
  non il giro. Le due stime possono differire, ed è giusto: su Avanzamento
  c'è scritto "in questo giro".

#### (b) Da dove viene il fatti/totale: tabella `StageRun`

Serve una tabella di "giri per stadio". Motivo nei fatti 14 e 15: il totale
lo sa solo l'agente, e contare le righe dà numeri sbagliati proprio sul
download. I log non hanno né totale né elementi.

**`StageRun`** (`stage_runs`, nella stessa migrazione `0026`): una riga per
ogni stadio di ogni giro.

- Chi: `run_id` (lo stesso codice di `LLMCall`), `stage`, `source` (cron /
  avviato a mano / comando), `job` (facoltativo, `SET_NULL`), `pid`.
- Stato: `waiting` (deve ancora partire) / `running` / `done` / `failed`,
  più `error` (frase corta) e `note` (es. "fermato: quota Instagram").
- Conteggi: `total` (vuoto finché l'agente non lo dichiara), `done`,
  `failed`, `skipped`, `unit` (reel, articoli, account, fonti), `phase`
  (nome della fase in corso), `phases` (elenco corto delle fasi già finite
  con i loro numeri).
- Adesso: `current` (tipo, id, nome dell'elemento e chi lo lavora), per gli
  stadi che non chiamano un LLM.
- Tempi: `started_at`, `phase_started_at`, `updated_at`, `finished_at`.
- Indici: `status`, `run_id`.

Chi la scrive:

- **`DAG.run`** (`pipeline/dag.py`): all'inizio del giro crea una riga
  `waiting` per ogni stadio previsto, così si vede anche cosa deve ancora
  arrivare; porta ogni stadio a `running`, poi a `done` o `failed` (con la
  frase dell'errore). È lo stesso punto dove il primo disegno metteva `scope`.
- **Gli agenti**, con un aiuto nuovo e minuscolo, `BEC/core/progress.py`, che
  fa tre cose: "apro il conteggio" (totale, unità, fase), "inizio un
  elemento" (tipo, id, nome), "elemento finito" (riuscito / fallito /
  saltato). Circa 11 punti in 7 file. "Inizio un elemento" serve due
  padroni: aggiorna la barra **e** dice a `LLMCall` quale elemento sta
  lavorando (punto c).
- Scritture frenate: al massimo una ogni 2 secondi per barra, più una a fine
  fase. Protette come quelle di `LLMCall`: se il database non risponde, lo
  stadio va avanti.

Cosa conta ogni stadio:

| Stadio | Totale | Fasi | Chi lavora |
|---|---|---|---|
| `scrape` | account attivi (23) | una | Apify, nessun modello |
| `download` | reel presi in questo giro, dopo il tetto | una | nessun modello |
| `transcribe` | reel da trascrivere | una | Whisper remoto o locale, per elemento |
| `batch` | consegne da ritirare, poi elementi da consegnare | ritiro, consegna | Anthropic in blocco |
| `enrich` | reel da analizzare, poi reel per le affermazioni | analisi, affermazioni | da `LLMCall` |
| `embed` | non dichiarato in v1 | - | modello di vettori locale |
| `blogscrape` | fonti attive (30); nella nota "3 di 12 articoli" | una | nessun modello |
| `knowledge` | articoli | analisi, affermazioni, vettori | da `LLMCall` |
| `cluster` | non dichiarato in v1 | - | locale + un modello per i nomi |

Uno stadio che non dichiara il totale mostra "in corso da 3 min" senza
numeri: come tqdm quando non conosce il totale. Onesto, e non blocca niente.

**Velocità e tempo rimanente** li calcola il server: fatti diviso tempo della
fase in corso; rimanente = quelli che mancano diviso la velocità. Prima di 3
elementi fatti la velocità vera non c'è: si usa quella dei giri precedenti
già calcolata da `core/queue_eta.py` (`_measured_rates`, per download,
trascrizione e analisi) e la si chiama "stima dai giri precedenti"; per gli
altri stadi si mostra "-". Per gli stadi con LLM si aggiungono i token al
secondo, da `LLMCall`.

**I Job** (upload, link, scansione di un blog, ideazione, strategia...): una
barra ciascuno con la percentuale e la frase che `Job` ha già. Niente
fatti/totale e niente tempo rimanente, perché il Job non li conosce (fatto
21): inventarli sarebbe peggio che non mostrarli. Il Job "pipeline" non ha
una barra sua: si vedono i suoi stadi, con scritto "giro avviato a mano".

**Il Batch**: un blocco a parte, "In consegna", letto da `BatchRun`: quanti
elementi, di che tipo, consegnati quando, "risposta attesa entro" (consegna
più 24 ore), modello. I numeri di ritorno sono quelli dell'ultimo giro della
pipeline, e la pagina lo dice. Nessuna barra che finge di muoversi.

**Giri interrotti**: se il processo muore, le sue righe `waiting` e `running`
vengono chiuse come `failed` ("giro interrotto"), con la stessa regola delle
righe fantasma di `LLMCall` (processo sparito o 3 ore). Nessun ritento.

#### (c) L'elemento in lavorazione adesso

Sotto la barra dello stadio in corso, una riga per elemento (fino a 5, poi
"e altri N"):

- stadi con LLM: dalle righe aperte di `LLMCall` di quel giro. Nome
  dell'elemento, modello, etichetta **locale** / **remoto**, stato (in coda
  per il modello locale / sta leggendo / sta scrivendo), token finora e token
  al secondo se locale, secondi passati;
- stadi senza LLM (download, trascrizione, raccolta): da `StageRun.current`.

Come `LLMCall` sa quale elemento: "inizio un elemento" lascia il nome in
un'etichetta legata al filo di esecuzione, e il registratore la legge quando
crea la riga. Su `enrich` va messa **dentro** il lavoro del singolo thread
(`_with_retry`), non nel ciclo principale: lì i risultati arrivano in ordine
e in ritardo. Attenzione per lo sviluppatore: con `ENRICH_WORKERS=1` quel
codice non passa da `_with_retry`, e il contatore va protetto perché lo
toccano 5 thread.

Chi lavora si scrive sempre a parole, mai solo con un colore: "locale",
"remoto", "in blocco (risposta entro 24 h)", "nessun modello".

#### (d) Ogni quanto si aggiorna, e quanto costa

- **Ogni 2 secondi** se qualcosa gira, **ogni 15** se è tutto fermo. A
  scheda nascosta non chiede niente (comportamento già predefinito di
  react-query; nessun file imposta `refetchIntervalInBackground`). Il tempo
  passato scorre ogni secondo sul telefono con `useTicker`, senza chiamate.
- **Endpoint leggero e separato**, `ops/progress/`: 4 letture su colonne
  indicizzate (stadi dell'ultimo giro, chiamate aperte, Job attivi, consegne
  aperte). Niente comandi di sistema, niente lettura del log. Attesa: poche
  decine di millisecondi, contro i 350-700 di `ops/status/` (fatto 16). Da
  cronometrare in collaudo: se supera 50 ms, si dice.
- La chiusura delle righe fantasma è una scrittura: al massimo una volta
  ogni 30 secondi, non a ogni richiesta.
- Scritture in più durante un giro: una ogni 2 s per la barra, una ogni 2 s
  per ogni chiamata locale aperta, due per ogni chiamata remota. Con un picco
  di 141 analisi al giorno sono poche migliaia di aggiornamenti di una riga.

#### (e) Sul telefono, a 380 px

Una colonna sola, niente tabelle, niente scorrimento laterale. "Stile tqdm"
vuol dire gli stessi quattro numeri nello stesso ordine, non la barra fatta
di caratteri: a 380 px non ci sta e uscirebbe dai token del brand.

- Stadio **in attesa**: una riga sola, nome e "in attesa".
- Stadio **finito**: una riga sola, "120 su 120 in 14 min", più "2 non
  riusciti" se ci sono.
- Stadio **in corso**: scheda aperta. Nome e fase; la barra (stessa di
  Stato, alta 8 px, con `role="progressbar"`); sotto, quattro caselle due
  per due: **Fatti** 37/120 · **Velocità** 4,2 al min · **Passato** 8 min ·
  **Mancano** circa 19 min. Poi le righe "sta lavorando", troncate con i
  puntini.

Così a 380 px si vedono 9 righe corte e una scheda aperta. Da 640 px in su
le quattro caselle stanno su una riga. Numeri con `tabular-nums` perché non
ballino. Si riusano `fmtDuration`, `useTicker`, `elapsedNow`, `Badge`,
`Skeleton`, `PanelError`. Ordine della pagina: Adesso, In consegna, Oggi.

#### (f) Quando non gira niente, e quando uno stadio fallisce

- **Niente in corso**: "Non sta girando niente. Ultimo giro: oggi alle
  14:15, 5 minuti, 9 stadi su 9." Sotto, l'ultimo giro chiuso (una riga per
  stadio) e le consegne in blocco ancora aperte, che esistono anche a
  macchina ferma. Gli orari dei prossimi giri restano su Stato, con un
  collegamento.
- **Prima installazione** (tabella vuota): "Qui comparirà l'avanzamento dal
  prossimo giro."
- **Stadio fallito**: la scheda resta aperta, con icona e la parola
  "Fallito" (non solo il rosso), la barra ferma dove si è fermata, una frase
  in chiaro sul motivo (si riusa `_client_message` di `upload_workflow.py`)
  e "37 fatti su 120 prima dell'errore". Gli stadi dopo continuano, come già
  fa la pipeline, e si vedono partire sotto.
- **Giro interrotto**: "Interrotto alle 04:12: il processo si è fermato."
- **Elementi non riusciti dentro uno stadio riuscito**: "2 non riusciti",
  senza promettere che verranno riprovati.
- La pagina è di sola lettura: nessun pulsante "riprova".

#### File da toccare, in più o cambiati

| File | Perché |
|---|---|
| `BEC/core/models.py`, `migrations/0026_*` | anche `StageRun`; 4 colonne in più su `LLMCall` |
| `BEC/core/progress.py` (nuovo) | apro il conteggio / inizio elemento / elemento finito |
| `BEC/pipeline/dag.py` | crea e chiude le righe degli stadi (oltre al blocco `scope`) |
| `downloader_agent`, `transcriber_agent`, `enrich_agent`, `knowledge_agent`, `blogscrape_agent`, `scraper_agent`, `batch_agent` | dichiarare totale ed elementi: circa 11 punti |
| `BEC/llm/client.py`, `BEC/llm/usage.py` | riga anche all'inizio per i remoti; nome dell'elemento |
| `BEC/core/progress_report.py` (nuovo, al posto di `llm_report.py`), `views.py`, `urls.py` | i due endpoint |
| comando di pulizia | pulisce anche `StageRun` |
| `BEC/core/tests/test_progress.py` (nuovo) | 5 thread sullo stesso contatore, database spento, stadio fallito, giro interrotto |
| `FEC/src/pages/Progress.tsx` (al posto di `LocalProcesses.tsx`), `components/ops/StageBar.tsx` e simili | la pagina |
| `FEC/src/pages/Status.tsx`, `components/ops/LiveActivity.tsx` | togliere i doppioni (punto a) |
| `Sidebar.tsx`, `App.tsx`, `i18n/it.json` | voce di menu e testi |

Non si toccano `embed_agent` e `cluster_agent`, né `queue_eta.py` e `ops.py`
(si leggono soltanto).

Documentazione, in più rispetto a prima: `02-pipeline.md` prende un
paragrafo vero (ogni stadio dichiara il suo avanzamento), `01-data-model.md`
due tabelle, `05-rest-api.md` due endpoint, `06-frontend.md` la pagina nuova
e cosa è uscito da Stato. **Il drawio adesso cambia**: una nota a pagina 2
(gli stadi scrivono in `stage_runs`). La pagina `Documentazione` dice al
cliente dove guardare.

#### Rischi nuovi

- **`owner_type`**: `StageRun` non ha proprietario e non contiene contenuti.
  La pagina non divide per Medyca/competitor, quindi nessun terzo valore può
  nascere. Lo stato `batched` non viene letto dalle righe: il blocco "In
  consegna" legge solo `BatchRun`.
- **I falliti restano `failed`**: le righe di un giro interrotto si chiudono
  come fallite e basta. Questa tabella non rimette in coda niente e non
  tocca le colonne di stato di reel e articoli.
- **Credenziali**: nessuna. La pagina non interroga Anthropic per lo stato
  del batch.
- **Sette agenti toccati**: è la parte più larga del lavoro. Ogni aggiunta è
  di una o due righe e non può fermare lo stadio, ma va collaudata con un
  giro vero e con il database spento a metà.
- **Due verità sui giri**: `RunTimeline` di Stato legge il log, Avanzamento
  legge `StageRun`. Su uno stadio fallito possono dire cose diverse (fatto
  18). Vedi domanda 9.
- **Nomi in chiaro**: nella tabella finiscono nomi di account e titoli di
  articoli, anche dei competitor. Sono già visibili nel resto dell'app.
- **Due giri insieme** (cron e avvio a mano): la pagina li mostra come due
  gruppi. Non verificato se oggi possa succedere davvero.

#### Cosa resta fuori (in più)

- `embed` e `cluster` con il conteggio: in v1 solo "in corso da X".
- I comandi lanciati a mano (`reprocess`, `ingest_blog`, `sonnet_batch`):
  senza barra. Le loro chiamate al modello si vedono come righe sciolte.
- Lo stato in diretta del batch presso Anthropic.
- Fatti/totale e tempo rimanente per i Job: solo la percentuale che hanno.
- La storia dei giri passati su questa pagina: solo l'ultimo.
- Correggere `RunTimeline` e far leggere a `queue_eta.py` la tabella nuova
  al posto del log: possibile dopo, non ora.
- Il comando da terminale `manage.py progress`: resta com'è.
- La barra fatta di caratteri, come nel terminale.

#### Domande aperte

Le sei di prima restano. Cambiano tre:

- **2 (Whisper)**: la trascrizione ora compare comunque, come barra, con
  scritto chi lavora. Resta da decidere solo se le sue ore entrano nel
  totale "Oggi".
- **5 (lentezza)**: chiusa dal registro delle decisioni e dalla PR #19.
- **6 (registrare i remoti)**: la richiesta nuova lo rende necessario, e
  anche all'inizio della chiamata. Serve solo una conferma.

Nuove:

7. **Va bene una pagina sola chiamata "Avanzamento"**, al posto di "Processi
   locali"? Dentro c'è tutto, locale e remoto.
8. **Posso togliere da Stato "Job in corso" e ridurre "In questo momento" a
   un collegamento?** Se preferisci non toccare Stato, gli stessi numeri si
   vedranno in due pagine.
9. **Lo stadio fallito che su Stato sembra "in corso" (fatto 18)**: lo
   correggiamo qui o con un lavoro a parte? Io direi a parte.
10. **`embed` e `cluster` senza numeri in v1** ("in corso da 3 min"): basta?
11. **Il batch senza barra viva**, solo "consegnati, risposta entro le ...":
    basta, o vuoi che la pagina chieda lo stato ad Anthropic?
12. **Nomi in chiaro** (account e titoli, anche dei competitor) salvati per
    90 giorni nella tabella delle chiamate: va bene?

## 3. Sviluppo           (sviluppatore)

Ramo `feat/processi-locali` da `main`. Disegno seguito nella versione «Revisione del disegno
(tqdm)», con il Registro delle decisioni (12 scelte chiuse).

### Cosa è stato fatto

**Dati.** `core/models.py` + `migrations/0026_llmcall_stagerun.py` (solo file: non applicata al
database di produzione). `StageRun` (`stage_runs`) e `LLMCall` (`llm_calls`) come da disegno, con le
quattro colonne in più (`item_kind`, `item_id`, `item_label`, `stage_run`). `makemigrations --check`
pulito.

**Registratore** `BEC/llm/usage.py`, agganciato in `BEC/llm/client.py` (`chat()`): riga `waiting`
prima del lucchetto, `running` quando lo prende, token in diretta ogni 2 s (un pezzo = un token),
numeri veri dall'ultima riga di Ollama, `truncated` su `done_reason=length` e su timeout con testo
parziale. Remoti (`_fast_chat`, `_anthropic_chat`, `_hf_chat`): riga all'inizio e aggiornamento a
fine, token da `usage`. Ogni scrittura è dentro un savepoint e protetta; un errore di database
accende un interruttore di 30 s così una chiamata al modello non paga un timeout di connessione in
più. Mai salvati prompt o risposta (c'è un test che lo controlla).

**Etichetta del processo**: `usage.scope()` (contextvar + riserva di processo, vedi sotto).
Messa in `DAG.run` (`pipeline:<stadio>`), `run_job.handle` (`job:<tipo>`), `knowledge.answer`
(`web:chat`) e nel riordino (`mcp:cerca`, solo se nient'altro etichetta). Senza blocco:
`cmd:<comando>` o `altro`.

**Contatori** `BEC/core/progress.py` (`plan_stages`, `bind`, `end_stage`, `open`, `start_item`,
`item_done`, `note`, `who`, `describe`). Agganciato in `dag.py` (righe per stadio, `waiting` poi
`running`/`done`/`failed`, righe non partite cancellate, frase d'errore in chiaro da
`_client_message`; `DAG.run` ha ora `source` e `job_id`; `pipeline_run` passa `manual` + job id,
`run_pipeline` distingue `command` da `cron` col terminale) e in 7 agenti: `scraper`, `downloader`,
`transcriber`, `batch`, `enrich`, `blogscrape`, `knowledge`. In `enrich` il conteggio sta **dentro
il thread** (`_tracked`, una volta per elemento, non per ritentativo di rate limit) e il contatore
è sotto lucchetto; funziona anche con `ENRICH_WORKERS=1`.

**Lettura** `BEC/core/progress_report.py` + `views.py`/`urls.py`: `GET /api/v1/ops/progress/` (6
letture indicizzate, un test lo blocca con `assertNumQueries(6)`) e `GET /api/v1/ops/llm/?day=`.
Velocità e rimanente calcolati dal server (misurata dopo 3 elementi; prima, «dai giri precedenti»
da `queue_eta._measured_rates`, con cache di 60 s; altrimenti nulla). Stime della singola
chiamata: «di solito ancora» (mediana di ≥5 risposte finite dello stesso processo) e «al massimo».
Righe fantasma chiuse `failed` («processo interrotto» / «giro interrotto»), al massimo ogni 30 s.

**Pulizia** `manage.py prune_llm_calls` (`--days`, `--dry-run`), `LLM_CALL_RETENTION_DAYS=90` in
`base.py` e `.env.example`. Cancella solo righe chiuse (`done`/`failed`).

**Frontend** `FEC/src/pages/Progress.tsx` (`/avanzamento`, voce «Avanzamento» sotto «Stato
pipeline», nuova icona `IconProgress`), `api/progress.ts`, `components/progress/` (`StageCard`,
`ModelLines`, `BatchBlock`, `DailyTotals`, `format.ts`). Letto `ui-design`: solo token del brand,
una colonna, niente tabelle, quattro caselle 2x2 e 1x4 da 640 px, `role="progressbar"`, chi lavora
sempre a parole, stati vuoto/caricamento/errore/dati vecchi. Aggiornamento ogni 2 s se gira
qualcosa, 15 s se fermo; il tempo passato scorre col `useTicker`. **Stato** (decisione 8): tolto
«Lavori in corso»; `LiveActivity` ridotta a una riga + collegamento «Segui l'avanzamento» (resta
la barra della rianalisi); titolo barre cambiato in «Totale storico per stadio».

**Documentazione**: `01-data-model.md` (due tabelle + diagramma), `02-pipeline.md` (paragrafo
«Progress of a round» + comandi), `03-llm-and-embeddings.md` («What is recorded for each call»;
tolta la frase «non c'è conteggio dei token», ora falsa), `05-rest-api.md` (2 endpoint),
`06-frontend.md` (pagina e cosa è uscito da Stato), `.claude/architecture-summary.md`, pagina
`Documentazione` dell'app (sezione «Dove vedere cosa sta succedendo» + un limite), nota a pagina 2
di `docs/medycabrain-pipeline-cliente.drawio` (XML verificato).

### Prove, esito vero

- `manage.py test` (tutta la suite, database di prova privato): **227 test, OK** (erano 177;
  +20 in `test_llm_usage.py`, +30 in `test_progress.py`). Dentro: database spento (create/update che
  sollevano `OperationalError`, interruttore), errore generico di scrittura, savepoint dentro
  `atomic`, 5 thread sullo stesso contatore (500 su 500), riserva di processo nei thread di un
  pool, una barra non conta due volte un ritentativo, stadio fallito con frase senza percorsi,
  stadio fatale che non lascia righe `waiting`, giro interrotto, velocità prima dei 3 elementi,
  nessun prompt/risposta salvati, totali del giorno (ore locali + Whisper vs riga remota),
  pulizia che tiene le righe aperte.
- `makemigrations --check --dry-run`: «No changes detected».
- `npm run build` (`tsc -b && vite build`): **OK**, 0 errori, `Progress-*.js` 18,75 kB.

Il database dei test è un Postgres 16 usa-e-getta avviato in una cartella temporanea sulla porta
55432 (`DATABASE_URL=postgres://testuser@127.0.0.1:55432/postgres`): l'utente del `.env` non può
creare database. Spento a fine lavoro. Il database di produzione non è stato toccato.

### Differenze dal disegno

1. **Colonna `kind` (`chat`|`stt`) in `LLMCall`**, non prevista: serve per mettere le ore di
   Whisper nel totale «Oggi» (decisione 2) senza confonderle con le chiamate al modello. Whisper
   locale conta nelle ore-macchina; Whisper remoto va nella riga «remoto» (non è tempo della
   macchina).
2. **La riserva di processo di `usage.scope` si imposta solo dal thread principale.** In un server
   web le richieste girano in thread e una variabile condivisa farebbe passare l'etichetta di una
   richiesta in un'altra (e si ripristinerebbe fuori ordine). Pipeline e Job sono thread principale.
3. **Fase «Consegna» del batch conta gli elementi** (come da disegno) ma solo se c'è una barra
   legata (`progress.is_bound()`): contarli carica le liste di pendenti una volta in più.
4. **`LLMCall` si cerca per stadio con `stage_run`**; le chiamate senza stadio (chat, MCP,
   comandi, Job) escono in `other_calls` come righe sciolte sulla pagina, non nascoste.
5. **Nessuna stima per «sta leggendo il prompt»**: la scheda dice solo «sta leggendo». Le stime
   «di solito/al massimo» ci sono solo quando sta scrivendo (il disegno chiedeva anche quella da
   lunghezza del prompt: non ho un campione misurato su cui basarla).
6. **Il comando di pulizia cancella solo righe chiuse**; quelle ancora aperte le chiude la pagina.
7. **«Mancano» per `batch`/`scrape`/`blogscrape` sono «—» finché non ci sono 3 elementi** e non
   c'è storico: nessun numero inventato.

### Cosa non ho potuto provare

- **Un giro vero** (pipeline notturna o «Aggiorna ora») con la tabella viva: la migrazione non è
  applicata alla produzione per ordine, quindi la pagina non ha mai visto dati reali. Le 7 modifiche
  agli agenti sono provate solo dove ci sono test (`enrich` via `_parallel`, `DAG.run`); `scraper`,
  `downloader`, `transcriber`, `batch`, `blogscrape`, `knowledge` sono controllati leggendo il
  codice e con import/compilazione, non eseguiti. Il collaudatore deve fare un giro vero dopo
  `migrate`, e provare col database spento a metà.
- **La pagina nel browser**, a 380 px e su desktop: costruita e compilata, mai vista. Il collaudo
  da utente vero resta da fare (anche il tempo di risposta di `/ops/progress/` contro i 50 ms
  scelti come soglia: nei test sono 6 query, non l'ho cronometrato su dati reali).
- **Una chiamata vera a Ollama** con la riga registrata: i test usano uno stream finto con la
  forma verificata dal capo (pezzi = token, ultima riga con `eval_count`). Il campo `usage` dei
  remoti è ancora «supposto» come nel disegno; se manca, i token restano vuoti e la riga si scrive.
- `OLLAMA_NUM_THREAD` non è stato toccato (già su main).

### Cosa resta fuori

Come da disegno: `embed` e `cluster` senza conteggio, comandi a mano senza barra, stato in
diretta del Batch presso Anthropic, fatti/totale per i Job, storia dei giri passati, correzione di
`RunTimeline` (fatto 18), alzare `num_ctx` oltre 4096, lasciare Anthropic/Apify. La riga nel
crontab per `prune_llm_calls` la aggiunge il rilasciatore, con conferma (una volta al giorno).
La copia `FEC/public/docs/medycabrain-pipeline-cliente.drawio` era già diversa da
`docs/` prima di questo lavoro: non l'ho riallineata. `FEC/dist` (ignorato da git) è stato
ricostruito dalla build: se il sito live serve quella cartella ora vede già la pagina nuova, che
senza la migrazione mostra solo errore di caricamento (le tabelle non esistono ancora).
### Secondo giro

Corretti i rilievi non bloccanti di revisione e collaudo (stesso ramo, nessuna migrazione nuova).

- **Giri lunghi chiusi per errore** (`llm/usage.py` `close_ghosts`, `core/progress.py` `bind`): per
  `StageRun` il tetto delle 3 ore guarda `updated_at`, non `created_at`; uno stadio `waiting` di un
  giro che batte ancora (un'altra riga dello stesso `run_id` scritta di recente) non si chiude; pid
  morto chiude subito come prima. `bind()` azzera `error` e `finished_at`. L'`update` ripete
  `status__in`. Le righe `LLMCall` restano col vecchio criterio (si scrivono a inizio e fine).
- **Stadio riuscito che sembra fallito**: `usage.guard(..., force=True)` ignora l'interruttore e,
  se riesce, lo azzera; `end_stage` lo usa. Se il database e' ancora spento in quel momento la riga
  resta `running` e la pagina la chiude come «giro interrotto»: limite scritto in `02-pipeline.md` e
  nel docstring di `progress.py`.
- **Tabella mancante**: `ProgrammingError` accende lo stesso interruttore (un avviso, non uno per
  scrittura). Cambia anche il rilievo 1 del revisore sul docstring dell'interruttore.
- **`tokens_so_far`** a fine chiamata = `output_tokens` (quando c'e').
- **Testi**: «1 stadio su 1» (plurale i18n `lastRound_one/_other`); frase d'aggiornamento «ogni 2
  secondi se gira qualcosa, ogni 15 se e' fermo»; `StageCard` non ripete la fase corrente nell'elenco
  delle fasi chiuse.
- **Documentazione**: `05-rest-api.md` e docstring di `progress_report.py` («6 letture, piu' una per
  ogni processo locale con token in corso»); `note()` ora e' limitata come i contatori (la chiusura
  scrive comunque l'ultima nota), docstring allineato.
- Test nuovi: giro lungo vivo/pid riusato/pid morto/riga chiusa nel frattempo, chiusura con
  l'interruttore aperto (e con database ancora spento), `bind` che ripulisce, `ProgrammingError`
  con un solo avviso, token finali. Il test dei token in diretta ora esclude la scrittura finale.

Non corretti (fuori dall'incarico): rilievo 4 (`source="cron"` senza terminale), rilievo 5 (`error`
con `str(exc)`), le 7 query contro 6 del collaudo (probabile token di login), le prove non fatte
del collaudo (giro vero con gli agenti reali, remoti, ore di Whisper).

Esito (Postgres 16 usa-e-getta sulla porta 55433, poi spento e cancellato; produzione non toccata):

```
manage.py test --noinput                    -> Ran 236 tests in 25.229s   OK   (erano 227)
manage.py makemigrations --check --dry-run  -> No changes detected
npx tsc -b                                  -> exit 0
npx vite build --outDir <scratchpad>/dist2  -> built in 30.36s   (FEC/dist non toccata)
```

## 4. Revisione          (revisore)

**Verdetto: passa.** Nessun rilievo bloccante. Letto tutto il diff `main..feat/processi-locali`
(3 commit, solo sul ramo) e il file di lavoro. Non ho eseguito la suite (serve un database di
prova): i 227 test sono quelli dichiarati dallo sviluppatore, non li ho riprovati. `stato:` resta
`revisione` finche' il collaudo non e' scritto.

**Controllato e a posto**
- Invarianti: nessun terzo valore di `owner_type` (le tabelle nuove non hanno proprietario ne'
  contenuti); i falliti restano `failed` (le righe fantasma si chiudono `failed`, nessun ritento,
  non si toccano le colonne di stato di reel/articoli); nessuna credenziale nuova.
- Segreti: nessuno nel diff (le sole corrispondenze sono `api_key: "k"` e `password="x"` nei test).
- Migrazione `0026` non ancora applicata (cron 03:30/14:15 col codice nuovo): ogni scrittura passa
  da `usage.guard` (`BEC/llm/usage.py` righe 148-164), che apre un savepoint (`transaction.atomic`)
  e cattura `Exception`. Con le tabelle assenti il database solleva `ProgrammingError`: il savepoint
  fa rollback, non avvelena la transazione di nessuno, `begin` restituisce una `Call` senza riga
  (tutti i metodi non fanno nulla), `plan_stages` restituisce `{}` quindi `bind(None)` e i contatori
  sono no-op. La chiamata al modello e lo stadio vanno avanti; resta solo qualche avviso nel log.
  `ProgrammingError` non accende l'interruttore da 30 s (solo `OperationalError`/`InterfaceError`):
  accettabile, perche' senza riga non ci sono altre scritture.
- `client.py`: ritorni, timeout, fallback tra provider, lucchetto e `num_thread` invariati. La riga
  locale nasce prima di `_ollama_slot`, `running()` e' la prima istruzione nel `with`; `rec.done()`
  ora gira dopo il rilascio del lucchetto (il lucchetto si tiene meno, non di piu'). Per
  `provider == "fast"` l'`endpoint` non e' mai `None` (`_providers`), quindi `endpoint["name"]` e'
  sicuro.
- Nessun prompt ne' risposta salvati: `begin` scrive solo `prompt_chars`, etichette e numeri.
- Thread: contatore sotto `_lock`, `_tracked` conta una volta per elemento dentro il thread (anche
  con `ENRICH_WORKERS=1`). Il server web e' `gthread` (`deploy/medycabrain-backend.service`), quindi
  le richieste non girano nel thread principale e la riserva di processo di `usage.scope` non si
  imposta li': nessuna etichetta passa da una richiesta all'altra.
- `/ops/progress/` e `/ops/llm/`: `IsAuthenticated` come `PipelineStatusView`; niente
  `LLMCall.error` nella risposta, solo la frase in chiaro di `StageRun.error`; nomi di account e
  titoli gia' visibili nell'app (decisione 12).
- Documentazione: modelli, pipeline, LLM, REST, frontend, riassunto, pagina `Documentazione`, drawio
  pagina 2. Nessuno strumento MCP cambia, quindi `04-mcp-connector.md` giustamente non si muove.

**Rilievi non bloccanti, per gravita'**

1. `BEC/llm/usage.py` righe 306-316 (`close_ghosts`): per `StageRun` il tetto delle 3 ore usa
   `created_at`, che e' il momento del piano (inizio giro), non l'ultimo battito. Con un giro che
   dura piu' di 3 ore (plausibile quando `enrich` passera' al locale: 1617 reel x ~100 s), la prima
   lettura della pagina chiude come `failed` / "giro interrotto" anche lo stadio che sta girando e
   quelli ancora `waiting`, con il pid vivo. Poi `bind()` (`progress.py` riga 82) rimette `running`
   ma non azzera `error` ne' `finished_at`, quindi il tempo passato resta congelato, e il fine
   stadio sovrascrive tutto. Oggi un giro dura ~5 minuti, quindi non si vede; va corretto prima del
   passaggio al locale (usare `updated_at` per `StageRun`, e azzerare `finished_at`/`error` in
   `bind`). Stesso punto: l'`update` finale filtra solo `id__in=dead`, senza ripetere
   `status__in=("waiting","running")`, quindi una riga appena chiusa `done` da un altro processo
   nello stesso istante potrebbe essere riscritta `failed` (finestra minima, solo nel ramo delle 3
   ore).
2. `BEC/pipeline/agents/blogscrape_agent.py` (nuova riga prima di `to_fetch`) + `progress.py` righe
   215-221: `note()` fa `_flush(force=True)`, quindi una scrittura per ogni articolo, fuori dal
   limite "una ogni 2 s" scritto in disegno e nel docstring. Sono poche centinaia di scritture
   protette, nessun rischio, ma il docstring non e' vero cosi' com'e'.
3. `documentation/low-level/05-rest-api.md` e `progress_report.py` docstring dicono "6 letture" /
   "four indexed reads": il numero cambia (una query in piu' per ogni processo locale con
   `tokens_so_far`, `_typical_tokens`). Il test blocca 6 solo nello scenario provato. Da dire
   "6 piu' una per processo locale in scrittura".
4. `run_pipeline.py`: `source = "command" if sys.stdin.isatty() else "cron"` etichetta come `cron`
   qualunque avvio senza terminale (anche un avvio da servizio o da un agente). Solo l'etichetta
   sulla pagina.
5. `usage.Call.fail` (`usage.py` riga 231): `error` contiene `str(exc)` troncato a 200 caratteri;
   un `HTTPError` di `requests` ne riporta l'URL. Oggi gli endpoint non hanno chiavi nell'URL e il
   campo non e' mai esposto dall'API, quindi non e' un problema; da ricordare se un provider mettera'
   la chiave nella query.
6. Non verificato da me ne' dallo sviluppatore: giro vero dopo `migrate`, database spento a meta',
   pagina a 380 px e desktop, tempo di `/ops/progress/` contro i 50 ms. Tocca al collaudatore
   (`scraper`, `downloader`, `transcriber`, `batch`, `blogscrape`, `knowledge` sono letti, non
   eseguiti). Ordine suggerito: applicare `0026` e solo dopo far girare un giro.

## 5. Collaudo           (collaudatore)

**Verdetto: PASSA**, con 5 note non bloccanti (in fondo) e un elenco di cose non provate. Collaudo del 13/11/2026 sul ramo `feat/processi-locali`. Tutto su una copia a lato: Postgres 16 temporaneo (porta 55432), `runserver` su 8031, frontend del ramo servito su 8032 (file statici + proxy). Il sito vero (9093), il suo database, `BEC/.env` e `FEC/dist` non sono stati toccati. A fine collaudo tutto è spento (porte 8031, 8032, 55432 libere; 9093 risponde 200 come prima; `git status` pulito a parte questo file).

### 1. Suite, migrazioni, tipi, build

```
$ python manage.py makemigrations --check --dry-run   ->  No changes detected
$ python manage.py check                              ->  System check identified no issues (0 silenced).
$ python manage.py test --noinput                     ->  Ran 227 tests in 28.536s   OK
$ npx tsc -b                                          ->  exit 0, nessun errore
$ npx vite build --outDir <scratchpad>/dist           ->  ✓ built in 20.88s   (git status pulito: FEC/dist non toccata)
```

### 2. Il cron senza migrazione (database fermo a 0025, `llm_calls`/`stage_runs` assenti)

Verificato: `showmigrations` -> `[X] 0025_search_indexes`, `[ ] 0026_llmcall_stagerun`; `\dt llm_calls` -> «Did not find any relation». Poi, col codice del ramo:

```
model qwen2.5:3b-instruct-q4_K_M order ['ollama'] threads 6
tables present: []
plan_stages -> {}
query inside atomic after chat: 0          <- query dopo chat() DENTRO transaction.atomic: la transazione non è avvelenata
chat out: 'Ciao!' 1.5s                     <- chiamata vera a Ollama, riuscita
connection usable: True in_atomic: False
```
Righe di log prodotte: 3 `WARNING llm.usage [usage] ... ProgrammingError('relation "stage_runs"/"llm_calls" does not exist')` (piano degli stadi, riga di chiamata, pulizia). Nessuna eccezione.
Poi `DAG.run` vero con 3 stadi finti (uno che apre il conteggio e scrive elementi, uno che solleva, uno ok) sullo stesso database:
```
✓ scrape done   ✗ download FAILED: RuntimeError('boom')   ✓ transcribe done
✗ failed steps: download        exit code 1 connection usable True
```
Esito: **passa**. Il comportamento è quello di prima della modifica (stadi e chiamate vanno, il fallimento resta fallimento, codice di uscita 1). Nota: l'errore «tabella mancante» è `ProgrammingError`, non `OperationalError`, quindi l'interruttore da 30 s **non** scatta: a ogni scrittura il programma riprova e fa un warning. Con un giro vero senza migrazione i warning sono pochi (lo stadio non ha riga legata, quindi `progress` non scrive), ma una chiamata `chat()` in un giro lungo farebbe un tentativo + warning per chiamata. Costo: una query fallita per scrittura. Non rompe niente.

### 3. Chiamata vera a Ollama via `client.chat` (copia a lato, `OLLAMA_NUM_THREAD=6`)

Modello 3b (quello del `.env`), prompt corto, `max_tokens=60`. Stati letti da `psql` ogni ~3 s:
```
17:52:26 | running | qwen2.5:3b... | tokens_so_far 1
17:52:30 | running | qwen2.5:3b... | tokens_so_far 30
17:52:33 | done    | qwen2.5:3b... | so_far 49 | prompt 39 | output 60 | wait 0.0 | durata 9.2 | eval 7.8 | truncated t
```
Riga finale: `load_seconds 0.01, prompt_seconds 1.26, eval_seconds 7.78, prompt_tokens 39, output_tokens 60, max_tokens 60, status done, truncated t` (tetto di token raggiunto: giusto). **3b: 60 token in 7,78 s = 7,7 token/s** (il 3b non era misurato).
Modello 7b, due processi insieme (per vedere la coda): 
```
id 2 done | 7b | wait 0      | durata 120.6 | load 103.69 | prompt 2.96 | eval 13.93 | out 60   -> 4,3 tok/s (a freddo, caricamento 104 s)
id 3 done | 7b | wait 119.14 | durata 12.63 | load 0      | prompt 0.24 | eval 12.34 | out 60   -> 4,9 tok/s
```
La seconda chiamata ha aspettato 119 s il lucchetto (stato `waiting` -> `running` -> `done`, `wait_seconds` giusto). 7b a 4,3-4,9 tok/s: un po' sopra il 3,8-4,0 atteso, plausibile (prompt corto). `tokens_so_far` si muove durante la generazione (1 -> 30 -> 49) e cresce a ogni poll. Nota: a fine chiamata `tokens_so_far` resta l'ultimo valore scritto (49, 55, 52) e non diventa uguale a `output_tokens` (60); la pagina usa `output_tokens` quando la riga è `done`, quindi non si vede, ma il campo non è «sostituito dal numero vero» come dice il disegno (fatto 3). Esito: **passa**.

### 4. Stadio simulato con `progress` (totale, avanzamenti, un fallimento a metà)

`DAG.run` con 4 stadi finti (scrape 6, download 40 con eccezione dopo 12, transcribe 60 a 1/s con 1 elemento fallito, enrich 3 chiamate vere a Ollama). `GET /api/v1/ops/progress/` a metà giro (estratto):
```
scrape      done    6/6   who=none   phases=[{done 6, total 6, seconds 2}]
download    failed  12/40 error "Errore imprevisto durante la lavorazione."  (RuntimeError con percorso interno: il percorso NON compare)
transcribe  running 6/60  rate_per_minute 56.85  rate_source "measured"  eta_seconds 57  who "stt"  current {kind reel, label "@competitor · tr5"}
enrich      waiting
```
Pagina a 18/60: «53,8 al min · passato 21s · mancano circa 47s». Per `enrich` (locale): «86 token · 5,4 token/s · sta scrivendo · locale · qwen2.5:3b»; «Velocità 5,3 al min, stima dai giri precedenti» (letta dal `logs/pipeline.log` vero, come da disegno). Stadio fallito: «Fallito», «12 fatti su 40 prima dell'errore».
**Tempo di risposta** di `/ops/progress/`: con `curl` via proxy 8 richieste = 39, 44, 47, 49, 52, 68, 125, 47 ms (il 125 ha anche autenticazione e runserver); nel processo Django (10 richieste, test client) **15 / 19 / 53 ms (min/mediana/max)**, **7 query** (il test del ramo dice `assertNumQueries(6)`: la settima è probabilmente il token di login del client reale, non l'ho isolata). `/ops/llm/?day=` 26 ms. Soglia dei 50 ms: la mediana la rispetta, le richieste reali via HTTP stanno intorno a 40-70 ms, quindi **al limite**; dati reali (migliaia di righe) non provati.
Processo ucciso con `kill -9` a metà giro: dopo ~3 s la pagina mostra «Interrotto alle 18:06: il processo si è fermato.» e le righe passano a `failed` / «giro interrotto» (la prima lettura dell'endpoint subito dopo la kill diceva ancora `running: true`: la pulizia è limitata a una volta ogni 30 s, come da disegno).

### 5. La pagina da utente vero (Chromium headless, Playwright in un venv a lato; login vero con utente creato nel database a lato)

Screenshot in `/tmp/claude-1001/-home-medyca-admin-projects-medycabrain/0d4cff47-c166-46c1-b8e9-f2d9487add1c/scratchpad/shots/` (m = 380 px, d = 1280 px):
- niente in corso, tabelle vuote: `empty-m.png`, `empty-d.png` («Qui comparirà l'avanzamento dal prossimo giro.»)
- niente in corso, dopo un giro: `idle-m.png`, `idle-d.png` («Non sta girando niente. Ultimo giro: oggi alle 18:04, 3 min, 1 stadi su 1.»)
- stadio in corso con barra: `running-m.png` (transcribe 18/60, con download fallito e scrape finito sopra), `live-m.png` e `live-d.png` (enrich locale, riga «sta scrivendo ... 86 token 5,4 token/s»), `enrich*.png`
- stadio fallito: visibile in `running-m.png` (scheda rossa con icona, parola «Fallito», frase, «12 fatti su 40 prima dell'errore»)
- giro interrotto: `killed-m.png`
- caricamento: `loading-m.png` (riquadro vuoto in attesa mentre «Oggi» è già visibile); errore: `error-m.png` («Non riesco a leggere l'avanzamento. Controlla la connessione e riprova.» + «Riprova»; risposta 500 simulata con intercettazione di rete)
- Stato: `stato-m.png`, `stato-d.png`
Misure: `scrollWidth` = 380 a 380 px e 1280 a 1280 px su tutte le viste (nessuno scorrimento orizzontale); nessun errore in console. Menu a sinistra su desktop: «Avanzamento» compare subito sotto «Stato pipeline», voce evidenziata sulla pagina. Le quattro caselle (Fatti, Velocità, Passato, Mancano) stanno 2x2 a 380 px (viste con gli occhi in `running-m.png` e `live-m.png`).
**Pagina Stato**: sparito «Job in corso»; «Ora in esecuzione» dice «Quello che sta girando adesso si vede nella pagina Avanzamento.» + «Segui l'avanzamento, stadio per stadio»; il titolo è «Totale storico per stadio». Esito: **passa**. (Nota: il «La raccolta riparte il .» con data vuota è sul database a lato vuoto, non l'ho attribuito al ramo.)
**Da guardare con occhi umani**: gli screenshot sopra sono stati guardati da me; il giudizio estetico (colori, peso del rosso del fallito, ritmo delle schede) resta a Giuseppe. Indirizzo/gesto: sul sito vero, dopo il rilascio, aprire `/avanzamento` e fare «Aggiorna ora» da Stato a telefono.

### 6. Database spento a metà di uno stadio

Postgres fermato (`pg_ctl stop -m fast`) a 18:07:12 mentre girava `transcribe` (30 elementi), riacceso a 18:07:52, con `enrich` (3 chiamate vere a Ollama, 400 token) nel mezzo:
```
WARNING llm.usage [usage] avanzamento non registrato: OperationalError('connection ... Connection refused')   (1 solo warning per stadio: l'interruttore da 30 s funziona)
✓ transcribe done in 30.1s     ✓ enrich done in 50.4s     ✓ all steps completed
```
**Lo stadio prosegue e finisce**, le chiamate a Ollama funzionano a database spento. Prezzo: le righe scritte durante il buco mancano (le 3 chiamate di `enrich` non sono in `llm_calls`), e la riga `transcribe` è rimasta `running 10/30`: poi la pagina l'ha chiusa come `failed` «giro interrotto» pur essendo lo stadio finito bene (vedi nota 2). Esito: **passa** per il requisito (non si ferma), con questo limite.

### Note non bloccanti (da decidere, non fermano il verdetto)

1. Tabelle mancanti = `ProgrammingError`, non scatta l'interruttore: un tentativo e un warning per scrittura. Se il cron girasse senza migrazione il log si riempie di warning, nient'altro.
2. Dopo un database spento a metà stadio, quello stadio può apparire «Fallito: giro interrotto» pur riuscito (il processo era vivo ma la riga non è stata aggiornata prima che il pid sparisse). Comunque è l'unico caso in cui la pagina «mente» in negativo; va scritto tra i limiti noti.
3. Piccoli difetti di testo: «1 stadi su 1» (plurale); sotto «ADESSO» la frase «Si aggiorna da solo ogni 2 secondi» resta anche quando non gira niente (e allora è ogni 15 s); «Fase: download · download 12/40» ripete la parola (probabilmente effetto dei nomi che ho dato io alle fasi nella simulazione).
4. `tokens_so_far` non è riallineato a `output_tokens` a fine chiamata (punto 3).
5. 7 query invece di 6 e 40-70 ms via HTTP: al limite dei 50 ms del disegno.

### Cosa NON ho potuto provare (e perché)

- **Un giro vero con gli agenti reali** (`scraper`, `downloader`, `transcriber`, `batch`, `blogscrape`, `knowledge`, `enrich` vero): servirebbero Apify/Instagram/Whisper/Anthropic e dati; ho usato stadi finti che chiamano `progress.*` e `client.chat` come fanno gli agenti. Le sette modifiche agli agenti restano provate solo dai test e dalla lettura. Va guardato il primo giro della notte dopo il rilascio.
- **Modelli remoti** (`usage` di Anthropic/OpenAI): nessuna chiave usata; la riga remota (inizio+fine) non è stata vista con una chiamata vera.
- **Blocco «In consegna» con dati** (`BatchRun` aperti): sul database a lato non ce n'erano; visto solo il caso vuoto.
- **Ore di Whisper nel totale «Oggi»**: non provate con una trascrizione vera.
- **Menu a hamburger a 380 px** aperto, e il comportamento a scheda nascosta (nessuna richiesta in background): non guardati.
- **Dati reali in volume** (tempo dell'endpoint con migliaia di righe) e **la pagina contro il backend di produzione** (non esiste ancora la migrazione lì, per ordine).
- Il «giudizio visivo» finale è di Giuseppe (vedi sopra).
- Nota d'ambiente: ho usato l'Ollama vero del VDS (porta 11434): ho caricato prima il 7b poi il 3b; ora è caricato il 3b. Nessun'altra modifica al servizio.
## 6. Rilascio           (rilasciatore)
## Registro delle decisioni

- 2026-11-13 - Abbandono di Anthropic API / Apify fuori da questo lavoro: prima
  si misura quanto costa in tempo il modello locale, poi si decide il passaggio.
- 2026-11-13 - Giuseppe ferma il lavoro: prima va capita la lentezza del
  modello locale. Misure del capo, macchina ferma, qwen2.5 7b Q4_K_M
  (Ollama 0.40.16 e llama.cpp compilato qui con GGML_NATIVE danno gli stessi
  numeri, quindi non è Ollama):
  - thread 18 (default Ollama): 0,2-0,8 tok/s · 12: 1,4-1,9 · 6: 3,8-4,0 ·
    4: 2,9-3,2 · 2: 2,3. Il massimo è a 6 thread.
  - 3 processi x 6 thread: 2,8 tok/s totali · 6 processi x 3 thread: 5,6.
  - 16 risposte in parallelo nello stesso processo, 6 thread: 7,1 tok/s
    totali (lettura del prompt 9-13 tok/s).
  - Non aiutano: attesa passiva dei thread (1,4 a 6 thread), pagine grandi
    (2,1 +/- 0,7 con 4,6 GB davvero in THP).
  - Macchina: EPYC Zen 1 (family 23 model 1), AVX2+FMA, niente AVX-512, KVM.
    sha256 scala 15x su 18 core, matmul in cache 13x (801 GFLOPS), ma la
    copia di memoria si ferma a ~13 GB/s da 9 processi in su e un page fault
    costa ~20 microsecondi (4 GB toccati in 20,6 s).
  - Lettura: il tetto è la memoria, non i core. Il crollo sopra 6 thread non
    è spiegato fino in fondo.
  File di prova in `~/llm-bench/` (fuori dal repo). Nessuna modifica fatta a
  codice o configurazione. Disegno in attesa della decisione di Giuseppe.
- 2026-11-13 - **Giuseppe approva il disegno rivisto** («vai implementa»), con
  le proposte del capo sulle domande aperte. Scelte chiuse:
  1. Modello 3b/7b nel `.env`: non si tocca in questo lavoro.
  2. Le ore di trascrizione (Whisper) entrano nel totale "Oggi".
  3. La pagina la vedono tutti, come Stato.
  4. 90 giorni di dettaglio bastano; nessuna tabella di riepilogo.
  5. Lentezza: chiusa dalla PR #19 (Ollama a 6 thread, 7b a 3,8-4,0 tok/s).
  6. Si registrano anche i modelli remoti, anche all'inizio della chiamata.
  7. Una pagina sola, "Avanzamento" (`/avanzamento`), sotto "Stato pipeline".
  8. Da Stato esce "Job in corso"; "In questo momento" diventa un collegamento.
  9. Lo stadio fallito che su Stato sembra "in corso": lavoro a parte, non qui.
  10. `embed` e `cluster` senza numeri in v1: solo "in corso da X".
  11. Batch senza barra viva: solo "consegnati, risposta entro le ...".
  12. Nomi di account e titoli salvati 90 giorni in `LLMCall`: sì, solo
      etichette, mai testo del contenuto.
  Vale la sottosezione "Revisione del disegno (tqdm)"; dove contraddice il
  primo disegno, vince la revisione.
