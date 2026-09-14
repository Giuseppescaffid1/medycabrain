#!/usr/bin/env python3
"""
Guarda i compagni della squadra medyca-* mentre lavorano.

I sottoagenti di Claude Code non scrivono a schermo: ognuno tiene un diario
JSONL in ~/.claude/projects/<progetto>/<sessione>/subagents/. Questo script li
segue tutti insieme e ne stampa una riga per azione, cosi in un pannello tmux
si vede chi sta facendo cosa mentre lo fa.

    python3 tools/guarda_agenti.py              # segue la sessione piu recente
    python3 tools/guarda_agenti.py --tutto      # ristampa anche quello gia fatto

Una riga per evento:
    14:32:07  architetto      > Bash        curl -s https://vimeo.com/api/...
    14:32:11  architetto      . 3 link su 3 rispondono all'oEmbed
"""
from __future__ import annotations

import argparse
import json
import sys
import pathlib
import re
import time
from pathlib import Path

ROOT = Path.home() / ".claude" / "projects"
C = {"architetto": "\033[36m", "sviluppatore": "\033[32m", "revisore": "\033[35m",
     "collaudatore": "\033[33m", "rilasciatore": "\033[31m"}
DIM, RESET, BOLD = "\033[2m", "\033[0m", "\033[1m"


def cartella_sessione() -> Path:
    """La cartella subagents/ della sessione piu recente di questo progetto."""
    slug = str(Path.cwd()).replace("/", "-")
    base = ROOT / slug
    if not base.is_dir():
        sys.exit(f"nessuna sessione trovata per {Path.cwd()}")
    cand = [p for p in base.glob("*/subagents") if p.is_dir()]
    if not cand:
        sys.exit("nessun sottoagente ha ancora lavorato in questo progetto")
    return max(cand, key=lambda p: p.stat().st_mtime)


# Il diario non porta un campo col nome del compagno: `slug` e quello della
# sessione, uguale per tutti. Il nome sta dentro il prompt che gli e stato
# dato, quindi lo si pesca una volta sola dalla testa del file e lo si tiene.
_NOMI: dict[pathlib.Path, str] = {}
_RE_NOME = re.compile(r"medyca-(architetto|sviluppatore|revisore|collaudatore|rilasciatore)")


def nome(f: "Path") -> str:
    if f not in _NOMI:
        try:
            # Il nome puo stare parecchio avanti nel diario, non solo in
            # testa: si legge a blocchi e ci si ferma appena si trova.
            testa = ""
            with f.open(encoding="utf-8", errors="replace") as fh:
                while len(testa) < 4_000_000:
                    blocco = fh.read(200_000)
                    if not blocco:
                        break
                    testa += blocco
                    if _RE_NOME.search(testa):
                        break
        except OSError:
            testa = ""
        m = _RE_NOME.search(testa)
        # Senza nome riconoscibile resta l'id: meglio un'etichetta brutta ma
        # vera che una inventata.
        _NOMI[f] = m.group(1) if m else f.stem.replace("agent-", "")[:10]
    return _NOMI[f]


def riga(ev: dict, f: "Path") -> str | None:
    """Una riga leggibile da un evento del diario, o None se non interessa."""
    msg = ev.get("message")
    if not isinstance(msg, dict):
        return None
    ora = (ev.get("timestamp") or "")[11:19]
    ag = nome(f)
    col = C.get(ag, "")
    testa = f"{DIM}{ora}{RESET}  {col}{ag:<14}{RESET}"

    for c in msg.get("content", []):
        if not isinstance(c, dict):
            continue
        if c.get("type") == "tool_use":
            nom = c.get("name", "?")
            inp = c.get("input") or {}
            det = (inp.get("command") or inp.get("pattern") or inp.get("file_path")
                   or inp.get("description") or inp.get("url") or "")
            det = " ".join(str(det).split())[:96]
            return f"{testa}{BOLD}>{RESET} {nom:<10} {DIM}{det}{RESET}"
        if c.get("type") == "text":
            t = " ".join((c.get("text") or "").split())
            if len(t) > 12:
                return f"{testa}{DIM}.{RESET} {t[:110]}"
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tutto", action="store_true",
                    help="ristampa anche gli eventi gia scritti")
    args = ap.parse_args()

    d = cartella_sessione()
    print(f"{DIM}guardo {d}{RESET}\n")
    # Quanto abbiamo gia letto di ogni diario. Partendo dalla fine si vede solo
    # cio che succede da adesso, che e quello che serve in un pannello aperto
    # accanto alla sessione.
    letti: dict[Path, int] = {}
    if not args.tutto:
        letti = {f: f.stat().st_size for f in d.glob("agent-*.jsonl")}

    try:
        while True:
            for f in sorted(d.glob("agent-*.jsonl")):
                era = letti.get(f, 0)
                ora_dim = f.stat().st_size
                if ora_dim <= era:
                    continue
                with f.open(encoding="utf-8", errors="replace") as fh:
                    fh.seek(era)
                    for linea in fh:
                        if not linea.strip():
                            continue
                        try:
                            r = riga(json.loads(linea), f)
                        except json.JSONDecodeError:
                            continue  # riga scritta a meta: la rileggiamo dopo
                        if r:
                            print(r, flush=True)
                    letti[f] = fh.tell()
            time.sleep(0.4)
    except KeyboardInterrupt:
        print()


if __name__ == "__main__":
    main()
