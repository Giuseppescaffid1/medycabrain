# La lavagna della squadra

Un file per lavoro. **È così che i cinque compagni si passano il contesto**: non
possono parlarsi, quindi ognuno legge questo file per intero prima di iniziare e
vi aggiunge solo la propria sezione. Quello che non è scritto qui, per il
compagno successivo non esiste.

Nome del file: `.claude/tasks/<AAAA-MM-GG>-<slug>.md`.

## Lo scheletro

```markdown
---
id: 2026-09-14-blog-autodiscovery
titolo: Trovare il blog partendo da un dominio nudo
stato: disegno
ramo: feat/blog-autodiscovery
pr: ""
ticket: MEDYC-9
---

## 1. Richiesta          (capo)
## 2. Disegno            (architetto)
## 3. Sviluppo           (sviluppatore)
## 4. Revisione          (revisore)
## 5. Collaudo           (collaudatore)
## 6. Rilascio           (rilasciatore)
## Registro delle decisioni
```

## Gli stati

| `stato:` | Dove siamo | Chi tocca a |
|---|---|---|
| `disegno` | l'architetto sta studiando, o il disegno aspetta un OK | Giuseppe |
| `approvato` | il disegno è stato approvato | sviluppatore |
| `sviluppo` | si sta scrivendo il codice, o sono tornati dei rilievi | sviluppatore |
| `revisione` | il codice è sul ramo | revisore + collaudatore |
| `pronto` | revisione e collaudo passati | capo (apre la PR) |
| `rilasciato` | fuso in `main` e messo in produzione | — |
| `fermo` | bloccato: il perché sta nel registro delle decisioni | Giuseppe |

Il campo `stato:` **è** la lavagna: non c'è nessun file indice da tenere
allineato a mano, perché divergerebbe. `/bacheca` legge il frontmatter di tutti
i file e stampa la tabella.

## Come si scrive

- **Numeri, non aggettivi.** «404 articoli su 835 bocciati» batte «molti
  articoli bocciati».
- **Cosa è rimasto fuori si scrive.** Un limite dichiarato è una promessa
  mantenuta; un limite taciuto diventa un bug.
- **Ognuno la sua sezione.** Nessuno riscrive quella di un altro. Se non sei
  d'accordo con chi ti ha preceduto, scrivilo nel registro delle decisioni, con
  la data.
- **Il registro delle decisioni è la memoria.** Le scelte chiuse restano chiuse:
  serve a non riaprire tre volte la stessa discussione.

Questi file restano nel repo anche a lavoro finito: sono il «perché» che il
codice da solo non racconta.
