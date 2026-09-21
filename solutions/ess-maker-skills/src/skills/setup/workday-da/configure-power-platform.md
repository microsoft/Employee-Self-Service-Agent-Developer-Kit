<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# DA-4 — Configure Power Platform and Agent Integration

Role: **Environment Maker**, with a **Power Platform Administrator** for
bot-to-flow authorization and **InfoSec/IT** for network allowlisting. This step
applies the Workday and Entra values captured earlier to the installed ESS DA HR
extension. It owns checklist rows **DA4.1 through DA4.8**.

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not claim that a manual portal setting was verified automatically.

The two required connection references are:

| Connection | Logical name |
| --- | --- |
| Workday OAuthUser | `new_sharedworkdaysoap_ff0df` |
| Microsoft Dataverse | `msviess_sharedcommondataserviceforapps_92b66` |

Never reuse Dev connection IDs, bot IDs, or workflow IDs in another
environment.

---

## DA4.0 — Determine fresh setup or simplified-setup upgrade

Ask whether this environment is a fresh simplified setup or an upgrade from a
legacy ISU/RaaS Workday installation.

- **Fresh setup** — continue normally.
- **Upgrade** — explain that updating the Workday package can make its
  connection stale. Reuse and update the existing Workday API client where
  appropriate, add the required functional areas and Workday-owned scope,
  reconnect the Power Platform connection, and move to the package's V2
  signed-in-user context. Do not decommission the legacy ISU, security groups,
  RaaS reports, or credentials until the simplified path has passed in every
  environment and has been observed for an agreed business cycle.

Persist `installPath: "simplified"` and, for an upgrade, also persist
`migrationSource: "legacy-isu-raas"`.

## DA4.1 — Connect the Workday OAuthUser reference

**Message:**

Now we'll create or reconnect the Workday connection used on behalf of each
signed-in employee.

In the Power Apps maker portal, select this environment and open the installed
Workday solution. Configure the **OAuthUser** connection reference using a
Workday connection with **Microsoft Entra ID Integrated** authentication.

Use the values captured earlier:

- Microsoft Entra resource URL: the Workday SAML identifier configured for
  this tenant, not the `api://` application ID URI.
- OAuth token URL: `{oauthTokenUrl}`.
- Workday API client ID: `{oauthClientId}`.
- SOAP base URL: `{soapBaseUrl}`.
- REST base URL: `{restBaseUrl}`. It must end exactly at `/api`.

Even if the page shows every reference as connected after the first connection,
open and configure each reference separately.

**End message.**

Ask the maker to confirm that OAuthUser is connected with the values above.
Record DA4.1 with `GATE="manual"`, `ACK=true`, and evidence describing the
connection name and environment. If it is not connected, leave the row
`in-progress`.

## DA4.2 — Connect the Dataverse reference

**Message:**

In the same Workday solution, configure the **Microsoft Dataverse** connection
reference with an active connection owned by your maker account. Confirm it
targets this environment, not a Dev connection copied from another environment.

**End message.**

Ask for confirmation and record DA4.2 as a manual row with the connection name
and environment in the evidence.

## DA4.3 — Share parameters and repair stale connections

**Message:**

Open the Workday connection's **Connection parameters** page and turn on
**Allow permission to share parameters**, then save.

If the parameter values appear empty, turn the setting off and save, turn it
back on and save again, then confirm the REST, SOAP, token, client, and resource
values are still populated.

If the connection is **Stale**, **Needs attention**, or no longer connected
after a package update or parameter change, reconnect it now. Users may also be
asked to authorize again on their next Workday request.

**End message.**

Require explicit confirmation that parameter sharing is enabled, the fields
remain populated, and the connection is connected. Record DA4.3 as manual.

## DA4.4 — Confirm connection binding

Guide the maker through the Workday solution's connection-reference and
connection-parameter configuration. Confirm:

1. OAuthUser is bound to the Workday connection created in DA4.1.
2. Microsoft Dataverse is bound to the Dataverse connection from DA4.2.
3. The required `connectionparametersetconfig` values are populated for the
   target environment.
4. No reference points to a connection from a different environment or user.

The authorization script does not perform this step. Require explicit
confirmation and record DA4.4 as manual.

## DA4.5 — Turn on the Workday cloud flows

Discover the Workday flows installed with the ESS DA HR extension when a
reliable DA-scoped listing is available. If they can be enabled through the
supported Power Platform API, preview the affected flows and ask for approval
before enabling them.

Otherwise show:

**Message:**

