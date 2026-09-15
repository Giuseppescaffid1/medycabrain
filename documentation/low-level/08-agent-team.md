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
| `medyca-revisore` | opus | the task file only | Reads `git diff main...HEAD`. Checks project invariants and secrets, not style. Explicit verdict. |
| `medyca-collaudatore` | sonnet | the task file only | Runs the tests, the build, and the real-user gesture on `:9093`. Pastes real output. |
| `medyca-rilasciatore` | sonnet | the task file only | **Inspects only.** Reports what the machine actually needs and hands the lead a list of commands. Does not migrate, build or restart. |

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

## Three defects found by running it (fixed 2026-09-14)

The first real cycle — Vimeo link support — exposed three faults in the team
itself, none of which were visible from reading the design. They are recorded
here because the next person will be tempted to reintroduce them.

**1. The reviewer and the tester could not write their own section.** They were
given read-only tools, which is right for *code* and wrong for the *board*. The
lead had to paste their verdicts by hand, so the context crossed the hub twice
and detail was lost. Fixed by giving both the `Edit` tool with an explicit,
narrow mandate: the task file in `.claude/tasks/` and nothing else.

**2. The developer refused to commit, citing a rule file that does not exist.**
It named `.claude/rules/no-commit.md` — deleted that morning and replaced by
`git-flow.md`, which says the opposite. A refusal grounded in an invented file
is not caution; it blocks the work. Fixed in two places: `git-flow.md` now
opens by stating it is the *only* git rule and that the old one is gone, and
`medyca-sviluppatore.md` tells the agent to run `ls .claude/rules/` before
refusing anything on the authority of a rule.

**3. `git-flow.md` invited the confusion.** Its first line used to read "this
rule replaces the old `no-commit.md`" — a helpful piece of history that an agent
skimming for rules reads as a live filename. Rewritten so the replacement is
stated as history, after the rule itself.

The general lesson, worth keeping: **an agent that refuses while citing a rule
is behaving correctly.** The bug was the phantom rule, not the refusal. Fix the
source of ambiguity rather than instructing the agent to override it — telling
an agent to ignore a rule it just cited is also the exact shape of a prompt
injection, and the security classifier flagged it as such.

## What the first cycle actually caught

Three defects that would have reached production, **none of them found by the
tests**:

1. The unlisted hash was lost whenever `h=` was not the first query parameter —
   the very form Vimeo generates. The link was then rejected with a false
   reason ("private or removed").
2. `vimeo.com/<id>/settings` was read as an unlisted hash, inventing an address
   that opens nothing and dedupes with nothing.
3. After the fix for (1), a greedy query group **swallowed the following link**:
   three links pasted from a spreadsheet cell became one, and the second video's
   hash was attached to the first video's id.

The third is the instructive one. The **tester passed** that code — correctly:
25 tests green, three versions of the module compared, zero regressions on the
client's 11 real production URLs. No test covered comma-separated links. The
**reviewer rejected** it, by reading the character class and seeing that it did
not exclude a comma.

Two opposite verdicts on the same code, both right within their own remit. One
agent would have shipped it.

## What the first cycle cost, and what was done about it (2026-09-15)

One small feature — Vimeo link support — cost roughly **567,000 tokens** across
five agent sessions, produced a **972-line** task file, and took about 45
minutes. Most of that was not thinking: it was four agents re-deriving what the
first one had already found, then each re-reading a file that kept growing.

Three changes, all aimed at the same root cause.

**1. The board is now two files.** `<slug>.md` is the board — Sintesi, Mappa,
verdicts, each section capped at roughly 40 lines — and everyone reads it in
full. `<slug>.log.md` is the log: full verdicts, command output, evidence. It
grows without limit precisely because nobody reads it end to end. A verdict
longer than its cap moves to the log with a pointer.

**2. `## 0. Mappa` — the architect's second deliverable.** The architect is the
only agent that explores the repo. What it finds goes into the Mappa as exact
paths and line numbers, and every later agent starts from there instead of
repeating the search. Any teammate that finds a missing file adds it, so the map
improves instead of ageing. The lead's prompts now say what *not* to re-derive.

**3. The tester dropped to Sonnet.** It runs commands and reports output
faithfully; that is not work that needs the most expensive model. The architect,
developer and reviewer stay on Opus, because finding what the tests do not cover
is exactly where the reasoning is worth paying for.

## The deployer was designed wrong, and never ran

Its original mandate said "ask for confirmation before every write or restart".
**A subagent cannot ask** — it talks to the lead, not to the human. A mandate
that requires an impossible permission ends one of two ways, and both are bad:
the agent stalls, or it decides on its own on a live machine.

So the boundary moved. `medyca-rilasciatore` now **inspects only** — migration
plan, changed dependencies, which services are affected, what is actually live —
and hands the lead an ordered list of commands with a note on which need `sudo`.
**The lead executes**, because the lead is the session the human is typing into
and therefore the only one that can genuinely ask. Commands needing `sudo` are
run by Giuseppe himself; the password never passes through an agent.

The first real deploy (Vimeo, 2026-09-15) was done this way and showed why the
inspection matters: no migrations, no dependency changes, and `mcp_bridge/`
untouched — so three of the six classic deploy steps were simply not needed. An
honest deploy is usually shorter than expected, and proposing steps that are not
needed on a live machine is risk given away for free.

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
