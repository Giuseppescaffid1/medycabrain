---
id: 2026-11-05-upload-link-affidabili
titolo: Caricare link e file senza errori nascosti
stato: pronto
ramo: feat/upload-link-affidabili
pr: "https://github.com/Giuseppescaffid1/medycabrain/pull/12"
ticket: ""
---

## 1. Richiesta          (capo)

Parole di Giuseppe: «I'm receiving a lot of complaints from my client, who is saying that these things are not working properly. [...] everything related to uploading links for documentation and stuff like that needs to be done in a better way. It needs to be counterchecked.» Poi, dopo la revisione: «proceed to correct everything».

Il lavoro è diviso in tre rami paralleli, tutti da `main` (062d874):
`feat/upload-link-affidabili`, `feat/fonti-stato-affidabili`, `feat/navigazione-errori`.
Ognuno ha il suo worktree in `/home/giuseppe/projects/medycabrain-wt-<slug>`.
Lavora SOLO nel tuo worktree.

**Confini di questo ramo (per non collidere con gli altri due):** Possiedi: UploadPanel.tsx, link_ingest.py, upload_workflow.py, run_job.py, le view/serializer di upload e from-links, la visibilità in Libreria dei documenti caricati (KnowledgeDocumentViewSet: solo il filtro is_inspiration), knowledge.py:139 per le schede di riferimento. NON toccare: JobsContext.tsx / api/jobs.ts / it.json chiavi jobs (li fa feat/navigazione-errori: tu esponi solo i kind upload_transcribe/link_transcribe nell'API se mancano), BlogSourceSerializer (lo fa feat/fonti-stato-affidabili).

Modelli: piano con Fable, esecuzione con Sonnet (regola in arrivo con `feat/regola-modelli`).

Malfunzionamenti da correggere (revisione di sola lettura del 2026-11-05; file:riga si riferiscono al checkout di allora, ricontrolla):

## A. Upload / links (UploadPanel, link_ingest, upload_workflow)
1. Only YouTube/Vimeo accepted; Instagram/blog/PDF/Drive -> 400; in mixed paste others silently dropped (link_ingest.py:102-133, views.py:203-207). access.log: 10/16 client POSTs = 400. No document upload exists (accept=audio/*,video/*).
2. All 14 imported links invisible in Library (owner_type=competitor, is_on_topic=False); "Vedi in Libreria" -> empty (UploadPanel.tsx:344-365, views.py:523-544).
3. Deleted/failed link can't be re-added ("già presenti"), no retry (views.py:214-245).
4. Backend restart during transcription -> UploadedMedia stuck "pending" forever, UI polls forever (run_job.py:26-39, views.py:683-694).
5. Post-transcription enrich/embed error marks a successful upload FAILED (upload_workflow.py:251-308).
6. Raw English repr / ffmpeg command with server path shown to client (upload_workflow.py:306, link_ingest.py:396,403). yt-dlp TimeoutExpired skips reference card.
7. UI shows only counts of rejected/duplicate links, not which/why (UploadPanel.tsx:98-103).
8. nginx 413 / 502 / network -> generic error; no client size check (UploadPanel.tsx:83-108).
9. Same file can't be re-picked after error; drop zone clickable during upload; multi-file drop keeps only first; .3gp/.amr/.wma/.aiff/.caf pass picker but refused.
10. Upload/link jobs not in global status bar; real progress never shown (JobsContext.tsx, api/jobs.ts:5).
11. Link error shown under file box, not textarea; old success note stays.
12. statusBadge shows "pronto" for skipped/batched.
13. Reference-only card (blocked link) excluded from chat index (knowledge.py:139 requires DONE).
S. YouTube cookies likely expired (last write 14 Sep, last success 15 Sep); many links -> 504; double paste -> duplicates; long local whisper reaped at 25 min while running.

## 2. Disegno            (architetto)

Scritto il 2026-11-05 sul worktree `medycabrain-wt-upload-link-affidabili`
(ramo `feat/upload-link-affidabili`, da `main` 062d874). Solo lettura: nessuna
riga di codice toccata.

### 2.0 Vincoli misurati (cosa ho verificato, con il comando)

| Fatto | Come l'ho accertato |
|---|---|
| Solo due fornitori: `PROVIDERS` ha 2 righe (youtube, vimeo). `provider_for()` rifiuta tutto il resto con una sola frase. Non esiste un cercatore di URL generici: un link Instagram/blog/PDF nel testo **non viene nemmeno visto** da `extract_links`, quindi non può finire tra i `rifiutati`. | `Read BEC/core/link_ingest.py` righe 198-247, 285-307 |
| Nessun caricamento di documenti: `create()` accetta `_AUDIO_EXT` (7 estensioni) e `_VIDEO_EXT` (6); il resto è 400. L'`accept` del picker è `audio/*,video/*`, non allineato alla lista del server. | `views.py:146-166`, `UploadPanel.tsx:185` |
| Il link «Vedi in Libreria» punta a `/medyca/library?type=article` → scope `medyca` → `owner_type=owned`. Un link importato come `competitor` (il default del select) non ci sarà **mai**. In più `KnowledgeDocumentViewSet` filtra `is_on_topic=True` senza l'eccezione `is_inspiration` che l'indice della chat invece ha. | `UploadPanel.tsx:345,362`, `Library.tsx:22`, `views.py:533`, `knowledge.py:112` |
| L'indice della chat/MCP **non** richiede `enrich_status=DONE` per i documenti: filtra `is_active`, `owner_type`, `(is_on_topic OR is_inspiration)` e `embedding != []`. Il `DONE` a `knowledge.py:131` riguarda solo i reel. Il punto 13 della revisione, in questo checkout, **non si riproduce** per via del codice: resta da provare dal vivo (vedi 2.13). | `grep -n "DONE\|is_on_topic\|is_inspiration" BEC/core/knowledge.py` → righe 83, 103, 112, 124, 131 |
| Cancellare un upload lascia il `KnowledgeDocument` con `is_active=False` ma con la stessa `source_url` (unique). `from_links` controlla `KnowledgeDocument.objects.filter(source_url=url).exists()` **senza** `is_active` → «già presente» per sempre. Nessuna azione di retry su `UploadedMediaViewSet` (`http_method_names` = get/post/delete). | `views.py:214-217, 239-245, 144` |
| Un riavvio uccide il worker: `run_job` aggiorna solo il `Job` nel gestore di segnale, mai la riga `UploadedMedia`. `_reap_stale_jobs` idem, e gira solo quando la UI interroga `/jobs/?active=1` o si crea un job: `UploadPanel` interroga `/uploads/`, quindi il mietitore non parte da lì. | `run_job.py:26-45`, `views.py:683-694, 1197-1203`, `UploadPanel.tsx:64-72` |
| Enrich/argomenti/embed dopo la trascrizione sono fuori dal `try` della bozza: un errore LLM lì fa `FAILED` un upload già trascritto e salvato (`transcribe_status=DONE` già scritto a riga 252, poi sovrascritto a 300). Il notturno `knowledge` riprenderebbe da solo quel documento (seleziona `enrich_status=PENDING`, qualunque `source_type`). | `upload_workflow.py:257-260, 297-310`; `knowledge_agent.py` run: `filter(enrich_status=PENDING, is_active=True)` |
| Messaggi grezzi: `repr(exc)` finisce in `last_error` per tutto ciò che non è `LinkRefused` (`CalledProcessError` di ffmpeg mostra il comando con il percorso del server). `subprocess.TimeoutExpired` (1800 s) di yt-dlp non è `LinkRefused` → salta `_save_reference_only`. | `upload_workflow.py:306-307`, `link_ingest.py:396-403` |
| `from_links` chiama `probe()` (oEmbed, timeout 20 s) **in serie dentro la richiesta HTTP**. Limiti: nginx `location /api/v1/uploads/` `proxy_read_timeout 300s`, gunicorn `--timeout 300`. 15 link lenti bastano per un 504. | `views.py:218-222`, `link_ingest.py:340`, `/etc/nginx/sites-enabled/medycabrain-port:35,51`, `medycabrain-backend.service:28` |
| Doppio incolla → doppioni: `UploadedMedia.source_url` **non** ha vincolo di unicità (i file hanno `""`), il controllo `exists()` non è atomico. | `models.py:743`; `grep -n "UniqueConstraint" BEC/core/migrations/*upload*.py` → nessuno |
| Il mietitore ferma a 25 min senza progresso (`STALE_AFTER = 25*60`). `_transcribe_long` chiama `progress()` solo tra un segmento e l'altro; un file sotto i 24 MB va in un'unica chiamata a whisper (locale se il remoto fallisce) senza battito → oltre 25 min viene dichiarato morto mentre lavora. | `views.py:680`, `upload_workflow.py:86-97` |
| Limite file reale: nginx `client_max_body_size 1G` sulla sola `location /api/v1/uploads/` (50M altrove). Django `DATA_UPLOAD_MAX_MEMORY_SIZE`/`FILE_UPLOAD_MAX_MEMORY_SIZE` = 50 MB **non** bloccano i file (sono soglie per i dati non-file e per il buffer in memoria). Nel frontend nessun controllo di dimensione e nessuna mappatura di 413/502/rete. | `medycabrain-port:9,50`, `settings/base.py:127-128`; `grep -rn "413\|size >" FEC/src` → 0 risultati |
| Cookie: `~/.config/medycabrain/yt_cookies.txt` modificato il **14 set**, `vimeo_cookies.txt` il **15 set**; oggi è il 5 nov. Conferma l'ipotesi «scaduti» della revisione. | `ls -la ~/.config/medycabrain/` |
| `Job.KIND_CHOICES` contiene già `upload_transcribe` e `link_transcribe`; `JobSerializer` espone `kind`. Lato API non manca nulla per il punto 10; manca solo il tipo in `api/jobs.ts` (riga 5), che **non è mio**. | `models.py:569-576`, `serializers.py:269-275` |
| Il tipo `Upload.transcribe_status` ammette `skipped`/`batched`; `statusBadge` li mostra come «pronto». | `uploads.ts:12`, `UploadPanel.tsx:117-127` |
| Riusabili già pronti: `external_ref.safe_get/_check_public` (anti-SSRF), `blog_agent.fetch_article/ingest` (pagina web → documento con trafilatura), `downloader_agent._ytdlp_fetch` (reel pubblico via yt-dlp anonimo, senza account), `BlogSourceViewSet.reactivate` (modello per un'azione «riprova»), `ContentDetail` su `/content/blog/:id` (dettaglio documento senza filtri di lista). | grep/Read indicati nelle sezioni sotto |
| 63 punti leggono `owner_type` come binario fuori da `models.py`. | `grep -rn owner_type BEC/core/*.py BEC/pipeline/agents/*.py BEC/mcp_bridge/*.py \| grep -v models.py \| wc -l` |
| Test esistenti: 28 test in `test_link_ingest.py` (estrazione, rifiuti, endpoint `from-links`), nessuno su upload file/retry/mietitura. | `grep -c "def test" BEC/core/tests/test_link_ingest.py` |

**Non verificato (bloccato dai permessi, resta dalla revisione):** lo stato delle 14 righe link nel DB (`owner_type=competitor`, `is_on_topic=False`), e il conteggio «10/16 POST = 400» da `access.log` (file leggibile solo da `www-data`/`adm`). Il collaudatore li riaccerti con `manage.py shell` prima di dichiarare chiuso il punto 2.

### 2.1 Ordine di lavoro (per impatto sul cliente)

1. **Punto 1** — link non YouTube/Vimeo e documenti: decisione di prodotto (§2.2).
2. **Punti 2 + 13** — i link importati non si trovano in Libreria (§2.3).
3. **Punti 7 + 11** — la UI non dice *quale* link è stato scartato e *perché* (§2.4).
4. **Punto 3** — non si può riaggiungere né riprovare (§2.5).
5. **Punti 4 + S(25 min)** — righe bloccate su «in trascrizione» per sempre (§2.6).
6. **Punto 5** — upload riuscito segnato come errore (§2.7).
7. **Punto 6** — messaggi grezzi e percorso del server mostrati al cliente (§2.8).
8. **S(504, doppioni)** — tanti link in un colpo e doppio incolla (§2.9).
9. **Punti 8 + 9** — esperienza del caricamento file (§2.10).
10. **Punto 12** — etichetta di stato (§2.11).
11. **Punto 10** — barra globale: non è mio, espongo solo il progresso (§2.12).
12. **S(cookie)** — operativo, non codice (§2.13).

### 2.2 Punto 1 — Quali link e quali file accettiamo (decisione di prodotto)

Oggi la risposta a un link Instagram, a un articolo o a un PDF è un 400 con «Non ho
trovato nessun link a un video», e in un incolla misto quei link **spariscono senza
traccia**. Qualunque opzione si scelga, la prima correzione è comune: `extract_links`
deve trovare **tutti** gli URL `http(s)` del testo (un pattern generico in più) e
restituire anche quelli che nessun fornitore riconosce, così da elencarli al cliente.

**Opzione A — accettare di più: reel Instagram, articoli web, PDF/DOCX.**
- *Articoli web* (link a un blog o a una pagina): riuso totale. `blog_agent.fetch_article(url)` legge la pagina con `safe_get` (già anti-SSRF) e trafilatura; `blog_agent.ingest(url, source=None, source_type="other")` la salva. Serve aggiungere a `ingest` i parametri `owner_type` e `is_inspiration` (oggi con `source=None` scrive `owned` fisso: per un articolo di un competitor sarebbe l'errore peggiore). `ingest` resta l'unico scrittore di `owner_type`, la regola è rispettata. Niente trascrizione: va in `KnowledgeDocument` e poi nel notturno `knowledge`. Costo: ~mezza giornata. Nuova riga in `PROVIDERS`? No: un articolo non è un video; va trattato come terzo «genere» del link (`video` / `articolo`), deciso dall'host: se non è YouTube/Vimeo/Instagram → si prova come pagina.
- *Reel Instagram* (`instagram.com/reel/<shortcode>/`): riuso di `downloader_agent._ytdlp_fetch` (yt-dlp **anonimo**, nessun account, nessun cookie: rispetta «niente credenziali di terzi»). Nessun oEmbed pubblico (quello di Instagram vuole un token Facebook): titolo e autore si prendono dai metadati di yt-dlp nel worker. Rischio: Instagram blocca l'IP a tratti (`IGThrottled` già previsto nel downloader). Attenzione: diventa un `UploadedMedia`/documento, **non** un `Reel` — niente metriche, niente cluster reel. Costo: ~mezza giornata + test.
- *PDF/DOCX*: 2 librerie nuove (`pypdf`, `python-docx`), un valore `document` in `UploadedMedia.KIND_CHOICES` (**migrazione**), un ramo in `run_upload_transcribe` che estrae il testo invece di trascrivere. PDF scansionati (senza strato di testo) → errore chiaro, niente OCR. Costo: ~1 giorno.
- *Google Drive / Dropbox*: **fuori** in ogni caso (richiedono autenticazione di terzi).
- Costo totale A: 2-3 giorni, 1 migrazione, 2 librerie, 3 nuove superfici che possono rompersi (blocchi Instagram, pagine con paywall, PDF scansionati). Rischio principale: più modi nuovi di fallire proprio mentre il cliente si lamenta dell'affidabilità.

**Opzione B — rifiutare chiaramente.** Nessun nuovo ingresso. Il server restituisce per
ogni URL non riconosciuto `{url, motivo}` («Non è un video YouTube o Vimeo: al momento
leggo solo quelli»), la UI li elenca uno per uno (§2.4), il testo di aiuto e i «Limiti
noti» della pagina Documentazione dicono in chiaro cosa si può incollare. Costo: ~mezza
giornata, già compresa nei punti 7/11. Rischio: il cliente **voleva** quei contenuti
(secondo la revisione, 10 POST su 16 erano proprio questi), quindi B da sola non toglie
la lamentela: la rende solo onesta.

**Raccomandazione: B in questo ramo, più A-articoli se Giuseppe approva (domanda 1).**
B è obbligatoria comunque (è la base dei punti 7/11). L'ingresso «articolo web» è
l'unica parte di A che riusa il 100% del codice esistente e non aggiunge librerie né
migrazioni: vale la pena farla qui. Reel Instagram e PDF/DOCX li lascerei a un ramo
successivo con la propria scheda in `.claude/tasks/`, perché portano migrazione, librerie
e una superficie d'errore nuova.

Regola owned/competitor per qualunque cosa entri: il valore lo sceglie il cliente nel
select, è binario, e la UI già avvisa quando sceglie «Di Medyca». Un valore non valido
in `owner_type` oggi diventa `owned` in silenzio (`views.py:200`): va cambiato in 400,
perché un errore di client non deve gonfiare la copertura di Medyca.

### 2.3 Punti 2 + 13 — I link importati non si trovano in Libreria

Correzione, tre pezzi piccoli:
- `UploadPanel.tsx`: «Vedi in Libreria» e «Vedi il riferimento» puntano a
  `/content/blog/{u.document}` (`ContentDetail`, già esistente: il dettaglio per id non
  ha filtri di lista, `views.py:527-528`). Così il link apre **quel** documento, sempre.
  Il link alla lista, se si vuole tenerlo, va costruito sullo scope giusto:
  `/${owner_type === "owned" ? "medyca" : "competitor"}/library?type=article`.
- `views.py` `KnowledgeDocumentViewSet.get_queryset`: `filter(is_on_topic=True)` →
  `filter(Q(is_on_topic=True) | Q(is_inspiration=True))`, lo stesso criterio di
  `knowledge.py:112`. Motivazione già scritta nel modello (`models.py:489-490`): il
  verdetto del modello non cancella dalla Libreria ciò che un umano ha messo apposta.
  Unico tocco a questo ViewSet, come da confini.
- Punto 13: dal codice la scheda-riferimento **è** nell'indice (vedi 2.0). Il
  collaudatore lo verifichi dal vivo con `semantic_search` su un titolo di scheda; se non
  esce, la causa è `embedding=[]` (embed fallito) e la correzione è nel ramo di
  `_save_reference_only` (loggare e rimettere `embed_status=FAILED` invece di lasciare
  `PENDING`). Niente da cambiare a `knowledge.py` a meno che il collaudo non lo smentisca.

### 2.4 Punti 7 + 11 — Dire cosa è successo a ogni link

- Server (`views.py from_links`): la risposta passa da tre a cinque liste, tutte con
  gli URL: `creati`, `gia_presenti`, `rifiutati[{url,motivo}]`,
  `non_riconosciuti[{url,motivo}]` (gli URL trovati ma di host non supportati),
  `riprovati` (§2.5). Le chiavi italiane esistenti restano.
- `uploads.ts`: aggiornare `LinkImport`.
- `UploadPanel.tsx`: al posto della riga di conteggi, un riquadro di esito **sotto la
  textarea** con un elenco per gruppo (URL abbreviato + motivo), chiudibile; l'errore
  della textarea (`addLinks.onError`) ha il suo stato separato da quello del file
  (`linkError` vs `fileError`), e la nota di successo precedente si azzera a ogni nuovo
  invio o modifica del testo.
- `it.json` chiavi `uploads.*` nuove (es. `linksUnknownHost`, `linksRetried`,
  `linksOutcomeTitle`). Non si toccano le chiavi `jobs.*`.

### 2.5 Punto 3 — Riaggiungere e riprovare

- Dedup in `from_links`: «già presente» solo se esiste una riga `UploadedMedia` con quel
  `source_url` **in stato pending/done**, oppure un `KnowledgeDocument` **attivo**
  (`is_active=True`) con quel URL. Una riga `failed` reincollata viene **rimessa in coda**
  (nuovo `Job`, `transcribe_status=PENDING`, `last_error=""`) e riportata in `riprovati`:
  è un retry esplicito, deciso dal cliente, non un azzeramento silenzioso.
- Nuova azione `POST /uploads/<id>/retry/` (modello: `BlogSourceViewSet.reactivate`,
  `views.py:112-123`): ammessa solo se `transcribe_status=failed`, altrimenti 409. Nella
  riga della tabella un pulsante «Riprova» accanto a «Rimuovi», visibile solo sui falliti.
  Serializer: nulla di nuovo oltre a §2.12.
- `upload_workflow.run_upload_transcribe`: nei `defaults` dell'`update_or_create` del
  documento aggiungere `"is_active": True` (come fa `blog_agent.ingest`, riga 170), così
  un link cancellato e poi riaggiunto rianima la scheda invece di collidere sull'unicità.
- `uploads.ts`: `retryUpload(id)`.

### 2.6 Punti 4 + S(25 min) — Righe «in trascrizione» per sempre

- `run_job.py`, gestore di segnale: se `job.kind` è `upload_transcribe`/`link_transcribe`
  aggiornare anche `UploadedMedia(id=params.upload_id)` → `transcribe_status=FAILED`,
  `last_error="Interrotto da un riavvio del server. Premi «Riprova»."`.
- `views._reap_stale_jobs`: stessa cosa per i job mietuti di quei due kind (una seconda
  `update` filtrata su `params__upload_id` degli id raccolti prima del primo `update`).
- `UploadedMediaViewSet.list` chiama `_reap_stale_jobs()` prima di rispondere: è la
  chiamata che la UI fa ogni 4 s mentre qualcosa è pending, quindi il mietitore gira
  dove serve (oggi gira solo da `/jobs/?active=1`).
- Rete di sicurezza nello stesso `list`: righe `pending` **senza** alcun `Job`
  queued/running con quel `upload_id` → `FAILED` con lo stesso messaggio (copre il caso
  «processo mai partito» o morto prima del segnale).
- Battito cardiaco in `run_job.handle`: un thread daemon che ogni 60 s fa
  `Job.objects.filter(id=..., status="running").update(updated_at=now())`. Con questo
  `STALE_AFTER=25 min` resta com'è e una trascrizione locale di 40 minuti non viene più
  dichiarata morta mentre lavora. In più `_transcribe_long` chiama `progress()` anche
  prima di una trascrizione singola (oggi solo tra i segmenti).

### 2.7 Punto 5 — Upload riuscito segnato come errore

`upload_workflow.py:257-260`: `_enrich_one` / `_extract_arguments` / `_embed_one` entrano
in un `try` separato come già fa la bozza. In caso di errore: log `warning`, il
documento resta `enrich_status=PENDING` (il notturno `knowledge` lo riprende da solo:
verificato, seleziona per stato e non per `source_type`), la riga resta `DONE` e
`last_error` riceve una nota informativa («Trascritto. L'analisi verrà completata nella
prossima elaborazione notturna.»). Il risultato del job lo dice (`analysis: "deferred"`).
Niente di silenzioso: il cliente vede «pronto» più la nota.

### 2.8 Punto 6 — Messaggi che il cliente possa leggere

- `upload_workflow.py` blocco `except`: una piccola tabella eccezione → frase italiana:
  `CalledProcessError` (ffmpeg) → «Non riesco a leggere l'audio di questo file: potrebbe
  essere danneggiato o in un formato non supportato.»; `TimeoutExpired` → «L'operazione ha
  superato il tempo massimo (30 minuti).»; `RuntimeError` con messaggio già italiano →
  così com'è; tutto il resto → «Errore imprevisto durante la lavorazione.». Il `repr`
  completo va **solo** nel log e in `job.error` (già oggi `run_job.py:71`), mai in
  `last_error`. Mai un percorso del server nel testo mostrato.
- `link_ingest.fetch_audio`: catturare `subprocess.TimeoutExpired` e rialzare
  `LinkRefused("Il download ha superato i 30 minuti…")`, così il link bloccato passa da
  `_save_reference_only` come gli altri rifiuti; e la frase di riserva
  `"Download non riuscito: {stderr}"` diventa un messaggio fisso senza stderr (lo stderr
  va nel log).

### 2.9 S — Tanti link in un colpo (504) e doppio incolla (doppioni)

- Spostare `probe()` **dentro il worker** (`run_upload_transcribe`, prima di
  `fetch_audio`): la richiesta `from-links` crea le righe con `title=url` e torna in
  millisecondi; il worker scrive titolo e canale appena li ha. Un video privato diventa
  una riga `failed` con il motivo (visibile nella lista) invece che un `rifiutato`
  sincrono: più coerente, e il 504 non può più accadere. I test `FromLinksEndpoint` vanno
  adattati (oggi mockano `probe`).
- Doppioni: vincolo `UniqueConstraint(fields=["source_url"], condition=~Q(source_url=""))`
  su `UploadedMedia` (**migrazione**, `0018_...`), e in `from_links` l'`IntegrityError`
  viene letto come «già presente». È l'unica correzione che regge due richieste
  simultanee; il `disabled` del pulsante da solo non basta. Strutturale → documentazione
  in `01-data-model.md`. Se Giuseppe preferisce non toccare lo schema in questo ramo
  (domanda 3), ripiego su `transaction.atomic` + `select_for_update` sulle righe esistenti,
  che riduce ma non azzera il rischio.

### 2.10 Punti 8 + 9 — Caricamento file

`UploadPanel.tsx` (e `uploads.ts` per i tipi):
- Controllo di dimensione **prima** di partire: oltre 1 GB (il limite nginx misurato) →
  messaggio chiaro, nessuna richiesta. Il numero va in una costante con il commento che
  cita `medycabrain-port:50`.
- Mappatura degli errori: 413 → «File troppo grande: il massimo è 1 GB»; 502/504 → «Il
  server non ha risposto in tempo: riprova»; nessuna risposta (rete) → «Connessione
  interrotta durante il caricamento»; 400 → `detail` del server. Oggi tutto cade su
  `common.error`.
- Azzerare `input.value` dopo ogni scelta (altrimenti lo stesso file non riparte).
- Drop zone disabilitata (niente click, niente drop, `aria-disabled`) mentre un
  caricamento è in corso.
- Più file insieme: coda sequenziale, un solo progress con «file 2 di 3»; ogni file
  diventa la sua riga.
- `accept` costruito da una lista esplicita di estensioni **identica** a quella del
  server. Lato server `_AUDIO_EXT` si allarga a `amr, wma, aiff, aif, caf` e `_VIDEO_EXT`
  a `3gp`: tutti passano da ffmpeg (`_to_mono_mp3`/`_extract_audio`) prima di whisper,
  quindi non serve altro. La lista va in un posto solo per lato (una costante), e il
  testo `uploads.formats` la rispecchia.

### 2.11 Punto 12 — Etichetta di stato

`statusBadge`: `skipped` → «senza trascrizione», `batched` → «in analisi». Due chiavi
`uploads.*` nuove. Solo frontend.

### 2.12 Punto 10 — Barra globale (non mio) e progresso reale (mio)

`JobsContext.tsx`, `api/jobs.ts` e le chiavi `jobs.*` sono di `feat/navigazione-errori`.
Lato API i due `kind` esistono già (verificato). Quello che posso fare nel mio perimetro:
`UploadedMediaSerializer` espone due campi di sola lettura `job_progress` (0-100) e
`job_message`, presi dall'ultimo `Job` con `params.upload_id = id` (una sola query in
`list()`, passata nel contesto del serializer: niente N+1 su 100 righe). `UploadPanel`
mostra la barra e il messaggio («Trascrivo il segmento 2 di 4…») nella riga pending.
Così il cliente vede il progresso anche se l'altro ramo non è ancora fuso.

### 2.13 S — Cookie YouTube/Vimeo scaduti: operativo, non codice

Date misurate: 14 e 15 settembre. Non c'è correzione di codice possibile: qualcuno con un
browser loggato deve riesportare i due file in `~/.config/medycabrain/` (regola «fuori dal
repository, mode 0600»). Il messaggio al cliente già dice la cosa giusta. Propongo in più
che `PipelineStatusView` (o il log del job) riporti **l'età** dei due file cookie, così
Giuseppe lo vede prima del cliente — ma `PipelineStatusView` non è nei confini di questo
ramo: lo segno come fuori, da decidere (domanda 5). Il collaudatore non potrà verificare
una trascrizione da link finché i cookie non sono rinnovati: il collaudo di quella parte
va fatto con `probe` + scheda-riferimento, e con un file caricato a mano.

### 2.14 File da toccare (riepilogo)

| File | Perché |
|---|---|
| `BEC/core/link_ingest.py` | URL generici → `non_riconosciuti`; `TimeoutExpired` → `LinkRefused`; stderr fuori dal messaggio; (A-articoli: classificazione `video`/`articolo`) |
| `BEC/core/upload_workflow.py` | probe nel worker; `try` attorno a enrich/embed; tabella eccezione→frase; `is_active: True`; (A-articoli: ramo che chiama `blog_agent.ingest`) |
| `BEC/core/management/commands/run_job.py` | segnale → riga `FAILED`; battito ogni 60 s |
| `BEC/core/views.py` | `UploadedMediaViewSet`: `from_links` (5 liste, dedup su attivi, requeue, 400 su owner non valido, `IntegrityError`), `retry`, `list` con mietitura e rete di sicurezza, estensioni; `_reap_stale_jobs` sulle righe; `KnowledgeDocumentViewSet` solo il filtro `is_on_topic` |
| `BEC/core/serializers.py` | `UploadedMediaSerializer`: `job_progress`, `job_message` |
| `BEC/core/models.py` + `migrations/0018_*` | vincolo di unicità condizionale su `source_url` (se approvato) |
| `BEC/pipeline/agents/blog_agent.py` | solo se A-articoli: `ingest(..., owner_type=, is_inspiration=)` |
| `BEC/core/tests/test_link_ingest.py` (+ nuovo `test_uploads.py`) | URL non riconosciuti, requeue, retry, mietitura, messaggi, `from_links` senza probe |
| `FEC/src/components/uploads/UploadPanel.tsx` | tutto il §2.3, 2.4, 2.5, 2.10, 2.11, 2.12 |
| `FEC/src/api/uploads.ts` | tipi `LinkImport`/`Upload`, `retryUpload` |
| `FEC/src/i18n/it.json` | **solo** chiavi `uploads.*` e `docs.*` (limiti) |
| `documentation/low-level/02-pipeline.md` | flusso link: probe nel worker, retry, mietitura, battito, elenco host accettati/rifiutati |
| `documentation/low-level/05-rest-api.md` | `retry`, nuove chiavi di `from-links`, campi serializer |
| `documentation/low-level/06-frontend.md` | `UploadPanel`: esiti per link, retry, coda file, limiti |
| `documentation/low-level/01-data-model.md` | solo se migrazione (vincolo) |
| `documentation/low-level/03-llm-and-embeddings.md` | niente, salvo A-articoli (nuovo ingresso nel RAG) |
| `docs/medycabrain-pipeline-cliente.drawio` | solo se A-articoli (nuovo ingresso nella scheda cliente) |
| pagina `Documentazione` (`it.json` `docs.inputs.items`, `docs.limits.items`) | cosa si può incollare/caricare e cosa no; retry; cosa succede a un riavvio |

### 2.15 Rischi e invarianti sfiorati

- **`owner_type` binario**: ogni ingresso nuovo prende il valore dal select del cliente;
  nessun terzo valore; l'`owner` non valido diventa 400 e non più `owned`. Se A-articoli,
  `blog_agent.ingest` resta l'unico scrittore.
- **I falliti restano `failed`**: il requeue avviene solo per gesto esplicito (reincolla o
  «Riprova»); il mietitore e il gestore di segnale scrivono `FAILED`, mai `PENDING`.
  Nessun ciclo automatico.
- **Niente credenziali di terzi**: i cookie restano fuori dal repo; l'eventuale Instagram
  è anonimo; Drive/Dropbox rifiutati.
- **Spostare `probe` nel worker cambia il contratto** di `from-links`: i video privati
  non sono più in `rifiutati` ma righe `failed`. I test esistenti e la doc 05 vanno
  aggiornati nello stesso commit.
- **Mietitura in `list`**: una `UPDATE` ogni 4 s mentre qualcosa è pending; costo
  trascurabile, ma è una scrittura in una GET: va commentata.
- **Filtro `is_inspiration` in Libreria**: fa riapparire schede competitor che il
  modello aveva giudicato fuori tema, solo nella Libreria competitor. È voluto (sono
  state messe dal cliente), ma va detto nei «Limiti noti».
- **Collisione con gli altri rami**: non tocco `JobsContext`, `api/jobs.ts`, chiavi
  `jobs.*`, `BlogSourceSerializer`. In `views.py` lavoro solo in `UploadedMediaViewSet`,
  `_reap_stale_jobs` e la riga 533 di `KnowledgeDocumentViewSet`; `it.json` è condiviso
  da tre rami → conflitti di merge probabili ma banali (blocchi diversi).

### 2.16 Cosa resta fuori (dichiarato)

- Reel Instagram da link e PDF/DOCX (opzione A piena): ramo successivo, se approvato.
- Link Google Drive/Dropbox/OneDrive: rifiutati con motivo, nessun piano di supporto.
- OCR di PDF scansionati.
- Rinnovo dei cookie (operativo) e il relativo avviso in `PipelineStatusView`.
- `JobsContext`/barra globale: dell'altro ramo.
- Ripresa automatica dei job interrotti da un riavvio: niente, per regola (i falliti
  restano tali; il cliente preme «Riprova»).
- Progresso byte-per-byte della trascrizione: si mostra il messaggio del job, non una
  percentuale reale di whisper.

### 2.17 Domande aperte per Giuseppe

1. **Punto 1**: B sola, oppure B + «articoli web» in questo ramo (riuso totale, nessuna
   migrazione)? Reel Instagram e PDF/DOCX li rimandiamo a una scheda a parte?
2. Un link **reincollato** che era `failed` deve ripartire da solo (riportato come
   «riprovato»), o vuoi solo il pulsante «Riprova» e il reincolla dice «già presente»?
3. Via libera alla **migrazione** per il vincolo di unicità su `source_url` (chiude i
   doppioni per davvero), o preferisci niente schema in questo ramo?
4. Spostare la lettura del titolo (`probe`) nel worker va bene anche se cambia la
   risposta di `from-links` (video privati → riga «errore» invece di «rifiutato»)?
5. Vuoi che l'**età dei file cookie** compaia nella pagina «Stato pipeline»? È fuori dai
   confini di questo ramo: posso lasciarlo a `feat/fonti-stato-affidabili`.
6. Chi riesporta i cookie YouTube/Vimeo, e quando? Senza, il collaudo della
   trascrizione da link non può passare.
7. Più file trascinati insieme: coda automatica (proposto) o rifiuto con «un file alla
   volta»?

## 3. Sviluppo           (sviluppatore)

Ramo `feat/upload-link-affidabili`. Seguite le decisioni del Registro (Q1-Q7).

### Cosa ho fatto (per punto della revisione)
- **1, 7, 11** `link_ingest.scan_links`: ogni indirizzo http(s) viene smistato in video / articolo / non riconosciuto con motivo (Instagram, social, Drive/Dropbox, PDF/Word, file audio-video, canali/playlist, URL > 500). `from-links` risponde con `creati, gia_presenti, riprovati, rifiutati, non_riconosciuti`; `owner_type` non valido -> 400. UI: riquadro «Cosa è successo ai link» sotto la textarea (per link + motivo), errori del link separati da quelli del file, reset a ogni modifica.
- **Articoli web (Q1)** nuovo `kind="article"` in `UploadedMedia`; il worker usa `blog_agent.ingest` (nuovi parametri `owner_type`, `is_inspiration`; un documento di una fonte non viene mai ri-assegnato da un incolla). Nessuna bozza.
- **2, 13** filtro `is_on_topic OR is_inspiration` in `KnowledgeDocumentViewSet`; «Vedi in Libreria/riferimento» apre `/content/blog/<id>`. Punto 13: dal codice la scheda era già nell'indice; ho solo fatto passare a `embed_status=failed` una scheda non indicizzabile (invece di `pending`). Da provare dal vivo (vedi sotto).
- **3 (Q2)** reincollare un link `failed` lo riavvia (`riprovati`, con owner/ispirazione scelti ora); pulsante «Riprova» + `POST /uploads/<id>/retry/` (409 se non failed). Un solo UPDATE condizionale: due click = un job. Link rimosso e reincollato: il worker rianima il documento (`is_active=True`).
- **4, S(25 min)** il gestore di segnale di `run_job` e `_reap_stale_jobs` mettono `failed` anche la riga `UploadedMedia`; `GET /uploads/` richiama il mietitore e fallisce le righe pending senza job vivo (grazia 2 min); battito ogni 60 s in `run_job`; `progress()` prima della trascrizione singola.
- **5** `_analyse`: errori di enrich/arguments/embed non rendono più «errore» un upload riuscito (riga `done` + nota, documento `pending` per il notturno, `analysis: "deferred"`).
- **6** `_client_message` (ffmpeg, timeout, sconosciuto -> frasi italiane, mai repr/percorsi); yt-dlp `TimeoutExpired` -> `LinkRefused` (salva la scheda); stderr di yt-dlp solo nel log.
- **S 504/doppioni (Q3, Q4)** `probe` spostato nel worker; vincolo unico su `source_url` (migrazione **0023**, con dedup preliminare dei doppioni esistenti) e `IntegrityError` letto come «già presente».
- **8, 9** limite 1 GB controllato prima, errori 413/502-504/rete mappati, `input.value` azzerato, zona disabilitata durante il caricamento, coda sequenziale per più file (Q7), `accept` da lista esplicita identica al server (aggiunti amr, wma, aiff, aif, caf, 3gp).
- **10** campi `job_progress`/`job_message` nel serializer (una query per lista) e barra di avanzamento nella riga.
- **12** `skipped` -> «senza trascrizione», `batched` -> «in analisi».

### File toccati
BEC: `core/link_ingest.py`, `core/upload_workflow.py`, `core/management/commands/run_job.py`, `core/views.py` (solo `UploadedMediaViewSet`, `_reap_stale_jobs` + 3 helper, filtro Libreria), `core/serializers.py` (solo `UploadedMediaSerializer`), `core/models.py`, `core/migrations/0023_uploadedmedia_unique_link.py`, `pipeline/agents/blog_agent.py`, test nuovi `core/tests/test_uploads.py`.
FEC: `components/uploads/UploadPanel.tsx`, `api/uploads.ts`, `i18n/it.json` (solo `uploads.*`, `docs.inputs`, `docs.limits`).
Doc: `documentation/low-level/01, 02, 05, 06`, `docs/medycabrain-pipeline-cliente.drawio` (una riga nel riquadro blog/link), pagina Documentazione (it.json).
Non toccati: `JobsContext.tsx`, `api/jobs.ts`, chiavi `jobs.*`, `BlogSourceSerializer`, `knowledge.py`.

### Comandi eseguiti (esito reale)
- `manage.py test core.tests.test_uploads core.tests.test_link_ingest` -> 65 test OK.
- `manage.py test core` (suite intera) -> **86 test OK**.
- `manage.py check` -> nessun problema; `makemigrations --check --dry-run` -> «No changes detected».
- `npm run build` in FEC (node_modules collegato dal checkout principale, poi rimosso) -> `built in 18.16s`, nessun errore di tipi.
- I test usano il database di test (`test_medycabrain`, creato e distrutto); nessun dato di produzione toccato, nessun servizio riavviato, nessun push.

### Cosa è rimasto fuori / da sapere
- **Collisione di migrazione**: `0023` parte da `0022_link_media`; se un altro ramo ne aggiunge una con lo stesso numero, va rinumerata al merge. `it.json` condiviso: conflitti possibili ma in blocchi diversi.
- Reel Instagram e PDF/DOCX: non fatti (scheda successiva); sono elencati al cliente come «non letti» col motivo.
- Cookie YouTube/Vimeo (Q6): li riesporta Giuseppe. Finché sono scaduti la trascrizione da link **non è verificabile**: si verifica solo probe + scheda-riferimento, articoli web e file caricati a mano. Età dei cookie in Stato pipeline: fuori (Q5).
- Barra globale dei job (punto 10): non toccata; il progresso si vede nella riga della tabella.
- Il collaudatore deve ancora verificare dal vivo: lo stato delle 14 righe link nel DB, il punto 13 (`semantic_search` su una scheda-riferimento), la lettura reale di una pagina web, e il comportamento dopo un riavvio con un job in corso. La pagina «Documentazione» mostra le nuove frasi in «Cosa entra» e «Limiti noti»; la pagina 1 del drawio non è stata ridisegnata (solo la nota tecnica).
- Il «Riprova» sui file caricati funziona solo se il file originale c'è ancora (per i video viene cancellato a trascrizione finita; se la riga è fallita prima, c'è). Altrimenti 409 «caricalo di nuovo».
- Il battito parte per ogni tipo di job (non solo upload): voluto, è innocuo.

### Secondo giro
Corretti i 4 rilievi non bloccanti di revisione e collaudo.
- **Job.message** (`run_job.py`): usa `_client_message`, la stessa mappa dell'upload; il repr resta in `job.error` e nello stderr. Test: percorso assente dal messaggio, presente in `error`.
- **Normalizzazione URL articoli** (`link_ingest._normalise_page_url`): via utm_*, fbclid, gclid, frammento e slash finale; gli altri parametri restano (spesso scelgono la pagina). Due test.
- **Doc**: `05-rest-api.md` (`rifiutati` sempre vuoto, video privati = righe `failed`, normalizzazione URL); `01-data-model.md` e docstring migrazione 0023 (cancellazione doppioni non reversibile, 0 doppioni oggi).
- **yt-dlp mancante**: `FileNotFoundError` in `fetch_audio` -> `ToolMissing` con «Lo strumento per scaricare i video non è installato sul server.» (non salva la scheda-riferimento: non e' un rifiuto del video). Test.
- **Esiti reali**: `manage.py test core` -> 90 test OK (86 + 4 nuovi); `npm run build` -> `built in 16.55s`, nessun errore. Symlink temporanei a venv, `.env` e node_modules del checkout principale, rimossi. Produzione non toccata, nessun push.
- Fuori: ffmpeg mancante resta sul messaggio generico; il rilievo 1 della revisione (blog_draft non copiato nel dedup) resta teorico, solo dichiarato.

## 4. Revisione          (revisore)

**Verdetto: PASSA** (nessun rilievo bloccante). Letto il diff `origin/main...HEAD` (1 commit, ramo `feat/upload-link-affidabili`, niente su `main`). Nessun segreto nel diff.

**Invarianti**
- `owner_type` resta binario: `from_links` rifiuta con 400 ogni valore diverso da owned/competitor (views.py, `from_links`); `blog_agent.ingest` resta l'unico scrittore, e un incolla non riassegna mai un documento che appartiene a una fonte (`existing.source_id` -> "unchanged"). Nessun terzo valore.
- I `failed` restano tali: gestore di segnale, mietitore e rete di sicurezza scrivono solo FAILED; il requeue avviene solo su gesto esplicito (Riprova / reincolla), con UPDATE condizionale (un solo vincitore).
- Nessuna credenziale di terzi. Gli articoli passano da `safe_get` (anti-SSRF verificato in `external_ref._check_public`).
- Documentazione nello stesso commit: 01, 02, 05, 06, drawio, pagina Documentazione.

**Migrazione 0023 (verificata in sola lettura sul DB reale)**
- `uploaded_media`: 14 righe, tutte con `source_url`; **0 doppioni** oggi, quindi la parte che cancella oggi non cancella nulla. Lunghezza massima URL 43.
- Nessuna foreign key punta a `uploaded_media` (query su `pg_constraint`): nessuna cascata possibile. La FK e' da `UploadedMedia` verso `KnowledgeDocument`/`BlogDraft` con SET_NULL, quindi cancellare una riga di coda non tocca il documento ne' la bozza.
- Reversibilita': la cancellazione e' `noop` all'indietro (le righe doppie non tornano); il vincolo e `kind` tornano indietro normalmente. E' dichiarato nel docstring della migrazione e in 01-data-model.
- Il numero 0023 non collide con gli altri due worktree (nessuna migrazione nuova li').

**Rilievi non bloccanti**
1. `0023_uploadedmedia_unique_link.py` (dedup): tra due doppioni tiene la riga "piu' avanti" ma non copia `blog_draft` dalla riga cancellata; se la bozza era sull'altra riga, la riga tenuta la perde (la bozza resta in `BlogDraft`). Con 0 doppioni oggi e' teorico. Meglio dichiarare nel docstring che il rollback non e' possibile.
2. `views.py` `from_links`: una pagina web gia' presente come documento attivo di una fonte crawled risponde "gia' presente" e non puo' essere marcata come ispirazione dal cliente. E' coerente con il disegno (non pagare due volte), ma va saputo.
3. `rifiutati` e' sempre `[]` dopo lo spostamento di `probe` nel worker: contratto mantenuto, ma la doc 05 dovrebbe dirlo (i video privati ora sono righe `failed`). Controllare in collaudo.
4. `scan_links`: gli URL articolo non vengono normalizzati (utm, slash finale): lo stesso articolo con parametri diversi diventa due righe/documenti. Limite noto da scrivere.

**Probe nel worker / retry / mietitore: verificati**
- `probe` e' fuori dal `try` interno di `fetch_audio` ma dentro il `try` esterno: un video privato diventa riga `failed` con la frase del `LinkRefused`; ripetuto solo se `channel` e' vuoto.
- Retry: UPDATE condizionale `failed -> pending`, 409 altrimenti; grazia di 2 minuti in `_fail_orphan_uploads` copre il vuoto tra UPDATE e creazione del Job.
- Mietitore: righe `pending` con Job stale o senza Job vivo -> `failed`; battito ogni 60 s evita la mietitura di una trascrizione lunga.

**Da fare dal collaudatore (dal vivo)**: punto 13 (`semantic_search` su una scheda-riferimento), lettura reale di una pagina web, riavvio con un job in corso, stato delle 14 righe link; trascrizione da link non verificabile finche' i cookie sono scaduti.
## 5. Collaudo           (collaudatore)

Collaudo del 2026-11-05, worktree `medycabrain-wt-upload-link-affidabili`, ramo `feat/upload-link-affidabili`. Produzione (:9093, DB `medycabrain`) NON toccata: nessuna migrazione, nessun riavvio, nessun POST al server live. Usato un database scratch `collaudo_upl` (creato, migrato fino a 0023, poi cancellato), backend del ramo su 127.0.0.1:8231, dist del ramo servito su 127.0.0.1:5274 con un piccolo proxy. Python/venv presi dal checkout principale (il worktree non ha venv: link simbolico temporaneo, rimosso).

**Verdetto: PASSA**, con 3 note minori sotto e le parti NON VERIFICATE elencate.

### Comandi (output reali)
- `makemigrations --check --dry-run` -> `No changes detected`
- `manage.py check` -> `System check identified no issues (0 silenced).`
- `manage.py test core --noinput` (DB di test `test_collaudo_upl`; `test_medycabrain` esisteva già e non l'ho distrutto) -> `Ran 86 tests in 14.931s` / `OK`
- `npm run build` in FEC -> `✓ built in 15.83s`, nessun errore di tipi (node_modules collegato e poi rimosso).

### Prova con backend vero (test client su DB scratch, worker veri partiti da `_spawn_job`)
- Incolla misto (YouTube, articolo OMS, Instagram, Drive, PDF, canale YT, owner=competitor): 202; `creati` = 2 (video + articolo), `non_riconosciuti` = 4 ciascuno con `motivo` in italiano. Niente sparisce.
- `owner_type="boh"` -> 400 «owner_type deve essere «owned» o «competitor».»; testo senza link -> 400 «Non ho trovato nessun link in quel testo.»
- Doppio incolla identico -> `creati: 0`, `gia_presenti` = 2 URL.
- Articolo web vero (who.int): riga `done`, titolo letto «Menopause», documento creato (competitor, on_topic, ispirazione). L'analisi LLM non è arrivata in tempo: riga resta `done` con nota «Trascritto. L'analisi verrà completata nella prossima elaborazione notturna.», documento `enrich=pending` (punto 5 confermato).
- YouTube (cookie scaduti, 14 set): `failed` con «YouTube ha bloccato il download da questo server. I cookie (YT_COOKIES_FILE) sono scaduti o mancanti… In alternativa carica il file video a mano.» e **scheda-riferimento salvata** (doc 2: `enrich=skipped`, `embed=done`, vettore 384).
- Retry: `POST /uploads/1/retry/` su failed -> 202 pending; di nuovo subito -> 409 «Si può riprovare solo un elemento in errore.»; su riga `done` -> 409. Retry su file rotto -> 202.
- Elimina articolo + reincolla -> documento `is_active=False`, poi `creati: 1` (non più «già presente»).
- File `.pdf` caricato -> 400 «Formato non supportato (pdf)…»; senza file -> 400. File mp3 corrotto -> «Non riesco a leggere l'audio di questo file: potrebbe essere danneggiato o in un formato non supportato.» (nessun percorso). Tono 3 s con estensione .amr (accettata) -> «La trascrizione è risultata vuota o troppo breve.»
- Riga pending senza job (vecchia di 10 min) e riga con job running fermo da 40 min: `GET /uploads/` le porta a `failed` con «Interrotto da un riavvio del server. Premi «Riprova».»; il job morto passa a `failed`.
- Libreria: `/knowledge/documents/?scope=competitor&type=article` mostra la scheda-riferimento (id 2) e l'articolo (id 1); `?scope=medyca` vuoto (corretto: sono competitor). `/knowledge/documents/2/` -> 200.
- **Punto 13**: `semantic_search("SALUTE METABOLICA cos'è e perché è importante")` con scope `all` e `competitor` -> `[(2, 'blog', "CANALE SALUTE: SALUTE METABOLICA…")]`. La scheda-riferimento è trovata. Punto 13 chiuso (su DB scratch, non sull'indice di produzione).

### Prova da utente vero (Chrome headless, /accounts, tab «Interviste», desktop 1280px e 380px)
- Incolla misto + «Aggiungi i video»: compare il riquadro «Cosa è successo ai link» sotto la textarea con gruppi (Rimessi in coda, Già presenti, ecc.) e URL abbreviati; screenshot letti a 1280 e 380 px, nessuno scroll orizzontale, nessun errore JS.
- `.pdf` scelto -> ««note.pdf» non è un formato accettato.» (controllo lato client).
- 413 simulato (route interceptata) -> «beep.mp3: File troppo grande: il massimo è 1 GB.»
- 504 simulato -> «beep.mp3: Il server non ha risposto in tempo. Riprova tra poco.»
- Rete interrotta simulata -> «beep.mp3: Connessione interrotta durante il caricamento. Riprova.»
- Stesso esito a 380 px.

### NON VERIFICATO (mai verde)
- **Trascrizione da link YouTube/Vimeo**: cookie scaduti (yt 14 set, vimeo 15 set). Provati solo probe + scheda-riferimento. Resta a Giuseppe riesportare i cookie e riprovare.
- Stato delle 14 righe link nel DB di produzione e conteggio 10/16 POST 400 da `access.log` (non accessibili/da non toccare).
- Riavvio reale del backend con un job in corso: simulato con righe e job invecchiati, non con un vero riavvio.
- Whisper su audio parlato vero (mancava un file con voce) e bozza blog per documenti `owned`.
- Limite reale nginx 1 GB e 413 reale di nginx: provati solo con risposta simulata nel browser.
- Caricamento multiplo con coda «File 2 di 3» e drop zone disabilitata durante l'upload: non esercitati a mano (solo lettura del codice: `aria-disabled={busy}`, `queueProgress`).
- Pagina Documentazione, drawio e documentazione `documentation/` non riletti nel collaudo.
- La rete di test resta sottile: 86 test verdi non provano la correttezza end-to-end.

### Note minori (non bloccanti)
1. `Job.message` del job fallito può contenere il testo grezzo dell'errore (visto: «Errore: [Errno 2] No such file or directory: '/home/giuseppe/projects/medycabrai…» con percorso del server). Non arriva in `last_error` della riga upload, ma può comparire dove la UI mostra il messaggio del job (barra globale, ramo `navigazione-errori`). In `run_job.py`.
2. Mobile 380px: la barra delle schede di Gestione fonti taglia a sinistra «Account Instagram» (non è codice di questo ramo, non verificato se preesistente).
3. Con yt-dlp assente (`venv/bin/yt-dlp` mancante) il cliente vede «Errore imprevisto durante la lavorazione.»: accettabile, ma poco utile.

Pulizia: server 8231/5274 fermati, DB `collaudo_upl` cancellato, link venv e node_modules rimossi, `BEC/media` di prova rimosso; `git status` mostra solo questo file.
## 6. Rilascio           (rilasciatore)
## Registro delle decisioni

- 2026-11-05 (capo, su mandato di Giuseppe: «once it finished trigger everything manually» = approvare e procedere con le scelte raccomandate):
  - Q1: **B + articoli web** in questo ramo. Instagram e PDF/DOCX in una scheda successiva. Drive/Dropbox fuori.
  - Q2: un link reincollato che era fallito o rimosso **riparte da solo** (riportato come «riprovato»), e in più il pulsante «Riprova».
  - Q3: sì alla migrazione per l'unicità di `source_url`.
  - Q4: sì, la lettura del titolo va nel worker.
  - Q5: età dei cookie nella pagina Stato: fuori da questo ramo (non fatto).
  - Q6: cookie YouTube/Vimeo da riesportare: **lo fa Giuseppe**; il collaudo segnala come «non verificabile» la trascrizione da link se i cookie sono scaduti, senza dichiararla verde.
  - Q7: più file trascinati = coda automatica.

- 2026-11-05 (capo): revisione PASSA, collaudo PASSA con parti NON VERIFICATE (trascrizione da link YouTube/Vimeo: cookie scaduti). Secondo giro sui rilievi minori fatto (630171c, 90 test OK). stato: pronto.

- 2026-11-05 (capo): #11 fuso in main con `0023_removed_at`. La migrazione di questo ramo rinumerata a `0024_uploadedmedia_unique_link`, dipende da `0023_removed_at` (niente merge/rebase: regola git-flow). Sul ramo da solo la catena è incompleta; la CI gira sul merge della PR, dove è lineare.
