<#
.SYNOPSIS
    One-liner bootstrap for FlightCheck-only installation.

.DESCRIPTION
    Downloads the installer script into a temp folder and runs it with
    -FlightCheckOnly. Installs only Python + Git, pip dependencies, and
    walks through interactive environment/agent discovery.

    Designed to be invoked from a single command:

        iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-flightcheck.ps1)

    All real work happens in Install-EssAdk.ps1; this file just gets the bits
    onto the customer's machine and passes the -FlightCheckOnly flag.

.PARAMETER InstallRoot
    Forwarded to Install-EssAdk.ps1. See that script for details.

.PARAMETER Branch
    Forwarded to Install-EssAdk.ps1. Defaults to "main".

.PARAMETER FlightCheckScope
    Required validation scope. Prompts with no default when interactive.
    Also accepts FLIGHTCHECK_SCOPE. Explicit argument takes precedence.

.PARAMETER SourceBaseUrl
    Where to fetch the installer files from. Defaults to the raw GitHub URL of
    the setup folder. Override for testing.

.PARAMETER DaTargetUrl
    Explicit Copilot Studio DA URL. Requires FlightCheckScope full,
    AgentSchemaName and ValidationRealm; bypasses Dataverse discovery.

.PARAMETER AgentSchemaName
    Expected schema name for the explicit DA target.

.PARAMETER ValidationRealm
    Deployment realm (dev/test/prod), independent of the service Ring.
#>

[CmdletBinding()]
param(
    [string] $InstallRoot,
    [string] $Branch = 'main',
    [ValidateSet('prod', 'preprod', 'test')]
    [string] $Ring = 'prod',
    [string] $FlightCheckScope = $env:FLIGHTCHECK_SCOPE,
    [string] $DaTargetUrl,
    [string] $AgentSchemaName,
    [ValidateSet('dev', 'test', 'prod')]
    [string] $ValidationRealm,
    [string] $SourceBaseUrl
)

function Resolve-FlightCheckScope {
    param(
        [string] $Scope,
        [bool] $Interactive = (
            [Environment]::UserInteractive -and -not [Console]::IsInputRedirected -and
            -not ([Environment]::GetCommandLineArgs() -match '^-NonI(nteractive)?$')
        )
    )
    # Keep this preflight self-contained: bootstrap runs it before downloading.
    # Scope names mirror cli.py, not its separate litmus profiles.
    $scopes = [ordered]@{
        full = 'All applicable validation categories'
        prerequisites = 'Prerequisite access and setup'
        infrastructure = 'Infrastructure and connectivity'
        environment = 'Power Platform environment'
        solution = 'Installed solution configuration'
        authentication = 'Authentication configuration'
        entraapp = 'Microsoft Entra application'
        workdaytenant = 'Workday tenant configuration'
        external = 'External system configuration'
        workday = 'External system and Workday checks'
        workdayextension = 'Workday checks and extension'
        workdayda = 'Workday declarative-agent package'
        topics = 'Workday topics'
        graphconnector = 'External system and Graph connector knowledge'
        handoff = 'Agent handoff topics'
        servicenow = 'External system and ServiceNow checks'
        local = 'Local agent files'
        publishing = 'Agent publishing'
        licensing = 'Licensing'
        cloudpolicy = 'Cloud policies'
    }
    $instructions = 'Specify -FlightCheckScope <scope> or set FLIGHTCHECK_SCOPE. Full requires explicit selection.'
    if ([string]::IsNullOrWhiteSpace($Scope)) {
        if (-not $Interactive -or $env:CI -or $env:TF_BUILD -or $env:GITHUB_ACTIONS) {
            throw "FlightCheck scope is required for unattended installation. $instructions Allowed: $($scopes.Keys -join ', ')."
        }
        Write-Host 'Choose a FlightCheck scope (no default):'
        foreach ($name in $scopes.Keys) { Write-Host "  $name - $($scopes[$name])" }
        try { $Scope = Read-Host 'Enter a scope name' } catch {
            throw "FlightCheck scope input is unavailable. $instructions"
        }
    }
    if ([string]::IsNullOrWhiteSpace($Scope) -or -not $scopes.Contains($Scope.Trim().ToLowerInvariant())) {
        throw "A valid FlightCheck scope is required; empty input does not select Full. $instructions Allowed: $($scopes.Keys -join ', ')."
    }
    return $Scope.Trim().ToLowerInvariant()
}

