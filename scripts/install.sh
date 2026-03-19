#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# teoria-engine installer (Linux + macOS)
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

OS="$(uname -s)"
ARCH="$(uname -m)"

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

# --- NVIDIA (Linux only) ---------------------------------------------------

install_nvidia_container_toolkit() {
    if [[ "$OS" != "Linux" ]]; then return; fi
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
echo "  platform    : ${OS}/${ARCH}"
echo "  install dir : $INSTALL_DIR"
echo "  branch      : $BRANCH"
echo "  service     : $INSTALL_SERVICE"
echo ""

command -v curl &>/dev/null || fail "curl is required"

HAS_GIT=false
command -v git &>/dev/null && HAS_GIT=true

if ! $HAS_GIT; then
    warn "git not found — will install via tarball download (updates will re-download full archive)"
fi

if ! command -v docker &>/dev/null; then
    if [[ "$OS" == "Darwin" ]]; then
        fail "docker is required — install Docker Desktop: https://www.docker.com/products/docker-desktop/"
    else
        fail "docker is required — install: https://docs.docker.com/engine/install/"
    fi
fi
docker compose version &>/dev/null || fail "docker compose plugin is required"

if [[ "$OS" == "Darwin" ]]; then
    if [[ "$ARCH" != "arm64" ]]; then
        fail "teoria-engine requires Apple Silicon (arm64). Intel Macs are not supported."
    fi
    info "macOS Apple Silicon detected — MLX backend"
    if $INSTALL_SERVICE; then
        warn "--service flag ignored on macOS (no systemd)"
        INSTALL_SERVICE=false
    fi
else
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

# --- install mlx-lm (macOS Apple Silicon only) --------------------------------

if [[ "$OS" == "Darwin" && "$ARCH" == "arm64" ]]; then
    if command -v mlx_lm.server &>/dev/null; then
        info "mlx-lm already installed"
    else
        info "installing mlx-lm (Apple Silicon LLM backend)..."
        if command -v pip3 &>/dev/null; then
            pip3 install --quiet mlx-lm
        elif command -v pip &>/dev/null; then
            pip install --quiet mlx-lm
        else
            warn "pip not found — install mlx-lm manually: pip install mlx-lm"
        fi

        if command -v mlx_lm.server &>/dev/null; then
            info "mlx-lm installed successfully"
        else
            warn "mlx-lm install may have succeeded but mlx_lm.server not found in PATH"
            warn "try: pip install mlx-lm"
        fi
    fi
fi

# --- clone / update ----------------------------------------------------------

_tarball_url() {
    local repo_base
    repo_base="$(echo "$REPO_URL" | sed 's/\.git$//')"
    echo "${repo_base}/archive/refs/heads/${BRANCH}.tar.gz"
}

_download_tarball() {
    local url tmptar tmpdir
    url="$(_tarball_url)"
    tmptar="$(mktemp)"
    info "downloading ${BRANCH} tarball..."
    curl -fsSL "$url" -o "$tmptar" || fail "failed to download tarball from $url"
    sudo mkdir -p "$INSTALL_DIR"
    tmpdir="$(mktemp -d)"
    tar xzf "$tmptar" -C "$tmpdir"
    rm -f "$tmptar"
    # tarball extracts to <repo>-<branch>/ subfolder
    local extracted
    extracted="$(ls -d "$tmpdir"/*/ | head -1)"
    sudo cp -a "$extracted"/. "$INSTALL_DIR"/
    rm -rf "$tmpdir"
    sudo chown -R "$(id -u):$(id -g)" "$INSTALL_DIR"
}

_fresh_clone() {
    sudo mkdir -p "$(dirname "$INSTALL_DIR")"
    sudo git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR"
    sudo chown -R "$(id -u):$(id -g)" "$INSTALL_DIR"
}

_fresh_install() {
    if $HAS_GIT; then
        _fresh_clone
    else
        _download_tarball
    fi
}

_backup_env() {
    _saved_env=""
    if [[ -f "$INSTALL_DIR/.env" ]]; then
        _saved_env="$(mktemp)"
        cp "$INSTALL_DIR/.env" "$_saved_env"
        info "backed up existing .env"
    fi
}

_restore_env() {
    if [[ -n "${_saved_env:-}" ]]; then
        cp "$_saved_env" "$INSTALL_DIR/.env"
        rm -f "$_saved_env"
        info "restored .env from backup"
    fi
}

if [[ -d "$INSTALL_DIR/.git" ]] && $HAS_GIT; then
    current_remote="$(git -C "$INSTALL_DIR" remote get-url origin 2>/dev/null || echo "")"
    if [[ "$current_remote" != "$REPO_URL" ]]; then
        info "remote URL changed ($current_remote -> $REPO_URL), updating origin"
        git -C "$INSTALL_DIR" remote set-url origin "$REPO_URL"
    fi
    info "updating existing installation at $INSTALL_DIR (git)"
    git -C "$INSTALL_DIR" fetch origin "$BRANCH"
    git -C "$INSTALL_DIR" reset --hard "origin/$BRANCH"
    git -C "$INSTALL_DIR" clean -fd
elif [[ -d "$INSTALL_DIR" ]]; then
    if [[ -z "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
        info "empty directory found at $INSTALL_DIR, removing and installing fresh"
        sudo rmdir "$INSTALL_DIR"
        _fresh_install
    else
        info "existing installation found at $INSTALL_DIR — preserving .env and reinstalling"
        _backup_env
        sudo rm -rf "$INSTALL_DIR"
        _fresh_install
        _restore_env
    fi
else
    info "installing teoria-engine into $INSTALL_DIR"
    _fresh_install
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

# --- systemd service (Linux only) -------------------------------------------

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
if [[ "$OS" == "Darwin" ]]; then
    echo ""
    echo "  MLX backend will be used automatically on this Mac."
    echo "  On first 'teoria-engine up', the model will be downloaded from HuggingFace."
fi
echo ""
if [[ "$OS" == "Linux" ]] && ! $INSTALL_SERVICE; then
    echo "  To install as system service:  sudo teoria-engine service"
    echo ""
fi
