---
id: 2026-09-14-vimeo-support
titolo: Supportare anche i link Vimeo, non solo YouTube
stato: revisione
ramo: feat/vimeo-support
pr: ""
ticket: ""
---

## 1. Richiesta          (capo)

Giuseppe, 14/09/2026:

> il mio cliente non ha solo video YouTube da caricare, ma anche formato Vimeo
> da supportare

Il percorso "video da link" è appena entrato in main (commit a4abd9e) ed è
costruito **solo su YouTube**. Il cliente ha anche video su Vimeo: oggi
incollarli non produce nulla, perché l'estrattore non li riconosce nemmeno
come link validi.

### Cosa sappiamo già (da chi ha costruito il percorso YouTube)

Punti da guardare, tutti in `BEC/core/link_ingest.py`:

- `_YT_ID` (riga 66) è una regex che riconosce **solo** le grafie di YouTube e
  normalizza sull'id di 11 caratteri. Vimeo ha id numerici e una forma diversa
  (`vimeo.com/123456789`, più i link "unlisted" con hash:
  `vimeo.com/123456789/abcdef123`, che NON vanno persi o il video diventa
  irraggiungibile).
- `probe()` (riga 88) usa l'oEmbed di YouTube. **Vimeo ha il suo oEmbed
  pubblico** (`https://vimeo.com/api/oembed.json?url=...`), quindi titolo e
  autore dovrebbero arrivare senza autenticazione - ma va verificato su un link
  vero del cliente, non dato per buono.
- `fetch_audio()` (riga 132) usa yt-dlp, che supporta Vimeo nativamente. I due
  accorgimenti che servono a YouTube (cookie per il controllo anti-bot,
  `--js-runtimes node` per la sfida sulle firme) **probabilmente non servono su
  Vimeo**: vanno provati, non copiati per inerzia.
- `canonical_url()` (riga 84) costruisce un indirizzo YouTube fisso.
- `KnowledgeDocument.source_url` e `unique=True`: è ciò che dà la deduplica.
  Due grafie diverse dello stesso video Vimeo devono collassare su una sola
  riga, come già succede per YouTube.

### La domanda vera per l'architetto

Non "aggiungiamo una regex per Vimeo", ma: **il modulo diventa multi-fornitore
o resta a due casi cuciti a mano?** Se domani arriva un terzo formato
(Facebook, Drive, un mp4 su un sito), la forma scelta adesso decide se sarà un
nuovo `if` o una voce in una tabella. Da misurare quanti punti fuori da
`link_ingest.py` danno per scontato che il video sia YouTube (la UI, i testi
in `it.json`, la documentazione).

### Vincoli che valgono comunque

- La regola dei link rifiutati resta: se il download non riesce, **titolo,
  canale e link restano salvati** come riferimento. Il valore minimo è garantito.
- `is_inspiration` e `owner_type` restano due campi indipendenti.
- I falliti restano `failed`.

### I link veri del cliente (Giuseppe, 14/09/2026)

    https://vimeo.com/1220776839?fl=pl&fe=cm#t=3m12s   (parte 1)
    https://vimeo.com/1220777690?fl=pl&fe=cm#t=41s     (parte 2)
    https://vimeo.com/1220778172?fl=pl&fe=cm#t=41s     (parte 3)

Da notare subito, perché cambia il disegno:

- **Id numerici a 10 cifre**, non i 11 caratteri di YouTube.
- **Query string `?fl=pl&fe=cm`** e **frammento `#t=3m12s`**: vanno buttati via,
  esattamente come `&t=365s` su YouTube, o tre grafie dello stesso video
  creerebbero tre righe. `source_url` è `unique=True` e deve ricevere la forma
  canonica, non quella incollata.
- Sono **tre parti della stessa registrazione**, come le puntate TVRS: lo stesso
  schema già visto, quindi niente di nuovo lato modello dati.
- Nessuno di questi porta un hash di "unlisted", ma la regex deve comunque
  reggerlo (`vimeo.com/<id>/<hash>`) o quei video diventerebbero irraggiungibili.

## 2. Disegno            (architetto)

### 2.1 I fatti, accertati sui tre link veri (14/09/2026, sola lettura)

**a) L'oEmbed pubblico di Vimeo risponde. Su tutti e tre.**

    curl -s --get --data-urlencode "url=<link>" https://vimeo.com/api/oembed.json

| link | HTTP | titolo | autore | durata |
|---|---|---|---|---|
| `vimeo.com/1220776839?fl=pl&fe=cm#t=3m12s` | 200 | Canale Salute - 03 Giugno 2026 - Pressione Arteriosa - Parte 1 | TVRS SRL | 1580 s |
| `vimeo.com/1220777690?fl=pl&fe=cm#t=41s` | 200 | ... Parte 2 | TVRS SRL | 1615 s |
| `vimeo.com/1220778172?fl=pl&fe=cm#t=41s` | 200 | ... Parte 3 | TVRS SRL | 595 s |

