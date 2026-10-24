<#
.SYNOPSIS
    Provisions the Dataverse records that allow Power Automate cloud flows to be installed and
    invoked by a Cosmos-backed Declarative Agent (template gptagent-1.0.0, schema gptagent_*).

.DESCRIPTION
    Flow-RP resolves the "mcsbot" delegated-authorization principal exclusively from Dataverse.
    A Cosmos-backed agent has no Dataverse 'bot' row, so that lookup fails and flow install /
    invoke return 403.

    Flow-RP never reads the 'bot' table. It only requires:
      1. a 'delegatedauthorization' row of providertype 3 (MCSBot) carrying the bot GUID
      2. an ACCESS team (teamtype 1) linked to that delegated authorization
      3. that team shared on each workflow the agent calls, with at least WriteAccess

    This script creates those three things idempotently. It is safe to re-run: existing records
    are detected and reused, and access is only granted where missing.

.PARAMETER OrgUrl
    Dataverse organization URL, e.g. https://contoso.crm.dynamics.com

.PARAMETER BotId
    The agent's CdsBotId (GUID).

.PARAMETER WorkflowId
    One or more workflow GUIDs (the 'workflowid' of each cloud flow the agent calls).

.PARAMETER PreferredUsername
    Environment Maker username that must be used for Dataverse authentication.

.PARAMETER TeamName
    Optional display name for the access team.

.PARAMETER AdministratorId
    Optional systemuserid to own the team. Must hold System Administrator. Auto-resolved if omitted.

.PARAMETER BusinessUnitId
    Optional business unit. Defaults to the org's root business unit.

.PARAMETER ExpectedAuthorizationId
    Optional exact delegated-authorization ID from the approved runtime plan.

.PARAMETER ExpectedTeamId
    Optional exact access-team ID from the approved runtime plan.

.PARAMETER AccessMask
    Access rights granted to the team on each workflow. WriteAccess is the significant one -
    Flow-RP maps a mask containing WriteAccess to UserAccessType.Owner.

.PARAMETER WhatIf
    Report what would change without writing anything.

.EXAMPLE
    .\Enable-CosmosDAFlowAuthorization.ps1 `
        -OrgUrl https://contoso.crm.dynamics.com `
        -BotId 923db1bf-2512-4378-a43b-71b944ea717c `
        -WorkflowId 3164dae9-3a2b-5843-98dd-e62bb5123324

.NOTES
    Uses the kit's Python authentication for the selected maker account. Azure CLI is only
    an optional token source when PreferredUsername is omitted. The account must have the
    Dataverse privileges required for the authorization records and flow sharing.
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]   $OrgUrl,
    [Parameter(Mandatory = $true)][guid]     $BotId,
    [Parameter(Mandatory = $true)][guid[]]   $WorkflowId,
    [string] $PreferredUsername,
    [string] $TeamName,
    [guid]   $AdministratorId,
    [guid]   $BusinessUnitId,
    [guid]   $ExpectedAuthorizationId,
    [guid]   $ExpectedTeamId,
    [string] $AccessMask = "ReadAccess,WriteAccess,AppendAccess,AppendToAccess,ShareAccess"
)

$ErrorActionPreference = 'Stop'
$OrgUrl  = $OrgUrl.TrimEnd('/')
$ApiBase = "$OrgUrl/api/data/v9.1"

# providertype option-set value for MCSBot on the delegatedauthorization entity.
$ProviderTypeMcsBot = 3
# teamtype option-set value for an Access team. Owner teams (0) are rejected by the platform
# with 0x80097207 when linked to a delegated authorization.
$TeamTypeAccess = 1

function Write-Step   { param([string]$m) Write-Host "`n=== $m" -ForegroundColor Cyan }
function Write-Ok     { param([string]$m) Write-Host "  [ok]     $m" -ForegroundColor Green }
function Write-Reuse  { param([string]$m) Write-Host "  [reuse]  $m" -ForegroundColor DarkGray }
function Write-Create { param([string]$m) Write-Host "  [create] $m" -ForegroundColor Yellow }
function Write-Fail   { param([string]$m) Write-Host "  [FAIL]   $m" -ForegroundColor Red }

