---
description: Mostra la lavagna della squadra - tutti i lavori aperti e a che punto sono
allowed-tools: ["Bash"]
---

Leggi il frontmatter di ogni file in `.claude/tasks/` (escluso `README.md`) ed
elenca i lavori in una tabella: **stato**, titolo, ramo, PR, chi tocca a
(secondo la tabella degli stati in `.claude/tasks/README.md`).

Ordina dal più avanzato al meno avanzato: `rilasciato`, `pronto`, `revisione`,
`sviluppo`, `approvato`, `disegno`, `fermo`.

Metti in evidenza quelli che aspettano qualcosa da Giuseppe: `disegno` (un OK al
disegno), `pronto` (un merge), `fermo` (una decisione).

Comando utile:

    grep -H -m1 -A6 '^---$' .claude/tasks/*.md

Se non c'è nessun file di lavoro, dillo in una riga: la lavagna è vuota.
