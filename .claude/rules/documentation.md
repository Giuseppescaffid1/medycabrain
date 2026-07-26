# Rule: document everything, as you build it

This project is delivered to a client who is not an engineer and who judges
the work by what they can see and understand. Documentation is therefore part
of the deliverable, not an afterthought — a feature that nobody can explain is
not finished.

## What must be updated, and when

Update documentation **in the same change** that alters behaviour, never in a
follow-up commit that may never come.

| When you… | Update |
|---|---|
| add or change a pipeline stage | `docs/medycabrain-pipeline-cliente.drawio` (both the client view and the technical view) **and** the in-app `Documentazione` page |
| add a user-visible feature | the `Documentazione` page, in the client's own words |
| change how a stage behaves (models, thresholds, limits) | the technical page of the diagram, plus the comment at the top of the module |
| discover a real constraint (a rate limit, a block, a schema quirk) | write it down where the next person will hit it — the module docstring — and in `~/brain` if it is reusable reference |
| fix a bug whose cause was non-obvious | a comment stating the constraint, never a comment restating the code |

## How to write it

- **Write for the client, not for the repo.** The client-facing page says what
  the platform does for them ("Capisce: trascrive l'audio e legge il testo"),
  never the class names. The technical page carries the agent names, tables
  and thresholds.
- **Numbers over adjectives.** "1 token/s, so a brief needed 10 minutes and
  timed out" beats "it was slow". Measure, then write the measurement.
- **Say what is NOT covered.** Known limits (the scraper only reads the /reels/
  tab; blog tracking is Medyca-only) belong in the documentation the moment
  they are known. A silent gap becomes a broken promise.
- **Keep diagrams regenerable, never hand-patched into divergence.** The
  drawio file is the source; the in-app page mirrors it in the brand style.

## The two audiences, kept separate

1. **Client** — `Documentazione` page in the app and page 1 of the diagram:
   plain Italian, no jargon, the flow and the outputs.
2. **Whoever maintains this** — module docstrings, page 2 of the diagram,
   commit messages that explain the cause rather than the change.

## Definition of done

A change is done when someone who was not present can (a) see what it does
from the client page, and (b) find why it was built that way from the code or
the commit. If either is missing, the change is unfinished.
