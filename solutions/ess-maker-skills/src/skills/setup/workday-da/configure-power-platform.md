<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Phases 4 and 5 - Connections and runtime

## Connections

The skill does not create physical connector connections or complete connector
OAuth. The maker performs those actions; the skill discovers and verifies the
result.

Ask the maker to create or confirm exactly two connected Power Platform
connections in the selected environment:

- Workday OAuthUser, using the Workday SAML resource URL, token URL, and
  Workday OAuth client ID from controller state;
- Microsoft Dataverse, using the selected maker account.

Explain that Workday connector OAuth is another credential store and may open
its own sign-in. Do not ask the maker to paste connection IDs.

Run runtime discovery:

```powershell
python scripts/workday_connect.py runtime-plan
```

The command uses PAC to discover connected physical connections and one shared
Dataverse session to discover the installed connection references, reviewed
flows, selected agent, and User Context V2 topics.

- If exactly one connection exists for each connector, discovery is
  deterministic.
- If more than one exists, show safe display names and ask which connection to
  use. Resolve the selected display name to its ID internally, then rerun with
  `--workday-connection-id` and/or `--dataverse-connection-id`; never ask the
  maker to paste or repeat an ID.
- If none exists or a connection is not connected, leave the phase waiting and
  show the exact missing connector.
After successful discovery of both physical connections, run:

```powershell
python scripts/workday_connect.py record-connections --evidence-json '{...}'
```

Set the Workday and Dataverse connected booleans only from observed evidence.
This completes the physical-connections phase so the controller can activate
the reviewed flows before Copilot Studio attaches them.

## Runtime approval and apply

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
complete. Run `WD-REST-002` after the scoped push and require it to pass.

If a Workday system topic shows `CloudFlow ... not found`, repair the missing
agent-level flow registration in Copilot Studio. Open the broken **Call an
action** node, select the exact existing flow, preserve its current
input/output mappings, and save the topic:

- **Workday System Get User Context V2** -> **ESS Workday Runtime**
- **Workday System Get REST Execution** ->
  **ESS Workday Runtime REST Execution**
- **Workday System Get CommonExecution** ->
  **ESS Workday Runtime References** and **ESS Workday Runtime**

Do not recreate or clone the flows. Their IDs in the reviewed topics already
match the installed Dataverse flows; reselecting them registers the missing
native flow contract.

Then open the agent connection settings. Connect **ESS Workday Runtime REST
Execution** and **ESS Workday Runtime**. **ESS Workday Runtime References** is
`EmbeddedOnly`, so it is not expected in the user-facing connection list. For
every agent connection used by the two visible flows, enable **Allow permission
to share parameters**. This prevents each employee from receiving an
unexpected first-use connection prompt.

Run the existing FlightCheck and require `WD-CONN-013` to pass. Then run
`src/skills/connect/workday/actions/activate-workday-topics.md`. That action
derives the complete Workday dialog list from the selected agent's
`.component-map.json`, previews the exact scope, and uses the native components
endpoint to set both `state` and `status` to `Active` for every Workday topic.
Do not activate only the two User Context setup topics.

The current
helpers do not independently read the Copilot Studio flow-to-agent attachment,
so retain the maker's explicit confirmation after the broken action nodes are
resolved and do not describe it as automatically verified.

Then run:

```powershell
python scripts/workday_connect.py record-agent-binding --evidence-json '{...}'
```

Set `userContextRedirectPassed` only from `WD-REST-002`,
`parameterSharingPassed` only from the FlightCheck result, and
`flowAttachmentConfirmed` only after the maker has saved the repaired action
nodes without a missing-flow diagnostic. Set `workdayTopicsActivated` only
when `activate-workday-topics.md` reports that every selected Workday topic was
reread as Active. This completes the runtime phase.

If runtime discovery reports that the selected package has no reviewed flow
catalog, record a manual handoff. Do not claim that connection references,
flows, authorization, or topics were changed.

Topic/business-scenario selection that is not represented by a reviewed
deterministic helper remains a concise manual handoff; do not expand it into a
per-topic internal checklist.
