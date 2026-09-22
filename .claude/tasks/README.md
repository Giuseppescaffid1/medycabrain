# La lavagna della squadra

I compagni non possono parlarsi. Si passano il contesto **solo** attraverso
questi file: quello che non è scritto qui, per il compagno dopo non esiste.

## Due file, non uno

Il primo giro vero ha prodotto un file di lavoro da **972 righe**, e ogni
compagno lo rileggeva per intero prima di iniziare: da solo valeva una buona
parte dei ~567.000 token che è costato quel giro. Da qui la divisione:

| File | Cos'è | Chi lo legge |
|---|---|---|
| `.claude/tasks/<data>-<slug>.md` | **la lavagna**: stato, mappa del codice, verdetti in poche righe | **tutti, sempre, per intero** |
| `.claude/tasks/<data>-<slug>.log.md` | **il registro**: verdetti per esteso, output dei comandi, prove | solo chi ha bisogno di un dettaglio |

La lavagna **non cresce**: ogni sezione sta in circa 40 righe, e quando un
verdetto è lungo va nel registro con un rimando. Il registro cresce quanto
vuole, perché nessuno lo legge da cima a fondo.

## La lavagna

```markdown
---
id: 2026-09-14-blog-autodiscovery
titolo: Trovare il blog partendo da un dominio nudo
stato: disegno
ramo: feat/blog-autodiscovery
pr: ""
---

## Sintesi            ← SEMPRE aggiornata, max 8 righe. Chi arriva legge questa.
Dove siamo, cosa manca, a chi tocca. Se leggi solo questo, devi capire tutto.

## 0. Mappa           ← la scrive l'architetto, la usano tutti
I file che contano, con percorso e riga. Serve a NON riesplorare il progetto
da capo: chi trova qualcosa che manca, lo aggiunge qui.

## 1. Richiesta       (capo)           le parole di Giuseppe, non le tue
## 2. Disegno         (architetto)     → si ferma e aspetta l'OK
## 3. Sviluppo        (sviluppatore)   file toccati, scelte, cosa è rimasto fuori
## 4. Revisione       (revisore)       verdetto + rilievi, uno per riga
## 5. Collaudo        (collaudatore)   verdetto + cosa non ha potuto provare
## 6. Rilascio        (capo)           passi eseguiti
## Decisioni          perché sì e perché no, con la data
```

## La sezione 0, che è la novità che fa risparmiare di più

L'architetto è l'unico che esplora il progetto. Quello che trova lo scrive nella
**Mappa**: percorsi esatti, righe, funzioni da riusare, vincoli misurati. Tutti
gli altri partono da lì invece di rifare la stessa ricerca.

```markdown
## 0. Mappa
- `BEC/core/link_ingest.py:66` — `_YT_ID`, la regex degli id
- `BEC/core/upload_workflow.py:114` — `run_upload_transcribe`, da riusare
- `BEC/core/views.py:210` — l'unico punto fuori dal modulo che assume YouTube
- vincolo: `source_url` è `unique=True` → la forma canonica è la deduplica
```

Se un compagno scopre un file che la mappa non aveva, **lo aggiunge**: è così
che la mappa migliora invece di invecchiare.

## Gli stati

| `stato:` | Dove siamo | Tocca a |
|---|---|---|
| `disegno` | l'architetto studia, o il disegno aspetta un OK | Giuseppe |
| `approvato` | disegno approvato | sviluppatore |
| `sviluppo` | si scrive, o sono tornati dei rilievi | sviluppatore |
| `revisione` | il codice è sul ramo | revisore + collaudatore |
| `pronto` | revisione e collaudo passati | capo (apre la PR) |
| `rilasciato` | fuso e in produzione | — |
| `fermo` | bloccato: il perché è nelle Decisioni | Giuseppe |

Il campo `stato:` **è** la lavagna: nessun file indice da tenere allineato a
mano, che divergerebbe. `/bacheca` legge il frontmatter e la Sintesi di tutti i
file e stampa la tabella.

## Come si scrive

- **La Sintesi si riscrive, non si appende.** È l'unica parte che si sovrascrive.
- **Numeri, non aggettivi.** «404 articoli su 835 bocciati» batte «molti».
- **Cosa è rimasto fuori si scrive.** Un limite dichiarato è una promessa
  mantenuta; un limite taciuto diventa un bug.
- **Ognuno la sua sezione.** Se non sei d'accordo con chi ti ha preceduto, lo
  scrivi nelle Decisioni con la data, non riscrivi la sua parte.
- **Più di 40 righe? Nel registro.** Nella lavagna resta il verdetto e il
  rimando: `dettagli nel registro, §4`.

Questi file restano nel repo a lavoro finito: sono il «perché» che il codice da
solo non racconta.
