# ESS DA Workday authorization in Test and Production

`Enable-CosmosDAFlowAuthorization.ps1` is the idempotent post-deployment script
for ESS Declarative Agent flow authorization. It creates or reuses the
Dataverse delegated authorization and access team required by a Cosmos-backed
ESS Declarative Agent, shares the target Workday cloud flows with that team,
and verifies the resulting access. Run the checked-in script as documented;
do not modify its implementation.

## PowerShell is the supported implementation

Run the checked-in `.ps1` directly. Do not port or replace the partner
implementation with Python. ADK orchestration may resolve parameters, preview
the operation, and invoke the script, but the authorization implementation
remains in the unchanged PowerShell file. The repository already uses
PowerShell for its Windows installers and CI smoke tests, and this script
parses under both PowerShell 7 and Windows PowerShell 5.1.

PowerShell 7 (`pwsh`) is preferred. The script also requires Azure CLI (`az`) in
the same process environment. A normal Git clone does not require changing the
machine execution policy. If organizational policy prevents local scripts from
running, use the customer-approved signed-script or pipeline process rather
than weakening the machine-wide execution policy.

This release supports the **ESS DA HR Agent** only. Do not run this procedure
for the ESS DA IT Agent.

## When to run it

In the development environment, `/connect workday` owns the guided setup and
can invoke this authorization operation after the ESS DA HR agent and Workday
flows exist.

Makers are not expected to run `/connect workday` in Test or Production.
Instead, a Power Platform administrator runs this script as a post-deployment
step in each target environment:

1. Deploy the ESS DA HR agent.
2. Install or upgrade the Workday extension package.
3. Apply the target environment's Workday and Dataverse connections.
4. Capture the target environment parameters below.
5. Run the script with `-WhatIf`.
6. Review the preview and obtain the normal deployment approval.
7. Run the script without `-WhatIf`.
8. Complete the connection-binding and runtime checks for that environment.

Run the operation separately in Test and Production. Never reuse Dev GUIDs.

## Prerequisites

- PowerShell 7 or Windows PowerShell.
- Azure CLI (`az`) installed.
- An Azure CLI sign-in to the Entra tenant that owns the target environment.
- Dataverse System Administrator access in the target environment.
- The ESS DA HR agent and Workday extension package already deployed.
- The Workday cloud flows already present in the target environment.

The script acquires a Dataverse token through Azure CLI. Do not pass an access
token, password, client secret, or Workday credential to the script.

## Required parameters

| Parameter | Meaning | How to obtain it |
| --- | --- | --- |
| `OrgUrl` | Target Dataverse organization URL | In the Power Platform admin center, open the target environment and copy its environment URL. Use the Test URL for Test and the Production URL for Production. |
| `BotId` | Target environment's ESS DA HR `CdsBotId` | Capture it from the ESS DA HR deployment or installation output for that target environment. If deployment is automated, expose it as a pipeline output or environment-scoped variable. Do not use the Dev bot ID. |
| `WorkflowId` | One or more target Workday cloud-flow `workflowid` GUIDs | In the target environment, open the installed Workday solution, list its cloud flows, and capture the GUID for every flow the ESS DA HR agent invokes. A flow's GUID is also the `flowId` referenced by the agent topic and the Dataverse `workflowid`. Do not include unrelated environment flows. |

Optional parameters:

| Parameter | Recommendation |
| --- | --- |
| `TeamName` | Use a stable target-specific name such as `ESS DA HR Workday - Test`. |
| `AdministratorId` | Omit unless your governance process requires a specific enabled System Administrator to own the team. |
| `BusinessUnitId` | Omit to let the script use the root business unit. |
| `AccessMask` | Keep the script's default unless updated Microsoft product guidance specifies a replacement. |

If the deployment process cannot unambiguously identify the target bot or
Workday flows, stop the deployment. Do not guess GUIDs.

## Sign in and verify the target

```powershell
az login --tenant "<target-tenant-id>"
az account show
az account get-access-token `
  --resource "https://<target-org>.crm.dynamics.com" `
  --query accessToken `
  --output tsv | Out-Null
```

The final command confirms that Azure CLI can acquire a token for the exact
target organization. It does not print or persist the token.

## Prepare the target parameters

Use values captured from the same target environment:

```powershell
$OrgUrl = "https://<target-org>.crm.dynamics.com"
$BotId = [guid]"<target-ess-da-hr-cdsbotid>"
$WorkflowIds = [guid[]]@(
    "<target-workday-workflow-id-1>",
    "<target-workday-workflow-id-2>"
)
$TeamName = "ESS DA HR Workday - Test"
```

For Production, replace every value with the Production environment value and
use a Production-specific team name.

## Preview

Run the authorization script with `-WhatIf` first:

```powershell
& ".\Enable-CosmosDAFlowAuthorization.ps1" `
    -OrgUrl $OrgUrl `
    -BotId $BotId `
    -WorkflowId $WorkflowIds `
    -TeamName $TeamName `
    -WhatIf
```

Review that the output targets:

- the intended Dataverse organization;
- the intended ESS DA HR bot;
- only the expected Workday workflows;
- an access team, not an owner team.

### New-environment `-WhatIf` behavior

The authorization script performs its final live verification after the
preview. In a new environment where the delegated authorization, access team,
or workflow shares do not exist yet, `-WhatIf` intentionally does not create
them. The final verification therefore prints `[FAIL]` for those not-yet-created
records and exits with code `1`.

For the preview only, this is expected when all of the following are true:

- each intended create/share operation is shown as `would create` or
  `would share`;
- the target organization, bot, team type, and workflows are correct;
- the only `[FAIL]` lines describe records that the preview intentionally did
  not create.

Any authentication, lookup, permission, wrong-target, missing-workflow,
unexpected existing-record, or Dataverse request error is a real preview
failure and must be resolved before apply. The real apply run must still meet
the strict success criteria below.

## Apply

After deployment approval, run the same command without `-WhatIf`:

```powershell
& ".\Enable-CosmosDAFlowAuthorization.ps1" `
    -OrgUrl $OrgUrl `
    -BotId $BotId `
    -WorkflowId $WorkflowIds `
    -TeamName $TeamName
```

The script is idempotent. Re-running it reuses valid existing records and adds
only missing workflow access.

## Successful result

The command must exit with code `0` and end with:

```text
Dataverse authorization is in place.
```

The verification output must also show:

- one team returned for the target bot;
- every supplied Workday workflow shared with that team;
- an access mask containing `WriteAccess`.

Treat any `[FAIL]` line or nonzero exit code as a deployment failure.
This strict rule applies to the real apply run. The documented new-environment
`-WhatIf` exception applies only to the preview and only under the conditions
listed above.

## Remaining target-environment steps

This script covers only DA bot-to-flow Dataverse authorization. Before release
sign-off, also confirm:

- Workday and Dataverse connection references use the target environment's
  connections;
- required connection parameter configuration is populated;
- Workday cloud flows are turned on;
- stale user flow-connection state is cleared, or validation uses a fresh
  test user;
- a signed-in test user can complete a Workday scenario through the ESS DA HR
  agent.

Record the parameter source, script output, and final runtime result in the
deployment evidence for each environment.
