<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Phases 4 and 5 - Connections and runtime

## Connections

Begin by preparing the selected Power Platform environment. Do not ask the
maker to create physical connections until the supported Workday package is
installed and verified.

Run:

```powershell
python scripts/workday_connect.py prepare-connections
```

When the package already exists, the command verifies it and continues without
an installation approval. When it returns `requiresApproval: true`, show only
its `approvalSummary`, then use:

```json
[
  {
    "header": "Install Workday package",
    "question": "The administrator prerequisites are complete. Install the supported Workday package in this verified Power Platform environment?",
    "options": [{ "label": "Install" }, { "label": "Not now" }],
    "allowFreeformInput": false
  }
]
```

Leave the selection unset. If the maker selects **Not now**, leave Connections
waiting without creating either physical connection.

If approved, write the returned `plan` object directly to
`.local/connect/workday-da/connections-package-plan.json`, then run:

```powershell
python scripts/workday_connect.py prepare-connections-approve --plan-file ".local\connect\workday-da\connections-package-plan.json"
python scripts/workday_connect.py prepare-connections --install-plan-hash "{PLAN_HASH}"
```

The apply command rediscovers the exact environment, package, agent, and maker,
rejects stale approval, installs through PAC, and rereads Dataverse. Continue
only after it confirms the package is ready.

The skill does not create physical connector connections or complete connector
OAuth. The maker performs those actions; the skill discovers and verifies the
result.

Agent **Connection Settings** is a later Runtime step. While either physical
connection is missing, disconnected, ambiguous, or awaiting confirmation, tell
the maker:

> Do not open Copilot Studio Connection Settings yet. That page is configured
> only after both Power Platform connections are verified and the Workday
> Runtime changes have been applied.

Do not provide the agent Connection Settings link during the Connections phase.
Do not diagnose the flow authorization script as failed when Runtime apply has
not run.

Form direct connection-creation links from the recorded environment ID and
service ring. Resolve `{POWER_AUTOMATE_ORIGIN}` exactly as follows:

- `prod` -> `https://make.powerautomate.com`
- `preprod` -> `https://make.preprod.powerautomate.com`
- `test` -> `https://make.test.powerautomate.com`

Never send a non-production environment to the production maker portal. If the
ring is missing or unsupported, do not guess; ask the maker to confirm it.

Use these environment-scoped links:

- Workday:
  `{POWER_AUTOMATE_ORIGIN}/environments/{ENVIRONMENT_ID}/connections/available/shared_workdaysoap`
- Microsoft Dataverse:
  `{POWER_AUTOMATE_ORIGIN}/environments/{ENVIRONMENT_ID}/connections/available/shared_commondataserviceforapps`
- Connections list fallback:
  `{POWER_AUTOMATE_ORIGIN}/environments/{ENVIRONMENT_ID}/connections`

Do not begin with a yes/no question asking whether both connections are
already connected. First explain that this phase needs exactly two Power
Platform connections, then discover them:

```powershell
python scripts/workday_connect.py record-connections
```

When both required connections resolve exactly, this read-only pass returns
`requiresConfirmation: true` with safe connection display names and the saved
non-secret Workday target values. It does not mark the phase complete.

Treat the two physical connections as sequential gates:

1. Create or verify Microsoft Dataverse.
2. Only after Microsoft Dataverse is connected, create or verify Workday.

The controller checks Microsoft Dataverse first. If it is missing,
disconnected, or ambiguous, show only the Microsoft Dataverse guidance below.
Do not show the Workday connection values, link, or confirmation form in the
same response. After the maker returns, rerun `record-connections`; continue
to Workday only when Microsoft Dataverse resolves exactly.

If the Microsoft Dataverse connection is missing or disconnected:

1. Show a **Create Microsoft Dataverse connection** link using the
   environment-scoped Microsoft Dataverse URL above.
2. If the direct link does not open, use the Connections list fallback or open
   the Power Apps maker portal, select the exact environment, open
   **Connections**, select **New connection**, and choose **Microsoft
   Dataverse**.
3. Create or repair the connection using the selected maker account.
4. Confirm that it shows **Connected**.

