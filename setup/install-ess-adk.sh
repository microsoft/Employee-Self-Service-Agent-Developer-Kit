#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# ESS ADK — macOS One-Shot Installer
#
# Installs the full ESS Maker Kit toolchain on macOS:
#   Homebrew, Python 3.12, Git, GitHub CLI, VS Code, Copilot extensions,
#   pip dependencies, clones the repo, launches VS Code, and auto-requests
#   /setup in Copilot Chat (requires VS Code 1.102+).
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
SKIP_MAKER_PROFILE="${SKIP_MAKER_PROFILE:-false}"
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

        # ESS Maker Profile (chat-first VS Code layout).
        # The bundled .vsix at tools/ess-maker-profile/extension/ hides
        # developer chrome and shows a big-button "Quick actions" rail
        # tied to the kit's slash commands. POC build — not on the
        # marketplace — so we install from the cloned repo. The extension
        # auto-activates on startup, including the `code chat /setup`
        # invocation in the launch step below. Non-fatal: a failure here
        # falls back to the stock VS Code layout.
        if [[ "$SKIP_MAKER_PROFILE" != "true" ]]; then
            # Glob so a version bump (0.4.0 -> 0.5.0) doesn't break the install.
            MAKER_VSIX_DIR="$REPO_PATH/tools/ess-maker-profile/extension"
            MAKER_VSIX=""
            if [[ -d "$MAKER_VSIX_DIR" ]]; then
                # shellcheck disable=SC2012 # ls -t is fine here; filenames
                # are author-controlled and match a tight glob.
                MAKER_VSIX="$(ls -t "$MAKER_VSIX_DIR"/ess-maker-profile-*.vsix 2>/dev/null | head -n 1 || true)"
            fi

            if [[ -z "$MAKER_VSIX" ]]; then
                warn "No ess-maker-profile-*.vsix found under $MAKER_VSIX_DIR. Skipping chat-first profile install."
            elif "$CODE_CMD" --install-extension "$MAKER_VSIX" --force 2>/dev/null; then
                ok "ESS Maker Profile ($(basename "$MAKER_VSIX"))"
                echo "    Tip: to revert to the stock VS Code layout, run 'ESS Maker: Restore Standard Layout' from the command palette."
                MAKER_PROFILE_INSTALLED=true
            else
                warn "ESS Maker Profile install failed (non-fatal, continuing with stock VS Code layout)"
            fi
        fi
    else
        warn "VS Code 'code' CLI not found. Install extensions manually after launching VS Code."
    fi
fi

