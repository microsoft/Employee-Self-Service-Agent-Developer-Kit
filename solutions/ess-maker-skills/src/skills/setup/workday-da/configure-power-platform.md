<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# DA-4 — Configure Power Platform and Agent Integration

Role: **Environment Maker**, with a **Power Platform Administrator** for
bot-to-flow authorization and **InfoSec/IT** for network allowlisting. This step
applies the Workday and Entra values captured earlier to the installed ESS DA HR
extension. It owns checklist rows **DA4.1 through DA4.8**.

Every **Message** block is the exact text to show the user. Copy it verbatim. Do
not claim that a manual portal setting was verified automatically.

The two required runtime connection references are:

| Connection | Logical name |
| --- | --- |
| Workday OAuthUser | `msdyn_sharedworkdaysoap_workdayruntime` |
| Microsoft Dataverse | `msdyn_sharedcommondataserviceforapps_workdayruntime` |

Never reuse Dev connection IDs, bot IDs, or workflow IDs in another
environment.

---

## DA4.0 — Prepare the connections page

This setup always uses the signed-in employee Workday runtime. Do not present
an installation-path or migration choice.

Build the environment's Connections URL from the recorded ring:

- `preprod` →
  `https://make.preprod.powerautomate.com/environments/{ENV_ID}/connections`
- `prod` →
  `https://make.powerautomate.com/environments/{ENV_ID}/connections`

Persist `installPath: "simplified"`.

## DA4.1 — Connect the Workday OAuthUser reference

**Message:**

Now we'll create the two connections the Workday runtime needs.

Open this environment's **Connections** page:

{CONNECTIONS_URL}

1. Select **New connection**, search for **Workday**, and create a connection
   using **Microsoft Entra ID Integrated** authentication.
3. Enter the values below. Complete the sign-in/consent window if one opens.
4. Wait until the Workday connection shows **Connected**.

Use the values captured earlier:

- Microsoft Entra resource URL: the Workday SAML identifier configured for
  this tenant, not the `api://` application ID URI.
- OAuth token URL: `{oauthTokenUrl}`.
- Workday API client ID: `{oauthClientId}`.
- SOAP base URL: `{soapBaseUrl}`.
- REST base URL: `{restBaseUrl}`. It must end exactly at `/api`.

**End message.**

If no Workday connection exists yet, do not ask the maker to confirm the
reference binding—guide the connection creation first. Re-read the ring-native
connection inventory and confirm the new `shared_workdaysoap` connection is
`Connected` and carries the expected resource, token, client, SOAP, REST, and
tenant values.
Record DA4.1 with `GATE="manual"`, `ACK=true`, and evidence describing the
connection name and environment. If it is not connected, leave the row
`in-progress`.

## DA4.2 — Connect the Dataverse reference

**Message:**

On the same **Connections** page, select **New connection** and create a
**Microsoft Dataverse** connection with your maker account. Wait until both the
Workday and Dataverse connections show **Connected**, then tell me they are
ready.

**End message.**

Re-read the ring-native connection inventory and confirm the Dataverse
connection is `Connected` and belongs to this environment. Record DA4.2 with
the connection name and environment in the evidence.

## DA4.3 — Bind the extension connections

Bind the installed solution references programmatically:

1. Resolve the physical Workday and Dataverse connection IDs created in
   DA4.1–DA4.2.
2. PATCH `msdyn_sharedworkdaysoap_workdayruntime.connectionid` to the Workday
   connection ID.
3. PATCH
   `msdyn_sharedcommondataserviceforapps_workdayruntime.connectionid` to the
   Dataverse connection ID.
4. Re-read both rows and confirm the IDs persisted.
5. Confirm neither reference points to a connection from a different
   environment or user.

Preview the two target logical names and connection display names before
PATCHing. The authorization script does not perform this step. Record DA4.3
only after the post-write verification passes.

## DA4.4 — Turn on the Workday cloud flows

Do not activate flows until DA4.1–DA4.3 are complete and the two installed
runtime `connectionreference` rows have non-empty connection bindings. A flow
whose references are unbound may activate but will fail at runtime.

Discover the Workday flows installed with the ESS DA HR extension when a
reliable DA-scoped listing is available. If they can be enabled through the
supported Power Platform API, preview the affected flows and ask for approval
before enabling them.

Otherwise show:

**Message:**

Open **Power Apps → Solutions → Workday → Cloud flows**. Turn on every flow used
by the ESS HR agent, then confirm they all show **On**. Do not enable unrelated
flows from other solutions.

**End message.**

Record DA4.4 only after every target Workday flow is verified as active.

## DA4.5 — Connect the agent and share parameters

**Message:**

The Workday and Dataverse connections are ready and the runtime flows are on.
Now connect those flows to this agent:

