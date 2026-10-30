<#
.SYNOPSIS
    One-liner web bootstrap for the ESS CA -> DA migration tool on a clean machine.

.DESCRIPTION
    Designed to be run straight from the web with nothing installed first:

        iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/tools/ess-ca-to-da/bootstrap.ps1)

    It ensures Git is present (installing it via winget if missing), shallow-clones
    the repository — which brings the tool and its vendored reference/ data — and
    leaves you in the tool folder, ready to run `.\run.ps1`. `run.ps1` then handles
    Python, the virtual environment, and installing the tool on first use.

    This does NOT run a migration for you: `migrate` needs your environment URL, so
    the safe default is to drop you at a ready-to-run prompt with instructions.

    Environment overrides:
      ESS_CA_TO_DA_ROOT   where to clone (default: %USERPROFILE%\Employee-Self-Service-Agent-Developer-Kit)
      ESS_ADK_BRANCH      branch to clone (default: main)
      ESS_ADK_SOURCE_URL  repository URL (default: the public GitHub repo)
#>
$ErrorActionPreference = 'Stop'

$RepoUrl = if ($env:ESS_ADK_SOURCE_URL) {
    $env:ESS_ADK_SOURCE_URL
} else {
    'https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit.git'
}
$Branch = if ($env:ESS_ADK_BRANCH) { $env:ESS_ADK_BRANCH } else { 'main' }
$Root = if ($env:ESS_CA_TO_DA_ROOT) {
    $env:ESS_CA_TO_DA_ROOT
} else {
    Join-Path $env:USERPROFILE 'Employee-Self-Service-Agent-Developer-Kit'
}

function Write-Info { param([string] $m) Write-Host "  $m" -ForegroundColor Cyan }
function Write-Ok   { param([string] $m) Write-Host "  $m" -ForegroundColor Green }
function Write-Warn2 { param([string] $m) Write-Host "  $m" -ForegroundColor Yellow }

function Install-GitIfMissing {
    if (Get-Command git -ErrorAction SilentlyContinue) { return $true }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { return $false }
    Write-Info 'Git not found. Installing Git via winget...'
    & winget install --id Git.Git --source winget `
        --accept-package-agreements --accept-source-agreements --silent 2>&1 | Out-Host
    # Refresh PATH for this session so the freshly installed git resolves.
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
    return [bool] (Get-Command git -ErrorAction SilentlyContinue)
}

# --- 1. Ensure Git ----------------------------------------------------------
if (-not (Install-GitIfMissing)) {
    Write-Warn2 'Could not find or install Git.'
    Write-Warn2 'Install it manually, then re-run this command:'
    Write-Warn2 '  winget install --id Git.Git'
    Write-Warn2 '  (or download from https://git-scm.com/download/win)'
    return
}
Write-Ok "Using Git: $((Get-Command git).Source)"

# --- 2. Clone or update the repository --------------------------------------
if (Test-Path (Join-Path $Root '.git')) {
    Write-Info "Updating existing clone at $Root ..."
    # A shallow `fetch origin <branch>` populates FETCH_HEAD but does NOT create
    # a remote-tracking ref (origin/<branch>), so checking out the branch name or
    # resetting to origin/<branch> fails. Check out FETCH_HEAD directly instead.
    & git -C $Root fetch --depth 1 origin $Branch | Out-Host
    & git -C $Root checkout -B $Branch FETCH_HEAD | Out-Host
    & git -C $Root reset --hard FETCH_HEAD | Out-Host
} else {
    Write-Info "Cloning $Branch into $Root ..."
    & git clone --depth 1 --branch $Branch $RepoUrl $Root | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Warn2 'Clone failed. See the git output above.'
        return
    }
}
Write-Ok 'Repository ready.'

# --- 3. Make sure script files are allowed to run ---------------------------
# A clean Windows client defaults to a Restricted execution policy, which blocks
# .ps1 files on disk (this bootstrap itself is exempt because it runs from a
# pipeline, not a file). Relax it to RemoteSigned for the current user only —
# no admin, no machine-wide change — so run.ps1 can run directly. If a machine
# or Group Policy still forces a blocking policy, fall back to a per-invocation
# bypass that needs no configuration.
function Get-RunPrefix {
    $blocking = @('Restricted', 'AllSigned', 'Undefined')
    if ((Get-ExecutionPolicy) -notin $blocking) { return '.\run.ps1' }
    try {
        Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force -ErrorAction Stop
        Write-Info 'Allowed local scripts to run (set execution policy RemoteSigned for your user).'
    } catch {
        Write-Warn2 'Could not change the execution policy (a machine/Group Policy may enforce it).'
    }
    if ((Get-ExecutionPolicy) -notin $blocking) { return '.\run.ps1' }
    return 'powershell -ExecutionPolicy Bypass -File .\run.ps1'
}

# --- 4. Land in the tool folder with next-step instructions -----------------
$tool = Join-Path $Root 'tools\ess-ca-to-da'
if (-not (Test-Path $tool)) {
    Write-Warn2 "Expected the tool at $tool but it is not there."
    return
}
Set-Location $tool

$run = Get-RunPrefix

Write-Host ''
Write-Ok "You're ready. You are now in: $tool"
Write-Host ''
Write-Host '  Next, run one of these (run.ps1 sets up Python and the tool on first use):' -ForegroundColor Cyan
Write-Host ''
Write-Host '    # See what a customer customized (read-only):' -ForegroundColor DarkGray
Write-Host "    $run inspect --environment-url https://contoso.crm.dynamics.com" -ForegroundColor White
Write-Host ''
Write-Host '    # Produce the Declarative Agent package and migration report:' -ForegroundColor DarkGray
Write-Host "    $run migrate --environment-url https://contoso.crm.dynamics.com --out out" -ForegroundColor White
Write-Host ''
Write-Host '  Add --vertical core|hr|it to target one agent, or omit it to detect them all.' -ForegroundColor DarkGray
Write-Host ''