function Test-DataverseToken {
    param(
        [Parameter(Mandatory = $true)][string]$Resource,
        [Parameter(Mandatory = $true)][string]$Token
    )
    try {
        Invoke-RestMethod `
            -Method GET `
            -Uri "$($Resource.TrimEnd('/'))/api/data/v9.1/WhoAmI" `
            -Headers @{ Authorization = "Bearer $Token"; Accept = 'application/json' } `
            -ErrorAction Stop | Out-Null
        return $true
    } catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 401) {
            return $false
        }
        throw
    }
}

function Get-DataverseToken {
    param(
        [string]$Resource,
        [string]$PreferredUsername
    )
    $tok = $null
    if ([string]::IsNullOrWhiteSpace($PreferredUsername)) {
        try {
            $tok = az account get-access-token --resource $Resource --query accessToken -o tsv 2>$null
        } catch {
            $tok = $null
        }
        if (-not [string]::IsNullOrWhiteSpace($tok) -and (Test-DataverseToken -Resource $Resource -Token $tok)) {
            return $tok
        }
    }

    if ($PreferredUsername) {
        Write-Host "  Using the kit's Dataverse sign-in for $PreferredUsername." -ForegroundColor Yellow
    } else {
        Write-Host "  Azure CLI token was unavailable or rejected; using the kit's Dataverse sign-in." -ForegroundColor Yellow
    }
    $helper = Join-Path $PSScriptRoot 'get_dataverse_token.py'
    $python = Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $python -or -not (Test-Path $helper)) {
        throw "Could not acquire a valid Dataverse token. Install Python, then run the kit setup or sign in with an account that can access $Resource."
    }

    $helperArgs = @('--environment', $Resource)
    if ($PreferredUsername) {
        $helperArgs += @('--preferred-username', $PreferredUsername)
    }
    $output = @(& $python.Source $helper @helperArgs 2>&1)
    if ($LASTEXITCODE -ne 0) {
        $safeError = ($output | Where-Object { $_ -notmatch '^ESS_DATAVERSE_TOKEN=' }) -join [Environment]::NewLine
        throw "Kit Dataverse authentication failed: $safeError"
    }
    $marker = $output | Where-Object { $_ -match '^ESS_DATAVERSE_TOKEN=' } | Select-Object -Last 1
    if (-not $marker) {
        throw "Kit Dataverse authentication did not return an access token."
    }
    $tok = ([string]$marker).Substring('ESS_DATAVERSE_TOKEN='.Length)
    if ([string]::IsNullOrWhiteSpace($tok)) {
        throw "Kit Dataverse authentication returned an empty access token for $Resource."
    }
    if (-not (Test-DataverseToken -Resource $Resource -Token $tok)) {
        throw "Kit Dataverse authentication returned a token that was rejected by $Resource."
    }
    return $tok
}

function Invoke-Dv {
    param(
        [ValidateSet('GET', 'POST', 'PATCH')][string]$Method = 'GET',
        [Parameter(Mandatory = $true)][string]$Path,
        $Body
    )
    $uri = if ($Path -match '^https?://') { $Path } else { "$ApiBase/$($Path.TrimStart('/'))" }
    $headers = @{
        Authorization      = "Bearer $script:Token"
        Accept             = 'application/json'
        'OData-MaxVersion' = '4.0'
        'OData-Version'    = '4.0'
        Prefer             = 'return=representation'
    }
    try {
        if ($null -ne $Body) {
            $json = if ($Body -is [string]) { $Body } else { $Body | ConvertTo-Json -Depth 10 }
            return Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers -Body $json -ContentType 'application/json'
        }
        return Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers
    } catch {
        # PowerShell 7: the response body lives on ErrorDetails. $_.Exception.Response.GetResponseStream()
        # does NOT exist on HttpResponseMessage and silently hides the real Dataverse error.
        $detail = $_.ErrorDetails.Message
        if ($detail) {
            try { $parsed = ($detail | ConvertFrom-Json).error.message } catch { $parsed = $detail }
            throw "Dataverse $Method $uri failed: $parsed"
        }
        throw
    }
}