# ---------------------------------------------------------------------------
# 7. FlightCheck-only: environment discovery, config, fetch, and run
# ---------------------------------------------------------------------------
if [[ "$FLIGHTCHECK_ONLY" == "true" ]]; then
    MAKER_KIT_PATH="$REPO_PATH/solutions/ess-maker-skills"
    if [[ ! -d "$MAKER_KIT_PATH" ]]; then
        err "Maker kit path not found at $MAKER_KIT_PATH. Was the clone successful?"
        exit 1
    fi
    cd "$MAKER_KIT_PATH"

    # Resolve python for discovery/fetch/flightcheck
    FLIGHTCHECK_PYTHON="$VENV_PATH/bin/python"
    if [[ ! -x "$FLIGHTCHECK_PYTHON" ]]; then
        FLIGHTCHECK_PYTHON="$PYTHON"
    fi

    LOCAL_DIR=".local"
    CONFIG_PATH="$LOCAL_DIR/config.json"
    DISCOVER_PY="scripts/discover.py"
    FETCH_PY="scripts/fetch_and_setup.py"

    # --- Config: reuse or create ---
    BOT_ID=""
    ENV_URL=""
    AGENT_NAME=""
    SCHEMA_NAME=""
    IS_MANAGED="true"

    if [[ -f "$CONFIG_PATH" ]]; then
        echo ""
        echo "    Config already exists at $CONFIG_PATH"
        read -rp "    Reconfigure? (Y/N): " RECONFIGURE
        if [[ "$RECONFIGURE" =~ ^[Yy] ]]; then
            rm -f "$CONFIG_PATH"
            ok "Removed existing config — starting fresh"
        else
            ok "Keeping existing config"
        fi
    fi

    if [[ ! -f "$CONFIG_PATH" ]]; then
        step "Configuring FlightCheck environment"

        if [[ ! -f "$DISCOVER_PY" ]]; then
            err "discover.py not found at $DISCOVER_PY. Was the repo cloned correctly?"
            exit 1
        fi

        # --- Step 1: List environments ---
        echo ""
        echo "    Listing Power Platform environments in your tenant..."
        echo "    A browser window will open for sign-in."
        echo ""

        ENV_OUTPUT=$("$FLIGHTCHECK_PYTHON" "$DISCOVER_PY" --list-environments 2>&1) || true
        echo "$ENV_OUTPUT"

        if echo "$ENV_OUTPUT" | grep -q "^ERROR:"; then
            err "Environment listing failed."
            exit 1
        fi

        echo ""
        read -rp "    Select environment number from the list above: " ENV_CHOICE
        ENV_CHOICE="${ENV_CHOICE// /}"
        if [[ -z "$ENV_CHOICE" || ! "$ENV_CHOICE" =~ ^[0-9]+$ ]]; then
            err "Invalid selection. Please re-run and pick a number."
            exit 1
        fi

        # Re-run with --select
        if ! SELECT_OUTPUT=$("$FLIGHTCHECK_PYTHON" "$DISCOVER_PY" --list-environments --select "$ENV_CHOICE" 2>&1); then
            err "Environment selection failed."
            exit 1
        fi

        ENV_JSON_LINE=$(echo "$SELECT_OUTPUT" | grep "^SELECTED_ENV_JSON:" | sed 's/^SELECTED_ENV_JSON://')
        if [[ -z "$ENV_JSON_LINE" ]]; then
            err "Could not parse environment selection output."
            exit 1
        fi

        ENV_URL=$(echo "$ENV_JSON_LINE" | "$FLIGHTCHECK_PYTHON" -c "import sys,json; d=json.load(sys.stdin); print(d.get('instanceUrl','').rstrip('/'))")
        ENV_DISPLAY=$(echo "$ENV_JSON_LINE" | "$FLIGHTCHECK_PYTHON" -c "import sys,json; d=json.load(sys.stdin); print(d.get('displayName',''))")

        if [[ -z "$ENV_URL" ]]; then
            err "Selected environment has no linked Dataverse URL."
            exit 1
        fi
        ok "Environment: $ENV_DISPLAY"
        ok "URL: $ENV_URL"

        # --- Step 2: List agents ---
        echo ""
        echo "    Discovering agents in this environment..."
        echo ""

        AGENT_OUTPUT=$("$FLIGHTCHECK_PYTHON" "$DISCOVER_PY" --url "$ENV_URL" 2>&1) && AGENT_EXIT=0 || AGENT_EXIT=$?
        echo "$AGENT_OUTPUT"

        if [[ $AGENT_EXIT -ne 0 ]] || echo "$AGENT_OUTPUT" | grep -q "^ERROR:"; then
            warn "Agent discovery failed. Config will be created without a bot ID."
            BOT_ID=""
            AGENT_NAME="FlightCheck-only (no agent selected)"
            SCHEMA_NAME=""
            IS_MANAGED="true"
        else
            echo ""
            read -rp "    Select agent number (or press Enter for environment-wide checks only): " AGENT_CHOICE
            AGENT_CHOICE="${AGENT_CHOICE// /}"

            if [[ -n "$AGENT_CHOICE" && "$AGENT_CHOICE" =~ ^[0-9]+$ ]]; then
                AGENT_SELECT_OUTPUT=$("$FLIGHTCHECK_PYTHON" "$DISCOVER_PY" --url "$ENV_URL" --select "$AGENT_CHOICE" 2>&1) || true
                AGENT_JSON_LINE=$(echo "$AGENT_SELECT_OUTPUT" | grep "^SELECTED_AGENT_JSON:" | sed 's/^SELECTED_AGENT_JSON://')

                if [[ -n "$AGENT_JSON_LINE" ]]; then
                    BOT_ID=$(echo "$AGENT_JSON_LINE" | "$FLIGHTCHECK_PYTHON" -c "import sys,json; d=json.load(sys.stdin); print(d.get('botid',''))")
                    AGENT_NAME=$(echo "$AGENT_JSON_LINE" | "$FLIGHTCHECK_PYTHON" -c "import sys,json; d=json.load(sys.stdin); print(d.get('name',''))")
                    SCHEMA_NAME=$(echo "$AGENT_JSON_LINE" | "$FLIGHTCHECK_PYTHON" -c "import sys,json; d=json.load(sys.stdin); print(d.get('schemaname',''))")
                    IS_MANAGED=$(echo "$AGENT_JSON_LINE" | "$FLIGHTCHECK_PYTHON" -c "import sys,json; d=json.load(sys.stdin); print('true' if d.get('ismanaged') else 'false')")
                    ok "Agent: $AGENT_NAME"
                else
                    warn "Agent selection failed. Continuing without bot ID."
                    BOT_ID=""
                    AGENT_NAME="FlightCheck-only (no agent selected)"
                    SCHEMA_NAME=""
                    IS_MANAGED="true"
                fi
            else
                warn "Skipping agent selection. Some agent-specific checks will be skipped."
                BOT_ID=""
                AGENT_NAME="FlightCheck-only (no agent selected)"
                SCHEMA_NAME=""
                IS_MANAGED="true"
            fi
        fi

        # Create .local directory and write config (use Python for safe JSON escaping)
        mkdir -p "$LOCAL_DIR"

        "$FLIGHTCHECK_PYTHON" -c "