After Microsoft Dataverse is connected, rerun `record-connections`.

If the Workday connection is then missing or disconnected, read the already
validated values from `workdayTarget` and show this complete value card in the
same order as the Workday connection form:

| Workday connection field                                 | Value                                                                                                                                                  |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Display name (optional)**                              | Leave blank, or enter a maker-chosen recognizable connection name.                                                                                     |
| **Authentication type**                                  | `Microsoft Entra ID Integrated`                                                                                                                        |
| **Microsoft Entra resource URL (Application ID URI) \*** | The saved Workday SAML Service Provider ID, `http://www.workday.com/{workdayTenant}`. Do not use the Entra application ID URI beginning with `api://`. |
| **Workday OAuth token URL \***                           | The exact saved Token Endpoint copied from **View API Client** in Workday.                                                                             |
| **Workday OAuth client ID \***                           | The saved Workday OAuth client ID copied from **View API Client**, not the Microsoft Entra application ID.                                             |
| **SOAP base URL \***                                     | The saved SOAP service base ending at `/ccx/service`, without the tenant name.                                                                         |
| **REST base URL**                                        | The saved REST base ending at `/ccx/api`.                                                                                                              |
| **Tenant name \***                                       | The saved Workday tenant name.                                                                                                                         |

These values were collected during the Workday administrator phase. Do not ask
the maker or administrator to provide them again. If any value is missing,
return to the affected Workday administrator step rather than guessing.

Then give the maker this creation process:

1. Show a **Create Workday connection** link using the environment-scoped
   Workday URL above. It opens the correct connector in the already selected
   environment.
2. If the direct link does not open, use the Connections list fallback or open
   the Power Apps maker portal, select the exact environment, open
   **Connections**, select **New connection**, and choose **Workday**.
3. Select **Microsoft Entra ID Integrated** authentication.
4. Enter the displayed values in the matching connection fields, preserving
   their order and keeping the tenant separate from the SOAP base URL.
5. Select **Create** and complete the Workday sign-in window. This connector
   uses a separate credential store, so an additional sign-in prompt is
   expected even when Microsoft or PAC authentication already succeeded.
6. Return to **Connections** and confirm that the Workday connection shows
   **Connected**.

Do not request or collect a Workday password, client secret, access token,
refresh token, or cookie. The maker completes authentication in the connector
sign-in window.

Reuse a healthy existing connection when one already exists. Do not create
duplicates merely to satisfy the phase, and do not ask the maker to paste
connection IDs.

Until both connections show **Connected** and `record-connections` succeeds,
keep the customer in the Power Apps **Connections** page. Ask them to return to
the skill for another check; do not redirect them to the agent's Connection
Settings page.

Show the safe display name of the selected Workday connection and the complete
saved non-secret Workday value card. Use `vscode_askQuestions`:

```json
[
  {
    "header": "Confirm Workday connection",
    "question": "Was this exact Workday connection created with all of the displayed Workday target values?",
    "options": [
      { "label": "Yes, confirm this connection" },
      { "label": "No, review or repair it" }
    ],
    "allowFreeformInput": false
  }
]
```

Leave the selection unset. This is target evidence, not a suggested answer.

If the maker does not confirm, leave Connections waiting. After confirmation,
verify both live connections using the internally resolved connection IDs:

```powershell
python scripts/workday_connect.py record-connections --workday-connection-id "{WORKDAY_CONNECTION_ID}" --dataverse-connection-id "{DATAVERSE_CONNECTION_ID}" --confirm-workday-target
```

The command discovers connected physical connections in the selected
environment and records the result only after both required connections are
live.

- If exactly one connection exists for each connector, discovery is
  deterministic.
- If more than one exists, show safe display names and ask which connection to
  use. Do not recommend, preselect, or visually favor a connection based on its
  name or owner. Resolve the selected display name to its ID internally, then rerun
  `record-connections` with
  `--workday-connection-id` and/or `--dataverse-connection-id`; never ask the
  maker to paste or repeat an ID.
- If none exists or a connection is not connected, leave the phase waiting and
  show the exact missing connector.

Do not construct or pass manual connection evidence.

## Runtime approval and apply

