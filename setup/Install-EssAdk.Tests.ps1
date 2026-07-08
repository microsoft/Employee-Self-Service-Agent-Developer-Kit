<#
.SYNOPSIS
    Lightweight smoke tests for Install-EssAdk.ps1 logic.
    Run with: pwsh -File Install-EssAdk.Tests.ps1
#>

$ErrorActionPreference = 'Stop'
$passed = 0
$failed = 0

function Test([string]$Name, [scriptblock]$Block) {
    try {
        & $Block
        $script:passed++
        Write-Host "  [PASS] $Name" -ForegroundColor Green
    } catch {
        $script:failed++
        Write-Host "  [FAIL] $Name" -ForegroundColor Red
        Write-Host "    $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

# Load the installer source to validate syntax and extract logic
$installerPath = Join-Path $PSScriptRoot 'Install-EssAdk.ps1'
$src = Get-Content $installerPath -Raw

Write-Host "Install-EssAdk.ps1 validation:" -ForegroundColor Cyan

Test 'script parses without syntax errors' {
    $tokens = $null; $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile($installerPath, [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) {
        throw "Parse errors: $($errors[0].Message)"
    }
}

Test 'script declares SkipMakerProfile parameter' {
    if ($src -notmatch '\[switch\]\s*\$SkipMakerProfile') {
        throw 'SkipMakerProfile switch parameter not found'
    }
}

Test 'script declares SkipLaunch parameter' {
    if ($src -notmatch '\[switch\]\s*\$SkipLaunch') {
        throw 'SkipLaunch switch parameter not found'
    }
}

Test 'known VS Code path fallback exists' {
    if ($src -notmatch 'Programs\\Microsoft VS Code\\bin\\code\.cmd') {
        throw 'Known VS Code path fallback not found'
    }
}

Test 'code CLI fallback is used in extension install section' {
    # Check that section 4 (extensions) has the fallback
    if ($src -notmatch 'knownCodeCmd.*=.*LOCALAPPDATA.*Programs.*Microsoft VS Code') {
        throw 'Extension section does not use known-path fallback'
    }
}

Test 'code CLI fallback is used in launch section' {
    # The launch section (section 7) should also have the fallback
    $launchSection = ($src -split '# 7\. Launch')[1]
    if (-not $launchSection) { throw 'Could not find section 7' }
    if ($launchSection -notmatch 'knownCodeCmd') {
        throw 'Launch section does not use known-path fallback'
    }
}

Test 'non-git directory detection exists' {
    if ($src -notmatch '\.git.*directory|Test-Path.*\.git') {
        throw 'Non-git directory detection not found'
    }
}

Test 'extension installs in both modes (writes essMaker.mode setting)' {
    if ($src -notmatch "essMaker\.mode.*\`$modeLabel") {
        throw 'Mode setting write logic not found'
    }
}

# Validate bootstrap scripts
Write-Host "`nbootstrap.ps1:" -ForegroundColor Cyan

$bootstrapPath = Join-Path $PSScriptRoot 'bootstrap.ps1'
$bootstrapSrc = Get-Content $bootstrapPath -Raw

Test 'bootstrap.ps1 parses without errors' {
    $tokens = $null; $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile($bootstrapPath, [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) { throw "Parse errors: $($errors[0].Message)" }
}

Test 'bootstrap.ps1 passes SkipMakerProfile = $true' {
    if ($bootstrapSrc -notmatch 'SkipMakerProfile\s*=\s*\$true') {
        throw 'SkipMakerProfile not set to $true in standard bootstrap'
    }
}

Write-Host "`nbootstrap-lite.ps1:" -ForegroundColor Cyan

$litePath = Join-Path $PSScriptRoot 'bootstrap-lite.ps1'
$liteSrc = Get-Content $litePath -Raw

Test 'bootstrap-lite.ps1 parses without errors' {
    $tokens = $null; $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile($litePath, [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) { throw "Parse errors: $($errors[0].Message)" }
}

Test 'bootstrap-lite.ps1 does NOT pass SkipMakerProfile as an argument' {
    # It may mention SkipMakerProfile in a comment, but the actual args hash should not include it
    if ($liteSrc -match 'SkipMakerProfile\s*=\s*\$true') {
        throw 'bootstrap-lite.ps1 should not set SkipMakerProfile = $true'
    }
}

# ---------------------------------------------------------------------------
# Encoding safety - regression guard for the Windows PowerShell 5.1 crash.
#
# 5.1 decodes a no-BOM script as ANSI (CP1252), so any non-ASCII byte (e.g. an
# em-dash U+2014) is mangled and [ScriptBlock]::Create parsing fails with a
# cascade of "Unexpected token" errors. The 'parses without errors' tests above
# use the running PowerShell (7 in CI), which defaults to UTF-8 and therefore
# does NOT catch this - so we assert ASCII-only bytes directly (parser- and
# version-independent), and check the bootstraps decode as UTF-8 explicitly.
# See PR #185.
# ---------------------------------------------------------------------------
Write-Host "`nEncoding safety:" -ForegroundColor Cyan

Test 'all setup/*.ps1 are ASCII-only (Windows PowerShell 5.1 safe)' {
    $offenders = @()
    Get-ChildItem (Join-Path $PSScriptRoot '*.ps1') | ForEach-Object {
        $lines = [System.IO.File]::ReadAllLines($_.FullName, [System.Text.Encoding]::UTF8)
        for ($i = 0; $i -lt $lines.Count; $i++) {
            if ($lines[$i] -match '[^\x00-\x7F]') {
                $offenders += "$($_.Name):$($i + 1)"
            }
        }
    }
    if ($offenders.Count -gt 0) {
        throw "Non-ASCII characters found (replace with ASCII to keep the installer 5.1-safe): $($offenders -join ', ')"
    }
}

Test 'bootstraps read the fetched installer as UTF-8 explicitly' {
    foreach ($name in @('bootstrap.ps1', 'bootstrap-lite.ps1', 'bootstrap-flightcheck.ps1')) {
        $path = Join-Path $PSScriptRoot $name
        if (-not (Test-Path $path)) { continue }
        $text = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
        if ($text -notmatch 'ReadAllText\(\$installer,\s*\[System\.Text\.Encoding\]::UTF8\)') {
            throw "$name does not read the installer via [IO.File]::ReadAllText(`$installer, [System.Text.Encoding]::UTF8) - Get-Content -Raw can mis-decode under 5.1"
        }
    }
}

# ---------------------------------------------------------------------------
# Installer telemetry wiring (ADO 7557940)
# ---------------------------------------------------------------------------
Write-Host "`nInstaller telemetry wiring (Install-EssAdk.ps1):" -ForegroundColor Cyan

Test 'initializes installer telemetry after locating the emitter' {
    if ($src -notmatch 'Initialize-EssInstallTelemetry') { throw 'Initialize-EssInstallTelemetry call not found' }
    if ($src -notmatch 'ESS_INSTALL_TELEMETRY_LIB') { throw 'ESS_INSTALL_TELEMETRY_LIB lookup not found' }
}

Test 'defines no-op telemetry stubs when the emitter is absent (fail-open)' {
    if ($src -notmatch 'function Initialize-EssInstallTelemetry') { throw 'no-op stub fallback not found' }
}

Test 'derives installer mode (flightcheck | adk | lite)' {
    if ($src -notmatch "FlightCheckOnly.*'flightcheck'") { throw 'flightcheck mode not derived' }
    if ($src -notmatch "SkipMakerProfile.*'adk'") { throw 'adk mode not derived' }
}

Test 'Write-Step is hooked to emit a per-step telemetry event' {
    if ($src -notmatch 'Write-EssInstallStep\s+-Step\s+\(Get-EssStepKey') { throw 'Write-Step does not emit a telemetry step' }
}

Test 'main body is wrapped so a completion event is always emitted' {
    if ($src -notmatch "Complete-EssInstallTelemetry\s+-Outcome\s+'failure'") { throw 'failure completion not found' }
    if ($src -notmatch "Complete-EssInstallTelemetry\s+-Outcome\s+'success'") { throw 'success completion not found' }
    if ($src -notmatch '(?s)\btry\s*\{.*\}\s*catch\s*\{.*\}\s*finally\s*\{') { throw 'try/catch/finally wrapper not found' }
}

# --- Emitter files: existence, parse, and pure-function behaviour ----------
Write-Host "`nInstaller telemetry emitters:" -ForegroundColor Cyan

$psEmitter = Join-Path $PSScriptRoot 'telemetry/install-telemetry.ps1'
$shEmitter = Join-Path $PSScriptRoot 'telemetry/install-telemetry.sh'

Test 'PowerShell emitter exists and parses without errors' {
    if (-not (Test-Path $psEmitter)) { throw 'telemetry/install-telemetry.ps1 missing' }
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($psEmitter, [ref]$null, [ref]$errors) | Out-Null
    if ($errors.Count -gt 0) { throw "Parse errors: $($errors[0].Message)" }
}

Test 'bash emitter exists with a shebang' {
    if (-not (Test-Path $shEmitter)) { throw 'telemetry/install-telemetry.sh missing' }
    $first = (Get-Content $shEmitter -TotalCount 1)
    if ($first -notmatch '^#!') { throw 'bash emitter missing shebang' }
}

# Dot-source the PS emitter and exercise its pure (no-network) functions.
. $psEmitter

Test 'tenant class: the MS corp tenant is internal' {
    if ((Get-EssTelTenantClass -TenantId '72f988bf-86f1-41af-91ab-2d7cd011db47') -ne 'internal') { throw 'corp tenant not internal' }
}
Test 'tenant class: any other tenant is customer' {
    if ((Get-EssTelTenantClass -TenantId '11111111-1111-1111-1111-111111111111') -ne 'customer') { throw 'other tenant not customer' }
}
Test 'tenant class: an empty tenant is unknown' {
    if ((Get-EssTelTenantClass -TenantId '') -ne 'unknown') { throw 'empty tenant not unknown' }
}
Test 'scrub strips paths, urls, emails and guids' {
    $s = ConvertTo-EssTelScrubbed -Text 'boom C:\Users\x https://a.com/b user@contoso.com 72f988bf-86f1-41af-91ab-2d7cd011db47'
    if ($s -match 'C:\\Users' -or $s -match 'https://' -or $s -match '@contoso' -or $s -match '72f988bf') { throw "not scrubbed: $s" }
}
Test 'opt-out is honored via the ESS_ADK_TELEMETRY env var' {
    $old = $env:ESS_ADK_TELEMETRY
    try { $env:ESS_ADK_TELEMETRY = 'off'; if (Test-EssTelemetryEnabled) { throw 'should be disabled' } }
    finally { $env:ESS_ADK_TELEMETRY = $old }
}
Test 'envelope iKey uses the o: prefix of the token before the first dash' {
    if ((Get-EssTelEnvelopeIKey -FullIKey 'abc123-def-456') -ne 'o:abc123') { throw 'envelope ikey wrong' }
}

# --- macOS installer + all bootstraps wiring -------------------------------
Write-Host "`nmacOS installer + bootstrap telemetry wiring:" -ForegroundColor Cyan

$macInstaller = Get-Content (Join-Path $PSScriptRoot 'install-ess-adk.sh') -Raw

Test 'install-ess-adk.sh sources the emitter and initializes telemetry' {
    if ($macInstaller -notmatch 'ESS_INSTALL_TELEMETRY_LIB') { throw 'lib lookup missing' }
    if ($macInstaller -notmatch 'ess_tel_init') { throw 'ess_tel_init call missing' }
}
Test 'install-ess-adk.sh emits completion on exit via an EXIT trap' {
    if ($macInstaller -notmatch 'ess_tel_on_exit' -or $macInstaller -notmatch 'trap .* EXIT') { throw 'EXIT trap missing' }
}
Test 'install-ess-adk.sh step() emits a per-step telemetry event' {
    if ($macInstaller -notmatch 'ess_tel_step' -or $macInstaller -notmatch 'ess_step_key') { throw 'step hook missing' }
}

foreach ($bs in @('bootstrap.ps1', 'bootstrap-flightcheck.ps1', 'bootstrap-lite.ps1')) {
    $bsSrc = Get-Content (Join-Path $PSScriptRoot $bs) -Raw
    Test "$bs downloads the telemetry lib and sets ESS_INSTALL_TELEMETRY_LIB" {
        if ($bsSrc -notmatch 'install-telemetry\.ps1') { throw 'telemetry lib not downloaded' }
        if ($bsSrc -notmatch 'ESS_INSTALL_TELEMETRY_LIB') { throw 'env var not set' }
    }
}
foreach ($bs in @('bootstrap-mac.sh', 'bootstrap-flightcheck-mac.sh', 'bootstrap-lite-mac.sh')) {
    $bsSrc = Get-Content (Join-Path $PSScriptRoot $bs) -Raw
    Test "$bs downloads the telemetry lib and sets ESS_INSTALL_TELEMETRY_LIB" {
        if ($bsSrc -notmatch 'install-telemetry\.sh') { throw 'telemetry lib not downloaded' }
        if ($bsSrc -notmatch 'ESS_INSTALL_TELEMETRY_LIB') { throw 'env var not set' }
    }
}

# Summary
Write-Host "`n$($passed + $failed) tests, $passed passed, $failed failed" -ForegroundColor $(if ($failed -gt 0) { 'Red' } else { 'Green' })
exit $(if ($failed -gt 0) { 1 } else { 0 })