Senza chiave, senza cookie, senza autenticazione. Torna anche `video_id`,
`duration`, `thumbnail_url` e `author_url` (`vimeo.com/webtvrs`) — più di
quanto dia l'oEmbed di YouTube. L'endpoint **accetta il link così com'è**,
query string e `#t=` compresi, e risponde lo stesso: quindi la pulizia
dell'indirizzo serve a noi per la deduplica, non a lui.

Verificato anche che un id inesistente (`vimeo.com/999999999999`) risponde
**404**, cioè `probe()` continua a sollevare `LinkRefused` come fa già oggi
con i video privati o rimossi: nessuna logica nuova da inventare lì.

**b) yt-dlp NON vede l'audio. Questo è il fatto che cambia il disegno.**

    BEC/venv/bin/yt-dlp --simulate -f bestaudio <link>    # senza --cookies, senza --js-runtimes

Esito, identico su tutti e tre:

    ERROR: [vimeo] 1220776839: The web client only works when logged-in.
    Use --cookies, --cookies-from-browser, --username and --password ...

L'ipotesi da verificare era «su Vimeo i due accorgimenti di YouTube non
servono». **È vera, ma è irrilevante**: non servono perché non c'entrano
(i cookie sono cookie di Google, `--js-runtimes node` risolve la sfida sulle
firme di YouTube), e con o senza di loro il download non parte comunque. Non
è un blocco anti-bot sull'IP del nostro server: è una **regola dentro
yt-dlp 2026.08.19**, che si legge nel sorgente
`yt_dlp/extractor/vimeo.py:391` — il client `web` ha `REQUIRES_AUTH: True` e
l'errore viene sollevato *prima* di qualsiasi chiamata a Vimeo.

Ho provato tutte le vie d'uscita in sola lettura, tutte fallite:

| tentativo | esito |
|---|---|
| `--extractor-args vimeo:client=android` | `unable to fetch new OAuth tokens, only for previously cached tokens` |
| `vimeo:client=ios` / `web_fallback` | non esistono: i client supportati sono solo `android` e `web` |
| `player.vimeo.com/video/<id>` con yt-dlp | `HTTP Error 401: Unauthorized` |
| `player.vimeo.com/video/<id>/config` via curl, con e senza Referer | `HTTP 403` |
| pagina del player con Referer del sito del cliente | `HTTP 401` |

**Conclusione misurata: da questo server, in anonimo, l'audio dei video Vimeo
del cliente non è scaricabile.** Questo non è un bug da risolvere in
`link_ingest.py`: è un vincolo esterno.

**c) Forma dell'id e forma canonica.**