1. Open the active agent's **Copilot Studio → Settings → Connection settings**
   page:

   `https://{CPS_HOST}/environments/{ENV_ID}/copilots/{BOT_ID}/da-settings/connectionSettings`
2. Open each Workday flow entry and select **Connect**.
3. Select the Workday connection created earlier and submit.
4. Under **Manage**, select **See details**.
5. Open **Connection parameters**.
6. Turn on **Allow permission to share parameters** and save.

If the parameter values appear empty, turn the setting off and save, turn it
back on and save again, then confirm the REST, SOAP, token, client, and resource
values remain populated.

**End message.**

This is agent/runtime wiring; solution-level binding does not replace it. Do
not infer it from the physical connection inventory's `allowSharing` property.
Require explicit confirmation that every Workday flow entry is connected,
parameter sharing is enabled, the fields remain populated, and the connection
is connected. If a connection is **Stale** or **Needs attention**, reconnect it
before continuing. Record DA4.5 as manual.

## DA4.6 — Authorize the DA to use the Workday flows

Use the checked-in authorization script:

`scripts/alm/Enable-CosmosDAFlowAuthorization.ps1`

Execute this PowerShell file directly. Do not translate, regenerate, or replace
it with Python. PowerShell 7 is preferred; Windows PowerShell 5.1 is also
supported by the script syntax. The script validates the Azure CLI Dataverse
token before use. If that token is rejected (including PPE environments), it
automatically reuses the kit's Dataverse authentication cache and opens the
standard kit sign-in only when a refresh is required.

Resolve parameters instead of asking the maker to paste GUIDs:

- `OrgUrl`: `.local/config.json` `dataverseEndpoint` when present; otherwise
  `.local/connect/workday-da/config.json` `sidecarDataverseEndpoint`. This must
  be the same effective Dataverse environment used by DA-1.
- `BotId`: active ESS DA HR agent → `agent.botId`.
- `WorkflowId[]`: the target Workday workflow IDs referenced by the active
  agent's Workday topics. Resolve topic `flowId` values to Dataverse
  `workflowid` values and exclude unrelated flows.
- `TeamName`: a deterministic name containing the agent and environment.

If the bot or workflow set cannot be resolved unambiguously, stop and explain
which value is missing. Never guess or run the script with a partial flow set.

Before invoking the checked-in script, perform the same read-only
delegated-authorization and team lookups documented by the script:

- exactly one MCSBot delegated authorization and one linked Access team already
  exist for the bot → the script reuses them and adds missing workflow shares;
- no authorization or team exists → the script may create them. Its Dataverse
  writes request `Prefer: return=representation`, so the new record IDs are
  captured and bound in the same run;
- more than one delegated authorization or linked team exists → stop and
  require administrator remediation. The script also fails closed on these
  ambiguous records.

First run the script with `-WhatIf`, show the target organization, agent, and
flow display names, and obtain explicit approval. Then run the same command
without `-WhatIf`.

The script's `-WhatIf` run may exit `1` after showing a correct `would create`
or `would share` plan. This happens because its final verification checks for
records and shares that `-WhatIf` intentionally did not write. Treat that
preview as acceptable only when the target values are correct and every
`[FAIL]` corresponds exactly to a listed preview operation. Authentication,
permission, lookup, missing-flow, wrong-target, conflicting-existing-record, or
multiple-team errors remain blocking. Do not apply based on an ambiguous
preview.

DA4.6 passes only when the applied result has exactly one linked Access team,
the script exits with code `0`, ends with
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

## DA4.7 — Configure employee context and Workday topics

Inspect the installed DA package before changing the agent. Do not assume the
CEA topic name or file shape. Identify the package's V2 signed-in-user context
component that uses the Workday `/workers/me` path.

Present these choices:

1. **Enable all Workday topics** — recommended for makers who want the complete
   Workday experience.
2. **Choose specific Workday topics** — show a multi-select list of available
   business scenarios.
3. **Keep the current topic selection** — make no topic-status changes.

Whichever option is selected, include the V2 signed-in-user context and every
system dependency required by the selected business topics. Preview the exact
topic list and obtain approval before changing anything. Confirm:

- the DA-equivalent V2 user-context component is enabled and wired;
- selected topics are enabled;
- unselected topics remain disabled;
- choosing **Enable all** enables every installed Workday business topic plus
  the required Workday system topics.

Topic activation is server-only state and is not stored in the topic YAML.
The current AgentBuilder client can fetch components, update the bot entity,
import, and publish, but it has no proven per-component status mutation API.
Until a supported API is added, do not guess a MinimalBot payload. Provide the
equivalent Copilot Studio enablement steps, including the **Enable all**
selection, and record DA4.7 as manual after confirmation.

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
