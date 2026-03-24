#!/usr/bin/env bash
# teoria-engine/scripts/status.sh
# Check health, show endpoints, active model, and container status.
# Usage: status.sh [--wait]   (--wait polls until healthy or timeout)

set -euo pipefail

INSTALL_DIR="${TEORIA_DIR:-/opt/teoria-engine}"
GATEWAY_PORT="${GATEWAY_PORT:-9000}"
HEALTH_URL="http://localhost:${GATEWAY_PORT}/health"
WAIT_MODE=false
MAX_WAIT_SEC="${TEORIA_START_TIMEOUT:-120}"

if [[ "${1:-}" == "--wait" ]]; then WAIT_MODE=true; fi

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'
info()    { echo -e "${BLUE}[teoria]${NC} $*"; }
ok()      { echo -e "${GREEN}[teoria]${NC} $*"; }
warn()    { echo -e "${YELLOW}[teoria]${NC} $*"; }
section() { echo -e "\n${BOLD}$*${NC}"; }

# ── Wait mode ─────────────────────────────────────────────────────────────────
if ${WAIT_MODE}; then
  info "Waiting for gateway (timeout: ${MAX_WAIT_SEC}s)..."
  elapsed=0
  while ! curl -sf "${HEALTH_URL}" >/dev/null 2>&1; do
    if (( elapsed >= MAX_WAIT_SEC )); then
      echo -e "\n${RED}[teoria] Timed out after ${MAX_WAIT_SEC}s${NC}" >&2
      exit 1
    fi
    echo -n "."
    sleep 5
    elapsed=$(( elapsed + 5 ))
  done
  echo ""
fi

# ── Gateway health ────────────────────────────────────────────────────────────
section "Gateway Health"
HEALTH_JSON=$(curl -sf "${HEALTH_URL}" 2>/dev/null || echo "")

if [[ -n "${HEALTH_JSON}" ]]; then
  ok "RUNNING on port ${GATEWAY_PORT}"
  # Pretty print if jq available
  if command -v jq &>/dev/null; then
    echo "${HEALTH_JSON}" | jq '.'
  else
    echo "${HEALTH_JSON}"
  fi
else
  warn "NOT RUNNING — gateway did not respond at ${HEALTH_URL}"
fi

# ── Endpoints ─────────────────────────────────────────────────────────────────
section "Endpoints"
echo "  Base URL  : http://localhost:${GATEWAY_PORT}/v1"
echo "  Health    : ${HEALTH_URL}"
echo "  Models    : http://localhost:${GATEWAY_PORT}/v1/models"
echo "  Docs      : http://localhost:${GATEWAY_PORT}/docs"

# ── Active model ──────────────────────────────────────────────────────────────
section "Active Model"
MODELS_JSON=$(curl -sf "http://localhost:${GATEWAY_PORT}/v1/models" \
  -H "x-api-key: ${GATEWAY_API_KEY:-$(grep -oP 'GATEWAY_API_KEY=\K\S+' "${INSTALL_DIR}/.env" 2>/dev/null || echo '')}" \
  2>/dev/null || echo "")

if [[ -n "${MODELS_JSON}" ]]; then
  if command -v jq &>/dev/null; then
    echo "${MODELS_JSON}" | jq -r '.data[].id' 2>/dev/null | head -5 | sed 's/^/  - /'
  else
    echo "${MODELS_JSON}"
  fi
else
  # Fall back to reading config
  if [[ -f "${INSTALL_DIR}/config/engine.yml" ]]; then
    ACTIVE=$(grep -oP 'active_model:\s*\K\S+' "${INSTALL_DIR}/config/engine.yml" 2>/dev/null || echo "unknown")
    echo "  Profile: ${ACTIVE} (config/engine.yml)"
  fi
fi

# ── Container status ──────────────────────────────────────────────────────────
section "Container Status"
if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
  docker ps --filter "label=com.docker.compose.project=teoria-llm-engine" \
    --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null \
    || docker compose -f "${INSTALL_DIR}/docker-compose.yml" ps 2>/dev/null \
    || warn "Could not list containers (docker compose context not detected)"
else
  warn "Docker not available — skipping container status."
fi

# ── Platform hint ─────────────────────────────────────────────────────────────
section "Agent Integration"
KEY="${GATEWAY_API_KEY:-\$GATEWAY_API_KEY}"
echo ""
echo "  # Environment variables for any OpenAI-compatible client:"
echo "  export OPENAI_BASE_URL=http://localhost:${GATEWAY_PORT}/v1"
echo "  export OPENAI_API_KEY=${KEY}"
echo ""
echo "  # Codex CLI:   OPENAI_BASE_URL=http://localhost:${GATEWAY_PORT}/v1 codex ..."
echo "  # Gemini CLI:  OPENAI_BASE_URL=http://localhost:${GATEWAY_PORT}/v1 gemini ..."
echo "  # Aider:       aider --openai-api-base http://localhost:${GATEWAY_PORT}/v1 ..."
echo ""
