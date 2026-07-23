#!/usr/bin/env bash
#
# mtk — ESS NextGen Migration Toolkit command entrypoint.
#
# A SINGLE dispatcher for every developer/operator command. New operational
# commands are added here as subcommands — never as new top-level scripts. This
# keeps the operator surface to one discoverable command (`mtk <command>`),
# mirroring tool wrappers like `./gradlew` and `./mvnw`.
#
# This file is the real implementation and lives in <toolkit-root>/scripts/.
# A single forwarder at the repository root (./mtk.sh) execs this file, so it
# can be run as `./mtk.sh run` from the top of the monorepo.
#
# Usage:
#   mtk run [--dev]       Run the toolkit. Customers (no --dev) reset to pristine
#                         origin/main first (local changes discarded); contributors
#                         (--dev) add dev tooling and skip the reset. Add
#                         --mode readonly|writeback.
#   mtk help              Show this help
#
# Everything is pip-free: uv is a self-contained binary that provisions both the
# pinned Python and the locked dependencies. pip is never used.
set -euo pipefail

# Always operate from the toolkit root (this file lives in <root>/scripts/).
cd "$(dirname "$0")/.."

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
find_uv() {
  if command -v uv >/dev/null 2>&1; then command -v uv; return 0; fi
  local c
  for c in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    [[ -x "$c" ]] && { echo "$c"; return 0; }
  done
  return 1
}