Run runtime discovery. The controller reuses the exact connection IDs recorded
in the Connections phase:

```powershell
python scripts/workday_connect.py runtime-plan
```

This discovers the installed connection references, supported package flows,
and selected agent. Employee-context topic wiring is verified later in this
phase.

For a package with a reviewed runtime flow catalog, the controller performs the
following writes after exact-plan approval. These are real automated changes,
not instructions for the maker:

Show only the returned `approvalSummary`, not raw connection, application,
workflow, or bot identifiers. Then use `vscode_askQuestions`:

```json
[
  {
    "header": "Apply Workday runtime changes",
    "question": "Apply these exact Workday runtime changes to the selected environment and agent?",
    "options": [{ "label": "Apply changes" }, { "label": "Not now" }],
    "allowFreeformInput": false
  }
]
```

Leave the selection unset. Do not represent mutation approval as recommended.

If the maker selects **Not now**, leave Runtime waiting and do not call
`runtime-approve` or `runtime-apply`.

If the maker approves, write the returned `plan` object directly to
`.local/connect/workday-da/runtime-plan.json` using a structured file-write
tool. Do not serialize it into a generated shell command. The combined runtime
plan will:

- bind the two reviewed connection references;
- activate only the checked-in Workday flow catalog;
- authorize the exact agent to invoke those exact workflow IDs;
- reread every changed record.

If the setup topic contains custom content, stop and preserve it. Do not
overwrite or approximate the topic.

Approve the exact plan:

```powershell
python scripts/workday_connect.py runtime-approve --plan-file ".local\connect\workday-da\runtime-plan.json"
```

Apply using the returned hash and the same disambiguating connection IDs, if
any:

```powershell
python scripts/workday_connect.py runtime-apply --plan-hash "{hash}"
```

The controller rediscovers the current target, rejects stale approval, reuses
one Dataverse token for Python mutations, invokes the checked-in delegated
authorization script, and verifies connection-reference bindings, flow state,
and authorization after each ordered stage. User Context V2 and selected-agent
flow attachment are verified separately below. The existing Dataverse readiness
coverage for the selected agent runs after that attachment is confirmed, when
the agent connection reference can be evaluated accurately. The controller
records each verified stage immediately, so a later failure resumes from
durable evidence rather than hiding earlier successful changes. Runtime apply identifies
`alm/Enable-CosmosDAFlowAuthorization.ps1` before each invocation and reports
whether its authorization verification completed or failed for the reviewed
flow. Report permission issues only from an explicit forbidden response,
`[FAIL]` marker, ambiguity result, or nonzero script exit.

Do not direct the maker to agent Connection Settings unless `runtime-apply`
returns `applied.verified: true` and confirms all three verified stages:
`connection-references-bound`, `runtime-flows-active`, and
`delegated-authorization-configured`. If Runtime apply has not run or any stage
is incomplete, keep Runtime active and show the controller's actual blocker.

## Agent binding after flow activation

Only after runtime apply has activated the reviewed flows, first initialize
the Workday runtime templates from the native agent's Conversation Start by
running the guarded action in
`src/skills/connect/workday/actions/wire-runtime-template-config.md`.
This scoped action must complete and
`record-runtime-template-wiring` must record
`runtime-template-configured` before changing the Admin User Context topic.
The guarded action runs this live verification command itself; do not invoke
it a second time here:

```powershell
python scripts/workday_connect.py record-runtime-template-wiring
```

Then wire the native agent's local `[Admin] - User Context - Setup` topic to
`Workday [System] - 1: Set User Context V2` using the existing guarded
checkpoint, scoped dry-run, approval, and push pattern in
`src/skills/connect/workday/actions/wire-user-context-redirect.md`. Pass the
recorded Power Platform maker as `--preferred-username` so the native push
cannot silently reuse another cached account. This scoped push changes only
the setup redirect; Workday topics remain inactive until connection sharing is
complete. Do not run a separate readiness checkpoint here; the controller
evaluates the required live coverage after attachment and topic activation.

