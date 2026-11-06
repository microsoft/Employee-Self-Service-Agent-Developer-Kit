#!/usr/bin/env bash
#
# One-command launcher for the ESS CA -> DA migration tool (essmig).
#
# Ensures Python 3.11+ is available (auto-installing via Homebrew on macOS if
# missing), creates an isolated .venv next to this script, installs essmig into
# it on first run, then forwards every argument to `python -m essmig`.
#
# So instead of:
#     python -m pip install -e ".[dev]"
#     python -m essmig migrate --environment-url ... --out out
# a customer runs:
#     ./run.sh migrate --environment-url ... --out out
#
# Force a reinstall of the tool into the venv with ESSMIG_REINSTALL=1.
#
# Examples:
#     ./run.sh migrate --environment-url https://contoso.crm.dynamics.com --out out
#     ./run.sh --help

set -euo pipefail

TOOL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$TOOL_ROOT/.venv"
MIN_MINOR=11   # pyproject requires-python = ">=3.11"

info() { printf '  \033[36m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m%s\033[0m\n' "$1"; }
warn() { printf '  \033[33m%s\033[0m\n' "$1"; }

# Does this interpreter satisfy the minimum version?
python_ok() {
    local exe="$1"
    "$exe" -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, $MIN_MINOR) else 1)" \
        >/dev/null 2>&1
}

# Resolve a usable Python 3.11+, echoing its path. Empty output means none found.
resolve_python() {
    local candidates=(python3.12 python3.11 python3 python)
    # Homebrew (Apple Silicon and Intel) locations, in case they aren't on PATH.
    candidates+=(/opt/homebrew/bin/python3.12 /usr/local/bin/python3.12)
    local c
    for c in "${candidates[@]}"; do
        if command -v "$c" >/dev/null 2>&1 && python_ok "$c"; then
            command -v "$c"
            return 0
        elif [[ -x "$c" ]] && python_ok "$c"; then
            echo "$c"
            return 0
        fi
    done
    return 1
}

install_python() {
    if [[ "$(uname -s)" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
        info 'Python 3.11+ not found. Installing Python 3.12 via Homebrew...'
        brew install python@3.12 || return 1
        return 0
    fi
    return 1
}

# --- 1. Ensure Python -------------------------------------------------------
PYTHON="$(resolve_python || true)"
if [[ -z "$PYTHON" ]]; then
    if install_python; then
        PYTHON="$(resolve_python || true)"
    fi
fi
if [[ -z "$PYTHON" ]]; then
    warn 'Could not find or install Python 3.11 or newer.'
    if [[ "$(uname -s)" == "Darwin" ]]; then
        warn 'Install it manually, then re-run this script:'
        warn '  brew install python@3.12'
        warn '  (or download from https://www.python.org/downloads/macos/)'
    else
        warn 'Install Python 3.11+ with your package manager, then re-run this script.'
        warn '  e.g. sudo apt-get install python3 python3-venv   (Debian/Ubuntu)'
    fi
    exit 1
fi
ok "Using Python: $PYTHON"

# --- 2. Ensure the virtual environment --------------------------------------
VENV_PYTHON="$VENV_PATH/bin/python"
FRESH_VENV=0
if [[ ! -x "$VENV_PYTHON" ]]; then
    info 'Creating virtual environment (.venv)...'
    "$PYTHON" -m venv "$VENV_PATH"
    FRESH_VENV=1
fi

# --- 3. Install essmig into the venv (first run, or on demand) ---------------
if [[ "$FRESH_VENV" == "1" || "${ESSMIG_REINSTALL:-}" == "1" ]]; then
    info 'Installing essmig and its dependencies...'
    "$VENV_PYTHON" -m pip install --upgrade --quiet --disable-pip-version-check pip
    "$VENV_PYTHON" -m pip install --quiet --disable-pip-version-check -e "$TOOL_ROOT"
    ok 'essmig ready.'
fi

# --- 4. Run -----------------------------------------------------------------
exec "$VENV_PYTHON" -m essmig "$@"
