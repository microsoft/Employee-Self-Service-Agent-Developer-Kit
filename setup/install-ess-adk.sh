#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# ESS ADK — macOS One-Shot Installer
#
# Installs the full ESS Maker Kit toolchain on macOS:
#   Homebrew, Python 3.12, Git, GitHub CLI, VS Code, Copilot extensions,
#   pip dependencies, clones the repo, and launches VS Code.
#
# Usage (full maker kit):
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-mac.sh)"
#
# Usage (FlightCheck only):
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-flightcheck-mac.sh)"
# ---------------------------------------------------------------------------
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BRANCH="${ESS_ADK_BRANCH:-main}"
INSTALL_ROOT="${ESS_ADK_INSTALL_ROOT:-$HOME/source}"
FLIGHTCHECK_ONLY="${FLIGHTCHECK_ONLY:-false}"
REPO_URL="https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit.git"
REPO_NAME="Employee-Self-Service-Agent-Developer-Kit"
CODE_CMD=""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

ok()   { echo -e "    ${GREEN}[ok]${NC}   $1"; }
warn() { echo -e "    ${YELLOW}[warn]${NC} $1"; }
err()  { echo -e "    ${RED}[ERR]${NC}  $1"; }
step() { echo -e "\n${CYAN}==> $1${NC}"; }

# ---------------------------------------------------------------------------
# 1. Homebrew
# ---------------------------------------------------------------------------
step "Checking Homebrew"