Topic metadata can report stale or transient component-reference diagnostics
even when the installed package and runtime flows are functioning. Record those
diagnostics for support, but do not treat them alone as proof of a broken
package, tell the customer to repair the installation, or block this phase.
Continue with the supported live checkpoints, topic-state verification, and
employee scenario. Do not recreate, clone, reselect, or rewrite packaged flows
in response to topic metadata alone.

Only now direct the maker to the selected agent's **Settings** >
**Connection Settings** page. Before they continue, show the exact recorded
Power Platform maker account and tell them to verify that Copilot Studio's
browser profile is signed in as that account. The CLI credential cache and the
Copilot Studio browser session are separate. If the browser shows another
account, the maker must switch accounts or use a separate browser profile
before selecting a connection.

Connect both reviewed maker-visible Workday entries:

1. **ESS Workday Runtime**
2. **ESS Workday Runtime REST Execution**

For each entry, select **Manage**, choose the already-created Workday
connection, and save or confirm the selection. The reviewed native agent
contract marks **ESS Workday Runtime References** as `EmbeddedOnly`; it is not
expected to require a separate maker-selected connection. For both exposed
entries, enable **Allow permission to share parameters**. This prevents each
employee from receiving an unexpected first-use connection prompt.

Internal execution note—never show this implementation detail to the customer:
`connectionType: EmbeddedOnly` is separate from the Dataverse
`delegatedauthorization` records created earlier. The former controls the
agent-facing connection contract; the latter grants the Cosmos-backed agent
principal access to the reviewed Dataverse workflows. Do not skip or scope the
authorization stage solely from `connectionType`.

Show the exact agent name and both reviewed agent-facing flows. Use
`vscode_askQuestions`:

```json
[
  {
    "header": "Confirm Workday flow connection",
    "question": "In this exact agent, are ESS Workday Runtime and ESS Workday Runtime REST Execution both connected to the reviewed Workday connection, with parameter sharing enabled for both entries?",
    "options": [
      { "label": "Yes, confirmed" },
      { "label": "No, review the agent connections" }
    ],
    "allowFreeformInput": false
  }
]
```

Leave the selection unset. This confirmation must reflect what the maker
observed in the selected agent.

If the maker does not confirm, leave Runtime active. If confirmed, write this
target-bound evidence to
`.local/connect/workday-da/agent-flow-attachment.json` using a structured
file-write tool:

```json
{
  "outcome": "maker-confirmed",
  "botId": "{SELECTED_AGENT_BOT_ID}",
  "flowNames": ["ESS Workday Runtime", "ESS Workday Runtime REST Execution"],
  "parameterSharingOutcome": "enabled-for-exposed-connections"
}
```

Then run internally:
`src/skills/connect/workday/actions/activate-workday-topics.md`. That action
derives the complete Workday dialog list from the selected agent's
`.component-map.json`, previews the exact scope, and uses the native components
endpoint to set both `state` and `status` to `Active` for every Workday topic.
Do not activate only the two User Context setup topics.

Then run:

```powershell
python scripts/workday_connect.py record-topic-activation
```

This command proves that every Workday topic included with the agent is
enabled. Topic diagnostics are retained as supporting detail but do not change
the activation result or create a package-repair blocker by themselves.

Then run:

```powershell
python scripts/workday_connect.py record-agent-binding --attachment-file ".local\connect\workday-da\agent-flow-attachment.json"
```

This command runs automatic readiness checks against the recorded Workday
state, signs in to the native components endpoint as the recorded maker, derives the
complete Workday topic set from `.component-map.json`, and rereads every
mapped topic. It completes the runtime phase only when the target-bound flow
attachment is confirmed, every Workday topic is Active, and the automatic
configuration checks are accepted. It retains any topic
diagnostics for support correlation without presenting them as runtime failure
evidence. The signed-in employee scenario remains the functional confirmation
that the Workday runtime works. Do not substitute an unscoped "done" response
for the structured confirmation, run separate readiness commands, or ask for
the flow-connection confirmation twice.

If runtime discovery reports that the selected package has no reviewed flow
catalog, record a manual handoff. Do not claim that connection references,
flows, authorization, or topics were changed.

Topic/business-scenario selection that is not represented by a reviewed
deterministic helper remains a concise manual handoff; do not expand it into a
per-topic internal checklist.
