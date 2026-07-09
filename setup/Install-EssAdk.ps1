#Requires -Version 5.1
<#
.SYNOPSIS
    One-shot installer for the Microsoft Employee Self-Service Agent Developer Kit (ESS ADK).

.DESCRIPTION
    Reduces the ESS ADK onboarding from "install 5 things + clone + setup" down to
    a single PowerShell invocation. Specifically, it:

      1. Verifies prerequisites (Windows 10/11, winget present).
      2. Runs `winget configure` against ess-adk-setup.winget.yaml to install
         VS Code, Python 3.12, PowerShell 7, Git, and GitHub CLI.
      3. Installs Python pip dependencies from requirements.txt (msal, requests,
         PyYAML, defusedxml, etc.) so that /setup scripts work immediately.
      4. Installs the VS Code extensions required by the maker kit
         (GitHub.copilot, GitHub.copilot-chat, ms-python.python).
      5. Clones the Employee-Self-Service-Agent-Developer-Kit repo to a known
         location (default: $env:USERPROFILE\source\Employee-Self-Service-Agent-Developer-Kit).
      6. Opens the ess-maker-skills workspace in VS Code and automatically
         requests `/setup` in Copilot Chat (requires VS Code 1.102+).

    The script is idempotent: re-run to repair a partial install.

.PARAMETER InstallRoot
    Folder under which the repo will be cloned. Defaults to "$env:USERPROFILE\source".

.PARAMETER RepoUrl
    Git URL to clone. Defaults to the public Microsoft repo.

.PARAMETER Branch
    Branch to check out. Defaults to "main".

.PARAMETER SkipExtensions
    Skip installing VS Code extensions (useful if the customer's policy installs
    them centrally via Intune).

.PARAMETER SkipClone
    Skip cloning the repo (useful if the customer already has a working copy).

.PARAMETER SkipLaunch
    Don't auto-open VS Code at the end.

.PARAMETER UseDsc
    Use 'winget configure' with the declarative YAML config instead of individual
    'winget install' calls. The YAML path is IT-auditable / Intune-friendly but
    requires a one-time 'winget configure --enable' opt-in (which installs DSC
    PowerShell modules from the Microsoft Store). Default is the direct install
    path, which works on any GA winget without that opt-in.

.PARAMETER FlightCheckOnly
    Install only the minimal toolchain needed to run FlightCheck (Python + Git +
    pip dependencies). Skips VS Code, extensions, and the full maker kit setup.
    Prompts for your Dataverse environment URL and creates a minimal
    .local/config.json so FlightCheck can authenticate without running /setup.

.PARAMETER SkipMakerProfile
    Skip installing the bundled "ESS Maker Profile" VS Code extension. The
    profile hides developer chrome (file tree, tabs, status bar, etc.) and
    drops the user into a chat-first surface tailored to the HR/IT admin
    persona. Use this switch to keep the stock VS Code layout - typically
    only relevant for developers iterating on the kit itself.

.EXAMPLE
    # Default invocation. May fail on stock Windows due to PowerShell
    # ExecutionPolicy=Restricted. If so, use the form below instead.
    .\Install-EssAdk.ps1

.EXAMPLE
    # Recommended local invocation - bypasses ExecutionPolicy for this run only,
    # without changing any machine-wide setting.
    powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-EssAdk.ps1

.EXAMPLE
    .\Install-EssAdk.ps1 -InstallRoot D:\repos -Branch main
#>

[CmdletBinding()]
param(
    [string] $InstallRoot   = (Join-Path $env:USERPROFILE 'source'),
    [string] $RepoUrl       = 'https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit.git',
    [string] $Branch        = 'main',
    [switch] $SkipExtensions,
    [switch] $SkipClone,
    [switch] $SkipLaunch,
    [switch] $UseDsc,
    [switch] $FlightCheckOnly,
    [switch] $SkipMakerProfile
)

$ErrorActionPreference = 'Stop'

function Write-Step  { param([string]$m) Write-Host "`n==> $m" -ForegroundColor Cyan; try { Write-EssInstallStep -Step (Get-EssStepKey $m) } catch {} }
function Write-Ok    { param([string]$m) Write-Host "    [ok]   $m" -ForegroundColor Green }
function Write-Warn2 { param([string]$m) Write-Host "    [warn] $m" -ForegroundColor Yellow }
function Write-Err2  { param([string]$m) Write-Host "    [err]  $m" -ForegroundColor Red }

# Helper: show elapsed time during a long-running operation.
# Start-Spinner records the start time; Stop-Spinner prints the elapsed duration.
function Start-Spinner {
    param([string]$Label)
    $script:spinnerLabel = $Label
    $script:spinnerSW = [System.Diagnostics.Stopwatch]::StartNew()
    Write-Host "    [..] $Label ..." -NoNewline -ForegroundColor DarkGray
}

function Stop-Spinner {
    if ($script:spinnerSW) {
        $elapsed = [math]::Floor($script:spinnerSW.Elapsed.TotalSeconds)
        $script:spinnerSW.Stop()
        $script:spinnerSW = $null
        # Overwrite the [..] line with elapsed time
        Write-Host "`r    [$($elapsed)s] $($script:spinnerLabel)           " -ForegroundColor DarkGray
        $script:spinnerLabel = $null
    }
}

# Helper: run a native command safely without $ErrorActionPreference = 'Stop'
# terminating on stderr output (PS 5.1 bug). Returns combined output as string[].
function Invoke-Native {
    param([scriptblock]$Command)
    $prevEAP = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = & $Command 2>&1
        return $output
    } finally {
        $ErrorActionPreference = $prevEAP
    }
}

# Helper: resolve Python executable robustly.
# Checks py launcher, python on PATH (excluding Store alias), and known install paths.
function Resolve-Python {
    # 1. py launcher (most reliable on Windows)
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $null = Invoke-Native { & py -3.12 --version }
        if ($LASTEXITCODE -eq 0) { return 'py -3.12' }
        $null = Invoke-Native { & py -3 --version }
        if ($LASTEXITCODE -eq 0) { return 'py -3' }
    }

    # 2. python on PATH (validate it's real, not the Store alias)
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        # Store alias lives in WindowsApps and outputs nothing useful
        if ($python.Source -notmatch 'WindowsApps') {
            $null = Invoke-Native { & $python.Source --version }
            if ($LASTEXITCODE -eq 0) { return $python.Source }
        }
    }

    # 3. Known install paths
    $knownPaths = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:ProgramFiles\Python312\python.exe",
        "${env:ProgramFiles(x86)}\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:ProgramFiles\Python311\python.exe"
    )
    foreach ($p in $knownPaths) {
        if (Test-Path $p) { return $p }
    }

    return $null
}

