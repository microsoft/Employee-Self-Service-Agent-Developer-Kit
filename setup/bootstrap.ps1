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

$installer = Join-Path $tempDir 'Install-EssAdk.ps1'

# Build argument list for the child process
$argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $installer, '-Branch', $Branch)
if ($InstallRoot) { $argList += @('-InstallRoot', $InstallRoot) }

# Launch in a child process with -ExecutionPolicy Bypass so the downloaded
# script runs even when the machine's policy is Restricted.
$proc = Start-Process powershell -ArgumentList $argList -Wait -PassThru -NoNewWindow
if ($proc.ExitCode -ne 0) {
    throw "Install-EssAdk.ps1 exited with code $($proc.ExitCode)"
}
