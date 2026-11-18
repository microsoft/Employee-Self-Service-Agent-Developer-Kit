#!/usr/bin/env bash
#
# One-liner web bootstrap for the ESS CA -> DA migration tool on a clean machine.
#
# Designed to be run straight from the web with nothing installed first:
#
#     /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/tools/ess-ca-to-da/bootstrap.sh)"
#
# It ensures Git is present (installing it via Homebrew on macOS if missing),
# shallow-clones the repository — which brings the tool and its vendored
# reference/ data — then prints the exact command to run. run.sh handles Python,
# the virtual environment, and installing the tool on first use.
#
# This does NOT run a migration for you: `migrate` needs your environment URL, so
# the safe default is to print a ready-to-run command with instructions. (This
# script runs in a subshell, so it cannot change your shell's directory for you —
# copy the printed `cd` command.)
#
# Environment overrides:
#   ESS_CA_TO_DA_ROOT   where to clone (default: ~/Employee-Self-Service-Agent-Developer-Kit)
#   ESS_ADK_BRANCH      branch to clone (default: main)
#   ESS_ADK_SOURCE_URL  repository URL (default: the public GitHub repo)

set -euo pipefail

REPO_URL="${ESS_ADK_SOURCE_URL:-https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit.git}"
BRANCH="${ESS_ADK_BRANCH:-main}"
ROOT="${ESS_CA_TO_DA_ROOT:-$HOME/Employee-Self-Service-Agent-Developer-Kit}"

info() { printf '  \033[36m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[32m%s\033[0m\n' "$1"; }
warn() { printf '  \033[33m%s\033[0m\n' "$1"; }

ensure_git() {
    if command -v git >/dev/null 2>&1; then
        return 0
    fi
    if [[ "$(uname -s)" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
        info 'Git not found. Installing Git via Homebrew...'
        brew install git && return 0
    fi
    return 1
}

# --- 1. Ensure Git ----------------------------------------------------------
if ! ensure_git; then
    warn 'Could not find or install Git.'
    if [[ "$(uname -s)" == "Darwin" ]]; then
        warn 'Install it manually, then re-run this command:'
        warn '  brew install git   (or xcode-select --install)'
    else
        warn 'Install Git with your package manager, then re-run this command:'
        warn '  e.g. sudo apt-get install git   (Debian/Ubuntu)'
    fi
    exit 1
fi
ok "Using Git: $(command -v git)"

# --- 2. Clone or update the repository --------------------------------------
if [[ -d "$ROOT/.git" ]]; then
    info "Updating existing clone at $ROOT ..."
    # A shallow `fetch origin <branch>` populates FETCH_HEAD but does NOT create
    # a remote-tracking ref (origin/<branch>), so checking out the branch name or
    # resetting to origin/<branch> fails. Check out FETCH_HEAD directly instead.
    git -C "$ROOT" fetch --depth 1 origin "$BRANCH"
    git -C "$ROOT" checkout -B "$BRANCH" FETCH_HEAD
    git -C "$ROOT" reset --hard FETCH_HEAD
else
    info "Cloning $BRANCH into $ROOT ..."
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$ROOT"
fi
ok 'Repository ready.'

# --- 3. Print next-step instructions ----------------------------------------
TOOL="$ROOT/tools/ess-ca-to-da"
if [[ ! -d "$TOOL" ]]; then
    warn "Expected the tool at $TOOL but it is not there."
    exit 1
fi

echo ''
ok "You're ready. The tool is at: $TOOL"
echo ''
printf '  \033[36mNext, run (run.sh sets up Python and the tool on first use):\033[0m\n'
echo ''
printf '    \033[90m# Move into the tool folder:\033[0m\n'
printf '    \033[97mcd "%s"\033[0m\n' "$TOOL"
echo ''
printf '    \033[90m# See what a customer customized (read-only):\033[0m\n'
printf '    \033[97m./run.sh inspect --environment-url https://contoso.crm.dynamics.com\033[0m\n'
echo ''
printf '    \033[90m# Produce the Declarative Agent package and migration report:\033[0m\n'
printf '    \033[97m./run.sh migrate --environment-url https://contoso.crm.dynamics.com --out out\033[0m\n'
echo ''
printf '  \033[90mAdd --vertical core|hr|it to target one agent, or omit it to detect them all.\033[0m\n'
echo ''
