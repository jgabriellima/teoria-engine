#!/usr/bin/env bash
# teoria-engine/scripts/start.sh
# Start the teoria-engine stack. Detects platform (Linux/macOS), validates prerequisites,
# and brings up all services. Safe to run multiple times — idempotent.

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
INSTALL_DIR="${TEORIA_DIR:-/opt/teoria-engine}"
GATEWAY_PORT="${GATEWAY_PORT:-9000}"
HEALTH_URL="http://localhost:${GATEWAY_PORT}/health"
MAX_WAIT_SEC="${TEORIA_START_TIMEOUT:-120}"
MODEL="${TEORIA_MODEL:-}"   # optional: override active_model in engine.yml

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[teoria]${NC} $*"; }
ok()    { echo -e "${GREEN}[teoria]${NC} $*"; }
warn()  { echo -e "${YELLOW}[teoria]${NC} $*"; }
die()   { echo -e "${RED}[teoria] ERROR:${NC} $*" >&2; exit 1; }

# ── Already running? ──────────────────────────────────────────────────────────
if curl -sf "${HEALTH_URL}" >/dev/null 2>&1; then
  ok "teoria-engine is already running on port ${GATEWAY_PORT}."
  echo ""
  echo "  Base URL : http://localhost:${GATEWAY_PORT}/v1"
  echo "  Health   : ${HEALTH_URL}"
  echo ""
  exit 0
fi

# ── Locate install dir ────────────────────────────────────────────────────────
if [[ ! -f "${INSTALL_DIR}/bin/teoria-engine" ]]; then
  # Try common fallback locations
  for candidate in "$HOME/teoria-engine" "$(pwd)" "$(pwd)/.."; do
    if [[ -f "${candidate}/bin/teoria-engine" ]]; then
      INSTALL_DIR="${candidate}"
      break
    fi
  done
fi

[[ -f "${INSTALL_DIR}/bin/teoria-engine" ]] \
  || die "teoria-engine not found. Install first:\n  curl -sSL https://raw.githubusercontent.com/jgabriellima/teoria-engine/main/scripts/install.sh | bash"

info "Using install dir: ${INSTALL_DIR}"

# ── .env check ───────────────────────────────────────────────────────────────
if [[ ! -f "${INSTALL_DIR}/.env" ]]; then
  warn ".env not found. Copying from .env.example — you MUST set GATEWAY_API_KEY."
  cp "${INSTALL_DIR}/.env.example" "${INSTALL_DIR}/.env"
fi

# Warn if using default/placeholder key
if grep -qE 'GATEWAY_API_KEY=(your-secure-key|changeme|)' "${INSTALL_DIR}/.env" 2>/dev/null; then
  warn "GATEWAY_API_KEY is using a placeholder value. Set a strong key in ${INSTALL_DIR}/.env"
fi

# ── Switch model profile if requested ─────────────────────────────────────────
if [[ -n "${MODEL}" ]]; then
  info "Switching to model profile: ${MODEL}"
  "${INSTALL_DIR}/bin/teoria-engine" config --model "${MODEL}"
fi

# ── Platform detect ───────────────────────────────────────────────────────────
OS="$(uname -s)"
case "${OS}" in
  Linux)
    if ! command -v nvidia-smi &>/dev/null; then
      warn "nvidia-smi not found — NVIDIA GPU may not be available."
    else
      GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 || echo "0")
      info "Detected NVIDIA GPU with ${GPU_MEM} MiB VRAM."
    fi
    ;;
  Darwin)
    if ! command -v mlx_lm.server &>/dev/null; then
      warn "mlx_lm.server not in PATH. Install: pip install mlx-lm"
    else
      info "Detected macOS Apple Silicon — using MLX backend."
    fi
    ;;
  *)
    die "Unsupported OS: ${OS}. teoria-engine supports Linux (NVIDIA) and macOS (Apple Silicon)."
    ;;
esac

# ── Docker check ─────────────────────────────────────────────────────────────
command -v docker &>/dev/null || die "Docker not found. Install Docker Engine (Linux) or Docker Desktop (macOS)."
docker info &>/dev/null       || die "Docker daemon is not running. Start it first."

# ── Start ─────────────────────────────────────────────────────────────────────
info "Starting teoria-engine..."
cd "${INSTALL_DIR}"
"${INSTALL_DIR}/bin/teoria-engine" up

# ── Wait for readiness ────────────────────────────────────────────────────────
info "Waiting for gateway to become healthy (timeout: ${MAX_WAIT_SEC}s)..."
elapsed=0
interval=5
while ! curl -sf "${HEALTH_URL}" >/dev/null 2>&1; do
  if (( elapsed >= MAX_WAIT_SEC )); then
    die "Gateway did not become healthy within ${MAX_WAIT_SEC}s.\nRun: cd ${INSTALL_DIR} && teoria-engine logs 50"
  fi
  echo -n "."
  sleep "${interval}"
  elapsed=$(( elapsed + interval ))
done
echo ""

# ── Print connection info ──────────────────────────────────────────────────────
ok "teoria-engine is ready!"
echo ""
echo "  Base URL  : http://localhost:${GATEWAY_PORT}/v1"
echo "  Health    : ${HEALTH_URL}"
echo "  Models    : http://localhost:${GATEWAY_PORT}/v1/models"
echo "  Docs      : http://localhost:${GATEWAY_PORT}/docs"
echo ""
echo "  API Key   : \$GATEWAY_API_KEY (from ${INSTALL_DIR}/.env)"
echo ""
echo "  Quick test:"
echo "    source ${INSTALL_DIR}/.env"
echo "    curl http://localhost:${GATEWAY_PORT}/v1/chat/completions \\"
echo "      -H \"Authorization: Bearer \$GATEWAY_API_KEY\" \\"
echo "      -H \"Content-Type: application/json\" \\"
echo "      -d '{\"messages\":[{\"role\":\"user\",\"content\":\"Hello\"}],\"max_tokens\":64}'"
echo ""
echo "  Stop with: bash teoria-engine/scripts/stop.sh"