Open **Power Apps → Solutions → Workday → Cloud flows**. Turn on every flow used
by the ESS DA HR Agent, then confirm they all show **On**. Do not enable unrelated
flows from other solutions.

**End message.**

Record DA4.5 only after the maker confirms the complete DA Workday flow set is
on.

## DA4.6 — Authorize the DA to use the Workday flows

Use the checked-in authorization script:

`scripts/alm/Enable-CosmosDAFlowAuthorization.ps1`

Execute this PowerShell file directly. Do not translate, regenerate, or replace
it with Python. PowerShell 7 is preferred; Windows PowerShell 5.1 is also
supported by the script syntax.

Resolve parameters instead of asking the maker to paste GUIDs:

- `OrgUrl`: `.local/config.json` → `dataverseEndpoint`.
- `BotId`: active ESS DA HR agent → `agent.botId`.
- `WorkflowId[]`: the target Workday workflow IDs referenced by the active
  agent's Workday topics. Resolve topic `flowId` values to Dataverse
  `workflowid` values and exclude unrelated flows.
- `TeamName`: a deterministic name containing the agent and environment.

If the bot or workflow set cannot be resolved unambiguously, stop and explain
which value is missing. Never guess or run the script with a partial flow set.

Before invoking the checked-in version, perform the same read-only
delegated-authorization and team lookups documented by the script:

- exactly one MCSBot delegated authorization and one linked Access team already
  exist for the bot → the script may verify/reuse them and add missing workflow
  shares;
- no authorization or team exists → stop before apply. The checked-in source
  version requires a Microsoft-owned update that requests Dataverse POST
  representations before it can safely create and bind those records;
- more than one linked team exists → stop and require administrator
  remediation. Do not rely on the script's exit code because this source
  version can print `[FAIL]` for multiple teams without returning failure.

First run the script with `-WhatIf`, show the target organization, agent, and
flow display names, and obtain explicit approval. Then run the same command
without `-WhatIf`.

When the authorization and team already exist but workflow shares are missing,
the unchanged script's `-WhatIf` run may exit `1` after showing the correct
`would share` plan. This happens because its final verification checks for
shares that `-WhatIf` intentionally did not write. Treat that preview as
acceptable only when the target values are correct and every `[FAIL]` is solely
an expected missing share corresponding to a listed preview operation. A
`would create` authorization/team operation, authentication, permission,
lookup, missing-flow, wrong-target, or unexpected-existing-record error remains
blocking. Do not apply based on an ambiguous preview.

DA4.6 passes only when the preflight found exactly one linked Access team, the
script exits with code `0`, ends with
`Dataverse authorization is in place.`, returns one access team for the target
bot, contains no `[FAIL]` line, and confirms `WriteAccess` for every supplied
workflow. On any failure,
leave the row blocked and show the script error. Do not replace this with an
attestation.

After successful apply verification, update DA4.6 through
[`shared/checklist-updater.md`](shared/checklist-updater.md) with
`STEP_ID="DA4.6"`, `GATE="prog"`, and
`CHECKPOINT_RESULT="PASSED"`, `RESULT_SOURCE="external"`, and
`EXTERNAL_EVIDENCE` containing the target environment, bot, workflow display
names, script exit code, and verification summary. Render that summary instead
of reading `workspace/flightcheck/results.json`. On an apply or verification
failure, use `CHECKPOINT_RESULT="FAILED"`, `RESULT_SOURCE="external"`, and the
safe failure summary so the row becomes blocked.

## DA4.7 — Configure employee context and selected topics

Inspect the installed DA package before changing the agent. Do not assume the
CEA topic name or file shape. Identify the package's V2 signed-in-user context
component that uses the Workday `/workers/me` path.

Present the available Workday topics and let the maker choose which scenarios
to enable. Preview the exact topic changes and obtain approval before mutating
the agent. Confirm:

- the DA-equivalent V2 user-context component is enabled and wired;
- selected topics are enabled;
- unselected topics remain disabled;
- no legacy ISU/RaaS user-context component is selected for the simplified
  path.

If the package does not expose enough metadata to make this safe, provide the
equivalent Copilot Studio steps and record DA4.7 as manual after confirmation.

## DA4.8 — Record firewall allowlisting

**Message:**

Your InfoSec/IT team must allow outbound access from the Power Platform Workday
managed connectors to these Workday hosts:

- REST: `{restBaseUrl host}`
- SOAP: `{soapBaseUrl host}`

Has that allowlisting been put in place for this environment?

**End message.**

This is an attestation, not a local connectivity test. Record DA4.8 only after
explicit acknowledgement and captured evidence.

Return to the orchestrator.
