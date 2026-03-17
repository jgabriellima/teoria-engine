#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# teoria-engine installer
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/jambu/teoria-llm-engine/main/scripts/install.sh | bash
#
# Or with options:
#   curl -sSL ... | bash -s -- --install-dir /opt/teoria-engine --service
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_URL="${TEORIA_REPO:-https://github.com/jambu/teoria-llm-engine.git}"
BRANCH="${TEORIA_BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-/opt/teoria-engine}"
INSTALL_SERVICE=false

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --install-dir) INSTALL_DIR="$2"; shift 2 ;;
        --service)     INSTALL_SERVICE=true; shift ;;
        --branch)      BRANCH="$2"; shift 2 ;;
        *) fail "unknown option: $1" ;;
    esac
done

# --- preflight checks -------------------------------------------------------

info "teoria-engine installer"
echo "  install dir : $INSTALL_DIR"
echo "  branch      : $BRANCH"
echo "  service     : $INSTALL_SERVICE"
echo ""

command -v git    &>/dev/null || fail "git is required"
command -v docker &>/dev/null || fail "docker is required — install: https://docs.docker.com/engine/install/"
docker compose version &>/dev/null || fail "docker compose plugin is required"

if command -v nvidia-smi &>/dev/null; then
    info "GPU detected:"
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || true
else
    warn "nvidia-smi not found — this machine may not have a GPU"
fi

if docker info 2>/dev/null | grep -q nvidia; then
    info "NVIDIA container runtime detected"
else
    warn "NVIDIA container runtime not detected — install: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
fi

# --- clone / update ----------------------------------------------------------

if [[ -d "$INSTALL_DIR/.git" ]]; then
    info "updating existing installation at $INSTALL_DIR"
    git -C "$INSTALL_DIR" fetch origin "$BRANCH"
    git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH"
else
    info "cloning teoria-engine into $INSTALL_DIR"
    sudo mkdir -p "$(dirname "$INSTALL_DIR")"
    sudo git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR"
    sudo chown -R "$(id -u):$(id -g)" "$INSTALL_DIR"
fi

# --- .env setup --------------------------------------------------------------

if [[ ! -f "$INSTALL_DIR/.env" ]]; then
    cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
    warn ".env created from .env.example — edit $INSTALL_DIR/.env before starting"
    warn "  at minimum, set GATEWAY_API_KEY to a secure value"
else
    info ".env already exists, skipping"
fi

chmod +x "$INSTALL_DIR/bin/teoria-engine"

# --- symlink to PATH --------------------------------------------------------

if [[ -d /usr/local/bin ]]; then
    sudo ln -sf "$INSTALL_DIR/bin/teoria-engine" /usr/local/bin/teoria-engine
    info "symlinked teoria-engine to /usr/local/bin/teoria-engine"
fi

# --- systemd service ---------------------------------------------------------

if $INSTALL_SERVICE; then
    info "installing systemd service..."
    sudo "$INSTALL_DIR/bin/teoria-engine" service
fi

# --- done --------------------------------------------------------------------

echo ""
info "installation complete"
echo ""
echo "  Next steps:"
echo "    1. Edit config:     nano $INSTALL_DIR/.env"
echo "    2. Run preflight:   teoria-engine preflight"
echo "    3. Start:           teoria-engine up       (or: make up)"
echo "    4. Check health:    teoria-engine health"
echo ""
if ! $INSTALL_SERVICE; then
    echo "  To install as system service:  sudo teoria-engine service"
    echo ""
fi