$FlightCheckScope = Resolve-FlightCheckScope -Scope $FlightCheckScope
if ($DaTargetUrl -or $AgentSchemaName -or $ValidationRealm) {
    if ($FlightCheckScope -ne 'full' -or -not $DaTargetUrl -or
        -not $AgentSchemaName.Trim() -or -not $ValidationRealm) {
        throw 'DA onboarding requires -FlightCheckScope full -DaTargetUrl <url> -AgentSchemaName <schema> -ValidationRealm <dev|test|prod>.'
    }
}

# Derive SourceBaseUrl from $Branch so that passing -Branch also fetches the
# installer files from that branch. If we hardcoded the default to `main` the
# `-Branch <fix>` path would download Install-EssAdk.ps1 from main and never
# exercise the fix - a footgun for anyone testing a branch end-to-end via the
# customer-facing one-liner. Explicit -SourceBaseUrl still wins.
if (-not $SourceBaseUrl) {
    $SourceBaseUrl = "https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/$Branch/setup"
}

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$tempDir = Join-Path $env:TEMP "ess-adk-bootstrap-$([Guid]::NewGuid().ToString('N').Substring(0,8))"
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

$files = @(
    'Install-EssAdk.ps1'
)

Write-Host "Fetching ESS ADK bootstrap files to $tempDir" -ForegroundColor Cyan
foreach ($f in $files) {
    $url = "$SourceBaseUrl/$f"
    $dst = Join-Path $tempDir $f
    Write-Host "  $url"
    try {
        Invoke-WebRequest -Uri $url -OutFile $dst -UseBasicParsing -TimeoutSec 60
    } catch {
        Write-Host "  [ERR] Failed to download: $url" -ForegroundColor Red
        Write-Host "  If raw.githubusercontent.com is blocked by your firewall/proxy," -ForegroundColor Yellow
        Write-Host "  download the repo manually and run:" -ForegroundColor Yellow
        Write-Host "    .\setup\Install-EssAdk.ps1 -FlightCheckOnly" -ForegroundColor Yellow
        throw $_
    }
}

# Best-effort: fetch the installer telemetry emitter (fail-open - a telemetry
# download failure must never block the install).
$telLib = Join-Path $tempDir 'install-telemetry.ps1'
try {
    Invoke-WebRequest -Uri "$SourceBaseUrl/telemetry/install-telemetry.ps1" -OutFile $telLib -UseBasicParsing -TimeoutSec 30
    $env:ESS_INSTALL_TELEMETRY_LIB = $telLib
} catch {
    Write-Host "  [warn] Installer telemetry unavailable (continuing)" -ForegroundColor DarkYellow
}

$installer = Join-Path $tempDir 'Install-EssAdk.ps1'

# Run the installer in-memory (as a script block) so execution policy never
# applies - the script content is never "executed from disk". Read as UTF-8
# explicitly: Windows PowerShell 5.1 otherwise decodes a no-BOM file as ANSI
# (CP1252), which mangles any non-ASCII byte and breaks ScriptBlock parsing.
$scriptContent = [System.IO.File]::ReadAllText($installer, [System.Text.Encoding]::UTF8)
$scriptBlock = [ScriptBlock]::Create($scriptContent)

$installerArgs = @{ Branch = $Branch; FlightCheckOnly = $true; FlightCheckScope = $FlightCheckScope }
if ($DaTargetUrl) {
    $installerArgs.DaTargetUrl = $DaTargetUrl
    $installerArgs.AgentSchemaName = $AgentSchemaName
    $installerArgs.ValidationRealm = $ValidationRealm.ToLowerInvariant()
}
if ($PSBoundParameters.ContainsKey('Ring')) { $installerArgs.Ring = $Ring }
if ($InstallRoot) { $installerArgs.InstallRoot = $InstallRoot }

& $scriptBlock @installerArgs
