#!/usr/bin/env bash
# Apre tmux con la squadra sotto gli occhi.
#
#   ┌───────────────────────────┬──────────────────────┐
#   │                           │  chi sta facendo cosa│
#   │   Claude Code (il capo)   ├──────────────────────┤
#   │                           │  la lavagna          │
#   └───────────────────────────┴──────────────────────┘
#
# Uso:  ./tools/squadra_tmux.sh        (poi ctrl-b o per saltare da un pannello all'altro)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
S=squadra

if tmux has-session -t "$S" 2>/dev/null; then
  echo "sessione '$S' gia aperta, mi ci attacco"
  exec tmux attach -t "$S"
fi

tmux new-session  -d -s "$S" -c "$REPO" -x "$(tput cols)" -y "$(tput lines)"

# Destra: i compagni mentre lavorano. Sotto: la lavagna, che si aggiorna da se.
tmux split-window -h -t "$S" -c "$REPO" -p 42 \
  "python3 tools/guarda_agenti.py; read -p 'invio per chiudere'"
tmux split-window -v -t "$S" -c "$REPO" -p 45 \
  "watch -tc -n 2 'python3 tools/bacheca.py'"

tmux select-pane -t "$S".0
tmux send-keys   -t "$S".0 'claude' C-m

exec tmux attach -t "$S"
