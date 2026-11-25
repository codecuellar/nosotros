#!/data/data/com.termux/files/usr/bin/bash
set -eu
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
export ROOT
export NOSOTROS_PORT=8787 NOSOTROS_HOST=127.0.0.1
export NOSOTROS_DATA="$HOME/nosotros-private/data"
export NOSOTROS_UPLOADS="$HOME/nosotros-private/uploads"
export NOSOTROS_BACKUPS="$HOME/nosotros-private/respaldos"
umask 077
case "${1:-start}" in
  start)
    command -v tmux >/dev/null || { printf 'Falta tmux
' >&2; exit 1; }
    test -f "$ROOT/server/app.py" || { printf 'Falta server/app.py
' >&2; exit 1; }
    mkdir -p "$NOSOTROS_DATA" "$NOSOTROS_UPLOADS" "$NOSOTROS_BACKUPS" "$HOME/logs"
    chmod 700 "$NOSOTROS_DATA" "$NOSOTROS_UPLOADS" "$NOSOTROS_BACKUPS"
    if ! tmux has-session -t '=nosotros-watch' 2>/dev/null; then
      tmux new-session -d -s nosotros-watch "bash '$ROOT/server-ops/watchdog.sh'"
    fi
    printf 'Watchdog iniciado; consultar: bash server-ops/start.sh status
'
    ;;
  run)
    cd "$ROOT"
    # No insecure-cookie override: the backend retains Secure by default.
    exec python "$ROOT/server-ops/log-runner.py" "$HOME/logs/nosotros.log" python -u "$ROOT/server/app.py"
    ;;
  stop)
    # Kill only exact app session names; never tmux kill-server/pkill.
    tmux kill-session -t '=nosotros-watch' 2>/dev/null || true
    tmux kill-session -t '=nosotros' 2>/dev/null || true
    ;;
  status)
    tmux has-session -t '=nosotros-watch' && printf 'watchdog: activo
'
    tmux has-session -t '=nosotros' && printf 'app: activa
'
    curl --fail --silent --show-error --max-time 5 http://127.0.0.1:8787/api/health
    ;;
  *) printf 'Uso: bash server-ops/start.sh {start|stop|status|run}
' >&2; exit 2 ;;
esac
