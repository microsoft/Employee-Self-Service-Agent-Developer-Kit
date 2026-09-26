<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# DA-4 — Configure Power Platform and Agent Integration

Role: **Environment Maker**, with a **Power Platform Administrator** for
bot-to-flow authorization. Involve **InfoSec/IT** only when organizational
network controls restrict the Workday hosts. This step applies the Workday and
Entra values captured earlier to the installed ESS DA HR extension. It owns
checklist rows **DA4.1 through DA4.8**.

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
2. Enter the connection fields in the order shown below.
3. Complete the sign-in or consent window if one opens.
4. Wait until the Workday connection shows **Connected**.

**Connection worksheet**

- Workday tenant: `{tenant}` *(verification context; enter it only if the form
  displays a tenant field)*
- Authentication: `Microsoft Entra ID Integrated`

| Connection form field | Value |
| --- | --- |
| Microsoft Entra resource URL | `http://www.workday.com/{tenant}` |
| OAuth token URL | `{oauthTokenUrl}` |
| Workday API client ID | `{oauthClientId}` |
| SOAP base URL | `{soapBaseUrl}` |
| REST base URL | `{restBaseUrl}` |

The Microsoft Entra resource URL is the Workday SAML Identifier / Entity ID
configured for this tenant, not the `api://` application ID URI. The REST base
URL must end exactly at `/api`.

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

**Message:**

The physical connections are created. Newly installed managed-solution flows
can still be **Off** at this point; that is expected until their connection
references are bound. Do not open the agent's Connection settings yet. I'll
bind both references first, then turn on and verify the Workday flows.

**End message.**

## DA4.2a — Approve the remaining runtime changes

When any of DA4.3, DA4.4, DA4.6, or the programmatic UserContext portion of
DA4.7 remains incomplete, prepare one scoped automation plan for the current
environment and active agent.

**Message:**

The two connections are ready. I can now complete the supported runtime
configuration for this environment:

- bind the Workday and Dataverse connection references;
- turn on the reviewed Workday cloud flows;
- authorize this agent to use those flows; and
- connect the employee-context setup topic to Workday User Context V2.

Each operation will run a read-only preview first, apply only to the selected
environment and agent, and verify the result. Topic selection and connecting
the Workday flows in Copilot Studio remain manual. Continue with this runtime
plan?

**End message.**

Use `vscode_askQuestions` with **Continue** and **Cancel** options. Do not
preselect an answer. **Continue** approves all remaining helper operations in
the listed scope for this invocation. **Cancel** pauses without mutation.

Show each helper's preview target names, but do not ask for another approval
when they match the approved environment, agent, connections, and reviewed
flow catalog. If any target or operation differs, stop and return here with a
new consolidated plan.

## DA4.3 — Bind the extension connections

Use the checked-in binding helper:

`scripts/bind_workday_da_connections.py`

Resolve `WORKDAY_DATAVERSE_URL`, `RING`, and the maker account from canonical
setup state; do not ask the maker to paste connection IDs. First preview:

```powershell
python scripts/bind_workday_da_connections.py `
  --url "{WORKDAY_DATAVERSE_URL}" `
  --ring "{RING}" `
  --preferred-username "{MAKER_ACCOUNT}"
```

The helper uses the ring-aware PAC profile to discover connected physical
connections and the Dataverse Web API to read the two installed runtime
references. It fails closed when either connection or reference is missing or
ambiguous. If multiple connected connections exist for a connector, show their
safe display names and ask the maker which one to use, then rerun the preview
with `--workday-connection-id` and/or `--dataverse-connection-id`.

Show the `WORKDAY_DA_BINDING_PLAN_JSON` target display names. When they match
the approved DA4.2a scope, run the identical command with `--apply` without a
second approval. Do not translate or replace the helper with ad hoc PATCH
calls.

The apply run must emit `WORKDAY_DA_BINDING_APPLIED_JSON`, report
`"verified": true`, and post-read:

- `msdyn_sharedworkdaysoap_workdayruntime.connectionid` equal to the selected
  Workday connection name;
- `msdyn_sharedcommondataserviceforapps_workdayruntime.connectionid` equal to
  the selected Dataverse connection name.

If either field remains empty, leave DA4.3 blocked and do not attempt flow
activation. The authorization script does not perform this binding. Record
DA4.3 only after the helper's post-write verification passes.

## DA4.4 — Turn on the Workday cloud flows

The AppSource installer installs the managed package but does not activate its
cloud flows. Seeing the Workday flows **Off** immediately after installation is
therefore expected and is not evidence that the physical connection failed.

Do not activate flows until DA4.1–DA4.3 are complete and the two installed
runtime `connectionreference` rows have non-empty connection bindings. A flow
whose references are unbound may activate but will fail at runtime.

Use the checked-in activation helper:

`scripts/activate_workday_da_flows.py`

The reviewed flow catalog comes from the selected package in
`workday-da.definition.json`; do not discover targets by name prefix or include
similarly named flows from another solution. First preview:

```powershell
python scripts/activate_workday_da_flows.py `
  --url "{WORKDAY_DATAVERSE_URL}" `
  --package-flavor "{PACKAGE_FLAVOR}" `
  --preferred-username "{MAKER_ACCOUNT}"
```