function Read-AgentAuthorization {
    $daResponse = Invoke-Dv -Path $daFilter
    $teamResponse = Invoke-Dv -Path $teamFilter
    if ($null -eq $daResponse.value -or $null -eq $teamResponse.value) {
        throw '[WD-AUTH-INVALID-RECORDS] Could not read authorization ownership. Ask the Dataverse administrator to investigate before retrying.'
    }
    $daExisting = @($daResponse.value)
    $teamExisting = @($teamResponse.value)
    if ($daExisting.Count -gt 1) {
        throw '[WD-AUTH-INVALID-RECORDS] Multiple delegated authorizations; expected exactly one. Ask the Dataverse administrator to resolve duplicates.'
    }
    if ($teamExisting.Count -gt 1) {
        throw '[WD-AUTH-INVALID-RECORDS] Multiple linked teams; expected exactly one. Ask the Dataverse administrator to resolve duplicates.'
    }
    $authorization = if ($daExisting.Count -eq 1) { $daExisting[0] } else { $null }
    $team = if ($teamExisting.Count -eq 1) { $teamExisting[0] } else { $null }
    if ($null -ne $authorization -and (
        -not $authorization.delegatedauthorizationid -or
        $authorization.botid -ne $BotId.ToString() -or
        $authorization.providertype -ne $ProviderTypeMcsBot
    )) {
        throw '[WD-AUTH-INVALID-RECORDS] Unexpected authorization owner or provider type. Ask the Dataverse administrator to inspect the selected agent.'
    }
    if ($null -ne $team -and (
        -not $authorization -or -not $team.teamid -or
        $team.teamtype -ne $TeamTypeAccess -or
        $team._delegatedauthorizationid_value -ne $authorization.delegatedauthorizationid
    )) {
        throw '[WD-AUTH-INVALID-RECORDS] The access team does not belong to the selected authorization. Do not adopt or relink another team.'
    }
    if (($ExpectedAuthorizationId -and (
        -not $authorization -or $authorization.delegatedauthorizationid -ne $ExpectedAuthorizationId.ToString()
    )) -or ($ExpectedTeamId -and (
        -not $team -or $team.teamid -ne $ExpectedTeamId.ToString()
    ))) {
        throw '[WD-AUTH-INVALID-RECORDS] The reviewed authorization identity changed. Refresh the runtime plan before retrying.'
    }
    if ($team -and $BusinessUnitId -and (
        ($TeamName -and $team.name -ne $TeamName) -or
        $team._businessunitid_value -ne $BusinessUnitId.ToString()
    )) {
        throw '[WD-AUTH-INVALID-RECORDS] The linked team differs from the reviewed name or business unit. Refresh the runtime plan.'
    }
    return [pscustomobject]@{ Authorization = $authorization; Team = $team }
}

# --------------------------------------------------------------------------------------------
Write-Step "Connecting to $OrgUrl"
$script:Token = Get-DataverseToken `
    -Resource $OrgUrl `
    -PreferredUsername $PreferredUsername
$who = Invoke-Dv -Path 'WhoAmI'
Write-Ok "Authenticated. UserId $($who.UserId), OrgId $($who.OrganizationId)"

# Validate every requested workflow before creating authorization records.
$workflowRows = @{}
$missingWorkflow = $false
foreach ($wf in $WorkflowId) {
    $wfRow = (Invoke-Dv -Path "workflows?`$select=workflowid,name,statecode&`$filter=workflowid eq $wf").value
    if (-not $wfRow) {
        Write-Fail "workflow $wf not found in this organization"
        $missingWorkflow = $true
        continue
    }
    $workflowRows[$wf.ToString()] = $wfRow[0]
}
if ($missingWorkflow) {
    Write-Fail 'One or more requested workflows were not found. No authorization records were changed.'
    exit 1
}

