# Authorize Workday flows after deployment

Use this procedure after deploying the **ESS DA HR agent** and the Workday
extension package to a Test or Production environment. It gives the agent
permission to use the Workday cloud flows in that environment.

This is a post-deployment task for a Power Platform administrator. Complete it
separately in every target environment. Do not reuse IDs from Development,
Test, or another environment.

> This procedure supports the ESS DA HR agent only. Do not use it for the
> ESS DA IT agent.

## Before you begin

Confirm that:

- the ESS DA HR agent is deployed to the target environment;
- the Workday extension package is installed or upgraded;
- the target environment contains the required Workday cloud flows;
- Workday and Dataverse connections are configured for the target environment;
- you have Dataverse System Administrator access;
- PowerShell and Azure CLI are available; and
- you can sign in to the Microsoft Entra tenant that owns the environment.

Do not provide passwords, access tokens, client secrets, Workday credentials,
certificate contents, or private keys.

## Gather the environment details

Collect all values from the same target environment:

| Information | What to use |
| --- | --- |
| Environment URL (`OrgUrl`) | The environment URL shown in the Power Platform admin center, such as `https://contoso.crm.dynamics.com`. |
| ESS DA HR agent ID (`BotId`) | The agent's `CdsBotId` from the deployment or installation output. |
| Workday flow IDs (`WorkflowId`) | The `workflowid` for every Workday cloud flow used by the agent. Do not include unrelated flows. |
| Authorization team name (`TeamName`) | A clear environment-specific name, such as `ESS DA HR Workday - Test`. |

If you cannot confidently identify the agent or its Workday flows, stop and
confirm the deployment details. Do not guess IDs.

## Authorize the flows

### 1. Open the authorization folder

From the kit's repository folder, open PowerShell and run:

```powershell
Set-Location ".\solutions\ess-maker-skills\scripts\alm"
```

### 2. Sign in to the target tenant

```powershell
az login --tenant "<target-tenant-id>"
az account show --output table
```

Confirm that the displayed tenant is the tenant for the target Power Platform
environment.

### 3. Enter the target environment values

The following example uses Test values. Replace every placeholder with the
values collected from your Test environment:

```powershell
$OrgUrl = "https://<test-org>.crm.dynamics.com"
$BotId = [guid]"<test-ess-da-hr-cdsbotid>"
$WorkflowIds = [guid[]]@(
    "<test-workday-workflow-id-1>",
    "<test-workday-workflow-id-2>"
)
$TeamName = "ESS DA HR Workday - Test"
```

### 4. Preview the changes

Always preview the operation before applying it:

```powershell
& ".\Enable-CosmosDAFlowAuthorization.ps1" `
    -OrgUrl $OrgUrl `
    -BotId $BotId `
    -WorkflowId $WorkflowIds `
    -TeamName $TeamName `
    -WhatIf
```

Review the preview and confirm that it shows:

- the intended environment URL;
- the intended ESS DA HR agent;
- only the expected Workday flows; and
- an access team with the expected environment-specific name.

Resolve any wrong-environment, sign-in, permission, missing-flow, or duplicate
record message before continuing.

#### First-time environment preview

In a new environment, the preview does not create the authorization records or
share the flows. It can therefore end with `[FAIL]` messages and exit code `1`
for records that do not exist yet.

This is expected only when:

- the preview says it **would create** the authorization and access team;
- the preview says it **would share** each expected Workday flow; and
- the environment, agent, team, and flow IDs are all correct.

Any other failure must be resolved before applying the changes.

### 5. Apply the changes

After reviewing and approving the preview, run the same command without
`-WhatIf`:

```powershell
& ".\Enable-CosmosDAFlowAuthorization.ps1" `
    -OrgUrl $OrgUrl `
    -BotId $BotId `
    -WorkflowId $WorkflowIds `
    -TeamName $TeamName
```

The operation can be run again safely. Existing valid authorization is reused,
and only missing Workday flow access is added.

## Confirm success

A successful run exits with code `0` and ends with:

```text
Dataverse authorization is in place.
```

The results must confirm that:

- one access team is associated with the target ESS DA HR agent;
- every supplied Workday flow is shared with that team; and
- no `[FAIL]` message is present.

Treat a nonzero exit code or any `[FAIL]` message during the apply step as a
deployment failure.

## Repeat for Production

Repeat the full process for Production using only Production values:

- Production environment URL;
- Production ESS DA HR agent ID;
- Production Workday flow IDs; and
- a Production-specific team name.

Do not copy the Test or Development IDs into Production.

## Complete the deployment check

Before release sign-off, also confirm that:

- Workday and Dataverse connection references use the target environment's
  connections;
- required connection settings are populated;
- the Workday cloud flows are turned on; and
- a signed-in test user can complete a Workday scenario through the ESS DA HR
  agent.

Keep the approved preview, apply results, source of the environment values, and
final runtime result with the deployment evidence for that environment.

## Additional options

Most deployments should use the defaults shown above. If your governance
process requires a specific administrator, business unit, or access setting,
review the built-in command help before running the operation:

```powershell
Get-Help ".\Enable-CosmosDAFlowAuthorization.ps1" -Detailed
```

Use the checked-in authorization file without modifying it for an individual
environment.
