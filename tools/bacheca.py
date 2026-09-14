#!/usr/bin/env python3
"""La lavagna: che lavori ci sono e a che punto sono.

Legge il frontmatter dei file in .claude/tasks/ - il campo `stato:` e la
lavagna, non c'e nessun indice da tenere allineato a mano. Stesso contenuto
del comando /bacheca, ma stampabile in un pannello tmux con `watch`.
"""
from __future__ import annotations

import pathlib
import re
import sys

ORDINE = ["fermo", "disegno", "approvato", "sviluppo", "revisione", "pronto", "rilasciato"]
# Chi tocca a, per stato: e l'unica informazione che si cerca davvero guardando
# la lavagna di sfuggita.
TOCCA = {"disegno": "Giuseppe (approvare)", "pronto": "Giuseppe (fondere)",
         "fermo": "Giuseppe (decidere)", "approvato": "sviluppatore",
         "sviluppo": "sviluppatore", "revisione": "revisore + collaudatore",
         "rilasciato": "-"}
COL = {"fermo": "\033[31m", "disegno": "\033[36m", "pronto": "\033[32m",
       "rilasciato": "\033[2m"}
R = "\033[0m"


def campo(testo: str, chiave: str) -> str:
    m = re.search(rf"^{chiave}:\s*(.*)$", testo, re.M)
    return (m.group(1).strip().strip('"') if m else "")


def main() -> None:
    d = pathlib.Path(__file__).resolve().parent.parent / ".claude" / "tasks"
    righe = []
    for f in sorted(d.glob("*.md")):
        if f.name == "README.md":
            continue
        t = f.read_text(encoding="utf-8", errors="replace")[:1200]
        righe.append((campo(t, "stato") or "?", campo(t, "titolo") or f.stem,
                      campo(t, "ramo"), campo(t, "pr")))
    if not righe:
        print("la lavagna e vuota")
        return
    righe.sort(key=lambda r: ORDINE.index(r[0]) if r[0] in ORDINE else 99)
    print(f"\033[1m{'STATO':<11} {'LAVORO':<38} {'TOCCA A':<22} RAMO{R}")
    for stato, titolo, ramo, pr in righe:
        c = COL.get(stato, "")
        print(f"{c}{stato:<11}{R} {titolo[:38]:<38} "
              f"{TOCCA.get(stato, ''):<22} \033[2m{pr or ramo}{R}")


if __name__ == "__main__":
    sys.exit(main())