The helper fails closed when either runtime reference is unbound, a reviewed
flow is missing or duplicated, or a matched record is not a cloud flow. Show
the `WORKDAY_DA_FLOW_ACTIVATION_PLAN_JSON` actions. When they match the
approved DA4.2a scope and reviewed catalog, run the identical command with
`--apply` without a second approval. Do not replace the helper with an ad hoc
Dataverse PATCH.

The apply run must emit `WORKDAY_DA_FLOWS_ACTIVATED_JSON` and report
`"verified": true`. If the selected package has no reviewed flow catalog, show:

**Message:**

Open **Power Apps → Solutions → Workday → Cloud flows**. Turn on every flow used
by the ESS HR agent, then confirm they all show **On**. Do not enable unrelated
flows from other solutions.

**End message.**

Record DA4.4 only after every target Workday flow is verified as active. If any
target flow cannot be turned on, show its exact activation error and return to
DA4.3 to verify both bindings. Never continue to agent Connection settings
while a required Workday flow is **Off**.

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
After the maker saves the setting, verify the active agent rather than accepting
only a completion statement:

```powershell
python scripts/flightcheck/cli.py `
  --checkpoint WD-DA-CONN-001 `
  --connect-config ".local/connect/workday-da/config.json" `
  --agent-slug "{ACTIVE_AGENT}"
```

Show the result per
[`shared/checklist-updater.md`](shared/checklist-updater.md) §U.0.

- `PASSED` proves that every connected Workday reference exposed by the active
  agent contains shared connection parameters. Update DA4.5 with
  `GATE="prog"`, `CHECKPOINT_RESULT="PASSED"`, and
  `RESULT_SOURCE="flightcheck"`.
- `FAILED` means at least one connected Workday reference does not contain
  shared parameters. Show the named remediation, leave DA4.5 blocked, and
  rerun the checkpoint after the maker saves the setting again.
- `NOT_CONFIGURED` means the active agent has no connected Workday reference.
  Return to the start of DA4.5 and connect every Workday flow entry.
- `WARNING` or `SKIPPED` means the setting could not be read. Refresh the
  active-agent authentication and retry. If the read remains unavailable, use
  the definition's manual fallback only after explicit confirmation that every
  Workday flow entry is connected, parameter sharing is enabled, the fields
  remain populated, and the connection shows **Connected**. A **Stale** or
  **Needs attention** connection must be reconnected first.

After DA4.5 passes or its documented fallback is completed, show:

**Message:**

The Workday connection parameters are shared with the agent. After the
remaining setup is complete and the agent is published, validate that sharing
works for another employee:

1. Share the agent with a test employee who is not the maker who created the
   Workday connection.
2. Sign in as that employee and start a new conversation.
3. Run a read-only Workday question, such as checking a vacation balance.
4. Confirm the agent returns that employee's Workday data without showing a
   **Connect**, consent, or additional sign-in prompt.
5. If a connection prompt appears, return to **Settings → Connection
   settings**, save **Allow permission to share parameters** again, rerun this
   verification, republish, and retry with a new conversation.

The final Workday validation will ask you to confirm this non-maker test. Do
not use a write or approval scenario until the read-only check succeeds.

**End message.**

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

Do not run this script before DA4.5 is complete. Both invocations below occur
after every Workday flow is connected and **Allow permission to share
parameters** is enabled. The two invocations are preview and apply; they are not
"before sharing" and "after sharing" runs.

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

First run the script with `-WhatIf` and show the target organization, agent,
and flow display names. When they match the approved DA4.2a scope, run the same
command without `-WhatIf`; do not request another approval.

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

Use the checked-in UserContext helper:

`scripts/configure_workday_da_user_context.py`

Resolve the active agent's `botId`, the effective Dataverse URL, and the maker
account from canonical state. Do not ask the maker to paste an agent ID. First
preview:

```powershell
python scripts/configure_workday_da_user_context.py `
  --url "{WORKDAY_DATAVERSE_URL}" `
  --bot-id "{BOT_ID}" `
  --preferred-username "{MAKER_ACCOUNT}"
```