# Helper: detect Windows ARM64 host. Used to add ARM64-specific guardrails to
# pip install (cryptography only shipped win_arm64 wheels in 46.0+; older
# resolutions fall back to a Rust source-build that needs VS Build Tools).
function Test-IsWindowsArm64 {
    try {
        return ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString() -eq 'Arm64')
    } catch {
        # Older .NET Framework without RuntimeInformation. Fall back to env var.
        return ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64')
    }
}

# Helper: read MSAL token cache and return unique signed-in usernames.
# The cache is a JSON document (the .bin extension is misleading). Each
# account entry has a `username` field. Multiple entries per user can
# appear (one per tenant/realm); dedupe.
#
# Output contract: pipeline-emits zero or more username strings. Callers
# MUST wrap the result with `@( ... )` to get a proper array - bare
# assignment of a single-element pipeline output collapses to a string in
# PowerShell (and `.Count` on that string then throws under
# `Set-StrictMode -Version Latest`, which some users have in their
# profile). Returns nothing on any parse failure - callers treat that as
# "unknown user" and fall back to a generic prompt.
function Get-CachedUsernames {
    param([Parameter(Mandatory)] [string] $CachePath)
    if (-not (Test-Path $CachePath)) { return }
    try {
        $raw = Get-Content -LiteralPath $CachePath -Raw -ErrorAction Stop
        if (-not $raw -or -not $raw.Trim()) { return }
        $cache = $raw | ConvertFrom-Json -ErrorAction Stop
        if (-not $cache -or -not $cache.Account) { return }
        $names = New-Object System.Collections.ArrayList
        foreach ($prop in $cache.Account.PSObject.Properties) {
            $u = $prop.Value.username
            if ($u) { [void] $names.Add([string] $u) }
        }
        if ($names.Count -eq 0) { return }
        # Emit each unique username into the pipeline. Caller wraps with @()
        # to get a guaranteed array regardless of count.
        $names | Sort-Object -Unique
    } catch {
        return
    }
}

# Helper: install pip requirements with ARM64-aware guardrails.
#   - Upgrades pip first (failures are warnings, not fatal - older pip can still install).
#   - Uses --prefer-binary so resolution favors wheels over sdists when possible.
#   - On Windows ARM64, adds --only-binary cryptography. cryptography source
#     builds need Rust + the MSVC linker (link.exe), which most ARM64 dev
#     boxes don't have. Failing fast with a wheel-missing message is better
#     than a 60-second Rust download + cryptic linker error.
#   - On failure, prints actionable remediation (especially for ARM64).
# Returns the pip install exit code so callers can decide what to do.
function Install-PipRequirements {
    param(
        [Parameter(Mandatory)] [string] $PythonExe,
        [Parameter(Mandatory)] [string] $RequirementsFile
    )

    # Normalize launcher invocation. 'py -3.12' / 'py -3' come back as space-
    # separated strings from Resolve-Python; everything else is an absolute path.
    if ($PythonExe -eq 'py -3.12' -or $PythonExe -eq 'py -3') {
        $pyExe = 'py'
        $pyPrefix = @(($PythonExe -split ' ')[1])
    } else {
        $pyExe = $PythonExe
        $pyPrefix = @()
    }

    # 1. Pip self-upgrade. Warn-and-continue on failure so a transient pip
    # issue doesn't mask a requirements install failure (or block the install
    # entirely when the existing pip would have been good enough).
    Start-Spinner 'upgrading pip'
    $upgradeOutput = Invoke-Native {
        & $pyExe @pyPrefix -m pip install --upgrade --quiet --disable-pip-version-check pip
    }
    $upgradeExit = $LASTEXITCODE
    Stop-Spinner
    if ($upgradeExit -ne 0) {
        Write-Warn2 "pip self-upgrade returned exit code $upgradeExit (non-fatal, continuing)"
        foreach ($line in $upgradeOutput) { Write-Host "      $line" }
    }

    # 2. Build pip install arguments.
    $pipArgs = @(
        '-m', 'pip', 'install',
        '--quiet',
        '--disable-pip-version-check',
        '--prefer-binary',
        '-r', $RequirementsFile
    )
    if (Test-IsWindowsArm64) {
        # cryptography sdists trigger a Rust toolchain bootstrap; without
        # VS Build Tools the cl/link.exe step fails. Force a wheel-only
        # resolution for cryptography on ARM64.
        $pipArgs += @('--only-binary', 'cryptography')
    }

    # 3. Install requirements.
    Start-Spinner 'installing pip dependencies'
    $pipOutput = Invoke-Native { & $pyExe @pyPrefix @pipArgs }
    $pipExit = $LASTEXITCODE
    Stop-Spinner
    foreach ($line in $pipOutput) { Write-Host "      $line" }

    if ($pipExit -eq 0) {
        Write-Ok 'pip dependencies installed'
    } else {
        Write-Warn2 "pip install returned exit code $pipExit (non-fatal, /setup will retry)"
        if (Test-IsWindowsArm64) {
            Write-Host ''
            Write-Warn2 'Windows ARM64 detected. A common cause is a missing win_arm64 wheel for'
            Write-Warn2 "'cryptography' (a transitive dependency of msal). Options:"
            Write-Warn2 '  (a) Recommended: install x64 Python and re-run. Side-by-side with the'
            Write-Warn2 '      ARM64 build, then prefer the x64 interpreter for pip:'
            Write-Warn2 '        winget install --id Python.Python.3.12 --architecture x64'
            Write-Warn2 '        (or download from https://www.python.org/downloads/windows/)'
            Write-Warn2 '      Verify with: python -c "import platform; print(platform.machine())"'
            Write-Warn2 '      AMD64 wheels run under Windows ARM64 emulation (Prism).'
            Write-Warn2 '  (b) Install Visual Studio Build Tools to build from source:'
            Write-Warn2 '        winget install --id Microsoft.VisualStudio.2022.BuildTools'
            Write-Warn2 '        (~7GB; select the "Desktop development with C++" workload)'
        }
    }

    return $pipExit
}

# ---------------------------------------------------------------------------
# Installer telemetry (Aria/1DS). Fail-open: never breaks the install.
# ---------------------------------------------------------------------------
function Get-EssStepKey {
    param([string]$m)
    switch -regex ($m) {
        'Preflight'                { 'preflight'; break }
        'winget|toolchain'         { 'toolchain'; break }
        'pip'                      { 'pip_dependencies'; break }
        'extension'                { 'vscode_extensions'; break }
        'Clon|clone|repo'          { 'clone'; break }
        'Maker Profile'            { 'maker_profile'; break }
        'FlightCheck environment|environment'  { 'flightcheck_config'; break }
        'agent solution|Fetch'     { 'fetch_agent'; break }
        'Running FlightCheck|Run FlightCheck'  { 'flightcheck_run'; break }
        'workspace|Launch|Open'    { 'launch'; break }
        default {
            # Fall back to a scrubbed slug of the first few words.
            $slug = ($m -replace '[^A-Za-z0-9 ]', '' ).Trim().ToLower() -replace '\s+', '_'
            if ($slug.Length -gt 40) { $slug = $slug.Substring(0, 40) }
            if ([string]::IsNullOrWhiteSpace($slug)) { 'step' } else { $slug }
        }
    }
}