ensure_brew_in_path() {
    if [[ -x /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -x /usr/local/bin/brew ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
}

if command -v brew &>/dev/null; then
    ok "Homebrew already installed"
else
    ensure_brew_in_path
    if command -v brew &>/dev/null; then
        ok "Homebrew found after PATH update"
    else
        echo "    Installing Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        ensure_brew_in_path
        if ! command -v brew &>/dev/null; then
            err "Homebrew installation failed. Please install manually: https://brew.sh"
            exit 1
        fi
        ok "Homebrew installed"
    fi
fi

# ---------------------------------------------------------------------------
# 2. Toolchain via Homebrew
# ---------------------------------------------------------------------------
step "Installing toolchain via Homebrew"

install_brew_pkg() {
    local pkg="$1"
    local name="${2:-$1}"
    if brew list "$pkg" &>/dev/null; then
        ok "$name (already installed)"
    else
        echo "    Installing $name ($pkg)..."
        brew install "$pkg" || true
        if brew list "$pkg" &>/dev/null; then
            ok "$name"
        else
            err "Failed to install $name. Try manually: brew install $pkg"
            exit 1
        fi
    fi
}

install_brew_cask() {
    local cask="$1"
    local name="${2:-$1}"
    local app_path="${3:-}"
    if brew list --cask "$cask" &>/dev/null; then
        ok "$name (already installed)"
    elif [[ -n "$app_path" && -d "$app_path" ]]; then
        ok "$name (already installed outside Homebrew)"
    else
        echo "    Installing $name ($cask)..."
        brew install --cask "$cask" || true
        if brew list --cask "$cask" &>/dev/null || [[ -n "$app_path" && -d "$app_path" ]]; then
            ok "$name"
        else
            err "Failed to install $name. Try manually: brew install --cask $cask"
            exit 1
        fi
    fi
}

# Core tools (always needed)
install_brew_pkg "python@3.12" "Python 3.12"

# Git: check if already available (e.g. via Xcode CLT) before installing via brew
if command -v git &>/dev/null; then
    ok "Git (already installed at $(command -v git))"
else
    install_brew_pkg "git" "Git"
fi

if [[ "$FLIGHTCHECK_ONLY" != "true" ]]; then
    # Full maker kit tools
    install_brew_pkg "gh" "GitHub CLI"
    install_brew_cask "visual-studio-code" "Visual Studio Code" "/Applications/Visual Studio Code.app"
fi

ok "Toolchain installed / verified"

# ---------------------------------------------------------------------------
# 3. Resolve Python
# ---------------------------------------------------------------------------
step "Resolving Python"

PYTHON=""
BREW_PREFIX="$(brew --prefix)"

# Try brew Python 3.12 first
if [[ -x "$BREW_PREFIX/bin/python3.12" ]]; then
    PYTHON="$BREW_PREFIX/bin/python3.12"
elif command -v python3.12 &>/dev/null; then
    PYTHON="$(command -v python3.12)"
elif command -v python3 &>/dev/null; then
    PY_VER="$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')"
    if printf '%s\n' "3.12" "$PY_VER" | sort -V | head -n1 | grep -q "3.12"; then
        PYTHON="$(command -v python3)"
    fi
fi

if [[ -z "$PYTHON" ]]; then
    err "Python 3.12+ not found after installation. Please check your PATH."
    exit 1
fi

ok "Using Python: $PYTHON"

# ---------------------------------------------------------------------------
# 4. Clone repository
# ---------------------------------------------------------------------------
step "Cloning repository"

REPO_PATH="$INSTALL_ROOT/$REPO_NAME"

if [[ -d "$REPO_PATH/.git" ]]; then
    ok "Repo already cloned at $REPO_PATH — pulling latest"
    git -C "$REPO_PATH" fetch --quiet origin
    git -C "$REPO_PATH" checkout "$BRANCH" 2>/dev/null || warn "git checkout $BRANCH failed. Continuing on current branch."
    git -C "$REPO_PATH" pull --quiet origin "$BRANCH" 2>/dev/null || warn "git pull failed. Continuing with local copy."
else
    echo "    Cloning to $REPO_PATH..."
    mkdir -p "$INSTALL_ROOT"
    GIT_TERMINAL_PROMPT=0 git clone --branch "$BRANCH" "$REPO_URL" "$REPO_PATH"
    ok "Cloned"
fi

# ---------------------------------------------------------------------------
# 5. Pip dependencies (using virtualenv to avoid PEP 668 restrictions)
# ---------------------------------------------------------------------------
step "Installing Python pip dependencies"

REQUIREMENTS_FILE="$REPO_PATH/solutions/ess-maker-skills/scripts/requirements.txt"
VENV_PATH="$REPO_PATH/.venv"

if [[ -f "$REQUIREMENTS_FILE" ]]; then
    if [[ ! -d "$VENV_PATH" ]]; then
        "$PYTHON" -m venv "$VENV_PATH"
    fi
    "$VENV_PATH/bin/pip" install --quiet --disable-pip-version-check -r "$REQUIREMENTS_FILE"
    ok "pip dependencies installed (virtualenv at .venv/)"
else
    warn "requirements.txt not found at $REQUIREMENTS_FILE"
fi

# ---------------------------------------------------------------------------
# 6. VS Code extensions (full install only)
# ---------------------------------------------------------------------------
if [[ "$FLIGHTCHECK_ONLY" != "true" ]]; then
    step "Installing VS Code extensions"

    # Resolve the code CLI
    CODE_CMD=""
    if command -v code &>/dev/null; then
        CODE_CMD="code"
    elif [[ -x "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code" ]]; then
        CODE_CMD="/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
    fi

    if [[ -n "$CODE_CMD" ]]; then
        # Required extensions — fail if these can't be installed
        REQUIRED_EXTENSIONS=("GitHub.copilot" "GitHub.copilot-chat")
        for ext in "${REQUIRED_EXTENSIONS[@]}"; do
            if ! "$CODE_CMD" --install-extension "$ext" --force 2>/dev/null; then
                err "Failed to install required extension: $ext"
                err "Possible causes:"
                err "  - VS Code marketplace is unreachable (corporate proxy/firewall)"
                err "  - No GitHub account with Copilot access signed in to VS Code"
                err "Re-run this script after resolving the issue."
                exit 1
            fi
            ok "$ext"
        done

        # Optional extensions — warn on failure
        OPTIONAL_EXTENSIONS=("ms-python.python")
        for ext in "${OPTIONAL_EXTENSIONS[@]}"; do
            "$CODE_CMD" --install-extension "$ext" --force 2>/dev/null && ok "$ext" || warn "Failed to install $ext"
        done
    else
        warn "VS Code 'code' CLI not found. Install extensions manually after launching VS Code."
    fi
fi

# ---------------------------------------------------------------------------
# 7. FlightCheck-only: environment discovery
# ---------------------------------------------------------------------------
if [[ "$FLIGHTCHECK_ONLY" == "true" ]]; then
    step "Running FlightCheck"

    MAKER_KIT_PATH="$REPO_PATH/solutions/ess-maker-skills"
    if [[ ! -d "$MAKER_KIT_PATH" ]]; then
        err "Maker kit path not found at $MAKER_KIT_PATH. Was the clone successful?"
        exit 1
    fi
    cd "$MAKER_KIT_PATH"
    FLIGHTCHECK_PYTHON="$VENV_PATH/bin/python"
    if [[ ! -x "$FLIGHTCHECK_PYTHON" ]]; then
        FLIGHTCHECK_PYTHON="$PYTHON"
    fi
    "$FLIGHTCHECK_PYTHON" scripts/flightcheck/cli.py --scope full
    exit $?
fi

# ---------------------------------------------------------------------------
# 8. Launch VS Code
# ---------------------------------------------------------------------------
step "Launching VS Code"

WORKSPACE_PATH="$REPO_PATH/solutions/ess-maker-skills"

if [[ -n "$CODE_CMD" ]]; then
    "$CODE_CMD" "$WORKSPACE_PATH"
    ok "VS Code opened at $WORKSPACE_PATH"
else
    warn "Could not launch VS Code. Open manually: $WORKSPACE_PATH"
fi

echo ""
echo -e "${GREEN}=== ESS Maker Kit ready! ===${NC}"
echo "Open Copilot Chat in VS Code and run /setup to connect your Dataverse environment."
echo ""
