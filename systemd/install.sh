#!/usr/bin/env bash
# ============================================================
# JARVIS OS — systemd installer (user units + linger)
#
# Usage:
#   bash systemd/install.sh              install + enable core units
#   bash systemd/install.sh --start     install, enable, and start now
#   bash systemd/install.sh --uninstall remove all units
#
# After install:
#   systemctl --user start jarvis.target     start everything
#   systemctl --user stop jarvis.target      stop everything (snapshots memory)
#   systemctl --user status 'jarvis-*'       status of all services
#   journalctl --user -u jarvis-react -f     follow a service log
#
# Optional units (installed but NOT enabled by default):
#   jarvis-voice         needs sounddevice + microphone
#   jarvis-n8n           needs podman-compose (pip3 install podman-compose)
#   jarvis-telegram-debug
#   jarvis-claude-proxy  Claude API mode — conflicts with jarvis-ollama
# Enable with: systemctl --user enable --now jarvis-voice
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"

CORE_UNITS=(
  jarvis-redis
  jarvis-qdrant
  jarvis-llama
  jarvis-init
  jarvis-snapshot
  jarvis-react
  jarvis-telegram
  jarvis-plan-runner
  jarvis-plan-api
  jarvis-bridge
  jarvis-pty
  jarvis-kokoro
  jarvis-dictation
  jarvis-task-loop
)

# jarvis-ollama: NOT enabled by default — the ollama installer registers a
# SYSTEM-level ollama.service that already owns :11434. Only enable this
# user unit if that system service is absent (check: systemctl status ollama).
OPTIONAL_UNITS=(
  jarvis-ollama
  jarvis-voice
  jarvis-n8n
  jarvis-telegram-debug
  jarvis-claude-proxy
)

if [[ "${1:-}" == "--uninstall" ]]; then
  echo "[JARVIS] Uninstalling systemd units..."
  systemctl --user stop jarvis.target 2>/dev/null || true
  for u in "${CORE_UNITS[@]}" "${OPTIONAL_UNITS[@]}"; do
    systemctl --user disable "$u" 2>/dev/null || true
    rm -f "$UNIT_DIR/$u.service"
  done
  systemctl --user disable jarvis.target 2>/dev/null || true
  rm -f "$UNIT_DIR/jarvis.target"
  systemctl --user daemon-reload
  echo "[JARVIS] Uninstalled."
  exit 0
fi

echo "[JARVIS] Installing systemd user units to $UNIT_DIR"
mkdir -p "$UNIT_DIR"

cp "$SCRIPT_DIR/jarvis.target" "$UNIT_DIR/"
for u in "${CORE_UNITS[@]}" "${OPTIONAL_UNITS[@]}"; do
  cp "$SCRIPT_DIR/$u.service" "$UNIT_DIR/"
done

systemctl --user daemon-reload

echo "[JARVIS] Enabling core units..."
systemctl --user enable jarvis.target
for u in "${CORE_UNITS[@]}"; do
  systemctl --user enable "$u" >/dev/null
done

# Linger: user services start at boot without a login session
if command -v loginctl >/dev/null 2>&1; then
  if ! loginctl show-user "$USER" 2>/dev/null | grep -q '^Linger=yes'; then
    echo "[JARVIS] Enabling linger for $USER (services start at WSL boot)..."
    loginctl enable-linger "$USER" 2>/dev/null \
      || sudo loginctl enable-linger "$USER" \
      || echo "[JARVIS] WARN: could not enable linger — services need a login session"
  fi
fi

echo ""
echo "[JARVIS] Installed. Core units enabled:"
printf '  %s\n' "${CORE_UNITS[@]}"
echo ""
echo "[JARVIS] Optional (enable manually):"
printf '  %s\n' "${OPTIONAL_UNITS[@]}"
echo ""

if [[ "${1:-}" == "--start" ]]; then
  echo "[JARVIS] Starting jarvis.target..."
  systemctl --user start jarvis.target
  sleep 3
  systemctl --user --no-pager list-units 'jarvis-*' || true
else
  echo "Start with:  systemctl --user start jarvis.target"
fi
