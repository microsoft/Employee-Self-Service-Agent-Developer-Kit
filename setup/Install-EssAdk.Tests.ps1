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

Test 'script declares InstallMode parameter' {
    if ($src -notmatch "\[string\]\s*\`$InstallMode\s*=\s*'prompt'") {
        throw 'InstallMode parameter with prompt default not found'
    }
    if ($src -notmatch "ValidateSet\('maker',\s*'developer',\s*'prompt'") {
        throw "InstallMode ValidateSet should start with the canonical 'maker','developer','prompt' triple"
    }
    # Legacy aliases 'lite'/'standard' remain in the ValidateSet so old
    # bootstrap-lite invocations and any pinned CI script don't blow up
    # under the rename.
    if ($src -notmatch "ValidateSet\('maker',\s*'developer',\s*'prompt',\s*'lite',\s*'standard'\)") {
        throw "InstallMode ValidateSet should also accept legacy 'lite','standard' values"
    }
}

Test 'script declares SkipMakerProfile parameter (back-compat)' {
    if ($src -notmatch '\[switch\]\s*\$SkipMakerProfile') {
        throw 'SkipMakerProfile switch parameter not found'
    }
}

Test 'SkipMakerProfile forces InstallMode developer for back-compat' {
    if ($src -notmatch 'if\s*\(\$SkipMakerProfile\)\s*\{\s*\$InstallMode\s*=\s*''developer''\s*\}') {
        throw 'SkipMakerProfile back-compat coercion to InstallMode=developer not found'
    }
}

Test 'legacy InstallMode values (lite/standard) are coerced to maker/developer' {
    if ($src -notmatch "if\s*\(\`$InstallMode\s+-eq\s+'lite'\)\s*\{\s*\`$InstallMode\s*=\s*'maker'\s*\}") {
        throw "legacy 'lite' -> 'maker' coercion missing"
    }
    if ($src -notmatch "if\s*\(\`$InstallMode\s+-eq\s+'standard'\)\s*\{\s*\`$InstallMode\s*=\s*'developer'\s*\}") {
        throw "legacy 'standard' -> 'developer' coercion missing"
    }
}

Test 'InstallMode=prompt fires a terminal Maker/Developer prompt (not a VS Code QuickPick)' {
    # Historically we tried to ask the mode question from inside VS Code
    # via a QuickPick, but that surface competes with the theme picker and
    # Copilot sign-in on first launch and reliably loses the race. The
    # installer now asks the question in the terminal before handing off
    # to VS Code so the answer is deterministic.
    if ($src -notmatch "if\s*\(\`$InstallMode\s+-eq\s+'prompt'\)") {
        throw 'no prompt branch guarding InstallMode=prompt'
    }
    if ($src -notmatch 'Read-Host') { throw 'terminal prompt must use Read-Host' }
    if ($src -notmatch 'Maker \(recommended\)') { throw 'Maker option label missing from prompt copy' }
    if ($src -notmatch '\[2\] Developer') { throw 'Developer option label missing from prompt copy' }
}