# Locate + dot-source the emitter: env var set by the bootstrap (one-liner
# install), else the copy shipped alongside this script in a clone. If it can't
# be found, define no-op stubs so every telemetry call below is always safe.
$essTelLoaded = $false
$essTelCandidates = @()
if ($env:ESS_INSTALL_TELEMETRY_LIB) { $essTelCandidates += $env:ESS_INSTALL_TELEMETRY_LIB }
if ($PSScriptRoot)  { $essTelCandidates += (Join-Path $PSScriptRoot 'telemetry\install-telemetry.ps1') }
if ($PSCommandPath) { $essTelCandidates += (Join-Path (Split-Path -Parent $PSCommandPath) 'telemetry\install-telemetry.ps1') }
foreach ($cand in $essTelCandidates) {
    if ($cand -and (Test-Path $cand)) {
        try { . $cand; $essTelLoaded = $true; break } catch { }
    }
}
if (-not $essTelLoaded) {
    function Initialize-EssInstallTelemetry { param($Installer) }
    function Write-EssInstallStep          { param($Step) }
    function Complete-EssInstallTelemetry  { param($Outcome, $ErrorRecord) }
}

$essInstaller = if ($FlightCheckOnly) { 'flightcheck' } elseif ($SkipMakerProfile) { 'adk' } else { 'lite' }
Initialize-EssInstallTelemetry -Installer $essInstaller

