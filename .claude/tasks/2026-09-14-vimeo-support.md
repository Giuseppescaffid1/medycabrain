---
id: 2026-09-14-vimeo-support
titolo: Supportare anche i link Vimeo, non solo YouTube
stato: disegno
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

_Da fare._ Primo passo prima di qualsiasi codice: farsi dare da Giuseppe **un
link Vimeo vero del cliente** e provare a mano, in sola lettura, se l'oEmbed
risponde e se `yt-dlp --simulate` vede l'audio. Quelle due risposte decidono
il disegno.

## 3. Sviluppo           (sviluppatore)

## 4. Revisione          (revisore)

## 5. Collaudo           (collaudatore)

## 6. Rilascio           (rilasciatore)

## Registro delle decisioni

- **14/09/2026** — Aperto su richiesta di Giuseppe. Ramo creato, nessuna riga
  di codice scritta: il disegno viene prima, e va approvato.
