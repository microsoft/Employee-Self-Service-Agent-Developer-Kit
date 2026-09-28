<#
.SYNOPSIS
    One-command launcher for the ESS CA -> DA migration tool (essmig).

.DESCRIPTION
    Ensures Python 3.11+ is available (auto-installing via winget if missing),
    creates an isolated .venv next to this script, installs essmig into it on
    first run, then forwards every argument to `python -m essmig`.

    So instead of:
        python -m pip install -e ".[dev]"
        python -m essmig migrate --environment-url ... --out out
    a customer runs:
        .\run.ps1 migrate --environment-url ... --out out

    Force a reinstall of the tool into the venv with -Reinstall (or set
    $env:ESSMIG_REINSTALL = '1').

.EXAMPLE
    .\run.ps1 migrate --environment-url https://contoso.crm.dynamics.com --out out

.EXAMPLE
    .\run.ps1 --help
#>
[CmdletBinding()]
param(
    [switch] $Reinstall,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Passthrough
)

$ErrorActionPreference = 'Stop'
$toolRoot = $PSScriptRoot
$venvPath = Join-Path $toolRoot '.venv'
$minMinor = 11   # pyproject requires-python = ">=3.11"

function Write-Info { param([string] $m) Write-Host "  $m" -ForegroundColor Cyan }
function Write-Ok   { param([string] $m) Write-Host "  $m" -ForegroundColor Green }
function Write-Warn2 { param([string] $m) Write-Host "  $m" -ForegroundColor Yellow }

# Run a native command and return its exit code without throwing.
function Invoke-Native { param([scriptblock] $Script) & $Script 2>&1 }

# Does this interpreter satisfy the minimum version? $Cmd is an array: exe + prefix args.
function Test-PythonVersion {
    param([string[]] $Cmd)
    try {
        $exe = $Cmd[0]
        $prefix = @($Cmd[1..($Cmd.Length - 1)] | Where-Object { $_ })
        $out = & $exe @prefix -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $false }
        $parts = "$($out | Select-Object -Last 1)".Trim().Split('.')
        return ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge $minMinor)
    } catch {
        return $false
    }
}

# Resolve a usable Python 3.11+, returned as an array (exe + any prefix args).
# Mirrors the resolution order proven in setup\Install-EssAdk.ps1.
function Resolve-Python {
    # 1. py launcher (most reliable on Windows)
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in @('-3.12', '-3.11', '-3')) {
            $cmd = @('py', $v)
            if (Test-PythonVersion $cmd) { return $cmd }
        }
    }
    # 2. python / python3 on PATH (skip the WindowsApps Store alias)
    foreach ($name in @('python', 'python3')) {
        $c = Get-Command $name -ErrorAction SilentlyContinue
        if ($c -and $c.Source -notmatch 'WindowsApps') {
            if (Test-PythonVersion @($c.Source)) { return @($c.Source) }
        }
    }
    # 3. Known install locations
    $known = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "${env:ProgramFiles(x86)}\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python311\python.exe"
    )
    foreach ($p in $known) {
        if ((Test-Path $p) -and (Test-PythonVersion @($p))) { return @($p) }
    }
    return $null
}

function Install-Python {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        return $false
    }
    Write-Info 'Python 3.11+ not found. Installing Python 3.12 via winget...'
    Invoke-Native { winget install --id Python.Python.3.12 --source winget `
            --accept-package-agreements --accept-source-agreements --silent } | Out-Host
    # Refresh PATH for this process so a freshly installed python resolves.
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
    return $true
}

# --- 1. Ensure Python -------------------------------------------------------
$python = Resolve-Python
if (-not $python) {
    if (Install-Python) { $python = Resolve-Python }
}
if (-not $python) {
    Write-Warn2 'Could not find or install Python 3.11 or newer.'
    Write-Warn2 'Install it manually, then re-run this script:'
    Write-Warn2 '  winget install --id Python.Python.3.12'
    Write-Warn2 '  (or download from https://www.python.org/downloads/windows/)'
    exit 1
}
Write-Ok "Using Python: $($python -join ' ')"

# --- 2. Ensure the virtual environment --------------------------------------
$venvPython = Join-Path $venvPath 'Scripts\python.exe'
$freshVenv = $false
if (-not (Test-Path $venvPython)) {
    Write-Info 'Creating virtual environment (.venv)...'
    $exe = $python[0]
    $prefix = @($python[1..($python.Length - 1)] | Where-Object { $_ })
    & $exe @prefix -m venv $venvPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
        Write-Warn2 'Failed to create the virtual environment.'
        exit 1
    }
    $freshVenv = $true
}

# --- 3. Install essmig into the venv (first run, or on demand) ---------------
if ($freshVenv -or $Reinstall -or $env:ESSMIG_REINSTALL -eq '1') {
    Write-Info 'Installing essmig and its dependencies...'
    & $venvPython -m pip install --upgrade --quiet --disable-pip-version-check pip | Out-Host
    & $venvPython -m pip install --quiet --disable-pip-version-check -e $toolRoot | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Warn2 'Failed to install essmig. See the pip output above.'
        exit 1
    }
    Write-Ok 'essmig ready.'
}

# --- 4. Run -----------------------------------------------------------------
& $venvPython -m essmig @Passthrough
exit $LASTEXITCODE
