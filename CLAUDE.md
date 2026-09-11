# medycabrain — istruzioni di progetto

Piattaforma di Content Intelligence per Medyca (nicchia menopausa).
`BEC/` Django + PostgreSQL · `FEC/` React + Vite · live su `:9093`.

## Architettura in breve

Quattro cose entrano — reel Instagram (Medyca + competitor), articoli di blog,
upload audio/video del cliente, temi indicati dal cliente. Una pipeline notturna
(`pipeline/dag.py`: `scrape → download → transcribe → enrich → embed → blogscrape
→ knowledge → cluster`) le scarica, trascrive l'audio, le fa leggere a un LLM,
le trasforma in vettori e le raggruppa in temi. **Regola che vale su tutto: il
contenuto di Medyca (`owner_type="owned"`) non si mescola mai con quello dei
competitor.** Tutto finisce in un unico database PostgreSQL (le tabelle stanno
nell'unica app Django `core`, `BEC/core/models.py`; i vettori sono colonne JSON,
niente pgvector). Si raggiunge in due modi: la UI React e il connettore **MCP**
(`BEC/mcp_bridge/server.py`, 4 strumenti di sola lettura che interrogano il DB via
ORM). Dettaglio completo in `documentation/` e riassunto in
`.claude/architecture-summary.md`.

## Regole

- **Spiega in modo semplice.** Documentazione, risposte in chat e messaggi: usa
  parole semplici, frasi corte, niente linguaggio complicato o gergo inutile.
  Quando un termine tecnico serve davvero, spiegalo in mezza riga. Il cliente non
  è un ingegnere: se una cosa non si può spiegare in modo semplice, non è finita.

- **Documenta tutto, nello stesso commit che cambia il comportamento.**
  Regola completa: `.claude/rules/documentation.md`. In breve: ogni nuova feature
  o cambiamento strutturale (modello/migrazione, stadio della pipeline, strumento
  MCP, endpoint, soglia/modello) aggiorna il file giusto in `documentation/`,
  `docs/medycabrain-pipeline-cliente.drawio` e la pagina `Documentazione` dell'app;
  i limiti noti si scrivono appena si conoscono.
- **Non fare commit e non fare push.** Regola completa:
  `.claude/rules/no-commit.md`. Le modifiche restano nella working tree, i
  commit li fa Giuseppe a mano dopo aver letto il diff. Vale anche quando la
  regola sulla documentazione dice “stesso commit”: significa *stesse
  modifiche insieme nella working tree*, non che Claude crei il commit.
- **UI**: seguire `.claude/skills/ui-design/` (token del brand Medyca, mobile
  first, stati vuoti/caricamento/errore sempre previsti).
- **Testare da utente reale prima di consegnare**: gesto vero sulla UI live,
  mobile e desktop, non solo la chiamata API.
- **Niente credenziali di terze parti rivendute** nella pipeline che lavora i
  contenuti del cliente.
- I fallimenti restano `failed`: non azzerarli silenziosamente per farli
  ritentare all'infinito.
