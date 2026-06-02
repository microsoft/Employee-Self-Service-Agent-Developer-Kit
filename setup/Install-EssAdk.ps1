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
      6. Opens the ess-maker-skills workspace in VS Code.

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
    [switch] $FlightCheckOnly
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
if ($FlightCheckOnly) {
    # Minimal set: just Python + Git (no VS Code, PowerShell 7, or GH CLI)
    $packages = @(
        @{ Id = 'Python.Python.3.12'; Name = 'Python 3.12'     },
        @{ Id = 'Git.Git';            Name = 'Git for Windows' }
    )
} else {
    $packages = @(
        @{ Id = 'Microsoft.VisualStudioCode'; Name = 'Visual Studio Code' },
        @{ Id = 'Python.Python.3.12';         Name = 'Python 3.12'        },
        @{ Id = 'Microsoft.PowerShell';       Name = 'PowerShell 7'       },
        @{ Id = 'Git.Git';                    Name = 'Git for Windows'    },
        @{ Id = 'GitHub.cli';                 Name = 'GitHub CLI'         }
    )
}

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
                         --disable-interactivity 2>&1 | ForEach-Object {
            $line = "$_".Trim()
            # Skip empty lines, spinner frames, and progress bar garbage
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
            throw "winget install $($pkg.Id) failed with exit code $code"
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
$pip = Get-Command pip -ErrorAction SilentlyContinue
if (-not $pip) {
    # Try python -m pip as a fallback (pip not on PATH yet after fresh install)
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $requirementsFile = Join-Path $PSScriptRoot '..\solutions\ess-maker-skills\scripts\requirements.txt'
        if (-not (Test-Path $requirementsFile)) {
            # If running from a temp dir (bootstrap), the repo hasn't been cloned yet.
            # Defer pip install to after clone (section 5b below).
            Write-Warn2 'requirements.txt not yet available (pre-clone). Will install after clone.'
            $deferPip = $true
        } else {
            & $python.Source -m pip install --quiet --disable-pip-version-check -r $requirementsFile 2>&1 | ForEach-Object { Write-Host "      $_" }
            if ($LASTEXITCODE -eq 0) {
                Write-Ok 'pip dependencies installed'
            } else {
                Write-Warn2 "pip install returned exit code $LASTEXITCODE (non-fatal, /setup will retry)"
            }
            $deferPip = $false
        }
    } else {
        Write-Warn2 'python not on PATH yet. Pip dependencies will be installed when you run /setup.'
        $deferPip = $false
    }
} else {
    $requirementsFile = Join-Path $PSScriptRoot '..\solutions\ess-maker-skills\scripts\requirements.txt'
    if (-not (Test-Path $requirementsFile)) {
        Write-Warn2 'requirements.txt not yet available (pre-clone). Will install after clone.'
        $deferPip = $true
    } else {
        & $pip.Source install --quiet --disable-pip-version-check -r $requirementsFile 2>&1 | ForEach-Object { Write-Host "      $_" }
        if ($LASTEXITCODE -eq 0) {
            Write-Ok 'pip dependencies installed'
        } else {
            Write-Warn2 "pip install returned exit code $LASTEXITCODE (non-fatal, /setup will retry)"
        }
        $deferPip = $false
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
# 5. Clone repo
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
# 5b. Deferred pip install (if requirements.txt was not available pre-clone)
# ---------------------------------------------------------------------------
if ($deferPip) {
    $requirementsFile = Join-Path $repoPath 'solutions\ess-maker-skills\scripts\requirements.txt'
    if (Test-Path $requirementsFile) {
        Write-Step 'Installing Python pip dependencies (deferred)'
        $python = Get-Command python -ErrorAction SilentlyContinue
        if ($python) {
            & $python.Source -m pip install --quiet --disable-pip-version-check -r $requirementsFile 2>&1 | ForEach-Object { Write-Host "      $_" }
            if ($LASTEXITCODE -eq 0) {
                Write-Ok 'pip dependencies installed'
            } else {
                Write-Warn2 "pip install returned exit code $LASTEXITCODE (non-fatal, /setup will retry)"
            }
        } else {
            Write-Warn2 'python still not on PATH. Run: pip install -r solutions/ess-maker-skills/scripts/requirements.txt'
        }
    } else {
        Write-Warn2 'requirements.txt not found in cloned repo - pip dependencies not installed'
    }
}

# ---------------------------------------------------------------------------
# 6. FlightCheck config generation (FlightCheckOnly mode)
# ---------------------------------------------------------------------------
$workspace = Join-Path $repoPath 'solutions\ess-maker-skills'
if (-not (Test-Path $workspace)) {
    Write-Warn2 "Expected workspace not found: $workspace"
    Write-Warn2 'Repo layout may have changed; using repo root instead.'
    $workspace = $repoPath
}

if ($FlightCheckOnly) {
    Write-Step 'Configuring FlightCheck environment'

    $localDir = Join-Path $workspace '.local'
    $configPath = Join-Path $localDir 'config.json'

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

    if (-not (Test-Path $configPath)) {
        $scriptsDir = Join-Path $workspace 'scripts'
        $discoverPy = Join-Path $scriptsDir 'discover.py'
        $python = Get-Command python -ErrorAction SilentlyContinue

        if (-not $python) {
            throw 'python not found on PATH. Cannot run environment discovery.'
        }
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
            & $python.Source $discoverPy --list-environments
            if ($LASTEXITCODE -ne 0) {
                throw 'Environment listing failed.'
            }

            Write-Host ''
            $envChoice = Read-Host '    Select environment number from the list above'
            $envChoice = $envChoice.Trim()
            if (-not $envChoice -or $envChoice -notmatch '^\d+$') {
                throw 'Invalid selection. Please re-run and pick a number from the list.'
            }

            # Re-run with --select to get machine-parseable JSON
            $envOutput = & $python.Source $discoverPy --list-environments --select $envChoice 2>&1
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

            & $python.Source $discoverPy --url $envUrl
            if ($LASTEXITCODE -ne 0) {
                Write-Warn2 'Agent discovery failed. Config will be created without a bot ID.'
                $botId = ''
                $agentName = 'FlightCheck-only (no agent selected)'
                $schemaName = ''
                $isManaged = $true
            } else {
                Write-Host ''
                $agentChoice = Read-Host '    Select agent number (or press Enter to run environment-wide checks only)'
                $agentChoice = $agentChoice.Trim()

                if ($agentChoice -and $agentChoice -match '^\d+$') {
                    $agentOutput = & $python.Source $discoverPy --url $envUrl --select $agentChoice 2>&1
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
        $config = @{
            setup              = 'complete'
            dataverseEndpoint  = $envUrl
            flightCheckOnly    = $true
            agent              = @{
                name       = $agentName
                botId      = $botId
                schemaName = $schemaName
                isManaged  = $isManaged
                slug       = 'flightcheck-only'
                folder     = ''
            }
            agents             = @()
            activeAgent        = ''
        }

        $config | ConvertTo-Json -Depth 4 | Set-Content -Path $configPath -Encoding utf8
        Write-Ok "Created $configPath"
    }

    # --- Run FlightCheck ---
    Write-Step 'Running FlightCheck'
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        Push-Location $workspace
        try {
            & $python.Source scripts/flightcheck/cli.py --scope full
        } finally { Pop-Location }
    } else {
        Write-Warn2 'python not found on PATH. Open a new terminal and run:'
        Write-Warn2 "  cd $workspace"
        Write-Warn2 '  python scripts/flightcheck/cli.py --scope full'
    }
    exit 0
}

# ---------------------------------------------------------------------------
# 7. Launch
# ---------------------------------------------------------------------------
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
