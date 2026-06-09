#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# JARVIS OS — n8n management block
# Drop this into your existing jarvis.sh command dispatcher,
# or source it as: source "$JARVIS_ROOT/scripts/n8n.sh"
# ─────────────────────────────────────────────────────────────────────────────

# ── Config ────────────────────────────────────────────────────────────────────
JARVIS_ROOT="${JARVIS_ROOT:-/mnt/e/coding/jarvis-os}"
N8N_COMPOSE="$JARVIS_ROOT/infra/podman-compose.n8n.yml"
N8N_ENV="$JARVIS_ROOT/infra/.env.n8n.local"
N8N_ENV_DEFAULT="$JARVIS_ROOT/infra/.env.n8n"
N8N_URL="http://localhost:5678"
N8N_CONTAINER="jarvis-n8n"

# ── Helpers ───────────────────────────────────────────────────────────────────
_n8n_check_deps() {
  if ! command -v podman &>/dev/null; then
    echo "[JARVIS] ✗ podman not found — install with: sudo apt install podman"
    return 1
  fi
  if ! command -v podman-compose &>/dev/null; then
    echo "[JARVIS] ✗ podman-compose not found — install with: pip3 install podman-compose"
    return 1
  fi
}

_n8n_resolve_env() {
  # Prefer .local override, fall back to default template
  if [[ -f "$N8N_ENV" ]]; then
    echo "$N8N_ENV"
  elif [[ -f "$N8N_ENV_DEFAULT" ]]; then
    echo "$N8N_ENV_DEFAULT"
  else
    echo ""
  fi
}

_n8n_host_gateway() {
  # Detect WSL2 host gateway for JARVIS_API_URL
  ip route show | awk '/default/ {print $3; exit}'
}

_n8n_status_line() {
  local state
  state=$(podman inspect --format '{{.State.Status}}' "$N8N_CONTAINER" 2>/dev/null)
  if [[ -z "$state" ]]; then
    echo "not created"
  else
    echo "$state"
  fi
}

# ── Commands ──────────────────────────────────────────────────────────────────

n8n_start() {
  echo "[JARVIS] Starting n8n automation hub..."

  _n8n_check_deps || return 1

  local env_file
  env_file=$(_n8n_resolve_env)

  if [[ -z "$env_file" ]]; then
    echo "[JARVIS] ✗ No env file found. Copy infra/.env.n8n to infra/.env.n8n.local and set N8N_PASSWORD."
    return 1
  fi

  # Detect and export WSL2 gateway so n8n can reach JARVIS API
  local gateway
  gateway=$(_n8n_host_gateway)
  if [[ -n "$gateway" ]]; then
    export JARVIS_API_URL="http://${gateway}:8000"
    echo "[JARVIS] Host gateway: $gateway → JARVIS_API_URL=$JARVIS_API_URL"
  fi

  podman-compose \
    -f "$N8N_COMPOSE" \
    --env-file "$env_file" \
    up -d

  if [[ $? -ne 0 ]]; then
    echo "[JARVIS] ✗ n8n failed to start. Check: podman logs $N8N_CONTAINER"
    return 1
  fi

  # Wait for healthcheck
  echo "[JARVIS] Waiting for n8n to be ready..."
  local attempts=0
  until podman inspect --format '{{.State.Health.Status}}' "$N8N_CONTAINER" 2>/dev/null | grep -q "healthy"; do
    attempts=$((attempts + 1))
    if [[ $attempts -ge 20 ]]; then
      echo "[JARVIS] ⚠ n8n health check timed out — it may still be starting"
      break
    fi
    sleep 3
    printf "."
  done
  echo ""

  echo "[JARVIS] ✓ n8n running → $N8N_URL"
}

n8n_stop() {
  echo "[JARVIS] Stopping n8n..."

  _n8n_check_deps || return 1

  local env_file
  env_file=$(_n8n_resolve_env)
  local env_arg=""
  [[ -n "$env_file" ]] && env_arg="--env-file $env_file"

  podman-compose \
    -f "$N8N_COMPOSE" \
    $env_arg \
    down

  echo "[JARVIS] ✓ n8n stopped"
}

n8n_restart() {
  n8n_stop && n8n_start
}

n8n_status() {
  local state
  state=$(_n8n_status_line)
  echo "[JARVIS] n8n status: $state"

  if [[ "$state" == "running" ]]; then
    # Show last 5 log lines
    echo ""
    podman logs --tail 5 "$N8N_CONTAINER" 2>&1
    echo ""
    echo "[JARVIS] UI → $N8N_URL"
  fi
}

n8n_logs() {
  podman logs -f "$N8N_CONTAINER"
}

# ── Dispatcher (integrate into your existing case block) ──────────────────────
# Add these to the main case "$1" in ... esac in jarvis.sh:
#
#   n8n:start)   n8n_start   ;;
#   n8n:stop)    n8n_stop    ;;
#   n8n:restart) n8n_restart ;;
#   n8n:status)  n8n_status  ;;
#   n8n:logs)    n8n_logs    ;;

# ── Standalone usage (if sourced or run directly) ─────────────────────────────
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  case "${1:-}" in
    start)   n8n_start   ;;
    stop)    n8n_stop    ;;
    restart) n8n_restart ;;
    status)  n8n_status  ;;
    logs)    n8n_logs    ;;
    *)
      echo "Usage: $0 {start|stop|restart|status|logs}"
      echo "  Or in jarvis.sh: jarvis.sh n8n:{start|stop|restart|status|logs}"
      exit 1
      ;;
  esac
fi