The helper scopes every read to the exact active agent. It requires exactly one
**[Admin] - User Context - Setup** topic and exactly one
**Workday [System] - 1: Set User Context V2** target. It changes only an empty
or bare setup scaffold, reports an already-correct redirect as unchanged, and
refuses to overwrite custom or ambiguous content.

Show the `WORKDAY_DA_USER_CONTEXT_PLAN_JSON` action. If the action is
`configure` and it matches the approved DA4.2a scope, rerun the identical
command with `--apply` without another approval.
The apply run must emit `WORKDAY_DA_USER_CONTEXT_APPLIED_JSON`, report
`"verified": true`, and confirm that the setup topic now redirects to the
installed target topic's exact schema name. The helper changes draft topic
content only; do not publish from this step.

If the helper reports custom content, cannot authenticate, cannot identify the
two topics unambiguously, or fails post-write verification, do not force an
overwrite. Show:

**Message:**

**Switch the user-context topic to V2**

1. In Microsoft Copilot Studio, open the active **ESS HR** agent.
2. Go to **Topics** and open **[Admin] - User Context - Setup**.
3. In the **Topic** node, select the existing topic reference and choose
   **Select a topic**.
4. Search for `v2`.
5. Select **Workday [System] - 1: Set User Context V2**.
6. Save the topic.

Tell me after the topic is saved. I will verify the redirect before completing
this setup step.

**End message.**

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

For the current ESS HR runtime package, the package-managed Workday system
topic catalog is:

- **Workday [System] - 1: Set User Context V2**
- **Workday [System] - 1: Set Runtime Template Configurations**
- **Workday System ParseError**
- **Workday System Get CommonExecution**
- **Workday System Get REST Execution**
- **Workday System Get ReferenceData**
- **Workday System Refresh ReferenceData**
- **Workday System ManagerCheck**
- **Workday System AccessCheck**

Use the installed component inventory as the runtime source of truth and match
these names exactly for the current package. If the active package flavor
exposes a different catalog, stop and report the package/version drift rather
than renaming, recreating, or guessing a substitute system topic.

Topic activation is server-only state and is not stored in the topic YAML.
The current AgentBuilder client can fetch components, update the bot entity,
import, and publish, but it has no proven per-component status mutation API.
Until a supported API is added, do not guess a MinimalBot payload. Provide the
equivalent Copilot Studio enablement steps, including the **Enable all**
selection.

After the maker confirms the selected topics and required system dependencies
are enabled, run:

```powershell
python scripts/flightcheck/cli.py `
  --checkpoint WD-DA-CTX-001 `
  --connect-config ".local/connect/workday-da/config.json" `
  --agent-slug "{ACTIVE_AGENT}"
```

Show the result per
[`shared/checklist-updater.md`](shared/checklist-updater.md) §U.0. Do not
complete DA4.7 unless the checkpoint is `PASSED`; a pass proves the setup topic
redirects to the exact Workday V2 target and that target is enabled. DA4.7
remains a manual gate because the selected business-topic set still requires
maker confirmation. Record the checkpoint result, explicit acknowledgement,
and safe evidence describing the selected topic mode without storing topic
contents.

After the selected Workday topics and required dependencies are confirmed,
show:

**Message:**

The Workday topic selection is complete. Do not edit, rename, delete, or
repurpose package-managed Workday topics or their required system
dependencies. In an environment that also contains ServiceNow, do not change
ServiceNow or other package-managed system topics while configuring Workday.
Put customer-specific behavior in separate custom topics.

**End message.**

## DA4.8 — Review network restrictions

**Message:**

The Workday connection uses these hosts:

- REST: `{restBaseUrl host}`
- SOAP: `{soapBaseUrl host}`

Most environments need no separate action. If your organization restricts
managed-connector destinations or Workday enforces network/IP restrictions,
share these hosts with the responsible Workday or network administrator before
employee validation. Otherwise continue.

**End message.**

This is a non-blocking advisory. Record DA4.8 with `GATE="advisory"` after the
message is shown. Do not request an attestation and do not block setup solely
because no firewall change was required. If runtime validation later reports a
network restriction, return here and show the same hosts as remediation.

Return to the orchestrator.
