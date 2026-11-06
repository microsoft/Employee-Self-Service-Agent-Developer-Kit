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

# Does the python.exe at $PythonPath satisfy the minimum version?
# Uses Start-Process with a hard timeout so a missing, broken, or hanging
# interpreter can't wedge the launcher forever — we just move on to the next
# candidate. `--version` keeps the arguments space-free, avoiding brittle -c
# quoting, and works identically across the classic and PyManager builds.
function Test-PythonVersion {
    param([string] $PythonPath, [int] $TimeoutMs = 15000)
    $outFile = [System.IO.Path]::GetTempFileName()
    $errFile = [System.IO.Path]::GetTempFileName()
    try {
        $proc = Start-Process -FilePath $PythonPath -ArgumentList '--version' -NoNewWindow -PassThru `
            -RedirectStandardOutput $outFile -RedirectStandardError $errFile -ErrorAction Stop
        if (-not $proc.WaitForExit($TimeoutMs)) {
            try { $proc.Kill() } catch { }
            return $false
        }
        if ($proc.ExitCode -ne 0) { return $false }
        $text = (Get-Content $outFile -Raw -ErrorAction SilentlyContinue) +
                (Get-Content $errFile -Raw -ErrorAction SilentlyContinue)
        if ($text -match 'Python\s+(\d+)\.(\d+)') {
            return ([int]$Matches[1] -eq 3 -and [int]$Matches[2] -ge $minMinor)
        }
        return $false
    } catch {
        return $false
    } finally {
        Remove-Item $outFile, $errFile -Force -ErrorAction SilentlyContinue
    }
}

# Concrete python.exe paths known to the py launcher, via its path listing
# (`py -0p`). This is a launcher-native query that does NOT spawn Python, so it
# is fast and safe on both the classic launcher and the newer PyManager launcher.
function Get-PyLauncherPythonPaths {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) { return @() }
    $lines = try { & py -0p 2>$null } catch { @() }
    $found = foreach ($line in $lines) {
        if ($line -match '([A-Za-z]:\\[^\r\n]*?python\.exe)') { $Matches[1].Trim() }
    }
    return @($found)
}

# Resolve a usable Python 3.11+, returned as a concrete python.exe path string
# (or $null). We deliberately avoid the `py -X` command form for execution: the
# newer PyManager launcher mishandles it (e.g. `py -3.12 -m venv` silently drops
# `-m venv` and opens an interactive REPL). Invoking python.exe directly is
# reliable everywhere.
function Resolve-Python {
    $candidates = New-Object System.Collections.Generic.List[string]

    # 1. python / python3 on PATH (skip the WindowsApps Store alias)
    foreach ($name in @('python', 'python3')) {
        $c = Get-Command $name -ErrorAction SilentlyContinue
        if ($c -and $c.Source -and $c.Source -notmatch 'WindowsApps') {
            $candidates.Add($c.Source)
        }
    }
    # 2. Concrete paths the py launcher knows about (classic + PyManager)
    foreach ($p in (Get-PyLauncherPythonPaths)) { if ($p) { $candidates.Add($p) } }
    # 3. Known install locations (winget / python.org / PyManager), newest first,
    #    so an install that never made it onto PATH is still found.
    $globs = @(
        "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
        "$env:ProgramFiles\Python3*\python.exe",
        "${env:ProgramFiles(x86)}\Python3*\python.exe",
        "$env:LOCALAPPDATA\Python\pythoncore-3.*\python.exe"
    )
    foreach ($g in $globs) {
        Get-ChildItem -Path $g -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            ForEach-Object { $candidates.Add($_.FullName) }
    }

    foreach ($p in $candidates) {
        if ($p -and (Test-Path $p) -and (Test-PythonVersion $p)) { return $p }
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
Write-Ok "Using Python: $python"

# --- 2. Ensure the virtual environment --------------------------------------
$venvPython = Join-Path $venvPath 'Scripts\python.exe'
$freshVenv = $false
if (-not (Test-Path $venvPython)) {
    Write-Info 'Creating virtual environment (.venv)...'
    & $python -m venv $venvPath
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
