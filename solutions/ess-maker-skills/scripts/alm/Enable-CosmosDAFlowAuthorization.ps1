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

.PARAMETER TeamName
    Optional display name for the access team.

.PARAMETER AdministratorId
    Optional systemuserid to own the team. Must hold System Administrator. Auto-resolved if omitted.

.PARAMETER BusinessUnitId
    Optional business unit. Defaults to the org's root business unit.

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
    Requires Azure CLI, signed in to an account with Dataverse system-administrator rights on
    the target org. Run Steps in the ESS runbook order: this script covers steps 2-4.
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]   $OrgUrl,
    [Parameter(Mandatory = $true)][guid]     $BotId,
    [Parameter(Mandatory = $true)][guid[]]   $WorkflowId,
    [string] $TeamName,
    [guid]   $AdministratorId,
    [guid]   $BusinessUnitId,
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

function Get-DataverseToken {
    param([string]$Resource)
    try {
        $tok = az account get-access-token --resource $Resource --query accessToken -o tsv 2>$null
    } catch {
        throw "Azure CLI token acquisition failed. Run 'az login' and ensure the account has access to $Resource."
    }
    if ([string]::IsNullOrWhiteSpace($tok)) {
        throw "Could not acquire a Dataverse token for $Resource. Check 'az account show' and that the correct subscription/tenant is selected."
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

# --------------------------------------------------------------------------------------------
Write-Step "Connecting to $OrgUrl"
$script:Token = Get-DataverseToken -Resource $OrgUrl
$who = Invoke-Dv -Path 'WhoAmI'
Write-Ok "Authenticated. UserId $($who.UserId), OrgId $($who.OrganizationId)"

# --------------------------------------------------------------------------------------------
Write-Step "Step 2/4 - delegatedauthorization for bot $BotId"

$daFilter = "delegatedauthorizations?`$select=delegatedauthorizationid,name,providertype&`$filter=botid eq '$BotId'"
$daExisting = (Invoke-Dv -Path $daFilter).value

if ($daExisting.Count -gt 0) {
    $daId = $daExisting[0].delegatedauthorizationid
    Write-Reuse "delegatedauthorization $daId (providertype $($daExisting[0].providertype))"
    if ($daExisting[0].providertype -ne $ProviderTypeMcsBot) {
        Write-Fail "Existing delegated authorization has providertype $($daExisting[0].providertype); expected $ProviderTypeMcsBot (MCSBot). Resolve manually."
        exit 1
    }
} else {
    $daBody = @{
        name         = if ($TeamName) { "$TeamName delegated auth" } else { "Cosmos DA delegated auth ($BotId)" }
        providertype = $ProviderTypeMcsBot
        botid        = $BotId.ToString()
    }
    if ($PSCmdlet.ShouldProcess("delegatedauthorization for bot $BotId", 'Create')) {
        $r = Invoke-Dv -Method POST -Path 'delegatedauthorizations?$select=delegatedauthorizationid' -Body $daBody
        $daId = $r.delegatedauthorizationid
        Write-Create "delegatedauthorization $daId"
    } else {
        Write-Create "would create delegatedauthorization (providertype $ProviderTypeMcsBot)"
        $daId = '<whatif>'
    }
}

# --------------------------------------------------------------------------------------------
Write-Step "Step 3/4 - access team linked to the delegated authorization"

# Query exactly the way Flow-RP does (XrmRequestFactory.GetTeamsForBotIdUri), so a hit here
# means Flow-RP will resolve the bot successfully.
$teamFilter = "teams?`$expand=delegatedauthorizationid&`$filter=delegatedauthorizationid/botid eq '$BotId'&`$select=teamid,name,teamtype"
$teamExisting = (Invoke-Dv -Path $teamFilter).value

if ($teamExisting.Count -gt 0) {
    $teamId = $teamExisting[0].teamid
    Write-Reuse "team $teamId '$($teamExisting[0].name)' (teamtype $($teamExisting[0].teamtype))"
    if ($teamExisting[0].teamtype -ne $TeamTypeAccess) {
        Write-Fail "Existing team is teamtype $($teamExisting[0].teamtype); must be $TeamTypeAccess (Access). Resolve manually."
        exit 1
    }
} else {
    if (-not $BusinessUnitId) {
        $bu = (Invoke-Dv -Path 'businessunits?$select=businessunitid,name&$filter=parentbusinessunitid eq null').value
        if (-not $bu) { throw 'Could not resolve the root business unit. Pass -BusinessUnitId explicitly.' }
        $BusinessUnitId = $bu[0].businessunitid
        Write-Ok "Resolved root business unit $BusinessUnitId ($($bu[0].name))"
    }

    if (-not $AdministratorId) {
        # The team administrator must hold System Administrator, otherwise team creation fails
        # with 0x80041d0a "The team administrator does not have privilege read team."
        $admins = (Invoke-Dv -Path ("systemuserrolescollection?`$select=systemuserid&`$top=0")) 2>$null
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

    $teamBody = @{
        name                                  = if ($TeamName) { $TeamName } else { "Cosmos DA bot team ($BotId)" }
        teamtype                              = $TeamTypeAccess
        'businessunitid@odata.bind'           = "/businessunits($BusinessUnitId)"
        'administratorid@odata.bind'          = "/systemusers($AdministratorId)"
        'delegatedauthorizationid@odata.bind' = "/delegatedauthorizations($daId)"
    }
    if ($PSCmdlet.ShouldProcess("access team for bot $BotId", 'Create')) {
        $r = Invoke-Dv -Method POST -Path 'teams?$select=teamid' -Body $teamBody
        $teamId = $r.teamid
        Write-Create "team $teamId"
    } else {
        Write-Create "would create access team (teamtype $TeamTypeAccess)"
        $teamId = '<whatif>'
    }
}

# --------------------------------------------------------------------------------------------
Write-Step "Step 4/4 - share each workflow with the team"

foreach ($wf in $WorkflowId) {

    $wfRow = (Invoke-Dv -Path "workflows?`$select=workflowid,name,statecode&`$filter=workflowid eq $wf").value
    if (-not $wfRow) {
        Write-Fail "workflow $wf not found in this organization - skipping"
        continue
    }
    $wfName = $wfRow[0].name

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

$teamCheck = (Invoke-Dv -Path $teamFilter).value
if ($teamCheck.Count -eq 1) {
    Write-Ok "GetTeamsForBotId returns 1 team ($($teamCheck[0].teamid))"
} else {
    Write-Fail "GetTeamsForBotId returned $($teamCheck.Count) teams; Flow-RP takes the first and expects exactly one"
    if ($teamCheck.Count -eq 0) { $ok = $false }
}

foreach ($wf in $WorkflowId) {
    $tid = '{"@odata.id":"workflows(' + $wf + ')"}'
    $spUri = "$ApiBase/RetrieveSharedPrincipalsAndAccess(Target=@tid)?@tid=" + [uri]::EscapeDataString($tid)
    try { $sp = Invoke-Dv -Path $spUri } catch { Write-Fail "$wf - could not read shares: $_"; $ok = $false; continue }

    $match = $sp.PrincipalAccesses | Where-Object {
        $_.Principal.'@odata.type' -match 'team' -and $_.Principal.ownerid -eq $teamCheck[0].teamid
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