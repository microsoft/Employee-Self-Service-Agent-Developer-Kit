#Requires -Version 7.0
<#
Requires Python 3.12 and MSAL: python -m pip install msal==1.37.0
No ADK, GitHub Copilot license, MSAL.PS, or client secret is required.
Browser authentication uses MSAL Python's form-post callback.
Start with -WhatIf; use -Confirm only after confirming the target.
#>
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory)][guid]$TenantId,
    [Parameter(Mandatory)][guid]$EnvironmentId,
    [Parameter(Mandatory)][guid]$AgentId,
    [Parameter(Mandatory)][uri]$LibraryUrl,
    [ValidateSet('prod', 'test')][string]$Ring = 'prod',
    [string]$AccessToken,
    [string]$Account,
    [string]$PythonExecutable = 'python'
)

$ErrorActionPreference = 'Stop'
if ($LibraryUrl.Scheme -ne 'https' -or
    $LibraryUrl.Host -notlike '*.sharepoint.com' -or
    $LibraryUrl.Query -or $LibraryUrl.Fragment -or $LibraryUrl.UserInfo -or
    $LibraryUrl.AbsolutePath -notmatch '/SitePages/?$') {
    throw 'Provide a direct HTTPS SharePoint SitePages library URL without query parameters.'
}

