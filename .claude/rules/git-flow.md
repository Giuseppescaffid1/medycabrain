# Regola: `main` si apre solo con una pull request

Questa regola sostituisce la vecchia `no-commit.md`, che diceva l'opposto:
allora Claude non toccava git e Giuseppe committava tutto a mano. Il motivo di
quella regola resta valido e non è cambiato - **Giuseppe vuole leggere ogni
diff prima che entri nella storia** - ma adesso è la pull request a garantirlo,
non il divieto.

## Le tre righe che contano

1. **`main` non si scrive mai direttamente.** Da nessuno: né dagli agenti, né a
   mano. È protetto anche lato GitHub, quindi un push diretto viene rifiutato
   dal server.
2. **Ogni modifica passa da un ramo e da una PR**: `feat/<slug>`, commit sul
   ramo, push, `gh pr create`.
3. **Il merge lo fa Giuseppe**, su GitHub, dopo aver letto il diff. Nessun
   agente esegue `gh pr merge`, mai, nemmeno con la revisione e il collaudo
   verdi.

## Cosa può fare un agente

- Creare un ramo: `git checkout -b feat/<slug>`
- Committare **sul ramo** - controllando prima `git branch --show-current`: se
  stampa `main`, ci si ferma
- Pushare il ramo: `git push -u origin feat/<slug>`
- Aprire la PR: `gh pr create` (la apre il capo, non lo sviluppatore)
- Tutto git di sola lettura: `status`, `diff`, `log`, `show`

## Cosa non fa mai

- `gh pr merge` - il merge è di Giuseppe
- `git push` su `main`, in qualunque forma
- `git push --force` o `-f`, su qualunque ramo
- `git merge`, `git rebase`, `git reset --hard`, `git stash`
- Riscrivere la storia di un ramo già pushato

Questi divieti sono anche in `.claude/settings.json`, ma quella è una cintura,
non il freno: le regole di corrispondenza non coprono ogni modo di scrivere un
comando. **Il freno vero è il ruleset su GitHub.**

## Il messaggio di commit

Spiega **la causa, non l'elenco delle modifiche**. Il diff dice già cosa è
cambiato; il messaggio deve dire perché. "Il cliente incollava lo stesso link
due volte e il secondo import esplodeva" vale più di "modificato
upload_workflow.py".

I commit scritti da un agente finiscono con:

    Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>

## Perché

Giuseppe vuole leggere ogni diff prima che entri nella storia, e tenere sua la
decisione di fondere. La PR gli dà entrambe le cose **e in più** un posto dove
la revisione e il collaudo restano scritti, invece di sparire con la sessione.