import json, sys
config = {
    'configVersion': 1,
    'setup': 'flightcheck-only',
    'dataverseEndpoint': sys.argv[1],
    'flightCheckOnly': True,
    'agent': {
        'name': sys.argv[2],
        'botId': sys.argv[3],
        'schemaName': sys.argv[4],
        'isManaged': sys.argv[5] == 'true',
        'slug': 'flightcheck-only',
        'folder': ''
    },
    'agents': [{
        'name': sys.argv[2],
        'botId': sys.argv[3],
        'schemaName': sys.argv[4],
        'isManaged': sys.argv[5] == 'true',
        'slug': 'flightcheck-only',
        'folder': ''
    }] if sys.argv[3] else [],
    'activeAgent': 'flightcheck-only' if sys.argv[3] else ''
}
with open(sys.argv[6], 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=4)
" "$ENV_URL" "$AGENT_NAME" "$BOT_ID" "$SCHEMA_NAME" "$IS_MANAGED" "$CONFIG_PATH"
        ok "Created $CONFIG_PATH"
    fi

    # --- Read config values if they came from an existing file ---
    if [[ -z "$BOT_ID" && -f "$CONFIG_PATH" ]]; then
        ENV_URL=$("$FLIGHTCHECK_PYTHON" -c "import sys,json; c=json.load(open('$CONFIG_PATH')); print(c.get('dataverseEndpoint',''))")
        BOT_ID=$("$FLIGHTCHECK_PYTHON" -c "import sys,json; c=json.load(open('$CONFIG_PATH')); print(c.get('agent',{}).get('botId',''))")
        AGENT_NAME=$("$FLIGHTCHECK_PYTHON" -c "import sys,json; c=json.load(open('$CONFIG_PATH')); print(c.get('agent',{}).get('name',''))")
        SCHEMA_NAME=$("$FLIGHTCHECK_PYTHON" -c "import sys,json; c=json.load(open('$CONFIG_PATH')); print(c.get('agent',{}).get('schemaName',''))")
        IS_MANAGED=$("$FLIGHTCHECK_PYTHON" -c "import sys,json; c=json.load(open('$CONFIG_PATH')); print('true' if c.get('agent',{}).get('isManaged') else 'false')")
    fi

    # --- Fetch solution snapshot for local file checks ---
    if [[ -n "$BOT_ID" ]]; then
        step "Fetching agent solution from Dataverse"
        if [[ -f "$FETCH_PY" ]]; then
            FETCH_ARGS=("$FETCH_PY" "--url" "$ENV_URL" "--bot-id" "$BOT_ID" "--name" "$AGENT_NAME" "--schema" "$SCHEMA_NAME")
            if [[ "$IS_MANAGED" == "true" ]]; then
                FETCH_ARGS+=("--managed")
            fi

            if "$FLIGHTCHECK_PYTHON" "${FETCH_ARGS[@]}" 2>&1; then
                ok "Agent solution fetched and extracted"
            else
                warn "fetch_and_setup.py exited with errors. Local file checks may be skipped."
            fi
        else
            warn "fetch_and_setup.py not found at $FETCH_PY. Local file checks will be skipped."
        fi
    else
        echo ""
        echo "    [info] No agent selected — skipping solution fetch (local file checks will be skipped)."
    fi

    # --- Run FlightCheck ---
    step "Running FlightCheck"
    "$FLIGHTCHECK_PYTHON" scripts/flightcheck/cli.py --scope full
    exit $?
