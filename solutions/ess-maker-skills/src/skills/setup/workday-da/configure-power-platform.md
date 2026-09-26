<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Phases 4 and 5 - Connections and runtime

## Connections

The skill does not create physical connector connections, complete connector
OAuth, connect flows to the agent, or enable parameter sharing. The maker
performs those actions; the skill discovers and verifies the result.

The current helpers do not independently read the Copilot Studio
flow-to-agent attachment. Record the maker's confirmation of that attachment
as manual handoff evidence; do not describe it as automatically verified.

Ask the maker to create or confirm exactly two connected Power Platform
connections in the selected environment:

- Workday OAuthUser, using the Workday SAML resource URL, token URL, and
  Workday OAuth client ID from controller state;
- Microsoft Dataverse, using the selected maker account.

Explain that Workday connector OAuth is another credential store and may open
its own sign-in. Do not ask the maker to paste connection IDs.

In Copilot Studio, connect the reviewed Workday flows to the selected ESS HR
agent. For every agent connection used by those flows, enable **Allow
permission to share parameters**. This is what prevents each employee from
receiving an unexpected first-use connection prompt. It is distinct from
binding the package's solution connection references.

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
- Run the existing FlightCheck and require `WD-CONN-013` to pass. If it does
  not, show only its safe display-name remediation, have the maker enable
  parameter sharing in Copilot Studio, and rerun that check.

After successful discovery, a passing `WD-CONN-013`, and the maker's recorded
confirmation that the reviewed flows are connected to the selected agent,
record the distinct automated and manual evidence and set `connections` to
`complete`.

## Runtime approval and apply

For a package with a reviewed runtime flow catalog, the controller performs the
following writes after exact-plan approval. These are real automated changes,
not instructions for the maker:

Show only the returned `approvalSummary`, not raw connection, application,
workflow, or bot identifiers. The combined runtime plan will:

- bind the two reviewed connection references;
- activate only the checked-in Workday flow catalog;
- authorize the exact agent to invoke those exact workflow IDs;
- redirect only an empty admin user-context scaffold to Workday User Context
  V2; and
- reread every changed record.

If the setup topic contains custom content, stop and preserve it. Do not
overwrite or approximate the topic.

Approve the exact plan:

```powershell
python scripts/workday_connect.py approve-plan --phase runtime --plan-json '{...}'
```

Apply using the returned hash and the same disambiguating connection IDs, if
any:

```powershell
python scripts/workday_connect.py runtime-apply --plan-hash "{hash}"
```

The controller rediscovers the current target, rejects stale approval, reuses
one Dataverse token for Python mutations, invokes the checked-in delegated
authorization script, and verifies bindings, flow state, authorization, and
User Context V2 after the write. Report permission issues only from an
explicit forbidden response, `[FAIL]` marker, ambiguity result, or nonzero
script exit.

If runtime discovery reports that the selected package has no reviewed flow
catalog, record a manual handoff. Do not claim that connection references,
flows, authorization, or topics were changed.

Topic/business-scenario selection that is not represented by a reviewed
deterministic helper remains a concise manual handoff; do not expand it into a
per-topic internal checklist.