# Echoes the uv path on stdout; all progress/log output goes to stderr so the
# path can be safely captured with command substitution.
ensure_uv() {
  local uv
  uv="$(find_uv || true)"
  if [[ -z "$uv" ]]; then
    echo "==> uv not found; installing the standalone uv (no Python required)..." >&2
    if command -v curl >/dev/null 2>&1; then
      curl -LsSf https://astral.sh/uv/install.sh | sh 1>&2
    elif command -v wget >/dev/null 2>&1; then
      wget -qO- https://astral.sh/uv/install.sh | sh 1>&2
    else
      echo "ERROR: need 'curl' or 'wget' to install uv." >&2
      echo "       https://docs.astral.sh/uv/getting-started/installation/" >&2
      return 1
    fi
    uv="$(find_uv || true)"
    if [[ -z "$uv" ]]; then
      echo "ERROR: uv installation did not produce a usable binary." >&2
      echo "       Open a new shell (so PATH refreshes) and re-run." >&2
      return 1
    fi
  fi
  echo "$uv"
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

# Provision the environment: uv + pinned Python + locked .venv. When dev=1 the
# full env (including the "dev" dependency-group) is synced and the toolkit's
# commit-time hooks are installed; otherwise a runtime-only env is synced.
cmd_provision() {
  local dev="$1"
  local UV
  UV="$(ensure_uv)"
  echo "==> Using uv: $("$UV" --version 2>&1)  ($UV)"

  # Provision the pinned Python (no system Python needed). uv downloads a
  # managed CPython matching .python-version if it isn't already available.
  local PIN
  PIN="$(cat .python-version 2>/dev/null || true)"
  echo "==> Ensuring pinned Python (${PIN:-from pyproject}) is available..."
  if [[ -n "$PIN" ]]; then "$UV" python install "$PIN"; else "$UV" python install; fi

  # `uv sync` creates the virtual environment (.venv) automatically. The "dev"
  # dependency-group is included by default, so plain `uv sync` gives
  # contributors their tooling; `--no-dev` gives customers a runtime-only env.
  if [[ "$dev" == "1" ]]; then
    echo "==> Syncing environment (runtime + dev tooling)..."
    "$UV" sync

    # Auto-enable the toolkit's commit-time quality gates so contributors never
    # have to run them by hand. The hooks are hard-scoped to this toolkit (see
    # .pre-commit-config.yaml), so they are a no-op for commits elsewhere in the
    # monorepo. Git hooks live in the shared .git/hooks and are not version-
    # controlled, so this one-time install must run per clone — folding it into
    # provisioning makes it seamless. Skipped outside a git work tree.
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      echo "==> Installing toolkit-scoped pre-commit hooks..."
      "$UV" run pre-commit install -c .pre-commit-config.yaml >/dev/null \
        && echo "    Commit-time gates active (ruff + mypy, toolkit only)." \
        || echo "    (Could not install pre-commit hooks; run gates with: $UV run pre-commit run --all-files)"
    fi
  else
    echo "==> Syncing environment (runtime only)..."
    "$UV" sync --no-dev
  fi

  if ! command -v uv >/dev/null 2>&1; then
    echo ""
    echo "Tip: add uv to your PATH so you can call it directly next time:"
    echo "      export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo "      (Add this to your shell profile — e.g. ~/.bashrc, ~/.zshrc, or ~/.profile)"
  fi
}

# Launch the toolkit. Execs the orchestration entry point
# (src/service/mtk_orchestrator.py), replacing the current process. The dev flag
# selects the matching run env: customers use --no-dev so `uv run` does not
# implicitly re-add the dev dependency-group to a runtime-only .venv.
launch_toolkit() {
  local dev="$1"
  local mode="$2"
  local UV
  UV="$(find_uv || true)"
  echo ""
  echo "==> Starting the toolkit CLI..."
  # Build the orchestrator argument list safely (bash 3.2 + set -u friendly).
  set -- src/service/mtk_orchestrator.py
  [[ "$dev" == "1" ]] && set -- "$@" --dev
  [[ -n "$mode" ]] && set -- "$@" --mode "$mode"
  if [[ "$dev" == "1" ]]; then
    exec "$UV" run python "$@"
  else
    exec "$UV" run --no-dev python "$@"
  fi
}

# Confirm before discarding local WORK-TREE changes. Only uncommitted changes and
# untracked files are ever discarded — local commits and branches are never
# touched (we check out origin/main detached, without moving any branch pointer).
# Skips the prompt when the work tree is already clean (nothing to lose). `--yes`
# bypasses the prompt; a non-interactive shell REFUSES rather than silently
# destroying work.
confirm_reset_or_abort() {
  local force="$1"
  # Only uncommitted tracked changes + untracked files are at risk. `git status
  # --porcelain` lists exactly those (and respects .gitignore, so runtime state
  # is not counted). Empty → nothing to lose, proceed silently.
  if [[ -z "$(git status --porcelain 2>/dev/null || true)" ]]; then
    return 0
  fi
  {
    echo ""
    echo "WARNING: 'mtk run' (customer mode) runs from a pristine checkout of origin/main."
    echo "  This DISCARDS your uncommitted changes and untracked files (git checkout -f + git clean -fd)."
    echo "  Your local commits and branches are PRESERVED (no branch is reset or deleted)."
    echo "  Contributors: re-run with '--dev' to keep everything and skip this."
  } >&2
  if [[ "$force" == "1" ]]; then
    echo "  --yes given; discarding uncommitted/untracked changes and continuing." >&2
    return 0
  fi
  if [[ ! -t 0 ]]; then
    echo "ERROR: refusing to discard uncommitted changes in a non-interactive shell." >&2
    echo "       Re-run with '--dev' (keep work) or '--yes' (discard uncommitted/untracked)." >&2
    exit 3
  fi
  printf "  Type 'yes' to discard uncommitted/untracked changes and continue: " >&2
  local reply=""
  read -r reply || true
  if [[ "$reply" != "yes" ]]; then
    echo "Aborted — nothing was changed." >&2
    exit 3
  fi
}

# Run from a pristine checkout of origin/main. Customer update path: check out
# origin/main **detached** (never moving/resetting any branch pointer) and clean
# untracked files, so the working tree exactly matches the latest reviewed main —
# discarding only uncommitted changes + untracked files. Local commits and
# branches are fully preserved. Guarded by confirm_reset_or_abort so it never
# silently destroys uncommitted work. Contributors (--dev) skip this entirely.
# Gitignored runtime state (.venv, .local, output/) is preserved (clean respects
# .gitignore).
sync_to_main() {
  local force="$1"
  git fetch --prune origin
  confirm_reset_or_abort "$force"
  echo "==> Checking out pristine origin/main (local commits and branches preserved)..."
  git -c advice.detachedHead=false checkout -f origin/main
  git clean -fd
}

# run = the single everyday command. Without --dev (customer) it first resets to
# pristine origin/main (discarding local changes, after confirmation), then
# provisions (idempotent) and runs. With --dev (contributor) it provisions
# runtime + dev tooling and runs WITHOUT touching git — contributors manage their
# own branches.
cmd_run() {
  local dev="$1"
  local mode="$2"
  local force="$3"
  if [[ "$dev" != "1" ]]; then
    sync_to_main "$force"
  fi
  cmd_provision "$dev"
  launch_toolkit "$dev" "$mode"
}

usage() {
  cat <<'EOF'
mtk — ESS NextGen Migration Toolkit

Usage:
  mtk run [--dev] [--mode readonly|writeback] [--yes]
                        Run the toolkit. Without --dev (customer), first resets to
                        pristine origin/main (discarding any local changes), then
                        provisions a locked runtime env and runs. With --dev
                        (contributor), provisions runtime + dev tooling and runs
                        WITHOUT touching git.
  mtk help              Show this help

Options:
  --dev                 Include developer tooling (ruff, mypy, pytest, pre-commit);
                        also skips the reset-to-main (contributors manage their git)
  --mode <mode>         Execution mode: readonly (default, no writes) or writeback (persist changes)
  --yes                 Skip the confirmation prompt before the customer reset-to-main
                        (required to reset non-interactively; ignored with --dev)
EOF
}

# ---------------------------------------------------------------------------
# Argument parsing — subcommand plus optional, position-independent --dev,
# --mode readonly|writeback (accepts `--mode X` and `--mode=X`), and --yes.
# ---------------------------------------------------------------------------
CMD=""
DEV=0
MODE=""
FORCE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    run)            CMD="run"; shift ;;
    help|-h|--help) CMD="help"; shift ;;
    --dev)          DEV=1; shift ;;
    --yes|-y)       FORCE=1; shift ;;
    --mode)         MODE="${2:-}"; shift 2 || shift ;;
    --mode=*)       MODE="${1#--mode=}"; shift ;;
    *) echo "ERROR: unknown argument '$1'" >&2; usage; exit 2 ;;
  esac
done

case "$CMD" in
  run)     cmd_run "$DEV" "$MODE" "$FORCE" ;;
  help)    usage ;;
  "")      echo "ERROR: no command given." >&2; usage; exit 2 ;;
esac
