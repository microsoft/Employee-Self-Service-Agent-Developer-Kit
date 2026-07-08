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

# Summary
Write-Host "`n$($passed + $failed) tests, $passed passed, $failed failed" -ForegroundColor $(if ($failed -gt 0) { 'Red' } else { 'Green' })
exit $(if ($failed -gt 0) { 1 } else { 0 })
