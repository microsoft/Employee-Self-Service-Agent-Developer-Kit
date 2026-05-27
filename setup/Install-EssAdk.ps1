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
      3. Installs the VS Code extensions required by the maker kit
         (GitHub.copilot, GitHub.copilot-chat, ms-python.python).
      4. Clones the Employee-Self-Service-Agent-Developer-Kit repo to a known
         location (default: $env:USERPROFILE\source\Employee-Self-Service-Agent-Developer-Kit).
      5. Opens the ess-maker-skills workspace in VS Code.

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
    [switch] $UseDsc
)

$ErrorActionPreference = 'Stop'

function Write-Step  { param([string]$m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok    { param([string]$m) Write-Host "    [ok]   $m" -ForegroundColor Green }
function Write-Warn2 { param([string]$m) Write-Host "    [warn] $m" -ForegroundColor Yellow }
function Write-Err2  { param([string]$m) Write-Host "    [err]  $m" -ForegroundColor Red }

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
if (-not $winget) {
    Write-Err2 'winget not found. Install "App Installer" from the Microsoft Store, then re-run.'
    throw 'winget is required.'
}
Write-Ok "winget at $($winget.Source)"

# ---------------------------------------------------------------------------
# 2. Toolchain install (winget)
# ---------------------------------------------------------------------------
Write-Step 'Installing toolchain via winget'

# Packages must match ess-adk-setup.winget.yaml. Keep these two in sync.
$packages = @(
    @{ Id = 'Microsoft.VisualStudioCode'; Name = 'Visual Studio Code' },
    @{ Id = 'Python.Python.3.12';         Name = 'Python 3.12'        },
    @{ Id = 'Microsoft.PowerShell';       Name = 'PowerShell 7'       },
    @{ Id = 'Git.Git';                    Name = 'Git for Windows'    },
    @{ Id = 'GitHub.cli';                 Name = 'GitHub CLI'         }
)

if ($UseDsc) {
    # Declarative path - requires `winget configure --enable` (one-time opt-in
    # that pulls DSC modules from the Microsoft Store). Provided for IT shops
    # that prefer the auditable YAML manifest.
    $configFile = Join-Path $PSScriptRoot 'ess-adk-setup.winget.yaml'
    if (-not (Test-Path $configFile)) {
        throw "Configuration file not found: $configFile"
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
        Write-Host "    installing $($pkg.Name) ($($pkg.Id))"
        & winget install --id $pkg.Id `
                         --source winget `
                         --exact `
                         --silent `
                         --accept-package-agreements `
                         --accept-source-agreements `
                         --disable-interactivity 2>&1 | ForEach-Object { Write-Host "      $_" }

        # winget exit codes:
        #   0                = installed OK
        #   -1978335189 (0x8A15002B) = APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE
        #                              ("No applicable update found" - already current)
        # Both mean "we're good", anything else is a real failure.
        $code = $LASTEXITCODE
        if ($code -eq 0 -or $code -eq -1978335189) {
            Write-Ok "$($pkg.Name)"
        } else {
            throw "winget install $($pkg.Id) failed with exit code $code"
        }
    }
}
Write-Ok 'Toolchain installed / verified'

# Refresh PATH in-process so newly-installed tools are callable
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
            [Environment]::GetEnvironmentVariable('Path','User')

# ---------------------------------------------------------------------------
# 3. VS Code extensions
# ---------------------------------------------------------------------------
if (-not $SkipExtensions) {
    Write-Step 'Installing VS Code extensions'

    $code = Get-Command code -ErrorAction SilentlyContinue
    if (-not $code) {
        Write-Warn2 'code CLI not on PATH yet. Open a new PowerShell window after this script and run:'
        Write-Warn2 '  code --install-extension GitHub.copilot'
        Write-Warn2 '  code --install-extension GitHub.copilot-chat'
        Write-Warn2 '  code --install-extension ms-python.python'
    } else {
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
                $out = & code --install-extension $ext --force 2>&1
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
# 4. Clone repo
# ---------------------------------------------------------------------------
$repoName = [IO.Path]::GetFileNameWithoutExtension(($RepoUrl -split '/')[-1])
$repoPath = Join-Path $InstallRoot $repoName

if (-not $SkipClone) {
    Write-Step "Cloning $RepoUrl"

    if (-not (Test-Path $InstallRoot)) {
        New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
    }

    if (Test-Path (Join-Path $repoPath '.git')) {
        Write-Ok "Repo already cloned at $repoPath - pulling latest"
        Push-Location $repoPath
        try {
            & git fetch --quiet origin
            & git checkout --quiet $Branch
            & git pull --quiet --ff-only
        } finally { Pop-Location }
    } else {
        & git clone --branch $Branch --single-branch $RepoUrl $repoPath
        if ($LASTEXITCODE -ne 0) {
            throw "git clone failed with exit code $LASTEXITCODE"
        }
        Write-Ok "Cloned to $repoPath"
    }
} else {
    Write-Warn2 'Skipping clone per -SkipClone'
}

# ---------------------------------------------------------------------------
# 5. Launch
# ---------------------------------------------------------------------------
$workspace = Join-Path $repoPath 'solutions\ess-maker-skills'
if (-not (Test-Path $workspace)) {
    Write-Warn2 "Expected workspace not found: $workspace"
    Write-Warn2 'Repo layout may have changed; opening repo root instead.'
    $workspace = $repoPath
}

if (-not $SkipLaunch) {
    Write-Step 'Opening workspace in VS Code'
    $code = Get-Command code -ErrorAction SilentlyContinue
    if ($code) {
        Start-Process -FilePath $code.Source -ArgumentList @($workspace) | Out-Null
        Write-Ok "Launched VS Code at $workspace"
    } else {
        Write-Warn2 "code CLI not on PATH. Open this folder manually: $workspace"
    }
} else {
    Write-Warn2 'Skipping launch per -SkipLaunch'
}

Write-Host "`nDone. Workspace: $workspace" -ForegroundColor Green
Write-Host "Next: in VS Code, open Copilot Chat and run /setup to connect Dataverse." -ForegroundColor Green
