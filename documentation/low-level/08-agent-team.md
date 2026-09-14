# 08 — The agent team, and how code reaches `main`

Every change to this repo is now built by a **team of agents** and enters `main`
through a **pull request**. Nobody writes to `main` directly — not the agents,
not by hand. This page says who the agents are, how they pass work to each
other, and what stops a bad change.

Rules that govern this: [`.claude/rules/git-flow.md`](../../.claude/rules/git-flow.md)
and [`.claude/rules/documentation.md`](../../.claude/rules/documentation.md).

## The shape: hub and spoke

```
                 Giuseppe
                    │  chiede una funzione, approva il disegno, fonde la PR
                    ▼
       ┌────────────────────────┐
       │  medyca-capo  (HUB)    │   la sessione principale di Claude Code
       │  skill, non un agente  │
       └───┬────────────────────┘
           │ lancia uno alla volta, e legge solo il verdetto
           │
   ┌───────┼───────────┬──────────────┬───────────────┐
   ▼       ▼           ▼              ▼               ▼
architetto  sviluppatore  revisore   collaudatore   rilasciatore
 (disegna)   (scrive)     (rilegge)   (esegue)       (mette in produzione)
   │            │            │            │               │
   └────────────┴──────┬─────┴────────────┴───────────────┘
                       ▼
          .claude/tasks/<data>-<slug>.md
          la lavagna condivisa — l'UNICO modo in cui
          i compagni si passano il contesto
```

**Why the hub is the main session and not an agent.** A Claude Code subagent
cannot call another subagent, and cannot talk to its siblings — it reports only
to whoever launched it. So the only thing that can actually orchestrate is the
session Giuseppe types into. `medyca-capo` is therefore a **skill**
(`.claude/skills/medyca-capo/SKILL.md`) that turns the main session into the
team lead, not a sixth agent.

The practical benefit: the heavy context (file reads, diffs, test output) stays
inside each spoke and never floods the hub.

## The five teammates

All live in `.claude/agents/`, all named `medyca-*` so they group together in
the agent list.

| Agent | Model | Writes? | Job |
|---|---|---|---|
| `medyca-architetto` | opus | no — read-only | Studies the existing code, proposes the structure, names the files to touch and the risks. **Stops for Giuseppe's approval.** |
| `medyca-sviluppatore` | opus | yes | Implements the approved design on `feat/<slug>`, updates the documentation in the same change, commits to the branch. |
| `medyca-revisore` | opus | no — read-only | Reads `git diff main...HEAD`. Checks project invariants and secrets, not style. Explicit verdict. |
| `medyca-collaudatore` | opus | no (runs commands) | Runs the tests, the build, and the real-user gesture on `:9093`. Pastes real output. |
| `medyca-rilasciatore` | sonnet | yes, after confirmation | Migrations, static files, frontend build, systemd restart. **Asks before every write or restart.** |

## The shared task list

`.claude/tasks/<AAAA-MM-GG>-<slug>.md`, one file per piece of work, with a fixed
skeleton (see [`.claude/tasks/README.md`](../../.claude/tasks/README.md)). Each
teammate reads the whole file before starting and appends **only its own
section**. Sections 1–6 map one-to-one onto the six roles.

The `stato:` field in the frontmatter **is** the board — there is no index file
to keep in sync, because it would drift. `/bacheca` reads every file's
frontmatter and prints the table.

States: `disegno → approvato → sviluppo → revisione → pronto → rilasciato`, plus
`fermo` when something is blocked.

## The cycle

1. Giuseppe asks for something (`/feature <descrizione>`).
2. The lead opens the task file and launches the **architetto**.
3. The design comes back in plain Italian. **Giuseppe approves it, or not.**
   This is the cheap moment to kill a wrong idea.
4. The **sviluppatore** branches, implements, documents, commits.
5. The **revisore** and the **collaudatore** run **in parallel** — one reads,
   one executes, so they do not collide. Two rounds of fixes at most; on the
   third the lead stops and calls Giuseppe, because the problem is in the design.
6. The lead pushes the branch and opens the PR. **It stops there.**
7. Giuseppe reads the diff on GitHub and merges.
8. On request, the **rilasciatore** deploys.

## What actually stops a bad change

Four gates, in increasing order of how hard they are to bypass:

1. **The design approval** — a human, before any code exists.
2. **`.claude/settings.json`** — denies `gh pr merge`, force push, `git merge`,
   `git rebase`, `git reset --hard`, and push to `main`. This is a *belt*: the
   pattern matching does not cover every way of spelling a command.
3. **CI** (`.github/workflows/ci.yml`) — two required jobs on every PR.
4. **The GitHub ruleset on `main`** — the real brake. It refuses a direct push
   however the command is written, requires a PR, an approval, and green CI.

## CI, and why it does not install `requirements.txt`

`requirements.txt` pulls in `sentence-transformers` and `faster-whisper`, hence
torch: gigabytes and minutes on every pull request, to run two smoke tests. CI
uses **`BEC/requirements-ci.txt`** instead — 11 light packages.

This works because the heavy models are imported **lazily**, inside the
functions that use them (`core/knowledge.py:_get_embedder`). `numpy` and
`curl_cffi` *are* module-level (`core/knowledge.py:25`, `scraper/ig_client.py:29`)
and are therefore included.

Verified on 2026-09-14 with a throwaway venv built from `requirements-ci.txt`:
`manage.py check`, `makemigrations --check --dry-run` and `test core` all pass.
If a heavy import ever moves back to module level, CI fails with
`ModuleNotFoundError` — that is the signal to fix the import, or this file.

The two jobs:

- **backend** — Postgres 16 service, then `makemigrations --check --dry-run`
  (catches a changed model with a missing migration — the failure that otherwise
  surfaces at deploy time), `check`, `test core`.
- **frontend** — `npm ci` then `npm run build`, which is `tsc -b && vite build`
  and therefore the only automatic type gate the frontend has.

## Known limits — read these before trusting the team

- **The teammates cannot talk to each other.** The task file is the only channel.
  If one of them fails to write its section, the next works blind. The fixed
  skeleton is the only guarantee.
- **The test net is thin**: two smoke tests and a type check. The collaudatore
  can legitimately report "green" on a broken feature. Until coverage grows, the
  real-user gesture on the live UI is not optional and not replaceable by an API
  call.
- **The ruleset binds GitHub, not this machine.** Locally `main` stays writable;
  the refusal happens at push time.
- **A full cycle is five model sessions, mostly Opus.** For a one-line fix that
  is disproportionate — the lead is explicitly allowed to do small work directly,
  though still on a branch and still through a PR.
- **Plane stays out of sync.** `TICKETS.md` is generated read-only by
  `tools/plane_tickets.py` (no write API), so no agent updates it. The `ticket:`
  field in a task file is a hand-written cross-reference, nothing more.