if (-not $AccessToken) {
    $audience = if ($Ring -eq 'prod') {
        'https://api.powerplatform.com'
    } else {
        'https://api.test.powerplatform.com'
    }
    $python = Get-Command -Name $PythonExecutable -CommandType Application -ErrorAction Stop |
        Select-Object -First 1
    $authenticationCode = @'
import json
import sys
try:
    import msal
except ModuleNotFoundError:
    sys.exit("Install MSAL for this Python: python -m pip install msal==1.37.0")

tenant_id, scope = sys.argv[1:3]
account = sys.argv[3] if len(sys.argv) > 3 else None
app = msal.PublicClientApplication(
    "417219b4-3a7d-42a2-bdb1-972bd8281a02",
    authority="https://login.microsoftonline.com/" + tenant_id,
)
arguments = {"scopes": [scope], "timeout": 300}
if account:
    arguments["login_hint"] = account
else:
    arguments["prompt"] = "select_account"
result = app.acquire_token_interactive(**arguments)
if not result.get("access_token"):
    sys.exit("Browser authentication failed: {}: {}".format(
        result.get("error", "unknown_error"),
        result.get("error_description", "No access token returned"),
    ))
print(json.dumps({
    "access_token": result["access_token"],
    "tenant_id": result.get("id_token_claims", {}).get("tid"),
}))
'@
    Write-Host 'Opening browser sign-in. Use the maker account for the confirmed target tenant.'
    # Incident rich-text editors may replace Python indentation with NBSP.
    $authenticationCode = $authenticationCode.Replace([char]0xA0, [char]0x20)
    $authJson = $authenticationCode | & $python.Source - $TenantId.ToString() `
        "$audience/CopilotStudio.MinimalBot.ReadWrite" $Account
    if ($LASTEXITCODE -ne 0) {
        throw 'Browser authentication did not complete. Review the Python error above; no agent update was attempted.'
    }
    $auth = $authJson | ConvertFrom-Json -ErrorAction Stop
    if ($auth.tenant_id -ne $TenantId.ToString()) {
        throw 'Browser authentication returned a different or missing tenant identity. No agent update was attempted.'
    }
    $AccessToken = $auth.access_token
}
if (-not $AccessToken) {
    throw 'Authentication did not return an access token.'
}

$compact = $EnvironmentId.ToString('N')
$suffix = if ($Ring -eq 'prod') {
    'environment.api.powerplatform.com'
} else {
    'environment.api.test.powerplatform.com'
}
$splits = if ($Ring -eq 'prod') { @(30, 31) } else { @(31, 30) }
$apiHostName = $null
foreach ($split in $splits) {
    $candidate = '{0}.{1}.{2}' -f $compact.Substring(0, $split),
        $compact.Substring($split), $suffix
    try {
        $null = [System.Net.Dns]::GetHostAddresses($candidate)
        $apiHostName = $candidate
        break
    } catch [System.Net.Sockets.SocketException] {
        Write-Verbose "Environment hostname did not resolve: $candidate"
    }
}
if (-not $apiHostName) {
    throw 'Neither expected environment API hostname resolved.'
}
$uri = "https://$apiHostName/copilotstudio/minimalBots/api/$AgentId/components?api-version=2022-03-01-preview"
$headers = @{
    Authorization = "Bearer $AccessToken"
    Accept = 'application/json'
    'x-ms-client-name' = 'CopilotStudio'
}
$before = Invoke-RestMethod -Method Post -Uri $uri -Headers $headers `
    -ContentType 'application/json' -Body '{}' -TimeoutSec 180
if (-not $before.changeToken -or -not $before.bot.schemaName) {
    throw 'Native agent fetch omitted the change token or agent schema name.'
}
$components = @($before.botComponentChanges | ForEach-Object { $_.component })
$existing = @($components | Where-Object {
    $_.'$kind' -eq 'KnowledgeSourceComponent' -and
    $_.configuration.source.'$kind' -eq 'SharePointSearchSource' -and
    ([string]$_.configuration.source.site.literalValue).TrimEnd('/') -eq $LibraryUrl.AbsoluteUri.TrimEnd('/')
})
if ($existing.Count -gt 0) {
    Write-Output "Already configured: $($existing[0].displayName) [$($existing[0].id)]. No changes made."
    return
}

$id = [guid]::NewGuid().ToString()
$component = @{
    '$kind' = 'KnowledgeSourceComponent'
    version = 1
    id = $id
    displayName = 'SharePoint Site Pages'
    description = "SharePoint knowledge scoped to $($LibraryUrl.AbsoluteUri)"
    schemaName = "$($before.bot.schemaName).knowledge.SitePages_$($id.Replace('-', ''))"
    configuration = @{
        '$kind' = 'KnowledgeSourceConfiguration'
        source = @{
            '$kind' = 'SharePointSearchSource'
            cascadeShare = $false
            site = @{
                '$kind' = 'StringExpression'
                literalValue = $LibraryUrl.AbsoluteUri
            }
        }
    }
}
$body = @{
    changeToken = $before.changeToken
    botComponentChanges = @(@{ '$kind' = 'BotComponentInsert'; component = $component })
    connectionReferenceChanges = @()
    connectorDefinitionChanges = @()
} | ConvertTo-Json -Depth 100

Write-Output "Agent: $($before.bot.displayName) [$AgentId]"
Write-Output "Environment: $EnvironmentId; ring: $Ring"
if (-not $PSCmdlet.ShouldProcess("$AgentId", "Add $($LibraryUrl.AbsoluteUri) without publishing")) {
    return
}
$backup = Join-Path (Get-Location).Path "ess-source-backup-$AgentId-$id.json"
$before | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $backup -Encoding utf8
Write-Output "Backup: $backup"
$null = Invoke-RestMethod -Method Put -Uri $uri -Headers $headers `
    -ContentType 'application/json' -Body $body -TimeoutSec 180
$after = Invoke-RestMethod -Method Post -Uri $uri -Headers $headers `
    -ContentType 'application/json' -Body '{}' -TimeoutSec 180
$added = @($after.botComponentChanges | ForEach-Object { $_.component } |
    Where-Object { $_.id -eq $id })
if ($added.Count -ne 1 -or
    $added[0].configuration.source.site.literalValue -cne $LibraryUrl.AbsoluteUri) {
    throw "The write completed but exact readback verification failed. Inspect source ID $id before retrying."
}
Write-Output "Verified source: $($added[0].configuration.source.site.literalValue)"
Write-Output "Source ID: $id. Existing sources retained. Agent not published."