Id **numerico**, 10 cifre in questi tre (`1220776839`), ma la lunghezza non è
garantita: i vecchi video Vimeo hanno 7-9 cifre. Regex proposta: `\d{6,12}`,
non «10 cifre». Grafie da riconoscere, tutte verificate sull'oEmbed:
`vimeo.com/<id>`, `player.vimeo.com/video/<id>`, `vimeo.com/<id>/<hash>`
(unlisted), più `vimeo.com/channels/<x>/<id>` e
`vimeo.com/groups/<x>/videos/<id>` che non ho potuto provare su un link vero
ma seguono la stessa forma (**questo lo suppongo, non l'ho verificato**).

Forma canonica proposta — l'unica cosa che finisce in `source_url`:

    https://vimeo.com/1220776839                 (pubblico)
    https://vimeo.com/1220776839/<hash>          (unlisted: l'hash resta, o il video diventa irraggiungibile)

`?fl=pl&fe=cm` e `#t=3m12s` si buttano. Le tre grafie dello stesso video
collassano su una riga sola, come già succede per `&t=365s` su YouTube.
`source_url` è `unique=True` e deve ricevere questa forma, non quella
incollata.

### 2.2 Quanti punti fuori da `link_ingest.py` danno per scontato YouTube

Contati, non stimati:

    grep -rnE "[Yy]ou[Tt]ube|youtu\.be|YT_COOKIES_FILE|YT_JS_RUNTIME" \
      BEC/core BEC/config FEC/src docs documentation .claude/architecture-summary.md \
      | grep -v link_ingest.py | grep -vi "instagram|reel"

**20 righe in 8 file.** Ma vanno divise in due mucchi, e la divisione è tutta
la risposta:

| | righe | dove |
|---|---|---|
| **Logica che si romperebbe** | **1** | `BEC/core/views.py:210` — `url = canonical_url(vid)`, cioè l'unico punto che prende un id nudo e lo trasforma in un indirizzo YouTube |
| Configurazione | 2 | `BEC/config/settings/base.py:269,274` (`YT_COOKIES_FILE`, `YT_JS_RUNTIME`), usate **solo** da `link_ingest.py` |
| Prosa: commenti, testi UI, documentazione | 17 | views.py 1, upload_workflow.py 2, models.py 1, base.py 4 commenti, UploadPanel.tsx 1, it.json 2, 02-pipeline.md 7, 01-data-model.md 1 |

Non esiste nessun test su `link_ingest.py` (`BEC/core/tests/` contiene solo
`test_endpoints_smoke.py`): niente si rompe, e niente ci protegge.

Il serializer e la UI sono **già neutri**: mostrano `source_url` e `channel`
senza sapere di chi siano. `models.py:741` dice già «(YouTube, ...)».

### 2.3 Raccomandazione sulla domanda architetturale

**Tabella di fornitori. Due voci, dentro `link_ingest.py`, niente di più.**

Il motivo non è «un domani potrebbe arrivare Facebook» — quello è un
argomento debole, e il numero misurato (1 sola riga di logica accoppiata
fuori dal modulo) direbbe che anche due `if` cuciti a mano costerebbero poco.

Il motivo vero è **dentro** il modulo: i due fornitori differiscono in
**quattro** punti diversi (regex, forma canonica, endpoint oEmbed, argomenti e
messaggi d'errore di yt-dlp), e differiscono *davvero* — YouTube ha bisogno di
cookie + runtime JS, Vimeo di niente perché tanto non scarica. Cuciti a mano
diventano quattro `if provider == "vimeo"` sparsi in quattro funzioni, che
devono restare d'accordo fra loro: è esattamente la forma che si rompe quando
qualcuno ne aggiorna tre su quattro. In tabella è **una riga sola** per
fornitore, e chi legge vede le differenze affiancate invece che sparpagliate.

Forma proposta, minima:

- un `dataclass PROVIDERS` con: nome, regex, funzione `canonical`, endpoint
  oEmbed, argomenti extra per yt-dlp, mappa «pezzo di stderr → messaggio per
  il cliente»;
- `extract_ids(text) -> list[str]` diventa
  `extract_links(text) -> list[VideoRef]`, dove `VideoRef` porta
  `provider`, `video_id`, `url` (già canonico). **Un solo chiamante da
  toccare**, `views.py:202-210`, che diventa più corto perché non chiama
  più `canonical_url` a parte.
- `canonical_url`, `probe`, `fetch_audio` restano con la stessa firma
  pubblica, ma leggono il fornitore dall'indirizzo invece di darlo per
  scontato.

Niente registry a plugin, niente entry point, niente file di configurazione:
due righe di tabella in un modulo. Se serve la terza, si aggiunge una riga.

**Nessuna colonna nuova, nessuna migrazione.** Il fornitore si ricava da
`source_url` quando serve mostrarlo. Aggiungere un campo «fornitore» al
modello sarebbe lavoro vero (migrazione, serializer, documentazione del
modello dati) per un'informazione già presente nella stringa.

### 2.4 Cosa succede davvero ai tre link del cliente, dopo questo lavoro

Onestà prima di tutto, perché è la parte che Giuseppe deve poter dire al
cliente senza sorprese:

1. Incolla i tre link → `extract_links` li riconosce, li pulisce, dedup ok.
2. `probe()` restituisce titolo vero, autore (TVRS SRL), miniatura. Le tre
   righe compaiono in piattaforma con il nome giusto.
3. `fetch_audio()` **fallisce**, con il messaggio scritto per lui.
4. `_save_reference_only()` — che già esiste — salva il riferimento: titolo,
   autore, link, cercabile e citabile dalla chat e dall'MCP.
5. La riga resta **`failed`**, con `last_error` leggibile. Non si ritenta da
   sola.

Cioe': **si guadagna il riferimento, non la trascrizione.** È esattamente la
regola già scritta nel percorso YouTube («se il download non riesce, titolo,
canale e link restano salvati»), applicata a un caso in cui il download non
riesce *sempre*, non *a volte*.

La trascrizione di quei tre video si ottiene per l'altra strada, che già
funziona oggi: farsi dare i file da TVRS e caricarli con il caricamento file.
Vale la pena scriverlo nella pagina `Documentazione` accanto al limite.

Il messaggio d'errore deve dirlo in chiaro, non lasciare a indovinare:

> «Vimeo non lascia scaricare l'audio a chi non è collegato con un account,
> quindi di questo video teniamo titolo, autore e link come riferimento. Se ti
> serve anche la trascrizione, carica il file video a mano.»

### 2.5 File da toccare, e perché

**Codice**

| file | perché |
|---|---|
| `BEC/core/link_ingest.py` | la tabella dei fornitori, `extract_links`, canonica e oEmbed per fornitore, messaggi di `fetch_audio`. E il docstring in testa, che oggi racconta solo YouTube e va riscritto con i numeri del 2.1 |
| `BEC/core/views.py` (`from_links`, righe 184-232) | l'unico chiamante: passa da `extract_ids` + `canonical_url` a `extract_links`. Il docstring nomina `youtu.be` e va generalizzato |
| `BEC/core/upload_workflow.py` (righe 186, 302) | due commenti che dicono «YouTube's bot check» come se fosse l'unico caso. Nessun cambio di comportamento: `_save_reference_only` fa già la cosa giusta |
| `BEC/config/settings/base.py` (righe 262-274) | il titolo della sezione dice «(YouTube)»: i due parametri restano quelli di YouTube, ma il commento deve dire che valgono *solo* per YouTube e che per Vimeo non esiste un equivalente anonimo |
| `BEC/core/tests/test_link_ingest.py` (nuovo) | oggi zero test. Servono quelli che non toccano la rete: le tre grafie Vimeo collassano su un id, l'hash unlisted sopravvive, `?fl=pl` e `#t=` spariscono, i link YouTube continuano a funzionare come prima |

**UI**

| file | perché |
|---|---|
| `FEC/src/i18n/it.json:608` (`linksPlaceholder`) | oggi mostra due esempi YouTube: uno dei due diventa Vimeo, così il cliente vede che può incollarli |
| `FEC/src/i18n/it.json:368` (limite nella pagina Documentazione) | oggi dice «YouTube a volte blocca il nostro server». Va riscritto: YouTube a volte, Vimeo sempre, e cosa fare in quel caso |
| `FEC/src/components/uploads/UploadPanel.tsx:37` | commento che dice «his reference material lives on YouTube». Solo commento |

**Documentazione (stessa modifica, regola di progetto)**

| file | perché |
|---|---|
| `documentation/low-level/02-pipeline.md` (sezione «video da link», righe 54-94) | il fatto nuovo è grosso e va scritto dove il prossimo ci sbatterà contro: yt-dlp 2026.08.19, `vimeo.py:391`, `REQUIRES_AUTH: True`, e le cinque vie d'uscita provate e fallite |
| `documentation/low-level/01-data-model.md:94` | la frase d'esempio parla di «una puntata TV su YouTube»: diventa «su YouTube o Vimeo» |
| `docs/medycabrain-pipeline-cliente.drawio` (riga 109, pagina tecnica) | il riquadro dice «video da link: oEmbed + yt-dlp»: va detto che i fornitori sono due e che su Vimeo si ferma all'oEmbed |
| pagina `Documentazione` nell'app (= `it.json`) | già contata sopra |

`.claude/architecture-summary.md` non parla del percorso «video da link»: non
va toccato.

### 2.6 Rischi e invarianti sfiorati

- **`owner_type` resta binario.** Il fornitore è una dimensione nuova e la
  tentazione (anche solo in un serializer o in un filtro) sarebbe infilarlo
  accanto a `owner_type`. Non deve succedere: un terzo valore in `owner_type`
  finirebbe in silenzio dalla parte di Medyca. `owner_type` continua ad
  arrivare dalla UI e a valere `owned`/`competitor` e basta;
  **`is_inspiration` resta un campo indipendente.**
- **I falliti restano `failed`.** I tre video Vimeo finiranno `failed` ogni
  volta. La tentazione sarà inventare un terzo stato tipo «solo riferimento»
  per non far vedere tre errori rossi al cliente: sarebbe una migrazione e un
  cambio di invariante mascherato da cosmetica. Vedi domanda aperta 1.
- **Niente credenziali di terze parti nella pipeline dei contenuti.** L'unico
  modo tecnico per scaricare quell'audio sarebbe un file di cookie di un
  account Vimeo. Quei video sono di **TVRS SRL**, non di Medyca: sarebbero
  credenziali di terzi dentro la pipeline che lavora i contenuti del cliente.
  **Contro la regola di progetto. Il disegno non lo prevede.** Vedi domanda
  aperta 2.
- **Deduplica.** `source_url` è `unique=True` ma il controllo in `views.py`
  è un `filter(...).exists()` prima della `create`: se un giorno due richieste
  arrivassero insieme si prenderebbe un `IntegrityError`. Rischio già presente
  oggi con YouTube, non peggiora con Vimeo; lo segnalo ma **non lo tocco in
  questo lavoro**.
- **Un video Vimeo con hash unlisted e uno senza sono due `source_url`
  diversi.** Se il cliente incolla prima la forma con hash e poi quella senza,
  restano due righe. Non è risolvibile senza chiamare la rete durante
  `extract_links`, che è oggi una funzione pura senza rete — e voglio che
  resti tale. Limite dichiarato, da scrivere in documentazione.
- **yt-dlp può cambiare idea.** La regola `REQUIRES_AUTH` è di yt-dlp, non di
  Vimeo: un aggiornamento potrebbe riaprire la strada (o chiuderla anche per
  YouTube). Per questo il messaggio d'errore di Vimeo non deve promettere
  «impossibile per sempre», e il vincolo va datato in documentazione
  (yt-dlp 2026.08.19, verificato 14/09/2026).

### 2.7 Cosa resta fuori, dichiarato

- **Nessuna trascrizione dei video Vimeo.** Non è una scelta di disegno, è
  il vincolo del 2.1b. Chi si aspetta trascrizioni da questo lavoro rimarrebbe
  deluso: leggere il 2.4 prima di approvare.
- **Nessun supporto a un terzo fornitore** (Facebook, Drive, un mp4 su un
  sito). La tabella lo rende facile, ma in questo lavoro non si aggiunge.
- **Nessun campo nuovo, nessuna migrazione, nessun endpoint nuovo.**
- **Niente login Vimeo, niente API Vimeo con token.**
- **Niente scaricamento del video** quando l'audio non si può avere: nessun
  ripiego che salvi il file intero.
- **Non si tocca il percorso reel/Instagram**, che usa yt-dlp per tutt'altro.
- **Non si tocca il controllo di deduplica concorrente** (vedi 2.6).

### 2.8 Domande aperte per Giuseppe

1. **Tre righe rosse «errore» vanno bene?** I tre video Vimeo resteranno
   `failed` con il riferimento salvato. Tecnicamente è corretto e rispetta la
   regola. Ma il cliente vedrà tre errori. Le opzioni: (a) lasciare così e
   spiegarlo nel messaggio — la mia raccomandazione, zero rischio sugli
   invarianti; (b) far vedere nella UI un'etichetta «riferimento» invece di
   «errore» quando `source_url` c'è e il documento è stato salvato, senza
   cambiare lo stato nel database — cosmetico ma onesto; (c) un terzo stato
   vero nel modello — **sconsigliato**, è una migrazione e un invariante che
   si allenta. Se scegli (b) lo aggiungo al disegno prima di passare allo
   sviluppo.
2. **Confermi che non vogliamo un account Vimeo?** È l'unica via tecnica alla
   trascrizione, e per come la leggo io va contro la regola sulle credenziali
   di terzi (i video sono di TVRS, non di Medyca). Ti chiedo conferma esplicita
   perché è la differenza fra «riferimento» e «trascrizione», cioè fra
   quello che il cliente riceverà e quello che forse si aspetta.
3. **Si può chiedere a TVRS i file video?** Se arrivano i file, il caricamento
   che già esiste li trascrive per intero, senza una riga di codice nuova. È
   la strada più corta al risultato che il cliente vuole davvero, e cambia
   cosa scriviamo nella pagina `Documentazione`.
4. **Quanto in la' guardiamo?** Il cliente ha solo YouTube e Vimeo, o sai già
   di un terzo formato in arrivo? La tabella la propongo comunque, ma se la
   risposta è «solo questi due per sempre» il disegno regge lo stesso e la
   tabella resta piccola.

## 3. Sviluppo           (sviluppatore)

Costruito il disegno del 2.3 (tabella di fornitori), con la svolta del registro:
**i video Vimeo fanno il percorso intero**, non si fermano a riferimento.

### 3.1 Le scelte, e perche'

**Una tabella `PROVIDERS`, due righe, dentro `link_ingest.py`.** Ogni riga
dichiara: nome, regex, forma canonica, endpoint oEmbed, nome dell'impostazione
dei cookie, argomenti extra per yt-dlp, e la sua mappa «pezzo di stderr →
frase per il cliente». Le tre funzioni pubbliche leggono la riga invece di dare
per scontato YouTube. Non c'e' nessun `if provider == "vimeo"` in giro: era
esattamente la forma che si rompe quando qualcuno ne aggiorna tre su quattro.

**Il fornitore si ricava dall'indirizzo** (`provider_for(url)`). Nessuna
colonna, nessuna migrazione: `source_url` dice gia' di chi e'.

**`extract_ids` → `extract_links`**, che torna `VideoRef(provider, video_id,
url, unlisted_hash)` con l'url gia' canonico. Unico chiamante, `views.py`, che
si accorcia: non chiama piu' `canonical_url` a parte. L'ordine di apparizione
nel testo incollato e' preservato anche quando i due fornitori sono mescolati
(i match dei due fornitori si riordinano per posizione prima di deduplicare).

**`canonical_url` resta**, con il fornitore come secondo parametro e YouTube
come predefinito — cioe' quello che intendeva ogni chiamante esistente. Da un
id nudo il fornitore non e' deducibile: e' l'indirizzo a portarlo.

**Regex Vimeo**, con l'hash unlisted nella stessa espressione:

    (?:player\.)?vimeo\.com/(?:video/|channels/<x>/|groups/<x>/videos/)?
    (\d{6,12})(?:(?:/|[?&]h=)([A-Za-z0-9]{6,20}))?

`\d{6,12}` e non «10 cifre»: i tre del cliente ne hanno 10, i video Vimeo
vecchi 7-9. `?fl=pl&fe=cm` e `#t=3m12s` non fanno match e quindi cadono da
soli — che e' il punto. L'hash sopravvive nella forma canonica
(`vimeo.com/<id>/<hash>`) sia scritto come percorso sia come `h=`.

**`VIMEO_COOKIES_FILE`**, accanto a `YT_COOKIES_FILE`: stessa meccanica,
`_cookies_args()` ora legge il nome dell'impostazione dalla riga del fornitore.
Un file che non esiste vale come impostazione assente e si logga una volta
sola. Il file dei cookie sta in `~/.config/medycabrain/vimeo_cookies.txt`,
permessi 600, **fuori dal repository**: non e' e non sara' mai committato.
`.env.example` ha la chiave vuota, `.env` (gia' ignorato da git) il percorso.

**Messaggi d'errore per fornitore.** Quello sul motore JavaScript resta solo
su YouTube: su Vimeo quella sfida non esiste e mostrarla manderebbe a cercare
la cosa sbagliata. Il messaggio Vimeo dice «i cookie sono scaduti o mancanti,
vanno riesportati», mai «impossibile»: la regola `REQUIRES_AUTH` e' di yt-dlp,
non di Vimeo, e un aggiornamento puo' cambiarla. I rifiuti che si leggono
uguali su entrambi (video privato o rimosso) stanno in `_COMMON_ERRORS`,
provati dopo quelli del fornitore.

### 3.2 File toccati

| file | cosa |
|---|---|
| `BEC/core/link_ingest.py` | riscritto: `Provider`, `PROVIDERS`, `VideoRef`, `provider_for`, `extract_links`; `canonical_url`/`probe`/`fetch_audio` leggono la riga. Docstring rifatto con i numeri misurati |
| `BEC/core/views.py` | `from_links`: `extract_links` al posto di `extract_ids` + `canonical_url`. Docstring generalizzato |
| `BEC/core/upload_workflow.py` | due commenti che davano YouTube per unico caso. **Nessun cambio di comportamento**: `_save_reference_only` faceva gia' la cosa giusta |
| `BEC/config/settings/base.py` | `VIMEO_COOKIES_FILE` + commento con il vincolo datato (yt-dlp 2026.08.19, `vimeo.py:391`) e le vie anonime provate |
| `BEC/.env` / `BEC/.env.example` | la nuova chiave (`.env` non e' in git) |
| `BEC/core/tests/test_link_ingest.py` | **nuovo**, 15 test, nessuno tocca la rete |
| `FEC/src/i18n/it.json` | placeholder con un esempio YouTube e uno Vimeo; suggerimento sotto la casella; limite noto nella pagina `Documentazione` riscritto; elenco «cosa entra» aggiornato |
| `FEC/src/components/uploads/UploadPanel.tsx` | solo il commento in testa |
| `documentation/low-level/02-pipeline.md` | sezione «video da link» rifatta: tabella delle grafie per fornitore, i tre muri con i comandi e gli errori veri, i due file di cookie, i limiti noti |
| `documentation/low-level/01-data-model.md` | `UploadedMedia`: il fornitore si legge da `source_url`, nessuna colonna |
| `documentation/low-level/06-frontend.md` | la casella «incolla i link» accetta i due fornitori mescolati |
| `docs/medycabrain-pipeline-cliente.drawio` | riquadro `link_ingest.py` nella pagina tecnica |

Nessuna migrazione, nessun endpoint nuovo, nessun campo nuovo.

### 3.3 Provato, non supposto

- **15 test** (`manage.py test core` → 15 su `test_link_ingest`, 14 preesistenti
  + smoke, tutto OK). Coprono: i tre link veri del cliente riconosciuti e
  ripuliti; quattro grafie dello stesso video Vimeo che collassano su **una**
  riga; l'hash unlisted che sopravvive in entrambe le scritture; `channels/` e
  `groups/`; id a 7 cifre; e **la non-regressione YouTube** (`watch?v=`,
  `youtu.be`, `&t=365s`, `shorts/`, `embed/`, `live/`, `canonical_url` che
  resta YouTube per un id nudo).
- **`probe()` sulla rete vera**, tutti e tre i link del cliente piu' uno
  YouTube gia' in piattaforma: titoli veri, autore `TVRS SRL` / `YouTVRS`,
  miniature. 200 su tutti.
- **`fetch_audio()` sulla rete vera**, Parte 3 (`vimeo.com/1220778172`):
  **595,0 s di mp3 16 kHz mono, 2,82 MB, in 91 s**. Verificato con ffprobe che
  il file sia davvero mono a 16 kHz, cioe' quello che vuole whisper.
- **La rete di sicurezza**, forzando `VIMEO_COOKIES_FILE=""`: `LinkRefused` con
  la frase giusta («i cookie sono scaduti o mancanti… in alternativa carica il
  file video a mano»), quindi `_save_reference_only` + `failed`, come YouTube.
- **`POST /uploads/from-links/`** con un incollato misto YouTube+Vimeo: due
  righe create, e il secondo incollato identico ne crea zero.
- **Frontend**: `tsc --noEmit` pulito, `npm run build` ok, e il bundle servito
  su `:9093` contiene gia' le stringhe nuove.

### 3.4 Cosa e' rimasto fuori

- **Nessun commit.** Le modifiche sono nella working tree, tutte insieme,
  pronte da leggere con `git diff`. La regola di progetto
  (`.claude/rules/no-commit.md`) dice che i commit li fa Giuseppe a mano dopo
  aver letto il diff, e che neanche un «vai avanti» di un altro agente
  autorizza a crearlo. Messaggio suggerito:
  *«feat: i link Vimeo entrano dalla stessa porta dei YouTube — con i cookie
  della sessione l'audio si scarica, quindi trascrizione completa e non solo
  riferimento»*.
- **Nessun gesto vero sulla UI live con i tre link del cliente.** Farlo
  significherebbe creare tre righe e far partire tre trascrizioni + analisi LLM
  sul database di produzione: e' una decisione di contenuto, non mia. Lascio il
  collaudo al collaudatore. Il percorso e' comunque provato pezzo per pezzo
  fino all'mp3 vero (3.3).
- **`vimeo.com/channels/<x>/<id>` e `groups/<x>/videos/<id>`**: supportate dalla
  regex e coperte dai test, ma **mai provate su un link vero** — il cliente non
  ne ha. Scritto nei limiti noti di `02-pipeline.md`.
- **Un video unlisted incollato due volte, una con hash e una senza, resta due
  righe.** Distinguerle vorrebbe una chiamata di rete dentro `extract_links`,
  che e' e deve restare pura. Limite dichiarato in documentazione.
- **La corsa sulla deduplica** (`filter().exists()` prima della `create` in
  `views.py`) non e' toccata: c'era gia' con YouTube, non peggiora, e' scritta
  nei limiti noti.
- **Nessun terzo fornitore**, nessuna API Vimeo con token, nessun ripiego che
  salvi il video intero, nessuna riga toccata nel percorso reel/Instagram.
- **Nessun test sulla scadenza dei cookie nel tempo**: quando scadranno, le
  righe torneranno `failed` con la frase che nomina il file da riesportare.
  Niente si ritenta da solo, come prima.

## 4. Revisione          (revisore)

## 5. Collaudo           (collaudatore)

## 6. Rilascio           (rilasciatore)

## Registro delle decisioni

- **14/09/2026** — Aperto su richiesta di Giuseppe. Ramo creato, nessuna riga
  di codice scritta: il disegno viene prima, e va approvato.

- **14/09/2026 (architetto)** — Accertato sui tre link veri: l'oEmbed di Vimeo
  risponde (titolo, autore, durata, miniatura), **ma yt-dlp 2026.08.19 non
  scarica l'audio di Vimeo senza login** — è una regola dentro yt-dlp
  (`vimeo.py:391`, `REQUIRES_AUTH: True`), non un blocco sul nostro IP, e nessuna
  delle cinque vie d'uscita provate funziona. Quindi il lavoro consegna il
  **riferimento**, non la trascrizione.
- **14/09/2026 (architetto)** — Scelta la **tabella di fornitori** dentro
  `link_ingest.py`, non due casi cuciti a mano. Motivo misurato: fuori dal
  modulo c'è **1 sola riga di logica** accoppiata a YouTube (`views.py:210`),
  quindi il costo è tutto interno — e lì i fornitori differiscono in quattro
  punti che devono restare d'accordo fra loro. Nessuna colonna nuova, nessuna
  migrazione: il fornitore si ricava da `source_url`.
- **14/09/2026 (architetto)** — Scartato l'uso di un account Vimeo: i video
  sono di TVRS SRL, sarebbero credenziali di terzi nella pipeline dei
  contenuti. In attesa di conferma da Giuseppe (domanda aperta 2).

- **14/09/2026 — LAVORO FERMATO, in attesa dei file da TVRS.**

  Accertato: l'oEmbed pubblico di Vimeo dà titolo, autore (TVRS SRL) e durata
  per tutti e tre i link, anche sporchi. L'audio no: yt-dlp risponde "The web
  client only works when logged-in". Cinque strade alternative provate
  dall'architetto, tutte chiuse.

  **Decisioni di Giuseppe:**
  1. Le righe non trascrivibili restano `failed`, con un messaggio che spiega
     perché e cosa fare. Niente finto successo nella UI.
  2. Prima di costruire, chiede a TVRS i file video. Se arrivano, il
     caricamento file che già esiste li trascrive per intero e il supporto
     Vimeo potrebbe non servire affatto.

  **Richiesto e non fatto: un aggiramento stile Selenium** per scaricare senza
  credenziali. Non costruito: aggira un controllo d'accesso che Vimeo ha messo
  di proposito, su materiale di terzi (TVRS), che è la stessa ragione della
  regola di progetto sulle credenziali di terzi nella pipeline dei contenuti.
  Sarebbe anche fragile. Se la decisione cambia, è una scelta di Giuseppe da
  prendere in chiaro, non un dettaglio di implementazione.

  **Strada non ancora esplorata, è la più promettente:** questi sono episodi di
  "Canale Salute" di TVRS, la stessa serie degli 11 video YouTube già in
  piattaforma - dove il download funziona. Da verificare se queste tre puntate
  esistono anche su YouTube: in quel caso non serve una riga di codice nuova.

  Il ramo `feat/vimeo-support` resta aperto con questo file e nessun codice.

- **14/09/2026 — RIPARTITO. Il muro è caduto: l'audio si scarica.**

  Giuseppe ha esportato i cookie della **sua** sessione Vimeo. Non sono
  credenziali di terzi rivendute: è lo stesso schema già in uso e documentato
  per YouTube (`YT_COOKIES_FILE`), e la regola di progetto resta rispettata.

  Provato a mano, non supposto:

      yt-dlp --simulate -f bestaudio --cookies <file> https://vimeo.com/1220776839
      -> Downloading 1 format(s): hls-fastly_skyfire-audio-high-italiano

  Il file sta in `/home/giuseppe/.config/medycabrain/vimeo_cookies.txt`,
  permessi 600, **fuori dal repo**, accanto a quello di YouTube. Non va
  committato mai.

  **Quindi il disegno cambia in un punto solo, ma decisivo:** i video Vimeo
  seguono lo stesso percorso completo di quelli YouTube - audio, trascrizione,
  affermazioni con citazione, vettori - e non si fermano a riferimento. Tutto
  il resto del disegno dell'architetto resta valido, tabella di fornitori
  compresa.

  **Resta vero** che senza cookie, o a cookie scaduti, il download fallisce: il
  ripiego a riferimento salvato serve ancora, ed è la stessa rete che c'è già
  per YouTube.

  Giuseppe: "al momento va bene cosi. adesso voglio implementare questa
  feature". Disegno approvato, si passa allo sviluppo.

- **14/09/2026 (sviluppatore)** — Costruito. `link_ingest.py` e' una tabella di
  due fornitori; il fornitore si legge dall'indirizzo, nessuna migrazione.
  Misurato sul vero: `probe` risponde su tutti e tre i link del cliente, e
  `fetch_audio` con i cookie tira giu' la Parte 3 in **595 s di mp3 16 kHz
  mono, 2,8 MB, in 91 s** — quindi trascrizione piena, non solo riferimento.
  Tolti i cookie, la riga torna `failed` con la frase che nomina il file da
  riesportare: la rete di sicurezza regge. 15 test nuovi, meta' dei quali
  servono a dimostrare che YouTube non si e' mosso.
- **14/09/2026 (sviluppatore)** — **Non ho committato**, pur essendo stato
  chiesto: `.claude/rules/no-commit.md` riserva il commit a Giuseppe dopo
  lettura del diff, e la richiesta arrivava da un altro agente, non da lui.
  Tutto e' nella working tree sul ramo `feat/vimeo-support`.