# --------------------------------------------------------------------------------------------
$daFilter = "delegatedauthorizations?`$select=delegatedauthorizationid,botid,name,providertype&`$filter=botid eq '$BotId'"
$teamFilter = "teams?`$expand=delegatedauthorizationid&`$filter=delegatedauthorizationid/botid eq '$BotId'&`$select=teamid,name,teamtype,_delegatedauthorizationid_value,_businessunitid_value"
$snapshot = Read-AgentAuthorization
if (-not $TeamName) {
    $TeamName = if ($snapshot.Team) { $snapshot.Team.name } else { "Cosmos DA bot team ($BotId)" }
}

if (-not $snapshot.Team) {
    if (-not $BusinessUnitId) {
        $bu = @((Invoke-Dv -Path 'businessunits?$select=businessunitid,name&$filter=parentbusinessunitid eq null').value)
        if ($bu.Count -ne 1 -or -not $bu[0].businessunitid) {
            throw 'Could not resolve exactly one root business unit. Ask the Dataverse administrator to inspect it.'
        }
        $BusinessUnitId = $bu[0].businessunitid
        Write-Ok "Resolved root business unit $BusinessUnitId ($($bu[0].name))"
    }
    $escapedName = $TeamName.Replace("'", "''")
    $nameQuery = "teams?`$select=teamid&`$filter=_businessunitid_value eq $BusinessUnitId and name eq '$escapedName'"
    $nameResponse = Invoke-Dv -Path $nameQuery
    if ($null -eq $nameResponse.value) {
        throw '[WD-AUTH-INVALID-RECORDS] Could not check the proposed team name. Ask the Dataverse administrator to verify read access.'
    }
    if (@($nameResponse.value).Count -gt 0) {
        throw '[WD-AUTH-TEAM-NAME-CONFLICT] The proposed team name is already in use in this business unit. Refresh the runtime plan; do not delete or adopt another team.'
    }
    if (-not $AdministratorId) {
        # The team administrator must hold System Administrator, otherwise team creation fails
        # with 0x80041d0a "The team administrator does not have privilege read team."
        $roleQ  = 'roles?$select=roleid&$filter=name eq ''System Administrator'''
        $role   = (Invoke-Dv -Path $roleQ).value
        if (-not $role) { throw 'Could not locate the System Administrator role. Pass -AdministratorId explicitly.' }
        $roleId = $role[0].roleid
        $userQ  = "systemusers?`$select=systemuserid,fullname&`$filter=systemuserroles_association/any(r:r/roleid eq $roleId) and isdisabled eq false&`$top=1"
        $admin  = (Invoke-Dv -Path $userQ).value
        if (-not $admin) { throw 'Could not locate an enabled System Administrator. Pass -AdministratorId explicitly.' }
        $AdministratorId = $admin[0].systemuserid
        Write-Ok "Resolved team administrator $AdministratorId ($($admin[0].fullname))"
    }
}

Write-Step "Step 2/4 - delegatedauthorization for bot $BotId"
if ($snapshot.Authorization) {
    $daId = $snapshot.Authorization.delegatedauthorizationid
    Write-Reuse "delegatedauthorization $daId (providertype $ProviderTypeMcsBot)"
} else {
    $daBody = @{
        name         = "$TeamName delegated auth"
        providertype = $ProviderTypeMcsBot
        botid        = $BotId.ToString()
    }
    if ($PSCmdlet.ShouldProcess("delegatedauthorization for bot $BotId", 'Create')) {
        try {
            $r = Invoke-Dv -Method POST -Path 'delegatedauthorizations?$select=delegatedauthorizationid' -Body $daBody
            $daId = $r.delegatedauthorizationid
        } catch {
            $concurrent = Read-AgentAuthorization
            if (-not $concurrent.Authorization) { throw }
            $daId = $concurrent.Authorization.delegatedauthorizationid
        }
        if (-not $daId) { throw '[WD-AUTH-INVALID-RECORDS] Authorization creation returned no record ID. Check the selected agent before retrying.' }
        Write-Create "delegatedauthorization $daId"
    } else {
        Write-Create "would create delegatedauthorization (providertype $ProviderTypeMcsBot)"
        $daId = '<whatif>'
    }
}

