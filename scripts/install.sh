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

REPO_URL="${TEORIA_REPO:-https://github.com/jgabriellima/teoria-engine.git}"
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

install_nvidia_container_toolkit() {
    if ! command -v curl &>/dev/null; then
        fail "curl is required to install NVIDIA Container Toolkit"
    fi

    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
        | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg 2>/dev/null

    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
        | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
        | tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null

    apt-get update -qq && apt-get install -y -qq nvidia-container-toolkit > /dev/null

    nvidia-ctk runtime configure --runtime=docker > /dev/null 2>&1

    if command -v systemctl &>/dev/null && systemctl is-active docker &>/dev/null; then
        systemctl restart docker
    else
        warn "could not restart docker via systemctl — restart docker manually if needed"
    fi

    if docker info 2>/dev/null | grep -q nvidia; then
        info "NVIDIA Container Toolkit installed and configured"
    else
        warn "NVIDIA Container Toolkit installed but docker may need a manual restart"
    fi
}

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
    if command -v nvidia-smi &>/dev/null; then
        info "NVIDIA driver found but container runtime missing — installing NVIDIA Container Toolkit..."
        install_nvidia_container_toolkit
    else
        warn "NVIDIA container runtime not detected (no GPU driver found, skipping toolkit install)"
    fi
fi

# --- install uv (needed by load-config) ------------------------------------

if ! command -v uv &>/dev/null; then
    info "installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if command -v uv &>/dev/null; then
        info "uv $(uv --version) installed"
    else
        warn "uv install succeeded but not found in PATH — add ~/.local/bin to PATH"
    fi
else
    info "uv already installed: $(uv --version)"
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
