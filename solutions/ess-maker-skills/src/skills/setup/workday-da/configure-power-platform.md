<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Phases 4 and 5 - Connections and runtime

## Connections

The skill does not create physical connector connections or complete connector
OAuth. The maker performs those actions; the skill discovers and verifies the
result.

Do not begin with a yes/no question asking whether both connections are
already connected. First explain that this phase needs exactly two Power
Platform connections and run live discovery:

```powershell
python scripts/workday_connect.py record-connections
```

If both required connections are already live, continue without asking the
maker to recreate or reconfirm them.

If the Workday connection is missing or disconnected, read the already
validated values from the Workday state and show them with these
customer-facing labels:

- **Microsoft Entra resource URL:** the Workday SAML Service Provider ID,
  `http://www.workday.com/{workdayTenant}`. Do not use the Entra application
  ID URI beginning with `api://`.
- **Workday OAuth token URL:** the exact Token Endpoint copied from
  **View API Client** in Workday.
- **Client ID:** the Workday OAuth client ID copied from **View API Client**,
  not the Microsoft Entra application ID.

These values were collected during the Workday administrator phase. Do not ask
the maker or administrator to provide them again. If any value is missing,
return to the affected Workday administrator step rather than guessing.

Then give the maker this creation process:

1. Open the Power Apps maker portal and select the exact Power Platform
   environment being configured.
2. Open **Connections**, select **New connection**, and choose **Workday**.
3. Select **Microsoft Entra ID Integrated** authentication.
4. Enter the three displayed values in the matching connection fields.
5. Select **Create** and complete the Workday sign-in window. This connector
   uses a separate credential store, so an additional sign-in prompt is
   expected even when Microsoft or PAC authentication already succeeded.
6. Return to **Connections** and confirm that the Workday connection shows
   **Connected**.

Do not request or collect a Workday password, client secret, access token,
refresh token, or cookie. The maker completes authentication in the connector
sign-in window.

If the Microsoft Dataverse connection is missing or disconnected:

1. In the same environment's **Connections** page, select **New connection**.
2. Choose **Microsoft Dataverse**.
3. Create or repair the connection using the selected maker account.
4. Confirm that it shows **Connected**.

Reuse a healthy existing connection when one already exists. Do not create
duplicates merely to satisfy the phase, and do not ask the maker to paste
connection IDs.

After the maker creates or repairs the missing connection, verify both live
connections again:

```powershell
python scripts/workday_connect.py record-connections
```

The command discovers connected physical connections in the selected
environment and records the result only after both required connections are
live.

- If exactly one connection exists for each connector, discovery is
  deterministic.
- If more than one exists, show safe display names and ask which connection to
  use. Resolve the selected display name to its ID internally, then rerun
  `record-connections` with
  `--workday-connection-id` and/or `--dataverse-connection-id`; never ask the
  maker to paste or repeat an ID.
- If none exists or a connection is not connected, leave the phase waiting and
  show the exact missing connector.

Do not construct or pass manual connection evidence.

## Runtime approval and apply

Run runtime discovery:

```powershell
python scripts/workday_connect.py runtime-plan
```

This discovers the installed connection references, supported package flows,
selected agent, and employee-context topics.

For a package with a reviewed runtime flow catalog, the controller performs the
following writes after exact-plan approval. These are real automated changes,
not instructions for the maker:

Show only the returned `approvalSummary`, not raw connection, application,
workflow, or bot identifiers. The combined runtime plan will:

- bind the two reviewed connection references;
- activate only the checked-in Workday flow catalog;
- authorize the exact agent to invoke those exact workflow IDs;
- reread every changed record.

If the setup topic contains custom content, stop and preserve it. Do not
overwrite or approximate the topic.

Approve the exact plan:

```powershell
python scripts/workday_connect.py runtime-approve --plan-json '{...}'
```

Apply using the returned hash and the same disambiguating connection IDs, if
any:

