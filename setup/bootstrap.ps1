<#
.SYNOPSIS
    Irreducible one-liner bootstrap for the ESS Agent Developer Kit.

.DESCRIPTION
    Downloads the winget config + installer script into a temp folder and runs them.
    Designed to be invoked from a single command (see README.md):

        iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap.ps1)

    All real work happens in Install-EssAdk.ps1; this file just gets the bits
    onto the customer's machine first.

.PARAMETER InstallRoot
    Forwarded to Install-EssAdk.ps1. See that script for details.

.PARAMETER Branch
    Forwarded to Install-EssAdk.ps1. Defaults to "main".

.PARAMETER SourceBaseUrl
    Where to fetch the installer files from. Defaults to the raw GitHub URL of
    this folder once it lands in the upstream repo. Override for testing.
#>

[CmdletBinding()]
param(
    [string] $InstallRoot,
    [string] $Branch = 'main',
    [string] $SourceBaseUrl = 'https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup'
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$tempDir = Join-Path $env:TEMP "ess-adk-bootstrap-$([Guid]::NewGuid().ToString('N').Substring(0,8))"
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

$files = @(
    'ess-adk-setup.winget.yaml',
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
        Write-Host "    .\setup\Install-EssAdk.ps1" -ForegroundColor Yellow
        throw $_
    }
}

# Best-effort: fetch the installer telemetry emitter (fail-open — a telemetry
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

$installerArgs = @{ Branch = $Branch; SkipMakerProfile = $true }
if ($InstallRoot) { $installerArgs.InstallRoot = $InstallRoot }

& $scriptBlock @installerArgs
