#requires -Version 5.1
<#
.SYNOPSIS
    mtk - ESS NextGen Migration Toolkit command entrypoint (Windows).

.DESCRIPTION
    A SINGLE dispatcher for every developer/operator command. New operational
    commands are added here as subcommands - never as new top-level scripts.
    Everything is pip-free: uv is a self-contained binary that provisions both
    the pinned Python and the locked dependencies.

    This file is the real implementation and lives in <toolkit-root>\scripts\.
    A single forwarder at the repository root (.\mtk.ps1) calls this file.

.PARAMETER Command
    run | help

.PARAMETER Dev
    Include developer tooling (ruff, mypy, pytest, pre-commit); also skips the
    reset-to-main (contributors manage their own branches).

.PARAMETER Mode
    Execution mode: readonly (default, no writes) or writeback (persist changes).

.PARAMETER Yes
    Skip the confirmation prompt before the customer reset-to-main (required to
    reset non-interactively; ignored with -Dev).

.EXAMPLE
    mtk run                      # customer: reset to pristine origin/main, provision, then run
    mtk run -Dev                 # contributor: provision runtime + dev tooling, run (no git reset)
    mtk run -Mode writeback      # run in writeback mode (persist changes)
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet("run", "help")]
    [string]$Command = "help",

    [switch]$Dev,

    [string]$Mode = "",

    [switch]$Yes
)

