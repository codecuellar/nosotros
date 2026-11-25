#!/data/data/com.termux/files/usr/bin/bash
# Install as a NEW ~/.termux/boot/nosotros; do not edit servidor or servidor.sh.
set -eu
command -v termux-wake-lock >/dev/null && termux-wake-lock || true
bash "$HOME/nosotros/server-ops/start.sh" start
# Explicit opt-in only; never authenticate or enable Serve/Funnel at boot.
if [ -f "$HOME/nosotros-private/tailscale/enable-boot" ]; then
  bash "$HOME/nosotros/server-ops/tailscale-userspace.sh" start
fi