```powershell
python scripts/workday_connect.py runtime-apply --plan-hash "{hash}"
```

The controller rediscovers the current target, rejects stale approval, reuses
one Dataverse token for Python mutations, invokes the checked-in delegated
authorization script, and verifies bindings, flow state, authorization, and
User Context V2 after each ordered stage. It records each verified stage
immediately, so a later failure resumes from durable evidence rather than
hiding earlier successful changes. The runtime phase remains active until the
maker completes the agent binding below. Report permission issues only from
an explicit forbidden response, `[FAIL]` marker, ambiguity result, or nonzero
script exit.

## Agent binding after flow activation

Only after runtime apply has activated the reviewed flows, wire the native
agent's local `[Admin] - User Context - Setup` topic to
`Workday [System] - 1: Set User Context V2` using the existing guarded
checkpoint, scoped dry-run, approval, and push pattern in
`src/skills/connect/workday/actions/wire-user-context-redirect.md`. Pass the
recorded Power Platform maker as `--preferred-username` so the native push
cannot silently reuse another cached account. This scoped push changes only
the setup redirect; Workday topics remain inactive until connection sharing is
complete. Run `WD-REST-002` after the scoped push and require it to pass:

```powershell
python scripts/flightcheck/cli.py --checkpoint WD-REST-002 --connect-config ".local/connect/workday-da/config.json" --agent-slug "{AGENT_SLUG}" --preferred-username "{POWER_PLATFORM_MAKER}"
```

Topic metadata can report stale or transient component-reference diagnostics
even when the installed package and runtime flows are functioning. Record those
diagnostics for support, but do not treat them alone as proof of a broken
package, tell the customer to repair the installation, or block this phase.
Continue with the supported live checkpoints, topic-state verification, and
employee scenario. Do not recreate, clone, reselect, or rewrite packaged flows
in response to topic metadata alone.

Then open the agent connection settings. Connect **ESS Workday Runtime REST
Execution** and any other Workday flow shown there. The reviewed native agent
contract marks **ESS Workday Runtime** and **ESS Workday Runtime References** as
`EmbeddedOnly`; embedded flows are not expected to require a maker-selected
user connection. For every Workday connection the page does expose, enable
**Allow permission to share parameters**. This prevents each employee from
receiving an unexpected first-use connection prompt.

Internal execution note—never show this implementation detail to the customer:
`connectionType: EmbeddedOnly` is separate from the Dataverse
`delegatedauthorization` records created earlier. The former controls the
agent-facing connection contract; the latter grants the Cosmos-backed agent
principal access to the reviewed Dataverse workflows. Do not skip or scope the
authorization stage solely from `connectionType`.

Run the existing FlightCheck and require `WD-CONN-013` to pass:

```powershell
python scripts/flightcheck/cli.py --checkpoint WD-CONN-013 --connect-config ".local/connect/workday-da/config.json" --agent-slug "{AGENT_SLUG}" --preferred-username "{POWER_PLATFORM_MAKER}"
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
python scripts/workday_connect.py record-agent-binding
```

This command reruns `WD-REST-002` and `WD-CONN-013` with the recorded Workday
state, signs in to the native components endpoint as the recorded maker,
derives the complete Workday topic set from `.component-map.json`, and rereads
every mapped topic. It completes the runtime phase only when every checkpoint
passes and every Workday topic is Active. It retains any topic diagnostics for
support correlation without presenting them as runtime failure evidence. The
signed-in employee scenario remains the functional confirmation that the
Workday runtime works. Do not construct or pass manual
boolean evidence.

If runtime discovery reports that the selected package has no reviewed flow
catalog, record a manual handoff. Do not claim that connection references,
flows, authorization, or topics were changed.

Topic/business-scenario selection that is not represented by a reviewed
deterministic helper remains a concise manual handoff; do not expand it into a
per-topic internal checklist.