Write-Step "Step 3/4 - access team linked to the delegated authorization"
if ($daId -ne '<whatif>') {
    $current = Read-AgentAuthorization
    if (-not $current.Authorization -or $current.Authorization.delegatedauthorizationid -ne $daId) {
        throw '[WD-AUTH-INVALID-RECORDS] Authorization ownership changed. Refresh the runtime plan before retrying.'
    }
    if (-not $snapshot.Team -and $current.Team -and (
        $current.Team.name -ne $TeamName -or
        $current.Team._businessunitid_value -ne $BusinessUnitId.ToString()
    )) {
        throw '[WD-AUTH-INVALID-RECORDS] A concurrent team differs from the reviewed name or business unit. Refresh the runtime plan.'
    }
    $snapshot = $current
}
if ($snapshot.Team) {
    $teamId = $snapshot.Team.teamid
    Write-Reuse "team $teamId '$($snapshot.Team.name)' (teamtype $TeamTypeAccess)"
} else {
    $teamBody = @{
        name                                  = $TeamName
        teamtype                              = $TeamTypeAccess
        'businessunitid@odata.bind'           = "/businessunits($BusinessUnitId)"
        'administratorid@odata.bind'          = "/systemusers($AdministratorId)"
        'delegatedauthorizationid@odata.bind' = "/delegatedauthorizations($daId)"
    }
    if ($PSCmdlet.ShouldProcess("access team for bot $BotId", 'Create')) {
        try {
            $r = Invoke-Dv -Method POST -Path 'teams?$select=teamid' -Body $teamBody
            $teamId = $r.teamid
        } catch {
            $concurrent = Read-AgentAuthorization
            if (-not $concurrent.Team -or
                $concurrent.Authorization.delegatedauthorizationid -ne $daId -or
                $concurrent.Team.name -ne $TeamName -or
                $concurrent.Team._businessunitid_value -ne $BusinessUnitId.ToString()
            ) { throw }
            $teamId = $concurrent.Team.teamid
        }
        if (-not $teamId) { throw '[WD-AUTH-INVALID-RECORDS] Team creation returned no record ID. Check the selected agent before retrying.' }
        Write-Create "team $teamId"
    } else {
        Write-Create "would create access team (teamtype $TeamTypeAccess)"
        $teamId = '<whatif>'
    }
}

# --------------------------------------------------------------------------------------------
Write-Step "Step 4/4 - share each workflow with the team"

