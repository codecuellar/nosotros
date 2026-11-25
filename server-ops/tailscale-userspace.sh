#!/data/data/com.termux/files/usr/bin/bash
set -eu
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
BASE="$HOME/nosotros-private/tailscale"
umask 077
mkdir -p "$BASE" "$HOME/logs"
case "${1:-start}" in
  start)
    test -x "$BASE/bin/tailscaled" || { printf 'Ejecutar setup-tailscale.py primero
' >&2; exit 1; }
    if ! tmux has-session -t '=nosotros-tail' 2>/dev/null; then
      tmux new-session -d -s nosotros-tail "bash '$ROOT/server-ops/tailscale-userspace.sh' run"
    fi ;;
  run)
    while :; do
      python "$ROOT/server-ops/log-runner.py" "$HOME/logs/nosotros-tailscale.log"         "$BASE/bin/tailscaled" --tun=userspace-networking --port=0         --state="$BASE/tailscaled.state" --socket="$BASE/tailscaled.sock" || true
      sleep 5
    done ;;
  stop) tmux kill-session -t '=nosotros-tail' 2>/dev/null || true ;;
  *) printf 'Uso: tailscale-userspace.sh {start|run|stop}
' >&2; exit 2 ;;
esac