$ErrorActionPreference = "Stop"
# Always operate from the toolkit root (this file lives in <root>\scripts\).
Set-Location (Join-Path $PSScriptRoot "..")

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
function Find-Uv {
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($c in @(
            (Join-Path $env:USERPROFILE ".local\bin\uv.exe"),
            (Join-Path $env:USERPROFILE ".cargo\bin\uv.exe"))) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

function Assert-UvInstalled {
    $uv = Find-Uv
    if (-not $uv) {
        Write-Host "==> uv not found; installing the standalone uv (no Python required)..."
        powershell -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
        $uv = Find-Uv
        if (-not $uv) {
            Write-Error ("uv installation did not produce a usable binary. Open a new " +
                "shell (so PATH refreshes) and re-run, or install uv manually: " +
                "https://docs.astral.sh/uv/getting-started/installation/")
        }
    }
    return $uv
}

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

# Provision the environment: uv + pinned Python + locked .venv. When -Dev the
# full env (including the "dev" dependency-group) is synced and the toolkit's
# commit-time hooks are installed; otherwise a runtime-only env is synced.
function Invoke-Provision {
    param([bool]$DevMode)

    $UV = Assert-UvInstalled
    Write-Host "==> Using uv: $(& $UV --version 2>&1)  ($UV)"

    $pin = if (Test-Path ".python-version") { (Get-Content ".python-version" -Raw).Trim() } else { "" }
    Write-Host "==> Ensuring pinned Python ($(if ($pin) { $pin } else { 'from pyproject' })) is available..."
    if ($pin) { & $UV python install $pin } else { & $UV python install }

    if ($DevMode) {
        Write-Host "==> Syncing environment (runtime + dev tooling)..."
        & $UV sync

        # Auto-enable the toolkit's commit-time quality gates so contributors
        # never have to run them by hand. The hooks are hard-scoped to this
        # toolkit (.pre-commit-config.yaml), so they no-op for commits elsewhere
        # in the monorepo. Git hooks live in the shared, un-versioned .git/hooks,
        # so this one-time install runs per clone - folding it into provisioning
        # makes it seamless. Skipped outside a git work tree.
        git rev-parse --is-inside-work-tree *> $null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "==> Installing toolkit-scoped pre-commit hooks..."
            & $UV run pre-commit install -c .pre-commit-config.yaml *> $null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "    Commit-time gates active (ruff + mypy, toolkit only)."
            } else {
                Write-Host "    (Could not install pre-commit hooks; run gates with: $UV run pre-commit run --all-files)"
            }
        }
    } else {
        Write-Host "==> Syncing environment (runtime only)..."
        & $UV sync --no-dev
    }

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host ""
        Write-Host "Tip: add uv to your PATH so you can call it directly next time:"
        Write-Host "      `$env:Path = `"`$env:USERPROFILE\.local\bin;`$env:Path`""
    }
}

# Launch the toolkit. Execs the orchestration entry point
# (src/service/mtk_orchestrator.py). The dev flag selects the matching run env:
# customers use --no-dev so `uv run` does not implicitly re-add the dev
# dependency-group to a runtime-only .venv.
function Invoke-Launch {
    param([bool]$DevMode, [string]$Mode)

    $UV = Find-Uv
    Write-Host ""
    Write-Host "==> Starting the toolkit CLI..."
    $pyArgs = @("src/service/mtk_orchestrator.py")
    if ($DevMode) { $pyArgs += "--dev" }
    if ($Mode) { $pyArgs += @("--mode", $Mode) }
    if ($DevMode) { & $UV run python @pyArgs } else { & $UV run --no-dev python @pyArgs }
}

# Confirm before discarding local WORK-TREE changes. Only uncommitted changes and
# untracked files are ever discarded — local commits and branches are never
# touched (we check out origin/main detached, without moving any branch pointer).
# Skips the prompt when the work tree is already clean. -Yes bypasses the prompt;
# a non-interactive session REFUSES rather than silently destroying work.
function Confirm-ResetOrAbort {
    param([bool]$Force)
    $dirty = [bool](git status --porcelain 2>$null)
    if (-not $dirty) { return }  # clean work tree → nothing to lose

    Write-Host ""
    Write-Host "WARNING: 'mtk run' (customer mode) runs from a pristine checkout of origin/main."
    Write-Host "  This DISCARDS your uncommitted changes and untracked files (git checkout -f + git clean -fd)."
    Write-Host "  Your local commits and branches are PRESERVED (no branch is reset or deleted)."
    Write-Host "  Contributors: re-run with '-Dev' to keep everything and skip this."
    if ($Force) { Write-Host "  -Yes given; discarding uncommitted/untracked changes and continuing."; return }
    if (-not [Environment]::UserInteractive) {
        Write-Error ("Refusing to discard uncommitted changes in a non-interactive session. " +
            "Re-run with '-Dev' (keep work) or '-Yes' (discard uncommitted/untracked).")
        exit 3
    }
    $reply = Read-Host "  Type 'yes' to discard uncommitted/untracked changes and continue"
    if ($reply -ne "yes") { Write-Error "Aborted - nothing was changed."; exit 3 }
}

# Run from a pristine checkout of origin/main. Customer update path: check out
# origin/main DETACHED (never moving/resetting any branch pointer) and clean
# untracked files, so the working tree exactly matches the latest reviewed main —
# discarding only uncommitted changes + untracked files. Local commits and
# branches are fully preserved. Guarded by Confirm-ResetOrAbort so it never
# silently destroys uncommitted work. Contributors (-Dev) skip this. Gitignored
# runtime state (.venv, .local, output/) is preserved (clean respects .gitignore).
function Sync-ToMain {
    param([bool]$Force)
    git fetch --prune origin
    Confirm-ResetOrAbort -Force:$Force
    Write-Host "==> Checking out pristine origin/main (local commits and branches preserved)..."
    git -c advice.detachedHead=false checkout -f origin/main
    git clean -fd
}

# run = the single everyday command. Without -Dev (customer) it first resets to
# pristine origin/main (discarding local changes, after confirmation), then
# provisions (idempotent) and runs. With -Dev (contributor) it provisions runtime
# + dev tooling and runs WITHOUT touching git.
function Invoke-Run {
    param([bool]$DevMode, [string]$Mode, [bool]$Force)
    if (-not $DevMode) { Sync-ToMain -Force:$Force }
    Invoke-Provision -DevMode:$DevMode
    Invoke-Launch -DevMode:$DevMode -Mode:$Mode
}

function Show-Usage {
    @"
mtk - ESS NextGen Migration Toolkit

Usage:
  mtk run [-Dev] [-Mode readonly|writeback] [-Yes]
                        Run the toolkit. Without -Dev (customer), first resets to
                        pristine origin/main (discarding any local changes), then
                        provisions a locked runtime env and runs. With -Dev
                        (contributor), provisions runtime + dev tooling and runs
                        WITHOUT touching git.
  mtk help              Show this help

Options:
  -Dev                  Include developer tooling (ruff, mypy, pytest, pre-commit);
                        also skips the reset-to-main (contributors manage their git)
  -Mode <mode>          Execution mode: readonly (default, no writes) or writeback (persist changes)
  -Yes                  Skip the confirmation prompt before the customer reset-to-main
                        (required to reset non-interactively; ignored with -Dev)
"@ | Write-Host
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
switch ($Command) {
    "run"   { Invoke-Run -DevMode:$Dev.IsPresent -Mode:$Mode -Force:$Yes.IsPresent }
    default { Show-Usage }
}
