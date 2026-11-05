# Regola: si pianifica con Fable, si esegue con Sonnet

## Le tre righe che contano

1. **Il piano lo fa Fable.** Disegno, analisi del codice, scelta dei file da
   toccare, rischi: tutto questo gira su Fable (`model: fable`). È il lavoro
   dove serve il modello più forte.
2. **Dopo l'OK di Giuseppe, si esegue con Sonnet.** Scrivere il codice,
   rileggere il diff, collaudare, rilasciare: `model: sonnet`. Fable non si usa
   per eseguire un piano già approvato: costa di più e non aggiunge nulla.
3. **La squadra `medyca-*` resta il percorso.** Questa regola dice *quale
   modello* usa ogni compagno, non cambia *chi fa cosa*. Il copione resta
   quello di `.claude/skills/medyca-capo/SKILL.md`: architetto → OK di
   Giuseppe → sviluppatore → revisore + collaudatore → PR → rilasciatore.

## Chi usa quale modello

| Fase | Compagno | Modello |
|---|---|---|
| Piano | `medyca-architetto` | fable |
| Esecuzione | `medyca-sviluppatore` | sonnet |
| Esecuzione | `medyca-revisore` | sonnet |
| Esecuzione | `medyca-collaudatore` | sonnet |
| Esecuzione | `medyca-rilasciatore` | sonnet |

Il modello è scritto nel campo `model:` in cima a ogni file di
`.claude/agents/`. Se si cambia lì, si cambia anche questa tabella e quella di
`documentation/low-level/08-agent-team.md`, nello stesso commit.

## Anche senza squadra

Quando il capo fa da solo un lavoro piccolo (vedi `medyca-capo`, «serve
davvero la squadra?»), vale lo stesso principio: se serve un piano lo si
chiede a un agente con `model: fable`, e il lavoro di esecuzione lo si affida
a un agente con `model: sonnet`. Non si passa a Fable per scrivere codice.

## Perché

Il piano è il punto dove un errore costa di più: un disegno sbagliato produce
codice sbagliato in tutti i passi dopo. Lì serve il modello migliore. Una volta
che Giuseppe ha approvato il disegno, il lavoro è seguire istruzioni chiare, e
Sonnet lo fa bene a un costo molto più basso.
