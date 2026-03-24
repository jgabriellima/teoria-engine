#!/usr/bin/env bash
# teoria-engine/scripts/stop.sh
# Stop the teoria-engine stack gracefully. Safe to run when already stopped.

set -euo pipefail

INSTALL_DIR="${TEORIA_DIR:-/opt/teoria-engine}"
GATEWAY_PORT="${GATEWAY_PORT:-9000}"
HEALTH_URL="http://localhost:${GATEWAY_PORT}/health"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[teoria]${NC} $*"; }
ok()    { echo -e "${GREEN}[teoria]${NC} $*"; }
warn()  { echo -e "${YELLOW}[teoria]${NC} $*"; }
die()   { echo -e "${RED}[teoria] ERROR:${NC} $*" >&2; exit 1; }

# ── Already stopped? ──────────────────────────────────────────────────────────
if ! curl -sf "${HEALTH_URL}" >/dev/null 2>&1; then
  ok "teoria-engine is not running (nothing to stop)."
  exit 0
fi

# ── Locate install dir ────────────────────────────────────────────────────────
if [[ ! -f "${INSTALL_DIR}/bin/teoria-engine" ]]; then
  for candidate in "$HOME/teoria-engine" "$(pwd)" "$(pwd)/.."; do
    if [[ -f "${candidate}/bin/teoria-engine" ]]; then
      INSTALL_DIR="${candidate}"
      break
    fi
  done
fi

[[ -f "${INSTALL_DIR}/bin/teoria-engine" ]] \
  || die "teoria-engine not found at ${INSTALL_DIR}. Set TEORIA_DIR env var."

info "Stopping teoria-engine..."
cd "${INSTALL_DIR}"
"${INSTALL_DIR}/bin/teoria-engine" down

# ── Confirm stopped ───────────────────────────────────────────────────────────
if curl -sf "${HEALTH_URL}" >/dev/null 2>&1; then
  warn "Gateway still responds after down — may need a moment to fully stop."
else
  ok "teoria-engine stopped successfully."
fi
