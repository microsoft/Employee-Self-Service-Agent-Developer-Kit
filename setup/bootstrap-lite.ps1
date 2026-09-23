<#
.SYNOPSIS
    Back-compat one-liner bootstrap that pins the installer to Maker Mode
    (formerly known as "Lite Mode").

.DESCRIPTION
    Downloads the installer and runs it with -InstallMode maker. Kept so
    existing links (docs, blog posts, share sheets) that point at
    bootstrap-lite.ps1 keep working after the standard + lite installers
    were merged into a single bootstrap.ps1 and the modes were renamed
    from lite/standard to maker/developer.

    New customers should use bootstrap.ps1, which prompts inside VS Code
    on first launch to pick the experience. This shim is documented as
    a redirect only.

        iex (irm https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/main/setup/bootstrap-lite.ps1)

    All real work happens in Install-EssAdk.ps1; this file just gets the bits
    onto the customer's machine and pins the mode to maker (the chat-first
    experience).

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
    [string] $SourceBaseUrl
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

# Derive SourceBaseUrl from -Branch when not explicitly set, so `-Branch <feature>`
# actually pulls the installer bits from that feature branch (not from main).
if (-not $SourceBaseUrl) {
    $SourceBaseUrl = "https://raw.githubusercontent.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/$Branch/setup"
}

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

# Maker mode (was "Lite mode" before the rename): pass -InstallMode maker
# so the ESS Maker Profile applies the chat-first layout without asking the
# maker. Kept as a compat shim while the single bootstrap.ps1 becomes the
# recommended entry point.
$installerArgs = @{ Branch = $Branch; InstallMode = 'maker' }
if ($InstallRoot) { $installerArgs.InstallRoot = $InstallRoot }

& $scriptBlock @installerArgs
