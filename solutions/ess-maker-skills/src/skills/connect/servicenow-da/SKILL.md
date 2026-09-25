z# Connect ServiceNow HRSD to a DA-GA HR Agent

This prototype uses the DA foundation handoff, MinimalBot Components, and the
Power Platform Connectivity API. It does not query Dataverse or activate cloud
flows. In the GA HR package, ServiceNow HRSD topics use direct connector
actions; the packaged flows are Workday-only.

## Resume and interaction contract

This is one resumable interactive workflow. A question that requires maker
input pauses at that question; it does not complete the task and it does not
require the maker to invoke `/connect servicenow` again.

- Run `inspect` at the beginning of every invocation and use its `progress`
  object as the current step status.
- Before every step, check its current live evidence and durable status.
- Automatically skip a step only when its current state can be verified by an
  API or by a successful kit operation tied to the current component revision.
  When such a step is `done`, do not repeat its question or operation. Print
  the corresponding skip message below and continue immediately.
- Agent UI binding, parameter-sharing controls, and Test pane behavior cannot
  be verified by the available APIs. Always ask the maker to confirm their
  current state, even when a prior local attestation exists. A prior
  attestation may be shown as context but is never sufficient to skip the
  current confirmation.
- Ask only for the first `pending` or `failed` step.
- A normal maker reply to the current question resumes this workflow at that
  step. Never require another slash-command merely because the workflow was
  waiting for input or a portal update.
- Never interpret a repeated `/connect servicenow` invocation as confirmation
  of a previous question. Destructive or remote mutations still require the
  explicit answer defined by their step.
- If the host reports that the maker is unavailable, treat that as no answer.
  Do not select a choice, do not advance state, do not say **Task completed**,
  and do not tell the maker to run the command again. Show only:

  > **Waiting for your response**
  >
  > Complete the requested Copilot Studio action or provide the requested
  > value here. I will continue from this step when you reply.

- Use **Task completed** only after a passing Test pane result has been
  recorded. A healthy credential, maker attestation, or successful publish is
  progress, not completion.

Skip messages:

- Topics: `✓ ServiceNow topics are already prepared; skipping topic updates.`
- Credential: `✓ A healthy ServiceNow credential already exists; skipping credential creation.`
- Publish: `✓ The current ServiceNow component revision is already published; skipping publish.`

## 1. Inspect

Run:

```text
python scripts/connect_servicenow_da.py inspect
```

If setup is not schema v4, has not established the environment, exact editable
Dev agent, and local workspace, or is not the HR agent, show the returned error
and stop. Canonical setup uses `authoring_ready` for this foundation boundary.
Do not require aggregate `connect_ready`: setup can report the ServiceNow
connection as not configured, and this workflow exists to resolve that
condition.

Summarize:

- ServiceNow topic count and active count.
- ServiceNow connector-action count.
- Physical connection count.
- Whether the currently referenced connection exists and is Connected.
- The status and message for every entry in `progress`.

Do not treat `/setup` `connect_ready: true` as integration readiness.
Do not treat the MinimalBot reference's connection ID as proof of the maker UI
agent binding.

## 2. Ask whether to enable all ServiceNow topics

If `progress.topics.status` is `done`, print the Topics skip message and
continue to step 3.

Otherwise show every ServiceNow HRSD topic with its current `Active` or
`Inactive` state. Summarize the total, active, and inactive counts, then ask:

> There are {INACTIVE_COUNT} inactive ServiceNow HRSD topics. Would you like
> to enable all ServiceNow HRSD topics?

If the maker says no, do not mutate any topic or continue to physical
connection creation. Record the choice and unchanged counts:

```text
python scripts/connect_servicenow_da.py record-topic-choice --choice keep-current
```

Report that the workflow is paused by the maker's topic choice. Do not call it
completed.

If the maker says yes, show the exact inactive topic names one more time and
ask for final confirmation. After confirmation, run:

```text
python scripts/connect_servicenow_da.py enable-all-topics --yes
```

The command sends `BotComponentUpdate` entries containing the complete fetched
`DialogComponent` objects, preserves identity, version, schema, parent
metadata, and dialog graphs, and changes `state` and `status` together. It
refetches and requires every ServiceNow HRSD topic to be `Active`.

Do not include Workday or other integration topics. Do not publish during topic
preparation. Record the before counts, customer choice, changed topic IDs and
names, and verified after counts.

## 3. Guide the maker to create the physical connection

If `progress.credential.status` is `done`, print the Credential skip message,
select the single Connected Entra user-login credential when unambiguous, and
continue to step 4. If multiple Connected credentials exist, ask which one to
use.

Otherwise run:

```powershell
python scripts\connect_servicenow_da.py create
```

