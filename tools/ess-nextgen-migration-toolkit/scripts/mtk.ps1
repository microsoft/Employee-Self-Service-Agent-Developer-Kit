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
    start | refresh | help

.PARAMETER Dev
    Include developer tooling (ruff, mypy, pytest, pre-commit).

.EXAMPLE
    mtk start            # provision runtime environment, then run (customers)
    mtk start -Dev       # provision runtime + dev tooling, then run (contributors)
    mtk refresh          # pull latest, then start (re-provision runtime + run)
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "refresh", "help")]
    [string]$Command = "help",

    [switch]$Dev
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

# Run the toolkit. Launches the orchestration entry point (src/service/mtk_orchestrator.py). The dev flag
# selects the matching run env: customers use --no-dev so `uv run` does not
# implicitly re-add the dev dependency-group to a runtime-only .venv.
function Invoke-Run {
    param([bool]$DevMode)

    $UV = Find-Uv
    Write-Host ""
    Write-Host "==> Starting the toolkit CLI..."
    if ($DevMode) { & $UV run python src/service/mtk_orchestrator.py --dev } else { & $UV run --no-dev python src/service/mtk_orchestrator.py }
}

# start = provision (idempotent) + run. The everyday command.
function Invoke-Start {
    param([bool]$DevMode)
    Invoke-Provision -DevMode:$DevMode
    Invoke-Run -DevMode:$DevMode
}

# refresh = pull latest code, then start (provision + run). It is the customer
# update path, so it always provisions a runtime-only environment (no -Dev).
function Invoke-Refresh {
    $branch = (git rev-parse --abbrev-ref HEAD).Trim()
    Write-Host "==> Updating '$branch' from origin (fast-forward only)..."
    git fetch --prune origin
    git rev-parse --abbrev-ref --symbolic-full-name '@{u}' *> $null
    if ($LASTEXITCODE -eq 0) {
        git pull --ff-only
    } else {
        Write-Host "    '$branch' has no upstream; pulling origin/main..."
        git pull --ff-only origin main
    }

    Invoke-Start -DevMode:$false
}

function Show-Usage {
    @"
mtk - ESS NextGen Migration Toolkit

Usage:
  mtk start [-Dev]      Provision a pip-free, locked environment (uv + Python + .venv), then run the toolkit
  mtk refresh           Pull latest code, then start (re-provision runtime env + run)
  mtk help              Show this help

Options:
  -Dev                  (start only) Include developer tooling (ruff, mypy, pytest, pre-commit)
"@ | Write-Host
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
switch ($Command) {
    "start"   { Invoke-Start -DevMode:$Dev.IsPresent }
    "refresh" {
        if ($Dev.IsPresent) {
            Write-Error ("'-Dev' is only valid with 'start'. 'refresh' is the customer " +
                "update path and always provisions a runtime-only environment. " +
                "Contributors: run 'mtk start -Dev' to (re)add dev tooling.")
            exit 2
        }
        Invoke-Refresh
    }
    default   { Show-Usage }
}
