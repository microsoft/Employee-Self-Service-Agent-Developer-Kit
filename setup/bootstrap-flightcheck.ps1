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

.PARAMETER SourceBaseUrl
    Where to fetch the installer files from. Defaults to the raw GitHub URL of
    the setup folder. Override for testing.
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
    Invoke-WebRequest -Uri $url -OutFile $dst -UseBasicParsing
}

$installer = Join-Path $tempDir 'Install-EssAdk.ps1'
$installerArgs = @{ Branch = $Branch; FlightCheckOnly = $true }
if ($InstallRoot) { $installerArgs.InstallRoot = $InstallRoot }

& $installer @installerArgs