This command is read-only. It derives the instance name and resource URI from
the installed ServiceNow connection-reference metadata when available.

If the command returns `status: input-required`, ask the maker only for the
fields listed in `missingFields`:

- **Instance Name**: the ServiceNow instance prefix, for example `contoso`
  rather than `contoso.service-now.com`.
- **Resource URI**: the Microsoft Entra resource identifier configured for
  this ServiceNow integration.

Then rerun `create` with `--instance-name` and/or `--resource-uri` for the
missing values. Do not invent defaults or persist placeholder values.

When all required values are known, the command returns the exact values plus
these maker steps:

1. Open Copilot Studio and select the target environment.
2. Open the Employee Self-Service HR agent.
3. Select **Settings** -> **Connection settings**.
4. Find ServiceNow and select the status link.
5. Open the connection configuration and select **Create new connection**.
6. Choose **Microsoft Entra ID User Login**.
7. Enter the displayed **Instance Name** and **Resource URI**.
8. Select **Sign in**, complete authentication, and select **Submit**.
9. Wait for the status to become **Connected**, then return to VS Code.

Ask the maker for the current result and remain at this step until the maker
answers. Do not request `Connectivity.Connections.Write` and do not call a
connection-create API.

After the maker confirms, rerun:

```powershell
python scripts\connect_servicenow_da.py inspect
```

If exactly one matching Connected Entra user-login connection is present, show
its display name and continue. If none exists, explain that the manual
connection is not Connected yet and repeat only the relevant UI step. If
multiple matches exist, show their display names and IDs and ask the maker
which one to use.

## 4. Maker connects the credential to the agent

Only continue when the physical connection reports `Connected`. Guide the
maker to return to **Settings** -> **Connection settings**, select
**Connect** for ServiceNow, choose the newly created connection, and save.
Disconnect uses the corresponding UI action.

The UI uses:

```text
POST /powervirtualagents/bots/<agent-schema>/channels/pva-studio/user-connections
```

with a `connectorBindings` payload. The endpoint and payload were captured
from a live UI request and returned `204`, but the ESS ADK OAuth client cannot
request its required `PowerVirtualAgents.Tokens.Read` delegated scope
(`AADSTS65002`: first-party preauthorization required). Do not call
MinimalBot `ConnectionReferenceUpdate` as a substitute and do not reuse a
browser token.

Do not infer this confirmation from a repeated slash-command or from the
MinimalBot reference field. After the maker explicitly reports that the
ServiceNow row shows Connected, record the
manual action and independently verify that the selected physical connection
is still Connected:

```text
python scripts/connect_servicenow_da.py record-agent-connection --connection-id <id>
```

This command records non-secret maker attestation and physical health evidence
under `.local/connect/servicenow/agents/<agent-id>/state.json`. It does not
claim API-level verification of the UI binding. The Test pane provides the
functional verification.

## 5. Check whether OBO parameter sharing is exposed

Guide the maker to open **Settings** -> **Connection settings** -> the
ServiceNow connection -> **See details** -> **Connection parameters**.

This is a maker-confirmed step. Ask every time this workflow validates the
current connection, even when `progress.parameterSharing.status` is
`confirmation-required` because a prior observation was recorded.

Some connections that support SSO expose **Allow permission to share
parameters**. If this option is present, explain that it lets an end user
authorize the agent to use the selected connection parameters on that user's
behalf. Ask the maker to enable it, select the required parameters, and save.

If the page shows only the parameter values and does not expose the sharing
option, record `OBO parameter sharing: not exposed` and continue. Do not claim
that OBO sharing was configured, and do not block a connection that is already
reported as `Connected`. End users might still receive a consent or connection
prompt when they first use the connector.

No supported automation API has been proven for this conditional step.

After the maker answers, persist the observed status:

```text
python scripts/connect_servicenow_da.py record-parameter-sharing --status enabled
python scripts/connect_servicenow_da.py record-parameter-sharing --status not-exposed
```

Run only the command matching the maker's answer.

## 6. Publish

If `progress.publish.status` is `done`, print the Publish skip message and
continue to step 7.

Otherwise show the pending ServiceNow changes. Publish only after explicit
confirmation in the current question:

```text
python scripts/connect_servicenow_da.py publish --yes
```

## 7. Test

Ask the maker to run one HRSD request in the Copilot Studio Test pane. This is
a maker-confirmed step and must be asked during every validation because no API
can prove the current functional result. Record
the prompt and pass/fail attestation in the connector-owned state:

```text
python scripts/connect_servicenow_da.py record-test --prompt "<prompt>" --result <pass-or-fail> --details "<optional details>"
```

Do not claim success from connection health alone.
After a failed result, report the failure and remain at the Test step for a
later corrected result. After a passing result is recorded, and only then,
report **Task completed**.
