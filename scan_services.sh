#!/usr/bin/env bash
# ============================================================
#  JARVIS OS — Port & Service Scanner
#  Scans known ports and tests service health
#  Run on WSL2: bash jarvis_port_scan.sh
# ============================================================

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

TIMEOUT=2
PASS=0; FAIL=0; UNKNOWN=0

# ── Known JARVIS services ────────────────────────────────────
# Format: "PORT|PROTOCOL|SERVICE_NAME|HEALTH_CHECK_URL_OR_EMPTY"
SERVICES=(
  # ── Core API / orchestration
  "8000|TCP|JARVIS API (FastAPI)         |http://localhost:8000/health"
  "8001|TCP|JARVIS API alt               |http://localhost:8001/health"
  "7900|TCP|WebSocket server (Parlor/WS) |"

  # ── LLM backends
  "11434|TCP|Ollama (qwen3-coder/planner) |http://localhost:11434/api/version"
  "8080|TCP|llama.cpp server (Gemma/live) |http://localhost:8080/health"

  # ── Memory / vector store
  "6379|TCP|Redis (short-term memory)    |"
  "6333|TCP|Qdrant HTTP (long-term vec.)  |http://localhost:6333/healthz"
  "6334|TCP|Qdrant gRPC                   |"

  # ── TTS
  "5000|TCP|Kokoro TTS (ONNX)            |http://localhost:5000/health"
  "5001|TCP|Kokoro TTS alt               |http://localhost:5001/health"

  # ── Workflow / automation
  "5678|TCP|n8n (workflow engine)        |http://localhost:5678/healthz"

  # ── Sandboxed execution
  "2376|TCP|Podman/Docker daemon         |"
  "8888|TCP|Jupyter (sandbox)            |http://localhost:8888/api"

  # ── Monitoring / misc
  "9090|TCP|Prometheus                   |http://localhost:9090/-/healthy"
  "3000|TCP|Grafana                      |http://localhost:3000/api/health"
  "8200|TCP|Vault (secrets)              |http://localhost:8200/v1/sys/health"

  # ── Add your custom ports below ──────────────────────────
  # "PORT|TCP|Description|http://localhost:PORT/health"
)

# ── Helpers ─────────────────────────────────────────────────
check_tcp() {
  timeout $TIMEOUT bash -c ">/dev/tcp/localhost/$1" 2>/dev/null
}

check_http() {
  local url="$1"
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time $TIMEOUT "$url" 2>/dev/null)
  echo "$code"
}

status_icon() {
  case $1 in
    open)    echo -e "${GREEN}●  OPEN   ${RESET}" ;;
    closed)  echo -e "${RED}○  CLOSED ${RESET}" ;;
    http_ok) echo -e "${GREEN}✓  HTTP OK${RESET}" ;;
    http_err)echo -e "${YELLOW}⚠  HTTP ${2}${RESET}" ;;
    no_url)  echo -e "${CYAN}─  (no check)${RESET}" ;;
  esac
}

# ── Header ───────────────────────────────────────────────────
echo -e "\n${BOLD}╔══════════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}║           JARVIS OS — Service Port Scanner               ║${RESET}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${RESET}"
echo -e "  Host: localhost   Timeout: ${TIMEOUT}s   $(date '+%Y-%m-%d %H:%M:%S')\n"
printf "  %-6s %-32s %-12s %s\n" "PORT" "SERVICE" "TCP" "HTTP HEALTH"
printf "  %-6s %-32s %-12s %s\n" "──────" "──────────────────────────────" "──────────" "──────────────"

# ── Scan loop ────────────────────────────────────────────────
for entry in "${SERVICES[@]}"; do
  IFS='|' read -r port proto name url <<< "$entry"
  port="${port// /}"
  name="${name%"${name##*[![:space:]]}"}"  # trim trailing spaces

  # TCP check
  if check_tcp "$port"; then
    tcp_status="open"
    ((PASS++))
  else
    tcp_status="closed"
    ((FAIL++))
  fi

  # HTTP check (only if port is open and URL provided)
  http_display=""
  if [[ "$tcp_status" == "open" && -n "${url// /}" ]]; then
    code=$(check_http "${url// /}")
    if [[ "$code" =~ ^(200|204|301|302)$ ]]; then
      http_display=$(status_icon "http_ok")
    else
      http_display=$(status_icon "http_err" "$code")
      ((UNKNOWN++))
    fi
  elif [[ -z "${url// /}" ]]; then
    http_display=$(status_icon "no_url")
  fi

  printf "  %-6s %-32s %s  %s\n" "$port" "$name" "$(status_icon $tcp_status)" "$http_display"
done

# ── Quick extra: scan for any listening ports not in list ────
echo -e "\n${BOLD}── Listening ports not in the list above ──────────────────${RESET}"
known_ports=$(printf '%s\n' "${SERVICES[@]}" | cut -d'|' -f1 | tr -d ' ' | sort -n)

if command -v ss &>/dev/null; then
  all_listening=$(ss -tlnp 2>/dev/null | awk 'NR>1 {split($4,a,":"); print a[length(a)]}' | sort -nu)
elif command -v netstat &>/dev/null; then
  all_listening=$(netstat -tlnp 2>/dev/null | awk 'NR>2 {split($4,a,":"); print a[length(a)]}' | sort -nu)
else
  echo "  (ss/netstat not found — install iproute2 or net-tools)"
  all_listening=""
fi

found_extra=0
for p in $all_listening; do
  [[ -z "$p" || "$p" == "0" ]] && continue
  if ! echo "$known_ports" | grep -qx "$p"; then
    echo -e "  ${YELLOW}?  Port $p is listening (unknown service)${RESET}"
    found_extra=1
  fi
done
[[ $found_extra -eq 0 ]] && echo "  No unknown listeners found."

# ── Summary ──────────────────────────────────────────────────
TOTAL=${#SERVICES[@]}
echo -e "\n${BOLD}── Summary ─────────────────────────────────────────────────${RESET}"
echo -e "  Total checked : $TOTAL"
echo -e "  ${GREEN}Open          : $PASS${RESET}"
echo -e "  ${RED}Closed        : $FAIL${RESET}"
echo -e "  ${YELLOW}HTTP warnings : $UNKNOWN${RESET}"
echo -e "\n  Tip: add custom services at the bottom of the SERVICES array."
echo -e "  Tip: run with sudo for full netstat/ss process names.\n"
