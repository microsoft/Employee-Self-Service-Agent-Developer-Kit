<#
.SYNOPSIS
    Irreducible one-liner bootstrap for the ESS Agent Developer Kit.

.DESCRIPTION
    Downloads the winget config + installer script into a temp folder and runs them.
    Designed to be invoked from a single command (see README.md):

        iex (irm https://aka.ms/ess-adk-setup)

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
    [string] $SourceBaseUrl = 'https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/bootstrap'
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
$installerArgs = @{ Branch = $Branch }
if ($InstallRoot) { $installerArgs.InstallRoot = $InstallRoot }

& $installer @installerArgs