try {

# ---------------------------------------------------------------------------
# 1. Preflight
# ---------------------------------------------------------------------------
Write-Step 'Preflight checks'

if ($PSVersionTable.PSVersion.Major -lt 5) {
    throw 'PowerShell 5.1 or later is required.'
}
Write-Ok "PowerShell $($PSVersionTable.PSVersion)"

$os = [Environment]::OSVersion
if ($os.Platform -ne 'Win32NT' -or $os.Version.Build -lt 17763) {
    throw 'Windows 10 1809 (build 17763) or later is required for winget configure.'
}
Write-Ok "Windows build $($os.Version.Build)"

$winget = Get-Command winget -ErrorAction SilentlyContinue
$wingetAvailable = [bool]$winget

if (-not $wingetAvailable) {
    if ($FlightCheckOnly) {
        # In FlightCheck-only mode, winget is preferred but not mandatory.
        # If Python and Git are already installed, we can skip winget entirely.
        Write-Warn2 'winget not found. Will check if Python and Git are already available.'
    } else {
        Write-Err2 'winget not found. Install "App Installer" from the Microsoft Store, then re-run.'
        throw 'winget is required for the full ADK install.'
    }
} else {
    Write-Ok "winget at $($winget.Source)"
}

# ---------------------------------------------------------------------------
# 2. Toolchain install (winget)
# ---------------------------------------------------------------------------
Write-Step 'Installing toolchain via winget'

# Packages must match ess-adk-setup.winget.yaml. Keep these two in sync.
if ($FlightCheckOnly) {
    # Minimal set: just Python + Git (no VS Code, PowerShell 7, or GH CLI)
    $packages = @(
        @{ Id = 'Python.Python.3.12'; Name = 'Python 3.12'; Cmd = 'python' },
        @{ Id = 'Git.Git';            Name = 'Git for Windows'; Cmd = 'git' }
    )
} else {
    $packages = @(
        @{ Id = 'Microsoft.VisualStudioCode'; Name = 'Visual Studio Code'; Cmd = 'code' },
        @{ Id = 'Python.Python.3.12';         Name = 'Python 3.12'; Cmd = 'python'      },
        @{ Id = 'Microsoft.PowerShell';       Name = 'PowerShell 7'; Cmd = 'pwsh'       },
        @{ Id = 'Git.Git';                    Name = 'Git for Windows'; Cmd = 'git'     },
        @{ Id = 'GitHub.cli';                 Name = 'GitHub CLI'; Cmd = 'gh'           }
    )
}

if (-not $wingetAvailable) {
    # winget not present - check if required tools are already installed
    Write-Warn2 'winget not available. Checking for pre-installed tools...'
    $missingTools = @()
    foreach ($pkg in $packages) {
        if ($pkg.Cmd -eq 'python') {
            # Use Resolve-Python to exclude the non-functional Store alias
            $resolved = Resolve-Python
            if ($resolved) {
                Write-Ok "$($pkg.Name) (found: $resolved)"
            } else {
                $missingTools += $pkg.Name
            }
        } else {
            $cmd = Get-Command $pkg.Cmd -ErrorAction SilentlyContinue
            if ($cmd) {
                Write-Ok "$($pkg.Name) (already installed at $($cmd.Source))"
            } else {
                $missingTools += $pkg.Name
            }
        }
    }
    if ($missingTools.Count -gt 0) {
        Write-Err2 "Missing tools that cannot be auto-installed without winget: $($missingTools -join ', ')"
        Write-Err2 'Please install them manually:'
        Write-Err2 '  Python 3.12: https://www.python.org/downloads/'
        Write-Err2 '  Git: https://git-scm.com/download/win'
        if (-not $FlightCheckOnly) {
            Write-Err2 '  VS Code: https://code.visualstudio.com/download'
            Write-Err2 '  PowerShell 7: https://aka.ms/powershell-release?tag=stable'
            Write-Err2 '  GitHub CLI: https://cli.github.com/'
        }
        throw "Required tools are missing and winget is not available to install them."
    }
} elseif ($UseDsc) {
    # Declarative path - requires `winget configure --enable` (one-time opt-in
    # that pulls DSC modules from the Microsoft Store). Provided for IT shops
    # that prefer the auditable YAML manifest.
    $configFile = if ($PSScriptRoot) { Join-Path $PSScriptRoot 'ess-adk-setup.winget.yaml' } else { '' }
    $cfgExists = $configFile -and (Test-Path -LiteralPath $configFile)
    if (-not $cfgExists) {
        throw "Cannot locate winget config - -UseDsc requires running Install-EssAdk.ps1 directly from disk, not via bootstrap."
    }
    Write-Ok "Using DSC config: $configFile"
    & winget configure --file $configFile `
                       --accept-configuration-agreements `
                       --disable-interactivity
    if ($LASTEXITCODE -ne 0) {
        throw "winget configure failed with exit code $LASTEXITCODE. If you see 'Extended features are not enabled', run 'winget configure --enable' once and retry, or omit -UseDsc to use the direct-install path."
    }
} else {
    # Default path - direct `winget install` per package. Works on any GA
    # winget without enabling extended features. Idempotent: re-running just
    # logs "already installed" for present packages.
    foreach ($pkg in $packages) {
        # Skip if already installed (avoids unnecessary winget calls + elevation prompts)
        $existing = if ($pkg.Cmd -eq 'python') { Resolve-Python } else { Get-Command $pkg.Cmd -ErrorAction SilentlyContinue }
        if ($existing) {
            Write-Ok "$($pkg.Name) (already installed)"
            continue
        }

        Start-Spinner "installing $($pkg.Name) ($($pkg.Id))"
        $wingetOutput = Invoke-Native {
            & winget install --id $pkg.Id `
                             --source winget `
                             --exact `
                             --silent `
                             --accept-package-agreements `
                             --accept-source-agreements `
                             --disable-interactivity
        }
        Stop-Spinner
        foreach ($rawLine in $wingetOutput) {
            $line = "$rawLine".Trim()
            if ($line -and $line -notmatch '^[\\/\|\-]$' -and $line -notmatch '[^\x20-\x7E]') {
                Write-Host "      $line"
            }
        }

        # winget exit codes:
        #   0                = installed OK
        #   -1978335189 (0x8A15002B) = APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE
        #                              ("No applicable update found" - already current)
        # Both mean "we're good", anything else is a real failure.
        $code = $LASTEXITCODE
        if ($code -eq 0 -or $code -eq -1978335189) {
            Write-Ok "$($pkg.Name)"
        } else {
            if ($FlightCheckOnly) {
                Write-Warn2 "$($pkg.Name) install exited $code. Will check if usable anyway."
            } else {
                throw "winget install $($pkg.Id) failed with exit code $code"
            }
        }
    }
}
Write-Ok 'Toolchain installed / verified'

# Refresh PATH in-process so newly-installed tools are callable
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
            [Environment]::GetEnvironmentVariable('Path','User')

# ---------------------------------------------------------------------------
# 3. Python pip dependencies
# ---------------------------------------------------------------------------
Write-Step 'Installing Python pip dependencies'

$deferPip = $false
$pythonExe = Resolve-Python

if (-not $pythonExe) {
    Write-Warn2 'Python not found on PATH or known locations. Pip dependencies will be installed when you run /setup.'
    $deferPip = $false
} else {
    Write-Ok "Using Python: $pythonExe"
    if ($PSScriptRoot) {
        $requirementsFile = Join-Path $PSScriptRoot '..\solutions\ess-maker-skills\scripts\requirements.txt'
    } else {
        $requirementsFile = ''
    }
    $reqFileExists = $requirementsFile -and (Test-Path -LiteralPath $requirementsFile)
    if (-not $reqFileExists) {
        Write-Warn2 'requirements.txt not yet available (pre-clone). Will install after clone.'
        $deferPip = $true
    } else {
        $null = Install-PipRequirements -PythonExe $pythonExe -RequirementsFile $requirementsFile
    }
}

# ---------------------------------------------------------------------------
# 4. VS Code extensions
# ---------------------------------------------------------------------------
if ($FlightCheckOnly) {
    Write-Warn2 'Skipping VS Code extensions (FlightCheck-only mode)'
} elseif (-not $SkipExtensions) {
    Write-Step 'Installing VS Code extensions'

    $code = Get-Command code -ErrorAction SilentlyContinue
    if (-not $code) {
        # Fallback: check the known VS Code install location (winget/user install)
        $knownCodeCmd = Join-Path $env:LOCALAPPDATA 'Programs\Microsoft VS Code\bin\code.cmd'
        if (Test-Path $knownCodeCmd) {
            $code = Get-Item $knownCodeCmd
        }
    }
    if (-not $code) {
        Write-Warn2 'code CLI not on PATH yet. Open a new PowerShell window after this script and run:'
        Write-Warn2 '  code --install-extension GitHub.copilot'
        Write-Warn2 '  code --install-extension GitHub.copilot-chat'
        Write-Warn2 '  code --install-extension ms-python.python'
    } else {
        # Normalize to path string
        $codeBin = if ($code.Source) { $code.Source } elseif ($code.FullName) { $code.FullName } else { 'code' }
        $extensions = @(
            'GitHub.copilot',
            'GitHub.copilot-chat',
            'ms-python.python'
        )
        foreach ($ext in $extensions) {
            # `code` writes its install errors to stderr; combined with the
            # script-global $ErrorActionPreference='Stop' that causes 2>&1 to
            # raise a terminating exception before we can inspect the output.
            # Scope EAP locally and use try/catch to keep classification logic
            # in charge of the success/skip decision.
            $out = $null
            $code_exit = 0
            try {
                $prevEAP = $ErrorActionPreference
                $ErrorActionPreference = 'Continue'
                $out = & $codeBin --install-extension $ext --force 2>&1
                $code_exit = $LASTEXITCODE
            } catch {
                $out = $_.Exception.Message
                $code_exit = if ($LASTEXITCODE) { $LASTEXITCODE } else { 1 }
            } finally {
                $ErrorActionPreference = $prevEAP
            }
            $joined = ($out | Out-String)

            # Recent VS Code (>=1.99) ships Copilot + Copilot Chat as built-in
            # extensions. The marketplace copy is older than the bundled one, so
            # `--install-extension` exits non-zero with a message like:
            #   "Extension 'github.copilot-chat' is a built-in extension with
            #    version 'X' and cannot be downgraded to version 'Y'."
            # That actually means we already have it (and a newer build), so we
            # treat it as success. Same for "already installed".
            $isBuiltInOrPresent = $joined -match 'is a built-in extension|is already installed|cannot be downgraded'

            if ($code_exit -eq 0) {
                Write-Ok "extension $ext"
            } elseif ($isBuiltInOrPresent) {
                Write-Ok "extension $ext (already present / built-in)"
            } else {
                Write-Warn2 "extension $ext returned exit $code_exit"
                $joined.TrimEnd() -split "`r?`n" | ForEach-Object { Write-Warn2 "  $_" }
            }
        }
    }
} else {
    Write-Warn2 'Skipping VS Code extensions per -SkipExtensions'
}

# ---------------------------------------------------------------------------
# 5. Clone repo
# ---------------------------------------------------------------------------
$repoName = [IO.Path]::GetFileNameWithoutExtension(($RepoUrl -split '/')[-1])
$repoPath = Join-Path $InstallRoot $repoName

if (-not $SkipClone) {
    Write-Step "Cloning $RepoUrl"

    # Prevent git from hanging waiting for credentials or host-key prompts
    $env:GIT_TERMINAL_PROMPT = '0'
    $env:GCM_INTERACTIVE = 'never'

    if (-not (Test-Path $InstallRoot)) {
        New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
    }

    # If the directory exists but isn't a git repo (leftover from a partial
    # install/cleanup), remove it so the clone can proceed.
    if ((Test-Path $repoPath) -and -not (Test-Path (Join-Path $repoPath '.git'))) {
        Write-Warn2 "Directory exists but is not a git repo: $repoPath"
        Write-Warn2 'This appears to be a leftover from a partial install.'
        Write-Warn2 "Contents will be deleted to perform a fresh clone."
        Write-Warn2 "Press Ctrl+C within 5 seconds to abort..."
        Start-Sleep -Seconds 5
        Remove-Item -Recurse -Force $repoPath
    }

    if (Test-Path (Join-Path $repoPath '.git')) {
        Write-Ok "Repo already cloned at $repoPath - pulling latest"
        Push-Location $repoPath
        try {
            # Self-heal --single-branch clones from earlier installer versions.
            # Without this, `git fetch origin` only refreshes the originally-
            # cloned branch and `git checkout $Branch` fails for any other
            # branch - pinning users to whatever branch they first installed
            # from. Idempotent: no-op if the refspec is already broad.
            $null = Invoke-Native { & git remote set-branches origin '*' }

            $gitOutput = Invoke-Native { & git fetch --quiet origin }
            foreach ($line in $gitOutput) { if ($line) { Write-Host "      $line" } }
            if ($LASTEXITCODE -ne 0) {
                Write-Warn2 "git fetch failed (exit $LASTEXITCODE). Continuing with local copy."
            } else {
                $currentBranch = (Invoke-Native { & git branch --show-current } | Select-Object -First 1).Trim()
                $gitOutput = Invoke-Native { & git checkout --quiet $Branch }
                foreach ($line in $gitOutput) { if ($line) { Write-Host "      $line" } }
                if ($LASTEXITCODE -ne 0) {
                    # Loud, actionable: silent fallback to stale code is what
                    # caused the "env types showing Unknown" / "browser doesn't
                    # open" regression reports for users who first installed
                    # from a feature branch.
                    Write-Warn2 "git checkout $Branch failed (exit $LASTEXITCODE)."
                    Write-Warn2 "Your local clone is on '$currentBranch' and cannot switch to '$Branch'."
                    Write-Warn2 "You will run STALE code from '$currentBranch' instead of '$Branch'."
                    Write-Warn2 "To recover: delete the local clone and re-run, e.g."
                    Write-Warn2 "  Remove-Item -Recurse -Force '$repoPath'"
                    Write-Warn2 "Then re-run the installer / bootstrap command."
                } else {
                    $gitOutput = Invoke-Native { & git pull --quiet --ff-only }
                    foreach ($line in $gitOutput) { if ($line) { Write-Host "      $line" } }
                    if ($LASTEXITCODE -ne 0) {
                        Write-Warn2 "git pull failed (exit $LASTEXITCODE). Continuing with local copy (may be behind '$Branch')."
                        Write-Warn2 "If you see stale behavior, delete '$repoPath' and re-run."
                    }
                }
            }
        } finally { Pop-Location }
    } else {
        Start-Spinner "cloning repository"
        # No --single-branch: the kit repo is small and a full clone lets
        # subsequent installer runs switch branches (e.g. testing a fix on
        # a feature branch, then back to main). The previous --single-branch
        # behavior trapped users on whichever branch they first installed.
        $gitOutput = Invoke-Native { & git clone --branch $Branch $RepoUrl $repoPath }
        Stop-Spinner
        foreach ($line in $gitOutput) { Write-Host "      $line" }
        if ($LASTEXITCODE -ne 0) {
            Write-Err2 "git clone failed with exit code $LASTEXITCODE"
            Write-Err2 "If this is a network/firewall issue, you can download the repo manually:"
            Write-Err2 "  https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/archive/refs/heads/$Branch.zip"
            throw "git clone failed with exit code $LASTEXITCODE"
        }
        Write-Ok "Cloned to $repoPath"
    }
} else {
    Write-Warn2 'Skipping clone per -SkipClone'
}

# ---------------------------------------------------------------------------
# 5b. Deferred pip install (if requirements.txt was not available pre-clone)
# ---------------------------------------------------------------------------
if ($deferPip) {
    $requirementsFile = Join-Path $repoPath 'solutions\ess-maker-skills\scripts\requirements.txt'
    if (Test-Path $requirementsFile) {
        Write-Step 'Installing Python pip dependencies (deferred)'
        $pythonExe = Resolve-Python
        if ($pythonExe) {
            $null = Install-PipRequirements -PythonExe $pythonExe -RequirementsFile $requirementsFile
        } else {
            Write-Warn2 'Python still not found. Run: pip install -r solutions/ess-maker-skills/scripts/requirements.txt'
        }
    } else {
        Write-Warn2 'requirements.txt not found in cloned repo - pip dependencies not installed'
    }
}

# ---------------------------------------------------------------------------
# 5c. ESS Maker Profile (chat-first VS Code layout)
# ---------------------------------------------------------------------------
# The bundled extension at tools/ess-maker-profile/extension/ hides developer
# chrome and surfaces a big-button "Quick actions" rail tied to the kit's
# slash commands. We install it from the cloned repo (not the marketplace -
# this is a POC build that isn't published) so it auto-activates the next
# time `code` launches. When the maker profile is installed, the extension
# itself opens chat and injects /setup (section 7 just opens the workspace).
#
# Skipped in FlightCheckOnly mode (no VS Code launch) and when the user
# passes -SkipExtensions (IT-locked-down boxes that block VSIX installs).
if (-not $FlightCheckOnly -and -not $SkipExtensions) {
    # Install the ESS Maker Profile extension in both modes. In lite mode it
    # applies the chat-first layout; in standard mode it only handles /setup
    # injection after the welcome wizard closes (no visual changes).
    $modeLabel = if ($SkipMakerProfile) { 'standard' } else { 'lite' }
    Write-Step "Installing ESS Maker Profile ($modeLabel mode)"

    $code = Get-Command code -ErrorAction SilentlyContinue
    if (-not $code) {
        $knownCodeCmd = Join-Path $env:LOCALAPPDATA 'Programs\Microsoft VS Code\bin\code.cmd'
        if (Test-Path $knownCodeCmd) { $code = Get-Item $knownCodeCmd }
    }
    $codeBin = if ($code.Source) { $code.Source } elseif ($code.FullName) { $code.FullName } else { $null }
    if (-not $codeBin) {
        Write-Warn2 'code CLI not on PATH. ESS Maker Profile will not be installed.'
        Write-Warn2 'To install it later, open a new PowerShell and run:'
        Write-Warn2 "  code --install-extension `"$repoPath\tools\ess-maker-profile\extension\ess-maker-profile-*.vsix`""
    } else {
        # Glob so a version bump (0.4.0 -> 0.5.0) doesn't break the install.
        $vsixDir = Join-Path $repoPath 'tools\ess-maker-profile\extension'
        $vsix = $null
        if (Test-Path $vsixDir) {
            $vsix = Get-ChildItem -Path $vsixDir -Filter 'ess-maker-profile-*.vsix' -ErrorAction SilentlyContinue |
                    Sort-Object LastWriteTime -Descending |
                    Select-Object -First 1
        }

        if (-not $vsix) {
            Write-Warn2 "No ess-maker-profile-*.vsix found under $vsixDir. Skipping extension install."
        } else {
            $out = $null
            $vsix_exit = 0
            try {
                $prevEAP = $ErrorActionPreference
                $ErrorActionPreference = 'Continue'
                $out = & $codeBin --install-extension $vsix.FullName --force 2>&1
                $vsix_exit = $LASTEXITCODE
            } catch {
                $out = $_.Exception.Message
                $vsix_exit = if ($LASTEXITCODE) { $LASTEXITCODE } else { 1 }
            } finally {
                $ErrorActionPreference = $prevEAP
            }

            if ($vsix_exit -eq 0) {
                Write-Ok "ESS Maker Profile installed ($($vsix.Name)) - $modeLabel mode"
            } else {
                Write-Warn2 "ess-maker-profile vsix install returned exit $vsix_exit (non-fatal)"
                ($out | Out-String).TrimEnd() -split "`r?`n" | ForEach-Object { Write-Warn2 "  $_" }
            }
        }

        # Write the mode setting so the extension knows whether to apply
        # the lite layout or inject /setup (standard mode).
        # Uses string manipulation to preserve JSONC comments in settings.json.
        $settingsDir = Join-Path $env:APPDATA 'Code\User'
        if (-not (Test-Path $settingsDir)) { New-Item -ItemType Directory -Path $settingsDir -Force | Out-Null }
        $settingsFile = Join-Path $settingsDir 'settings.json'
        $modeEntry = "`"essMaker.mode`": `"$modeLabel`""
        if (Test-Path $settingsFile) {
            $raw = Get-Content $settingsFile -Raw
            if ($raw -match '"essMaker\.mode"\s*:') {
                # Update existing key in place
                $raw = $raw -replace '"essMaker\.mode"\s*:\s*"[^"]*"', $modeEntry
            } elseif ($raw -match '^\s*\{') {
                # Insert after opening brace
                $raw = $raw -replace '^\s*\{', "{ $modeEntry,"
            } else {
                # Malformed - create fresh
                $raw = "{ $modeEntry }"
            }
            Set-Content -Path $settingsFile -Value $raw -Encoding UTF8 -NoNewline
        } else {
            Set-Content -Path $settingsFile -Value "{ $modeEntry }" -Encoding UTF8 -NoNewline
        }
    }
}

# ---------------------------------------------------------------------------
# 6. FlightCheck config generation (FlightCheckOnly mode)
# ---------------------------------------------------------------------------
$workspace = Join-Path $repoPath 'solutions\ess-maker-skills'
if (-not (Test-Path $workspace)) {
    Write-Warn2 "Expected workspace not found: $workspace"
    Write-Warn2 'Repo layout may have changed. Opening repo root instead.'
    $workspace = $repoPath
}

if ($FlightCheckOnly) {
    Write-Step 'Configuring FlightCheck environment'

    $localDir = Join-Path $workspace '.local'
    $configPath = Join-Path $localDir 'config.json'

    # Resolve python command early - needed for both discovery and fetch
    $pythonExe = Resolve-Python
    if (-not $pythonExe) {
        throw 'Python not found on PATH or known locations. Cannot run FlightCheck.'
    }
    if ($pythonExe -eq 'py -3.12') {
        $pyCmd = 'py'; $pyBaseArgs = @('-3.12')
    } elseif ($pythonExe -eq 'py -3') {
        $pyCmd = 'py'; $pyBaseArgs = @('-3')
    } else {
        $pyCmd = $pythonExe; $pyBaseArgs = @()
    }

    if (Test-Path $configPath) {
        Write-Host ''
        Write-Host "    Config already exists at $configPath" -ForegroundColor White
        Write-Host '    Would you like to reconfigure? (Y/N)' -ForegroundColor Gray
        Write-Host ''
        $reconfigure = Read-Host '    Reconfigure'
        if ($reconfigure -notmatch '^[Yy]') {
            Write-Ok 'Keeping existing config'
        } else {
            Remove-Item $configPath -Force
            Write-Ok 'Removed existing config - starting fresh'
        }
    }

    # --- Account selection: offer to clear cached MSAL tokens ---
    # Runs before BOTH the discover.py auth (when reconfiguring) and the
    # FlightCheck run (which also authenticates via cli.py), so a single
    # prompt covers every code path that hits the MSAL cache.
    # All FlightCheck clients share .local/.token_cache.bin. The cached
    # tokens silently sign the next run in as whichever user authenticated
    # last - desirable most of the time, but bites users who installed
    # under one account and now need to FlightCheck a different tenant /
    # different user (e.g. customer-engineer scenarios). Offer an explicit
    # switch rather than making them hunt for the cache file.
    $tokenCacheFile = Join-Path $localDir '.token_cache.bin'
    if (Test-Path $tokenCacheFile) {
        # Force array context with @(...) - Get-CachedUsernames returns a
        # [string[]] guarded by the unary comma operator, but belt-and-
        # suspenders here in case the function output ever changes.
        $cachedUsers = @(Get-CachedUsernames -CachePath $tokenCacheFile)
        Write-Host ''
        if ($cachedUsers.Count -eq 1) {
            Write-Host "    Existing sign-in detected: $($cachedUsers[0])" -ForegroundColor White
        } elseif ($cachedUsers.Count -gt 1) {
            Write-Host '    Existing sign-in detected for:' -ForegroundColor White
            foreach ($u in $cachedUsers) {
                Write-Host "      - $u" -ForegroundColor White
            }
        } else {
            # Cache present but couldn't read the username (corrupt JSON,
            # schema change, etc.). Fall back to the generic message.
            Write-Host '    Existing sign-in detected from a previous session.' -ForegroundColor White
        }
        Write-Host '    Sign in as a different account? (y/N)' -ForegroundColor Gray
        $switchAccount = Read-Host '    Switch account'
        if ($switchAccount -match '^[Yy]') {
            try {
                Remove-Item $tokenCacheFile -Force
                Write-Ok 'Cleared sign-in cache - you will be prompted to sign in fresh'
                Write-Host '    Tip: your browser may auto-SSO into the previous account.' -ForegroundColor DarkGray
                Write-Host '          If so, sign out at https://login.microsoftonline.com' -ForegroundColor DarkGray
                Write-Host '          or use an InPrivate/Incognito browser window.' -ForegroundColor DarkGray
            } catch {
                Write-Warn2 "Could not remove token cache at $tokenCacheFile - $($_.Exception.Message)"
                Write-Warn2 'Continuing with cached sign-in.'
            }
        } else {
            Write-Ok 'Using cached sign-in'
        }
    }

    if (-not (Test-Path $configPath)) {
        $scriptsDir = Join-Path $workspace 'scripts'
        $discoverPy = Join-Path $scriptsDir 'discover.py'

        if (-not (Test-Path $discoverPy)) {
            throw "discover.py not found at $discoverPy. Was the repo cloned correctly?"
        }

        # --- Step 1: List environments and let user pick ---
        Write-Host ''
        Write-Host '    Listing Power Platform environments in your tenant...' -ForegroundColor White
        Write-Host '    A browser window will open for sign-in.' -ForegroundColor Gray
        Write-Host ''

        # Run discover.py --list-environments (interactive - shows table to user)
        Push-Location $workspace
        try {
            $discoverArgs = $pyBaseArgs + @($discoverPy, '--list-environments')
            $output = Invoke-Native { & $pyCmd @discoverArgs }
            foreach ($line in $output) { Write-Host $line }
            if ($LASTEXITCODE -ne 0) {
                throw 'Environment listing failed.'
            }

            Write-Host ''
            $envChoice = Read-Host '    Select environment number from the list above'
            if ($envChoice) { $envChoice = $envChoice.Trim() }
            if (-not $envChoice -or $envChoice -notmatch '^\d+$') {
                throw 'Invalid selection. Please re-run and pick a number from the list.'
            }

            # Re-run with --select to get machine-parseable JSON
            $selectArgs = $pyBaseArgs + @($discoverPy, '--list-environments', '--select', $envChoice)
            $envOutput = Invoke-Native { & $pyCmd @selectArgs }
            if ($LASTEXITCODE -ne 0) {
                throw "Environment selection failed: $envOutput"
            }
            $envJsonLine = ($envOutput | Where-Object { $_ -match '^SELECTED_ENV_JSON:' }) -replace '^SELECTED_ENV_JSON:', ''
            if (-not $envJsonLine) {
                throw 'Could not parse environment selection output.'
            }
            $selectedEnv = $envJsonLine | ConvertFrom-Json
            $envUrl = $selectedEnv.instanceUrl.TrimEnd('/')

            if (-not $envUrl) {
                throw 'Selected environment has no linked Dataverse URL.'
            }
            Write-Ok "Environment: $($selectedEnv.displayName)"
            Write-Ok "URL: $envUrl"

            # --- Step 2: List agents and let user pick ---
            Write-Host ''
            Write-Host '    Discovering agents in this environment...' -ForegroundColor White
            Write-Host ''

            $agentListArgs = $pyBaseArgs + @($discoverPy, '--url', $envUrl)
            $output = Invoke-Native { & $pyCmd @agentListArgs }
            foreach ($line in $output) { Write-Host $line }
            if ($LASTEXITCODE -ne 0) {
                Write-Warn2 'Agent discovery failed. Config will be created without a bot ID.'
                $botId = ''
                $agentName = 'FlightCheck-only (no agent selected)'
                $schemaName = ''
                $isManaged = $true
            } else {
                Write-Host ''
                $agentChoice = Read-Host '    Select agent number (or press Enter to run environment-wide checks only)'
                if ($agentChoice) { $agentChoice = $agentChoice.Trim() }

                if ($agentChoice -and $agentChoice -match '^\d+$') {
                    $agentSelectArgs = $pyBaseArgs + @($discoverPy, '--url', $envUrl, '--select', $agentChoice)
                    $agentOutput = Invoke-Native { & $pyCmd @agentSelectArgs }
                    if ($LASTEXITCODE -ne 0) {
                        Write-Warn2 "Agent selection failed. Continuing without bot ID."
                        $botId = ''
                        $agentName = 'FlightCheck-only (no agent selected)'
                        $schemaName = ''
                        $isManaged = $true
                    } else {
                        $agentJsonLine = ($agentOutput | Where-Object { $_ -match '^SELECTED_AGENT_JSON:' }) -replace '^SELECTED_AGENT_JSON:', ''
                        if ($agentJsonLine) {
                            $selectedAgent = $agentJsonLine | ConvertFrom-Json
                            $botId = $selectedAgent.botid
                            $agentName = $selectedAgent.name
                            $schemaName = $selectedAgent.schemaname
                            $isManaged = [bool]$selectedAgent.ismanaged
                            Write-Ok "Agent: $agentName"
                        } else {
                            $botId = ''
                            $agentName = 'FlightCheck-only (no agent selected)'
                            $schemaName = ''
                            $isManaged = $true
                        }
                    }
                } else {
                    Write-Warn2 'Skipping agent selection. Some agent-specific checks will be skipped.'
                    $botId = ''
                    $agentName = 'FlightCheck-only (no agent selected)'
                    $schemaName = ''
                    $isManaged = $true
                }
            }
        } finally { Pop-Location }

        # Create .local directory
        if (-not (Test-Path $localDir)) {
            New-Item -ItemType Directory -Path $localDir -Force | Out-Null
        }

        # Write minimal config.json sufficient for FlightCheck
        $slug = 'flightcheck-only'
        $agentEntry = @{
            name       = $agentName
            botId      = $botId
            schemaName = $schemaName
            isManaged  = $isManaged
            slug       = $slug
            folder     = ''
        }

        # Match the structure setup.py produces: agents array + activeAgent slug
        if ($botId) {
            $agentsList = [System.Collections.ArrayList]@()
            $agentsList.Add($agentEntry) | Out-Null
        } else {
            $agentsList = [System.Collections.ArrayList]@()
        }

        $config = @{
            configVersion      = 1
            setup              = 'flightcheck-only'
            dataverseEndpoint  = $envUrl
            flightCheckOnly    = $true
            agent              = $agentEntry
            agents             = $agentsList
            activeAgent        = if ($botId) { $slug } else { '' }
        }

        $json = $config | ConvertTo-Json -Depth 4 -Compress:$false
        [System.IO.File]::WriteAllText($configPath, $json, (New-Object System.Text.UTF8Encoding $false))
        Write-Ok "Created $configPath"
    }

    # --- Read config values if they came from an existing file ---
    if (-not $botId -and (Test-Path $configPath)) {
        $existingConfig = Get-Content $configPath -Raw | ConvertFrom-Json
        $envUrl = $existingConfig.dataverseEndpoint
        $botId = $existingConfig.agent.botId
        $agentName = $existingConfig.agent.name
        $schemaName = $existingConfig.agent.schemaName
        $isManaged = $existingConfig.agent.isManaged
    }

    # --- Fetch solution snapshot for local file checks ---
    if ($botId) {
        Write-Step 'Fetching agent solution from Dataverse'
        $fetchPy = Join-Path $workspace 'scripts\fetch_and_setup.py'
        if (Test-Path $fetchPy) {
            Push-Location $workspace
            try {
                $fetchArgs = $pyBaseArgs + @(
                    $fetchPy,
                    '--url', $envUrl,
                    '--bot-id', $botId,
                    '--name', $agentName,
                    '--schema', $schemaName
                )
                if ($isManaged) { $fetchArgs += '--managed' }

                Start-Spinner "fetching agent solution"
                $fetchOutput = & $pyCmd @fetchArgs 2>&1
                $fetchExit = $LASTEXITCODE
                Stop-Spinner "fetching agent solution"

                if ($fetchExit -eq 0) {
                    Write-Ok 'Agent solution fetched and extracted'
                } else {
                    Write-Warn2 'fetch_and_setup.py exited with errors. Local file checks may be skipped.'
                    foreach ($line in $fetchOutput) { Write-Host "      $line" }
                }
            } finally { Pop-Location }
        } else {
            Write-Warn2 "fetch_and_setup.py not found at $fetchPy. Local file checks will be skipped."
        }
    } else {
        Write-Host ''
        Write-Host '    [info] No agent selected - skipping solution fetch (local file checks will be skipped).' -ForegroundColor Gray
    }

    # --- Run FlightCheck ---
    Write-Step 'Running FlightCheck'
    $pythonExe = Resolve-Python
    if ($pythonExe) {
        Push-Location $workspace
        try {
            # Run FlightCheck with EAP=Continue so stderr doesn't terminate,
            # but let output stream directly to console (FlightCheck is interactive)
            $prevEAP = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            if ($pythonExe -eq 'py -3.12') {
                & py -3.12 scripts/flightcheck/cli.py --scope full --invocation-source installer
            } elseif ($pythonExe -eq 'py -3') {
                & py -3 scripts/flightcheck/cli.py --scope full --invocation-source installer
            } else {
                & $pythonExe scripts/flightcheck/cli.py --scope full --invocation-source installer
            }
            $ErrorActionPreference = $prevEAP
        } finally { Pop-Location }
    } else {
        Write-Warn2 'Python not found. Open a new terminal and run:'
        Write-Warn2 "  cd $workspace"
        Write-Warn2 '  python scripts/flightcheck/cli.py --scope full'
    }
    # ``return`` (not ``exit 0``) so the script ends without terminating
    # the PowerShell host. When this installer is invoked via
    # ``iex (irm .../bootstrap-flightcheck.ps1)`` from an interactive
    # shell, ``exit`` closes the user's terminal window; ``return`` just
    # stops the script and leaves ``$LASTEXITCODE`` from ``cli.py``
    # available to the calling session.
    return
}

# ---------------------------------------------------------------------------
# 7. Launch
# ---------------------------------------------------------------------------
if (-not $SkipLaunch) {
    $code = Get-Command code -ErrorAction SilentlyContinue
    if (-not $code) {
        $knownCodeCmd = Join-Path $env:LOCALAPPDATA 'Programs\Microsoft VS Code\bin\code.cmd'
        if (Test-Path $knownCodeCmd) { $code = Get-Item $knownCodeCmd }
    }
    $codePath = if ($code.Source) { $code.Source } elseif ($code.FullName) { $code.FullName } else { $null }
    if ($codePath) {
        # Launch strategy depends on mode:
        # - Lite mode: just open the workspace. The ESS Maker Profile extension
        #   handles layout + /setup injection after the welcome wizard closes.
        # - Standard mode: use `code chat '/setup'` which opens Copilot Chat in
        #   the sidebar panel on the right (the standard chat experience).
        Push-Location $workspace
        try {
            if ($SkipMakerProfile) {
                # Standard mode - use code chat to open /setup in sidebar panel
                Write-Step 'Opening workspace in VS Code and requesting /setup in Copilot Chat'
                $chatOutput = Invoke-Native { & $codePath chat '/setup' }
                $chatExit = $LASTEXITCODE
                foreach ($line in $chatOutput) { if ($line) { Write-Host "      $line" } }
                if ($chatExit -ne 0) {
                    Write-Warn2 "'code chat' failed or is unsupported (exit $chatExit). Falling back to opening the workspace only."
                    Write-Warn2 "If you have an older VS Code (pre-1.102 / June 2025), update VS Code and re-run, or run /setup manually in Copilot Chat."
                    Start-Process -FilePath $codePath -ArgumentList @($workspace) | Out-Null
                    Write-Ok "Launched VS Code at $workspace"
                    Write-Host "Next: in VS Code, open Copilot Chat and run /setup to connect Dataverse." -ForegroundColor Green
                } else {
                    Write-Ok "Requested /setup in Copilot Chat at $workspace"
                    Write-Host "If VS Code prompts you to trust the workspace or sign in to GitHub/Copilot, accept those prompts and /setup will run." -ForegroundColor Yellow
                    Write-Host "If /setup does not start after trust/sign-in, open Copilot Chat manually and run /setup." -ForegroundColor Yellow
                }
            } else {
                # Lite mode - extension handles /setup after welcome wizard
                Write-Step 'Opening workspace in VS Code'
                Start-Process -FilePath $codePath -ArgumentList @('.') | Out-Null
                Write-Ok "Launched VS Code at $workspace"
                Write-Host "The ESS Maker Profile will run /setup in Copilot Chat after the welcome screen closes." -ForegroundColor Yellow
                Write-Host "If VS Code prompts you to trust the workspace, accept the prompt." -ForegroundColor Yellow
            }
        } finally { Pop-Location }
    } else {
        Write-Warn2 "code CLI not on PATH. Open this folder manually: $workspace"
        Write-Host "Next: in VS Code, open Copilot Chat and run /setup to connect Dataverse." -ForegroundColor Green
    }
} else {
    Write-Warn2 'Skipping launch per -SkipLaunch'
    Write-Host "Next: in VS Code, open Copilot Chat and run /setup to connect Dataverse." -ForegroundColor Green
}

Write-Host "`nDone. Workspace: $workspace" -ForegroundColor Green

# Record success here, at the end of the normal path (NOT in finally) so an
# interrupt (Ctrl+C bypasses catch) is never mislabeled as a successful install.
Complete-EssInstallTelemetry -Outcome 'success'

}
catch {
    Complete-EssInstallTelemetry -Outcome 'failure' -ErrorRecord $_
    throw
}
finally {
    # Safety net for cancellation: if neither success nor failure was recorded
    # above (Ctrl+C stops the pipeline and skips catch), record it as cancelled.
    # Idempotent: a no-op once any outcome has already been emitted.
    Complete-EssInstallTelemetry -Outcome 'cancelled'
}
