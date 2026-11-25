#!/data/data/com.termux/files/usr/bin/bash
set -eu
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
# Independent supervisor. A crashed app is relaunched after at most 5 seconds.
while :; do
  if ! tmux has-session -t '=nosotros' 2>/dev/null; then
    tmux new-session -d -s nosotros "bash '$ROOT/server-ops/start.sh' run" || true
  fi
  sleep 5
done
