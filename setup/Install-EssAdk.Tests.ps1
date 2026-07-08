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
    [System.Management.Automation.Language.Parser]::ParseFile($installerPath, [ref]$tokens, [ref]$errors)
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
    [System.Management.Automation.Language.Parser]::ParseFile($bootstrapPath, [ref]$tokens, [ref]$errors)
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
    [System.Management.Automation.Language.Parser]::ParseFile($litePath, [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) { throw "Parse errors: $($errors[0].Message)" }
}

Test 'bootstrap-lite.ps1 does NOT pass SkipMakerProfile as an argument' {
    # It may mention SkipMakerProfile in a comment, but the actual args hash should not include it
    if ($liteSrc -match 'SkipMakerProfile\s*=\s*\$true') {
        throw 'bootstrap-lite.ps1 should not set SkipMakerProfile = $true'
    }
}

# Summary
Write-Host "`n$($passed + $failed) tests, $passed passed, $failed failed" -ForegroundColor $(if ($failed -gt 0) { 'Red' } else { 'Green' })
exit $(if ($failed -gt 0) { 1 } else { 0 })