Test 'InstallMode=prompt defaults to maker under non-interactive stdin / CI' {
    if ($src -notmatch 'IsInputRedirected') {
        throw 'non-interactive detection (Console::IsInputRedirected) missing'
    }
    if ($src -notmatch '\$env:CI') { throw 'CI env-var non-interactive guard missing' }
    if ($src -notmatch 'Defaulting to Maker mode') {
        throw 'non-interactive branch should default to Maker mode with a visible message'
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

Test 'shared code CLI resolver is used in extension install section' {
    $extensionSection = ($src -split '# 4\. VS Code extensions')[1] -split '# 5\. Clone repo' | Select-Object -First 1
    if (-not $extensionSection) { throw 'Could not find section 4' }
    if ($extensionSection -notmatch '\$code\s*=\s*Resolve-CodeCommand') {
        throw 'Extension section does not use Resolve-CodeCommand'
    }
}

Test 'shared code CLI resolver is used in launch section' {
    $launchSection = ($src -split '# 7\. Launch')[1]
    if (-not $launchSection) { throw 'Could not find section 7' }
    if ($launchSection -notmatch '\$code\s*=\s*Resolve-CodeCommand') {
        throw 'Launch section does not use Resolve-CodeCommand'
    }
}

Test 'non-git directory detection exists' {
    if ($src -notmatch '\.git.*directory|Test-Path.*\.git') {
        throw 'Non-git directory detection not found'
    }
}

Test 'extension installs in every mode (writes essMaker.mode setting from resolved $modeLabel)' {
    if ($src -notmatch "essMaker\.mode.*\`$settingsModeValue") {
        throw 'Mode setting write logic (uses $settingsModeValue) not found'
    }
    if ($src -notmatch '\$settingsModeValue\s*=\s*\$modeLabel') {
        throw '$settingsModeValue should be assigned directly from the CLI-resolved $modeLabel (never "prompt" by this point)'
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

Test 'bootstrap.ps1 does not pin SkipMakerProfile (consolidated installer resolves mode in the CLI)' {
    if ($bootstrapSrc -match 'SkipMakerProfile\s*=\s*\$true') {
        throw 'bootstrap.ps1 should not set SkipMakerProfile = $true after installer consolidation (ADO #7895603)'
    }
    if ($bootstrapSrc -match "InstallMode\s*=\s*'(maker|developer|lite|standard)'") {
        throw "bootstrap.ps1 should not pin InstallMode; it should let the installer default to 'prompt' so VS Code asks the maker."
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

Test 'bootstrap-lite.ps1 passes -InstallMode maker (back-compat shim for legacy URL)' {
    if ($liteSrc -match 'SkipMakerProfile\s*=\s*\$true') {
        throw 'bootstrap-lite.ps1 should not set SkipMakerProfile = $true'
    }
    if ($liteSrc -notmatch "InstallMode\s*=\s*'maker'") {
        throw "bootstrap-lite.ps1 should pin InstallMode = 'maker' so old links keep landing in maker mode (was 'lite' before the rename)"
    }
}

Write-Host "`nbootstrap-dev.ps1:" -ForegroundColor Cyan

$devPath = Join-Path $PSScriptRoot 'bootstrap-dev.ps1'
$devSrc = if (Test-Path $devPath) { Get-Content $devPath -Raw } else { '' }

Test 'bootstrap-dev.ps1 exists' {
    if (-not (Test-Path $devPath)) {
        throw "bootstrap-dev.ps1 should exist as the shortcut for makers who want the Developer (default VS Code) experience"
    }
}

Test 'bootstrap-dev.ps1 parses without errors' {
    if (-not $devSrc) { return }
    $tokens = $null; $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile($devPath, [ref]$tokens, [ref]$errors)
    if ($errors.Count -gt 0) { throw "Parse errors: $($errors[0].Message)" }
}

Test 'bootstrap-dev.ps1 passes -InstallMode developer' {
    if (-not $devSrc) { throw 'bootstrap-dev.ps1 does not exist' }
    if ($devSrc -notmatch "InstallMode\s*=\s*'developer'") {
        throw "bootstrap-dev.ps1 should pin InstallMode = 'developer'"
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

Test 'derives installer mode (flightcheck | adk) - lite consolidated into adk' {
    if ($src -notmatch "FlightCheckOnly.*'flightcheck'") { throw 'flightcheck mode not derived' }
    if ($src -notmatch "\}\s*else\s*\{\s*'adk'\s*\}") { throw "post-consolidation installer identity should collapse to 'adk' for non-flightcheck installs" }
    if ($src -match "SkipMakerProfile.*'adk'.*else.*'lite'") { throw 'lite installer identity should no longer be derived here (installMode dim carries the distinction)' }
}

Test 'passes -InstallMode to Initialize-EssInstallTelemetry' {
    if ($src -notmatch 'Initialize-EssInstallTelemetry\s+-Installer\s+\$essInstaller\s+-InstallMode\s+\$modeLabel') {
        throw '-InstallMode $modeLabel must be threaded into telemetry init'
    }
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

Test 'installer telemetry emits no tenant dimension (unknowable pre-sign-in)' {
    # The installer runs before sign-in, so the tenant is never known; emitting
    # tenantId/tenantClass produced a meaningless 'unknown' on ~every event.
    $data = Get-EssTelCommonData
    if ($data.ContainsKey('tenantId'))    { throw 'tenantId should not be emitted by the installer' }
    if ($data.ContainsKey('tenantClass')) { throw 'tenantClass should not be emitted by the installer' }
    if (Get-Command -Name 'Get-EssTelTenantClass' -ErrorAction SilentlyContinue) { throw 'Get-EssTelTenantClass should be removed' }
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
Test 'envelope time is culture-invariant ISO-8601 (non-colon-separator locales)' {
    # Regression: a custom DateTime format string renders ':' as the current
    # culture's TimeSeparator ('.' under fi-FI), which would corrupt the
    # Common Schema time field. It must stay ISO-8601 regardless of locale.
    $orig = [System.Threading.Thread]::CurrentThread.CurrentCulture
    try {
        [System.Threading.Thread]::CurrentThread.CurrentCulture = [System.Globalization.CultureInfo]::GetCultureInfo('fi-FI')
        $envelope = New-EssTelEnvelope -Name 'ESSMakerKit.Installer.Start' -EnvelopeIKey 'o:abc' -Data @{}
        if ($envelope.time -notmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$') { throw "time not ISO-8601 under fi-FI: $($envelope.time)" }
    } finally {
        [System.Threading.Thread]::CurrentThread.CurrentCulture = $orig
    }
}
Test 'installer telemetry emits an installMode dimension' {
    Initialize-EssInstallTelemetry -Installer 'adk' -InstallMode 'maker'
    try {
        $data = Get-EssTelCommonData
        if (-not $data.ContainsKey('installMode')) { throw 'installMode dimension not emitted' }
        if ($data.installMode -ne 'maker') { throw "installMode wrong: $($data.installMode)" }
    } finally { $script:EssTel.Ready = $false; $script:EssTel.Completed = $false }
}

Test 'installer telemetry defaults installMode to prompt when unspecified' {
    Initialize-EssInstallTelemetry -Installer 'adk'
    try {
        $data = Get-EssTelCommonData
        if ($data.installMode -ne 'prompt') { throw "expected default prompt, got: $($data.installMode)" }
    } finally { $script:EssTel.Ready = $false; $script:EssTel.Completed = $false }
}

Test 'installer telemetry accepts legacy lite/standard values (back-compat)' {
    # Old bootstrap-lite invocations may still pass -InstallMode lite until
    # they resync. The emitter must accept those without validation errors.
    Initialize-EssInstallTelemetry -Installer 'adk' -InstallMode 'lite'
    try {
        if ($script:EssTel.InstallMode -ne 'lite') { throw "legacy 'lite' should be accepted verbatim" }
    } finally { $script:EssTel.Ready = $false; $script:EssTel.Completed = $false }
    Initialize-EssInstallTelemetry -Installer 'adk' -InstallMode 'standard'
    try {
        if ($script:EssTel.InstallMode -ne 'standard') { throw "legacy 'standard' should be accepted verbatim" }
    } finally { $script:EssTel.Ready = $false; $script:EssTel.Completed = $false }
}

Test 'maker installer identity is instrumented (post-consolidation)' {
    # Regression: pre-consolidation the emitter guarded out Installer='lite'
    # because the lite installer was slated for removal. With bootstrap-lite.ps1
    # now a compat shim into the unified installer that passes -InstallMode maker,
    # the guard would drop all shim events. It must be gone.
    $old = $env:ESS_ADK_TELEMETRY
    try {
        $env:ESS_ADK_TELEMETRY = ''
        Initialize-EssInstallTelemetry -Installer 'lite' -InstallMode 'maker'
        if (-not $script:EssTel.Ready) { throw 'legacy lite installer identity should be telemetry-ready after consolidation' }
    } finally { $env:ESS_ADK_TELEMETRY = $old; $script:EssTel.Ready = $false; $script:EssTel.Completed = $false }
}
Test 'PowerShell emitter no longer guards out the legacy lite installer' {
    $emitterSrc = Get-Content $psEmitter -Raw
    if ($emitterSrc -match "if\s*\(\`$Installer\s+-eq\s+'lite'\)\s*\{\s*\`$script:EssTel\.Ready\s*=\s*\`$false") {
        throw 'PS emitter still guards out lite installer; guard should be removed after consolidation (ADO #7895603)'
    }
}
Test 'bash emitter still guards out the legacy lite installer (macOS scope unchanged in this iteration)' {
    # macOS consolidation is out of scope for the current PR. Until a follow-up
    # US addresses macOS, bootstrap-lite-mac.sh remains a separate installer
    # tagged as ess_tel_installer=lite and the bash emitter still gates it out.
    $shSrc = Get-Content $shEmitter -Raw
    if ($shSrc -notmatch 'ESS_TEL_INSTALLER.*==.*"lite"') { throw 'lite guard missing in bash emitter (macOS scope not yet migrated)' }
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

Test 'install-ess-adk.sh honors INSTALL_MODE (maker|developer|prompt) with legacy SKIP_MAKER_PROFILE alias' {
    if ($macInstaller -notmatch 'INSTALL_MODE=') { throw 'INSTALL_MODE env var not consumed' }
    if ($macInstaller -notmatch 'SKIP_MAKER_PROFILE.*==.*"true"[\s\S]{0,120}INSTALL_MODE="developer"') {
        throw 'legacy SKIP_MAKER_PROFILE=true should map to INSTALL_MODE=developer'
    }
    if ($macInstaller -notmatch 'INSTALL_MODE.*==.*"lite"[\s\S]{0,80}INSTALL_MODE="maker"') {
        throw "legacy 'lite' should be coerced to 'maker' on macOS"
    }
    if ($macInstaller -notmatch 'INSTALL_MODE.*==.*"standard"[\s\S]{0,80}INSTALL_MODE="developer"') {
        throw "legacy 'standard' should be coerced to 'developer' on macOS"
    }
    if ($macInstaller -notmatch 'INSTALL_MODE"?\s*==\s*"developer"') { throw 'developer launch branch missing' }
    # Maker is now the fall-through `else` branch of the launch block (prompt
    # is resolved to maker|developer before any launch code runs), so we
    # assert the maker log copy is present instead of the explicit == check.
    if ($macInstaller -notmatch 'ESS Maker Profile will run /setup') { throw 'maker launch branch (fall-through else) missing' }
}

Test 'install-ess-adk.sh INSTALL_MODE=prompt fires a terminal Maker/Developer prompt' {
    if ($macInstaller -notmatch 'INSTALL_MODE"?\s*==\s*"prompt"') { throw 'no prompt branch guarding INSTALL_MODE=prompt' }
    if ($macInstaller -notmatch 'read -r answer') { throw 'terminal read for maker/developer answer missing' }
    if ($macInstaller -notmatch '/dev/tty') {
        throw '/dev/tty read fallback required so the prompt works when the script is piped through bash from a curl one-liner'
    }
    if ($macInstaller -notmatch 'Maker \(recommended\)') { throw 'Maker option label missing from prompt copy' }
    if ($macInstaller -notmatch '\[2\] Developer') { throw 'Developer option label missing from prompt copy' }
}

Test 'install-ess-adk.sh INSTALL_MODE=prompt defaults to maker under non-interactive / CI' {
    if ($macInstaller -notmatch '\$\{CI:-\}') { throw 'CI env-var non-interactive guard missing' }
    if ($macInstaller -notmatch '! -t 0') { throw 'stdin-is-a-tty non-interactive guard missing' }
    if ($macInstaller -notmatch 'Defaulting to Maker mode') {
        throw 'non-interactive branch should default to Maker mode with a visible message'
    }
}

Test 'bootstrap-dev-mac.sh exists and pins INSTALL_MODE=developer' {
    $devMacPath = Join-Path $PSScriptRoot 'bootstrap-dev-mac.sh'
    if (-not (Test-Path $devMacPath)) { throw 'bootstrap-dev-mac.sh missing' }
    $devMacSrc = Get-Content $devMacPath -Raw
    if ($devMacSrc -notmatch 'INSTALL_MODE="developer"') { throw 'bootstrap-dev-mac.sh should pin INSTALL_MODE=developer' }
}

Test 'bootstrap-lite-mac.sh pins INSTALL_MODE=maker (back-compat shim)' {
    $liteMacSrc = Get-Content (Join-Path $PSScriptRoot 'bootstrap-lite-mac.sh') -Raw
    if ($liteMacSrc -notmatch 'INSTALL_MODE="maker"') { throw 'bootstrap-lite-mac.sh should pin INSTALL_MODE=maker so legacy URL still lands in the chat-first experience' }
}

foreach ($bs in @('bootstrap.ps1', 'bootstrap-flightcheck.ps1', 'bootstrap-lite.ps1', 'bootstrap-dev.ps1')) {
    $bsSrc = Get-Content (Join-Path $PSScriptRoot $bs) -Raw
    Test "$bs downloads the telemetry lib and sets ESS_INSTALL_TELEMETRY_LIB" {
        if ($bsSrc -notmatch 'install-telemetry\.ps1') { throw 'telemetry lib not downloaded' }
        if ($bsSrc -notmatch 'ESS_INSTALL_TELEMETRY_LIB') { throw 'env var not set' }
    }
}
foreach ($bs in @('bootstrap-mac.sh', 'bootstrap-flightcheck-mac.sh', 'bootstrap-lite-mac.sh', 'bootstrap-dev-mac.sh')) {
    $bsSrc = Get-Content (Join-Path $PSScriptRoot $bs) -Raw
    Test "$bs downloads the telemetry lib and sets ESS_INSTALL_TELEMETRY_LIB" {
        if ($bsSrc -notmatch 'install-telemetry\.sh') { throw 'telemetry lib not downloaded' }
        if ($bsSrc -notmatch 'ESS_INSTALL_TELEMETRY_LIB') { throw 'env var not set' }
    }
}

Test 'install-ess-adk.sh maps SIGINT/SIGTERM (130/143) to a cancelled outcome' {
    if ($macInstaller -notmatch 'ess_tel_complete cancelled') { throw 'cancelled outcome not emitted on interrupt' }
    if ($macInstaller -notmatch '130' -or $macInstaller -notmatch '143') { throw 'SIGINT/SIGTERM codes not handled' }
}
Test 'Install-EssAdk.ps1 records success on the normal path, not in finally' {
    # Regression: Ctrl+C bypasses catch, so success must be emitted at the end of
    # try. finally must fall back to cancelled, never force success.
    if ($src -notmatch "(?s)Done\. Workspace.*?Complete-EssInstallTelemetry -Outcome 'success'") {
        throw "success not recorded at the end of the try block"
    }
    if ($src -notmatch "(?s)finally\s*\{[^}]*Complete-EssInstallTelemetry -Outcome 'cancelled'") {
        throw "finally must record 'cancelled', not 'success'"
    }
    if ($src -match "(?s)finally\s*\{[^}]*Complete-EssInstallTelemetry -Outcome 'success'") {
        throw "finally must not force a 'success' outcome (mislabels Ctrl+C)"
    }
}
Test 'Install-EssAdk.ps1 records success for a FlightCheck-only install before its early return' {
    # Regression: the FlightCheck-only branch returns from inside the top-level
    # try before the normal-path success emit, so it must emit its own success
    # completion. Otherwise the finally net mislabels it 'cancelled' and the
    # Installer Outcomes / by-Platform tiles never receive a real completion.
    if ($src -notmatch "(?s)Python not found\..*?Complete-EssInstallTelemetry -Outcome 'success'\s*\r?\n[^}]*?return") {
        throw "FlightCheck-only branch must emit a 'success' completion before its early return"
    }
}
Test 'PS emitter uses a short send timeout and trips a circuit breaker on failure' {
    $emitterSrc = Get-Content $psEmitter -Raw
    if ($emitterSrc -notmatch 'TimeoutSec 3') { throw 'PS emitter should use a short (3s) send timeout' }
    # The catch of the transport must disable further sends so an unreachable
    # collector adds ~one timeout total, not one per step.
    if ($emitterSrc -notmatch '(?s)catch\s*\{[^}]*EssTel\.Ready\s*=\s*\$false') { throw 'PS emitter missing circuit breaker' }
}
Test 'bash emitter uses a short send timeout and trips a circuit breaker on failure' {
    $shSrc = Get-Content $shEmitter -Raw
    if ($shSrc -notmatch 'curl -fsS -m 3') { throw 'bash emitter should use a short (3s) send timeout' }
    if ($shSrc -notmatch 'ESS_TEL_READY=0') { throw 'bash emitter missing circuit breaker' }
}

# Summary
Write-Host "`n$($passed + $failed) tests, $passed passed, $failed failed" -ForegroundColor $(if ($failed -gt 0) { 'Red' } else { 'Green' })
exit $(if ($failed -gt 0) { 1 } else { 0 })
