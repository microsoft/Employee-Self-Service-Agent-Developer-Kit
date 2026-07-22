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
# can be run as `./mtk.sh start` from the top of the monorepo.
#
# Usage:
#   mtk start [--dev]     Provision a pip-free, locked environment, then run the toolkit
#   mtk refresh           Pull latest code, then start (re-provision runtime env + run)
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

# Run the toolkit. Launches the orchestration entry point (src/service/mtk_orchestrator.py), replacing the
# current process. The dev flag selects the matching run env: customers use
# --no-dev so `uv run` does not implicitly re-add the dev dependency-group to a
# runtime-only .venv.
cmd_run() {
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

# start = provision (idempotent) + run. The everyday command.
cmd_start() {
  local dev="$1"
  local mode="$2"
  cmd_provision "$dev"
  cmd_run "$dev" "$mode"
}

# refresh = pull latest code, then start (provision + run). It is the customer
# update path, so it always provisions a runtime-only environment (no --dev).
cmd_refresh() {
  local mode="$1"
  # 1. Pull the latest code (fast-forward only; never rewrites local work).
  local branch
  branch="$(git rev-parse --abbrev-ref HEAD)"
  echo "==> Updating '$branch' from origin (fast-forward only)..."
  git fetch --prune origin
  if git rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
    git pull --ff-only
  else
    echo "    '$branch' has no upstream; pulling origin/main..."
    git pull --ff-only origin main
  fi

  # 2. Start: re-provision from the (updated) lockfile, then run (runtime only).
  cmd_start "0" "$mode"
}

usage() {
  cat <<'EOF'
mtk — ESS NextGen Migration Toolkit

Usage:
  mtk start [--dev] [--mode readonly|writeback]
                        Provision a pip-free, locked environment (uv + Python + .venv), then run the toolkit
  mtk refresh [--mode readonly|writeback]
                        Pull latest code, then start (re-provision runtime env + run)
  mtk help              Show this help

Options:
  --dev                 (start only) Include developer tooling (ruff, mypy, pytest, pre-commit)
  --mode <mode>         Execution mode: readonly (default, no writes) or writeback (persist changes)
EOF
}

# ---------------------------------------------------------------------------
# Argument parsing — subcommand plus an optional, position-independent --dev
# and --mode readonly|writeback (accepts `--mode X` and `--mode=X`).
# ---------------------------------------------------------------------------
CMD=""
DEV=0
MODE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    start|refresh)  CMD="$1"; shift ;;
    help|-h|--help) CMD="help"; shift ;;
    --dev)          DEV=1; shift ;;
    --mode)         MODE="${2:-}"; shift 2 || shift ;;
    --mode=*)       MODE="${1#--mode=}"; shift ;;
    *) echo "ERROR: unknown argument '$1'" >&2; usage; exit 2 ;;
  esac
done

case "$CMD" in
  start)   cmd_start "$DEV" "$MODE" ;;
  refresh)
    if [[ "$DEV" == "1" ]]; then
      echo "ERROR: '--dev' is only valid with 'start'. 'refresh' is the customer" >&2
      echo "       update path and always provisions a runtime-only environment." >&2
      echo "       Contributors: run 'mtk start --dev' to (re)add dev tooling." >&2
      exit 2
    fi
    cmd_refresh "$MODE" ;;
  help)    usage ;;
  "")      echo "ERROR: no command given." >&2; usage; exit 2 ;;
esac
