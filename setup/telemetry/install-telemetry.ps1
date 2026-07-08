<#
.SYNOPSIS
    Installer telemetry emitter (Aria / 1DS OneCollector) for the ESS ADK
    installers — Windows / PowerShell.

.DESCRIPTION
    Emits install start / per-step / completion events so we can measure
    install success and failure rates and see which stage fails, per installer
    (ADK, ADK-lite, standalone FlightCheck). This is a dependency-light,
    self-contained mirror of the Python telemetry SDK
    (solutions/ess-maker-skills/scripts/flightcheck/telemetry.py): the
    installers run PowerShell/bash BEFORE Python is guaranteed to exist (the
    ADK installer's job is partly to install Python), so we cannot shell out to
    the Python emitter — the OneCollector envelope + POST are reproduced here.

    Design rules (deliberate — read before changing):

    * Fail-open, NEVER break the install. Every function swallows its own
      errors; nothing here throws, and telemetry never changes the installer's
      exit code. A telemetry bug must never break a customer's setup.
    * Same privacy model as the ADK/FlightCheck telemetry: no developer/user
      identity; a random per-install ``instance_id`` for dedup; the raw tenant
      GUID (OII) only where available; enums + scrubbed errors only. Error
      text is scrubbed of paths, URLs, emails/UPNs and GUIDs.
    * Same unified opt-out: ``ESS_ADK_TELEMETRY=off`` or
      ``python scripts/adk_telemetry.py off`` (which writes ~/.adk/config).
      The one-time consent notice is shown on first install.

    The iKeys are 1DS *ingestion* keys: write-only, safe to embed (the same
    keys ship in flightcheck/telemetry.py and the VS Code extension).

    This file only DEFINES functions; dot-source it, then call
    Initialize-EssInstallTelemetry / Write-EssInstallStep /
    Complete-EssInstallTelemetry.
#>

# --- Constants -------------------------------------------------------------
$script:EssTelIKeys = @{
    dev  = '08e397b2c6c243eeaeb341e111c36167-294d89f6-c806-4c65-adf3-dea3bb44f949-7206'
    prod = '311254257bbc417e860c76781d4863c8-8cff75a4-47b7-4675-9646-45a4ca9bc138-7062'
}
$script:EssTelCollectorUrl = 'https://mobile.events.data.microsoft.com/OneCollector/1.0/?cors=true&content-type=application/x-json-stream'
$script:EssTelSchemaVersion = '1.0'
# Microsoft corporate Entra tenant — the only internal tenancy by default
# (mirrors flightcheck/telemetry.py classify_tenant; ADO 7558661).
$script:EssTelCorpTenant = '72f988bf-86f1-41af-91ab-2d7cd011db47'

# Per-process state, populated by Initialize-EssInstallTelemetry.
$script:EssTel = @{
    Ready        = $false
    Installer    = 'adk'
    Env          = 'prod'
    IKey         = ''
    InstanceId   = ''
    TenantId     = ''
    FirstRun     = $true
    Platform     = 'Windows'
    OsVersion    = ''
    AdkVersion   = 'unknown'
    Stopwatch    = $null
    CurrentStep  = ''
    StepIndex    = 0
    Completed    = $false
}

$script:EssTelConfigDir  = Join-Path $HOME '.adk'
$script:EssTelConfigPath = Join-Path $script:EssTelConfigDir 'config'

$script:EssTelNotice = @'
------------------------------------------------------------------------
ESS Agent Developer Kit collects pseudonymous installation telemetry
(install success/failure, which step failed, scrubbed error categories,
duration, platform) to help us improve setup reliability. It does NOT
collect your identity, credentials, file contents, or agent content.
Opt out any time:  python scripts/adk_telemetry.py off   (or set
ESS_ADK_TELEMETRY=off). Details: https://aka.ms/adk-telemetry
------------------------------------------------------------------------
'@

# --- Config / consent (mirrors adk_telemetry.py) ---------------------------
function Get-EssTelConfig {
    try {
        if (Test-Path $script:EssTelConfigPath) {
            $raw = Get-Content $script:EssTelConfigPath -Raw -ErrorAction Stop
            if ($raw) { return ($raw | ConvertFrom-Json -ErrorAction Stop) }
        }
    } catch { }
    return [pscustomobject]@{}
}

function Set-EssTelConfigValue {
    param([string]$Name, $Value)
    try {
        $cfg = Get-EssTelConfig
        $ht = @{}
        foreach ($p in $cfg.PSObject.Properties) { $ht[$p.Name] = $p.Value }
        $ht[$Name] = $Value
        if (-not (Test-Path $script:EssTelConfigDir)) {
            New-Item -ItemType Directory -Path $script:EssTelConfigDir -Force | Out-Null
        }
        ($ht | ConvertTo-Json -Depth 5) | Set-Content -Path $script:EssTelConfigPath -Encoding UTF8
    } catch { }
}

function Test-EssTelemetryEnabled {
    # True unless opted out via env var or ~/.adk/config.
    $val = "$env:ESS_ADK_TELEMETRY".Trim().ToLowerInvariant()
    if ($val -in @('0', 'off', 'false', 'no', 'disabled')) { return $false }
    if ($val -in @('1', 'on', 'true', 'yes', 'enabled'))  { return $true }
    $cfg = Get-EssTelConfig
    return ($cfg.telemetry -ne 'disabled')
}

function Show-EssTelemetryNotice {
    # One-time consent notice, idempotent via config.noticeShown. Returns $true
    # if it was shown this time.
    $cfg = Get-EssTelConfig
    if ($cfg.noticeShown) { return $false }
    [Console]::Error.WriteLine("`n$script:EssTelNotice`n")
    Set-EssTelConfigValue -Name 'noticeShown' -Value $true
    if (-not $cfg.telemetry) { Set-EssTelConfigValue -Name 'telemetry' -Value 'enabled' }
    return $true
}

# --- Identity --------------------------------------------------------------
function Get-EssTelInstanceInfo {
    # Returns @{ Id = <guid>; FirstRun = <bool> }. Reuses an existing per-install
    # id (repo .local/.instance_id first so it matches the Python runtime, then
    # ~/.adk/.instance_id), else mints one. FirstRun is $true only when no id
    # existed before this install.
    $candidates = @()
    if ($env:ESS_ADK_INSTALL_ROOT) {
        $candidates += (Join-Path (Join-Path $env:ESS_ADK_INSTALL_ROOT 'Employee-Self-Service-Agent-Developer-Kit') '.local\.instance_id')
    }
    $candidates += (Join-Path $script:EssTelConfigDir '.instance_id')
    foreach ($p in $candidates) {
        try {
            if (Test-Path $p) {
                $existing = (Get-Content $p -Raw -ErrorAction Stop).Trim()
                if ($existing) { return @{ Id = $existing; FirstRun = $false } }
            }
        } catch { }
    }
    $newId = [guid]::NewGuid().ToString()
    $target = Join-Path $script:EssTelConfigDir '.instance_id'
    try {
        if (-not (Test-Path $script:EssTelConfigDir)) {
            New-Item -ItemType Directory -Path $script:EssTelConfigDir -Force | Out-Null
        }
        Set-Content -Path $target -Value $newId -Encoding UTF8 -ErrorAction Stop
    } catch { }
    return @{ Id = $newId; FirstRun = $true }
}

function Get-EssTelTenantClass {
    param([string]$TenantId)
    if ([string]::IsNullOrWhiteSpace($TenantId)) { return 'unknown' }
    $t = $TenantId.Trim().ToLowerInvariant()
    $internal = @($script:EssTelCorpTenant.ToLowerInvariant())
    if ($env:ESS_ADK_INTERNAL_TENANTS) {
        foreach ($x in ($env:ESS_ADK_INTERNAL_TENANTS -split ',')) {
            $x = $x.Trim().ToLowerInvariant()
            if ($x) { $internal += $x }
        }
    }
    if ($internal -contains $t) { return 'internal' }
    return 'customer'
}

# --- Scrub (mirrors adk_telemetry._scrub) ----------------------------------
function ConvertTo-EssTelScrubbed {
    param([string]$Text, [int]$Limit = 200)
    if ([string]::IsNullOrEmpty($Text)) { return '' }
    $s = $Text -replace "`r", ' ' -replace "`n", ' '
    $s = $s.Trim()
    $s = [regex]::Replace($s, '[A-Za-z]:\\[^\s]+', '<path>')
    $s = [regex]::Replace($s, 'https?://[^\s]+', '<url>')
    $s = [regex]::Replace($s, '(?<!\w)/[^\s]+', '<path>')
    $s = [regex]::Replace($s, '[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', '<email>')
    $s = [regex]::Replace($s, '\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b', '<guid>')
    if ($s.Length -gt $Limit) { $s = $s.Substring(0, $Limit) }
    return $s
}

# --- Envelope + transport (mirrors telemetry.py) ---------------------------
function Get-EssTelEnvelopeIKey { param([string]$FullIKey) return 'o:' + ($FullIKey -split '-', 2)[0] }

function New-EssTelEnvelope {
    param([string]$Name, [string]$EnvelopeIKey, [hashtable]$Data)
    $now = [DateTime]::UtcNow
    return @{
        ver  = '4.0'
        name = $Name
        time = $now.ToString('yyyy-MM-ddTHH:mm:ss.') + ('{0:000}' -f $now.Millisecond) + 'Z'
        iKey = $EnvelopeIKey
        data = $Data
    }
}

function Send-EssTelEvent {
    # Fail-open POST of a single Common Schema 4.0 envelope as x-json-stream.
    param([hashtable]$Envelope)
    if (-not $script:EssTel.Ready) { return $null }
    try {
        $line = ($Envelope | ConvertTo-Json -Depth 12 -Compress)
        $now = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
        $headers = @{
            'apikey'         = $script:EssTel.IKey
            'Client-Id'      = 'NO_AUTH'
            'client-version' = "ess-maker-installer-$($script:EssTel.AdkVersion)"
            'upload-time'    = "$now"
            'cache-control'  = 'no-cache, no-store'
            'NoResponseBody' = 'true'
        }
        $resp = Invoke-WebRequest -Uri $script:EssTelCollectorUrl -Method Post `
            -Body ($line + "`n") -ContentType 'application/x-json-stream' `
            -Headers $headers -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        return [int]$resp.StatusCode
    } catch {
        return $null
    }
}

# --- Public API ------------------------------------------------------------
function Get-EssTelCommonData {
    return @{
        schemaVersion    = $script:EssTelSchemaVersion
        env              = $script:EssTel.Env
        installer        = $script:EssTel.Installer
        invocationSource = 'installer'
        platform         = $script:EssTel.Platform
        os               = $script:EssTel.OsVersion
        instanceId       = $script:EssTel.InstanceId
        tenantId         = $script:EssTel.TenantId
        tenantClass      = (Get-EssTelTenantClass -TenantId $script:EssTel.TenantId)
        adkVersion       = $script:EssTel.AdkVersion
        firstRun         = $script:EssTel.FirstRun
    }
}

function Initialize-EssInstallTelemetry {
    <#
    .SYNOPSIS Begin installer telemetry: notice, identity, and the start event.
    .PARAMETER Installer  One of adk | lite | flightcheck.
    .PARAMETER TenantId   Raw Entra tenant GUID if known (optional).
    #>
    param(
        [ValidateSet('adk', 'lite', 'flightcheck')]
        [string]$Installer = 'adk',
        [string]$TenantId = ''
    )
    try {
        if (-not (Test-EssTelemetryEnabled)) { $script:EssTel.Ready = $false; return }
        Show-EssTelemetryNotice | Out-Null

        $envName = "$env:ESS_ADK_ARIA_ENV".Trim().ToLowerInvariant()
        if (-not $envName) { $envName = "$env:ESS_FLIGHTCHECK_ARIA_ENV".Trim().ToLowerInvariant() }
        if ($envName -ne 'dev') { $envName = 'prod' }

        $inst = Get-EssTelInstanceInfo
        $adkVer = "$env:ESS_ADK_VERSION".Trim(); if (-not $adkVer) { $adkVer = 'unknown' }

        $script:EssTel.Installer   = $Installer
        $script:EssTel.Env         = $envName
        $script:EssTel.IKey        = $script:EssTelIKeys[$envName]
        $script:EssTel.InstanceId  = $inst.Id
        $script:EssTel.FirstRun    = $inst.FirstRun
        $script:EssTel.TenantId    = $TenantId
        $script:EssTel.Platform    = 'Windows'
        $script:EssTel.OsVersion   = [string][Environment]::OSVersion.Version
        $script:EssTel.AdkVersion  = $adkVer
        $script:EssTel.Stopwatch   = [System.Diagnostics.Stopwatch]::StartNew()
        $script:EssTel.StepIndex   = 0
        $script:EssTel.CurrentStep = 'start'
        $script:EssTel.Completed   = $false
        $script:EssTel.Ready       = $true

        $data = Get-EssTelCommonData
        $env2 = Get-EssTelEnvelopeIKey -FullIKey $script:EssTel.IKey
        Send-EssTelEvent -Envelope (New-EssTelEnvelope -Name 'ESSMakerKit.Installer.Start' -EnvelopeIKey $env2 -Data $data) | Out-Null
    } catch {
        $script:EssTel.Ready = $false
    }
}

function Write-EssInstallStep {
    <#
    .SYNOPSIS Record the current install step and emit a step event.
    .PARAMETER Step Short stable step key (e.g. 'preflight', 'toolchain').
    #>
    param([string]$Step)
    try {
        if (-not $script:EssTel.Ready) { return }
        $script:EssTel.StepIndex++
        $script:EssTel.CurrentStep = $Step
        $data = Get-EssTelCommonData
        $data.step = $Step
        $data.stepIndex = $script:EssTel.StepIndex
        $data.outcome = 'reached'
        $env2 = Get-EssTelEnvelopeIKey -FullIKey $script:EssTel.IKey
        Send-EssTelEvent -Envelope (New-EssTelEnvelope -Name 'ESSMakerKit.Installer.Step' -EnvelopeIKey $env2 -Data $data) | Out-Null
    } catch { }
}

function Complete-EssInstallTelemetry {
    <#
    .SYNOPSIS Emit the completion event exactly once.
    .PARAMETER Outcome One of success | failure | cancelled.
    .PARAMETER ErrorRecord The caught error (optional; scrubbed).
    #>
    param(
        [ValidateSet('success', 'failure', 'cancelled')]
        [string]$Outcome = 'success',
        $ErrorRecord = $null
    )
    try {
        if (-not $script:EssTel.Ready -or $script:EssTel.Completed) { return }
        $script:EssTel.Completed = $true
        $dur = 0.0
        if ($script:EssTel.Stopwatch) { $dur = [math]::Round($script:EssTel.Stopwatch.Elapsed.TotalSeconds, 1) }
        $data = Get-EssTelCommonData
        $data.outcome = $Outcome
        $data.failedStep = if ($Outcome -eq 'success') { '' } else { $script:EssTel.CurrentStep }
        $data.durationSecs = $dur
        if ($ErrorRecord) {
            $msg = ''; $code = ''; $cat = ''
            try {
                $msg  = ConvertTo-EssTelScrubbed -Text ([string]$ErrorRecord.Exception.Message)
                $code = ConvertTo-EssTelScrubbed -Text ([string]$ErrorRecord.FullyQualifiedErrorId) -Limit 80
                $cat  = ConvertTo-EssTelScrubbed -Text ([string]$ErrorRecord.CategoryInfo.Category) -Limit 60
            } catch { }
            $data.errorMessage  = $msg
            $data.errorCode     = $code
            $data.errorCategory = $cat
        }
        $env2 = Get-EssTelEnvelopeIKey -FullIKey $script:EssTel.IKey
        Send-EssTelEvent -Envelope (New-EssTelEnvelope -Name 'ESSMakerKit.Installer.Complete' -EnvelopeIKey $env2 -Data $data) | Out-Null
    } catch { }
}
