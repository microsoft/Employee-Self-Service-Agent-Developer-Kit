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

.EXAMPLE
    mtk run                      # customer: pull latest, provision runtime, then run
    mtk run -Dev                 # contributor: provision runtime + dev tooling, run (no git pull)
    mtk run -Mode writeback      # run in writeback mode (persist changes)
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet("run", "help")]
    [string]$Command = "help",

    [switch]$Dev,

    [string]$Mode = ""
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

# Reset the checkout to pristine origin/main. Customer update path: force-switch
# to main pointed at origin/main and DISCARD any local branch position,
# uncommitted changes, and untracked files, so the tool only ever runs from the
# latest reviewed main. Contributors (-Dev) manage their own git. Gitignored
# runtime state (.venv, .local, output/) is preserved (clean respects .gitignore).
function Sync-ToMain {
    Write-Host "==> Customer mode: resetting to pristine origin/main."
    Write-Host "    Local branch position and uncommitted/untracked changes will be discarded"
    Write-Host "    so the tool runs only from the latest reviewed main."
    Write-Host "    (Contributors: use 'mtk run -Dev' to keep your work and skip this.)"
    git fetch --prune origin
    git checkout -f -B main origin/main
    git clean -fd
}

# run = the single everyday command. Without -Dev (customer) it first resets to
# pristine origin/main (discarding local changes), then provisions (idempotent)
# and runs. With -Dev (contributor) it provisions runtime + dev tooling and runs
# WITHOUT touching git.
function Invoke-Run {
    param([bool]$DevMode, [string]$Mode)
    if (-not $DevMode) { Sync-ToMain }
    Invoke-Provision -DevMode:$DevMode
    Invoke-Launch -DevMode:$DevMode -Mode:$Mode
}

function Show-Usage {
    @"
mtk - ESS NextGen Migration Toolkit

Usage:
  mtk run [-Dev] [-Mode readonly|writeback]
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
"@ | Write-Host
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
switch ($Command) {
    "run"   { Invoke-Run -DevMode:$Dev.IsPresent -Mode:$Mode }
    default { Show-Usage }
}
