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
        # Skip if already installed (avoids unnecessary winget calls + elevation prompts)
        if ($FlightCheckOnly) {
            $existing = if ($pkg.Cmd -eq 'python') { Resolve-Python } else { Get-Command $pkg.Cmd -ErrorAction SilentlyContinue }
            if ($existing) {
                Write-Ok "$($pkg.Name) (already installed)"
                continue
            }
        }

        Write-Host "    installing $($pkg.Name) ($($pkg.Id))"
        $wingetOutput = Invoke-Native {
            & winget install --id $pkg.Id `
                             --source winget `
                             --exact `
                             --silent `
                             --accept-package-agreements `
                             --accept-source-agreements `
                             --disable-interactivity
        }
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
    $requirementsFile = Join-Path $PSScriptRoot '..\solutions\ess-maker-skills\scripts\requirements.txt'
    if (-not (Test-Path $requirementsFile)) {
        Write-Warn2 'requirements.txt not yet available (pre-clone). Will install after clone.'
        $deferPip = $true
    } else {
        # Use Invoke-Native to avoid PS 5.1 stderr termination
        if ($pythonExe -eq 'py -3.12' -or $pythonExe -eq 'py -3') {
            $pyArgs = ($pythonExe -split ' ')[1]
            $pipOutput = Invoke-Native { & py $pyArgs -m pip install --quiet --disable-pip-version-check -r $requirementsFile }
        } else {
            $pipOutput = Invoke-Native { & $pythonExe -m pip install --quiet --disable-pip-version-check -r $requirementsFile }
        }
        foreach ($line in $pipOutput) { Write-Host "      $line" }
        if ($LASTEXITCODE -eq 0) {
            Write-Ok 'pip dependencies installed'
        } else {
            Write-Warn2 "pip install returned exit code $LASTEXITCODE (non-fatal, /setup will retry)"
        }
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

    # Prevent git from hanging waiting for credentials or host-key prompts
    $env:GIT_TERMINAL_PROMPT = '0'
    $env:GCM_INTERACTIVE = 'never'

    if (-not (Test-Path $InstallRoot)) {
        New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
    }

    if (Test-Path (Join-Path $repoPath '.git')) {
        Write-Ok "Repo already cloned at $repoPath - pulling latest"
        Push-Location $repoPath
        try {
            $gitOutput = Invoke-Native { & git fetch --quiet origin }
            foreach ($line in $gitOutput) { if ($line) { Write-Host "      $line" } }
            if ($LASTEXITCODE -ne 0) {
                Write-Warn2 "git fetch failed (exit $LASTEXITCODE). Continuing with local copy."
            } else {
                $gitOutput = Invoke-Native { & git checkout --quiet $Branch }
                foreach ($line in $gitOutput) { if ($line) { Write-Host "      $line" } }
                if ($LASTEXITCODE -ne 0) {
                    Write-Warn2 "git checkout $Branch failed (exit $LASTEXITCODE). Continuing on current branch."
                } else {
                    $gitOutput = Invoke-Native { & git pull --quiet --ff-only }
                    foreach ($line in $gitOutput) { if ($line) { Write-Host "      $line" } }
                    if ($LASTEXITCODE -ne 0) {
                        Write-Warn2 "git pull failed (exit $LASTEXITCODE). Continuing with local copy."
                    }
                }
            }
        } finally { Pop-Location }
    } else {
        $gitOutput = Invoke-Native { & git clone --branch $Branch --single-branch $RepoUrl $repoPath }
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
            if ($pythonExe -eq 'py -3.12' -or $pythonExe -eq 'py -3') {
                $pyArgs = ($pythonExe -split ' ')[1]
                $pipOutput = Invoke-Native { & py $pyArgs -m pip install --quiet --disable-pip-version-check -r $requirementsFile }
            } else {
                $pipOutput = Invoke-Native { & $pythonExe -m pip install --quiet --disable-pip-version-check -r $requirementsFile }
            }
            foreach ($line in $pipOutput) { Write-Host "      $line" }
            if ($LASTEXITCODE -eq 0) {
                Write-Ok 'pip dependencies installed'
            } else {
                Write-Warn2 "pip install returned exit code $LASTEXITCODE (non-fatal, /setup will retry)"
            }
        } else {
            Write-Warn2 'Python still not found. Run: pip install -r solutions/ess-maker-skills/scripts/requirements.txt'
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
        $pythonExe = Resolve-Python

        if (-not $pythonExe) {
            throw 'Python not found on PATH or known locations. Cannot run environment discovery.'
        }
        if (-not (Test-Path $discoverPy)) {
            throw "discover.py not found at $discoverPy. Was the repo cloned correctly?"
        }

        # Build the base python command components for consistent invocation
        if ($pythonExe -eq 'py -3.12') {
            $pyCmd = 'py'; $pyBaseArgs = @('-3.12')
        } elseif ($pythonExe -eq 'py -3') {
            $pyCmd = 'py'; $pyBaseArgs = @('-3')
        } else {
            $pyCmd = $pythonExe; $pyBaseArgs = @()
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
        $config = @{
            setup              = 'complete'
            dataverseEndpoint  = $envUrl
            flightCheckOnly    = $true
            agent              = $agentEntry
            agents             = if ($botId) { @(,$agentEntry) } else { @() }
            activeAgent        = if ($botId) { $slug } else { '' }
        }

        $json = $config | ConvertTo-Json -Depth 4
        [System.IO.File]::WriteAllText($configPath, $json, (New-Object System.Text.UTF8Encoding $false))
        Write-Ok "Created $configPath"
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
                & py -3.12 scripts/flightcheck/cli.py --scope full
            } elseif ($pythonExe -eq 'py -3') {
                & py -3 scripts/flightcheck/cli.py --scope full
            } else {
                & $pythonExe scripts/flightcheck/cli.py --scope full
            }
            $ErrorActionPreference = $prevEAP
        } finally { Pop-Location }
    } else {
        Write-Warn2 'Python not found. Open a new terminal and run:'
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