foreach ($wf in $WorkflowId) {

    $wfName = $workflowRows[$wf.ToString()].name

    $shared = $false
    if ($teamId -ne '<whatif>') {
        # RetrieveSharedPrincipalsAndAccess is a FUNCTION, not an action. POSTing it returns
        # 0x80060888 "Resource not found for the segment".
        $tid = '{"@odata.id":"workflows(' + $wf + ')"}'
        $spUri = "$ApiBase/RetrieveSharedPrincipalsAndAccess(Target=@tid)?@tid=" + [uri]::EscapeDataString($tid)
        $sp = Invoke-Dv -Path $spUri
        $match = $sp.PrincipalAccesses | Where-Object {
            $_.Principal.'@odata.type' -match 'team' -and $_.Principal.ownerid -eq $teamId
        }
        if ($match) {
            if ($match.AccessMask -match 'WriteAccess') {
                Write-Reuse "'$wfName' already shared with the team (mask: $($match.AccessMask))"
                $shared = $true
            } else {
                Write-Host "  [fix]    '$wfName' shared but mask lacks WriteAccess ($($match.AccessMask)) - re-granting" -ForegroundColor Yellow
            }
        }
    }

    if (-not $shared) {
        $grant = @{
            Target          = @{ '@odata.type' = 'Microsoft.Dynamics.CRM.workflow'; workflowid = $wf.ToString() }
            PrincipalAccess = @{
                Principal  = @{ '@odata.type' = 'Microsoft.Dynamics.CRM.team'; teamid = $teamId }
                AccessMask = $AccessMask
            }
        }
        if ($PSCmdlet.ShouldProcess("workflow '$wfName' ($wf)", "Grant $AccessMask to team $teamId")) {
            # GrantAccess is idempotent enough in practice, but ModifyAccess is the documented
            # call when a share already exists. Try GrantAccess, fall back to ModifyAccess.
            try   { Invoke-Dv -Method POST -Path 'GrantAccess'  -Body $grant | Out-Null }
            catch { Invoke-Dv -Method POST -Path 'ModifyAccess' -Body $grant | Out-Null }
            Write-Create "'$wfName' shared with team ($AccessMask)"
        } else {
            Write-Create "would share '$wfName' with the team"
        }
    }
}

# --------------------------------------------------------------------------------------------
Write-Step 'Verification - replaying the exact lookups Flow-RP performs'

$ok = $true

$verification = Read-AgentAuthorization
$teamCheck = @()
if ($verification.Team) { $teamCheck = @($verification.Team) }
if ($teamCheck.Count -eq 1 -and $teamCheck[0].teamid -eq $teamId -and
    $verification.Authorization.delegatedauthorizationid -eq $daId
) {
    $verifiedTeamId = $teamCheck[0].teamid
    Write-Ok "GetTeamsForBotId returns 1 team ($verifiedTeamId)"
} else {
    Write-Fail "GetTeamsForBotId returned $($teamCheck.Count) teams or a different authorization target; expected the exact reviewed team"
    $verifiedTeamId = $null
    $ok = $false
}

foreach ($wf in $WorkflowId) {
    $tid = '{"@odata.id":"workflows(' + $wf + ')"}'
    $spUri = "$ApiBase/RetrieveSharedPrincipalsAndAccess(Target=@tid)?@tid=" + [uri]::EscapeDataString($tid)
    try { $sp = Invoke-Dv -Path $spUri } catch { Write-Fail "$wf - could not read shares: $_"; $ok = $false; continue }

    $match = $sp.PrincipalAccesses | Where-Object {
        $_.Principal.'@odata.type' -match 'team' -and $_.Principal.ownerid -eq $verifiedTeamId
    }
    if ($match -and $match.AccessMask -match 'WriteAccess') {
        # XrmPrincipalAccessExtensions.ToUserAccessType: a mask containing WriteAccess maps to
        # UserAccessType.Owner, the maximum, which is unambiguously sufficient for install.
        Write-Ok "$wf resolves to UserAccessType.Owner (mask: $($match.AccessMask))"
    } else {
        Write-Fail "$wf is NOT shared with the team with WriteAccess"
        $ok = $false
    }
}

Write-Host ''
if ($ok) {
    Write-Host 'Dataverse authorization is in place.' -ForegroundColor Green
    Write-Host 'Remaining steps, outside this script:' -ForegroundColor Green
    Write-Host '  - Ensure the flow connection reference has connectionparametersetconfig populated (UX workstream).'
    Write-Host '  - Ensure delegated authorization is NOT suppressed for Cosmos-backed agents (product code workstream).'
    Write-Host '  - Clear cached user flow state before retesting: POST user-connections with connectionId null, or use a fresh user.'
    exit 0
} else {
    Write-Host 'Verification FAILED - see [FAIL] lines above.' -ForegroundColor Red
    exit 1
}