fi

# ---------------------------------------------------------------------------
# 8. Launch VS Code and request /setup in Copilot Chat
# ---------------------------------------------------------------------------
WORKSPACE_PATH="$REPO_PATH/solutions/ess-maker-skills"

if [[ -n "$CODE_CMD" ]]; then
    if [[ "${MAKER_PROFILE_INSTALLED:-false}" == "true" ]]; then
        # The ESS Maker Profile extension takes over /setup orchestration:
        # on activation it opens a chat editor in the editor area (full
        # width, not the narrow aux bar) and injects /setup itself. So
        # just launch the workspace plainly here — don't use
        # `code chat /setup`, which would also open an aux-bar chat and
        # leave us with two competing chat surfaces.
        step "Launching VS Code (Maker Profile will run /setup)"
        if (cd "$WORKSPACE_PATH" && "$CODE_CMD" .); then
            ok "Launched VS Code at $WORKSPACE_PATH"
            warn "The ESS Maker Profile will open Copilot Chat and run /setup automatically."
            warn "If VS Code prompts you to trust the workspace or sign in to GitHub/Copilot, accept those prompts."
        else
            warn "Could not launch VS Code. Open manually: $WORKSPACE_PATH"
            echo "Next: in VS Code, open Copilot Chat and run /setup to connect your Dataverse environment."
        fi
    else
        step "Launching VS Code and requesting /setup in Copilot Chat"
        # `code chat <prompt>` (VS Code 1.102+, June 2025) opens the chat panel in
        # the workspace at the current working directory and submits the prompt.
        # We cd into $WORKSPACE_PATH so it targets the kit folder.
        # NOTE: exit 0 means "VS Code accepted the chat request," NOT that /setup
        # actually ran. The user may still need to grant workspace trust and sign
        # in to GitHub/Copilot before /setup executes.
        if (cd "$WORKSPACE_PATH" && "$CODE_CMD" chat "/setup"); then
            ok "Requested /setup in Copilot Chat at $WORKSPACE_PATH"
            warn "If VS Code prompts you to trust the workspace or sign in to GitHub/Copilot, accept those prompts and /setup will run."
            warn "If /setup does not start after trust/sign-in, open Copilot Chat manually and run /setup."
        else
            warn "'code chat' failed or is unsupported. Falling back to opening the workspace only."
            warn "If you have an older VS Code (pre-1.102 / June 2025), update VS Code and re-run, or run /setup manually in Copilot Chat."
            "$CODE_CMD" "$WORKSPACE_PATH" || warn "Could not launch VS Code. Open manually: $WORKSPACE_PATH"
            echo "Next: in VS Code, open Copilot Chat and run /setup to connect your Dataverse environment."
        fi
    fi
else
    warn "Could not launch VS Code. Open manually: $WORKSPACE_PATH"
    echo "Next: in VS Code, open Copilot Chat and run /setup to connect your Dataverse environment."
fi

echo ""
echo -e "${GREEN}=== ESS Maker Kit ready! ===${NC}"
echo ""
