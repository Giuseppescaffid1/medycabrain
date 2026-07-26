# medycabrain — istruzioni di progetto

Piattaforma di Content Intelligence per Medyca (nicchia menopausa).
`BEC/` Django + PostgreSQL · `FEC/` React + Vite · live su `:9093`.

## Regole

- **Documenta tutto, nello stesso commit che cambia il comportamento.**
  Regola completa: `.claude/rules/documentation.md`. In breve: ogni modifica a
  uno stadio della pipeline aggiorna sia `docs/medycabrain-pipeline-cliente.drawio`
  sia la pagina `Documentazione` dell'app; i limiti noti si scrivono appena si
  conoscono.
- **UI**: seguire `.claude/skills/ui-design/` (token del brand Medyca, mobile
  first, stati vuoti/caricamento/errore sempre previsti).
- **Testare da utente reale prima di consegnare**: gesto vero sulla UI live,
  mobile e desktop, non solo la chiamata API.
- **Niente credenziali di terze parti rivendute** nella pipeline che lavora i
  contenuti del cliente.
- I fallimenti restano `failed`: non azzerarli silenziosamente per farli
  ritentare all'infinito.
