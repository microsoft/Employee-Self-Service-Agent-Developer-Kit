<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Set Up an Existing DA Dev Agent

Connect this ADK workspace to an existing editable DA Dev agent. Do not run the Dataverse setup path, request a Dataverse URL, create a preferred solution, or start Dataverse MCP.

Use one Power Platform environment per ADK workspace. The workspace can contain multiple Dev agents from that environment and has one active agent. A target in another environment uses **Create and open a new workspace** from the parent skill.

## Connect from the agent URL

Ask for the URL of the agent in Copilot Studio only when the parent setup router has neither a current-invocation inspection result nor a complete recorded local target. A complete agent URL is preferred for a new target because it identifies the environment and agent without tenant-wide inventory. Never request a URL merely to revalidate the exact agent already recorded for this workspace.

Infer the environment ID, agent ID, and service ring from the URL. The URL
should have a segment denoting the ring, such as `test` or `preprod`; when
neither segment is present, confirm the `prod` ring with the user. Ask only
when the environment ID or agent ID is unclear.

Use a current-invocation `DA_AGENT_ROUTE_JSON:` result when the parent setup
router already inspected the supplied or recorded agent. Otherwise, use the
shared authorization message from `SKILL.md`, then run:

```text
python scripts/setup_existing_da.py inspect-agent \
  --environment-id "{ENVIRONMENT_ID}" \
  --agent-id "{AGENT_ID}" \
  --ring "{RING}"
```

Parse `DA_AGENT_ROUTE_JSON:`. Continue only when the current invocation has a
service result reporting `realm: dev`. Do not infer the realm from the URL,
agent name, environment metadata, canonical setup state, or conversation
history. If the service reports another realm, explain that this setup path
requires an editable Dev agent and stop.

After a Dev result, show:

> Editable Dev agent verified. Preparing its local authoring workspace...

Run:

```text
python scripts/setup_existing_da.py attach \
  --environment-id "{ENVIRONMENT_ID}" \
  --tenant-id "{TENANT_ID}" \
  --host "{VALIDATED_HOST}" \
  --ring "{RING}" \
  --api-version "{API_VERSION}" \
  --agent-id "{AGENT_ID}"
```

The access token supplies the tenant identity during initial inspection; do not infer it from the environment ID.

The command validates the exact agent identity and direct Dev route, fetches the authoritative component change set, confirms its component identity and schema, converts supported authoring components with the Microsoft Object Model serializer, and materializes the local workspace. It does not require published Dev configuration; publishing is outside foundation setup and is not attachment remediation. It persists canonical setup progress for that agent before materialization when identity is complete. Complete the native FlightCheck maintenance below before treating the agent's `connect_ready: true` as current.

If Object Model dependencies are missing, run:

```text
python scripts/install_agentbuilder_object_model.py
```

This prerequisite check runs before authentication or remote agent validation. Report it as a local prerequisite failure, then rerun the same attach command after installation.

## Inspect without attaching

Use these independent read-only operations when setup needs to classify, select, or validate a target:

```text
python scripts/setup_existing_da.py inspect-agent \
  --environment-id "{ENVIRONMENT_ID}" \
  --agent-id "{AGENT_ID}" \
  --ring "{RING}"

python scripts/setup_existing_da.py validate-agent \
  --environment-id "{ENVIRONMENT_ID}" \
  --agent-id "{AGENT_ID}" \
  --ring "{RING}"
```

`inspect-agent` returns the service-owned route realm. `validate-agent` verifies one exact editable Dev agent without writing setup state or workspace files. Do not run `validate-agent` immediately before `attach` merely to create another visible step; `attach` performs its own exact validation.

If the maker provides an environment URL without an agent ID, list visible Dev-realm candidates:

```text
python scripts/setup_existing_da.py list-agents \
  --environment-id "{ENVIRONMENT_ID}" \
  --ring "{RING}"
```

Show candidate display names and ask the maker to choose one. Validate only the selected candidate through `validate-agent` or `attach`. A missing list entry is not proof that a directly addressable agent is absent; accept a known agent ID and validate it directly.

## Maintain native FlightCheck evidence

After every successful `attach` or unchanged existing-workspace resume, treat all four setup-owned FlightChecks and their maintenance calls as one presentation unit. Run all four for the exact agent and attempt every check whose prerequisites remain available.

Run each checkpoint into its dedicated local evidence folder:

```text
python scripts/flightcheck/cli.py --checkpoint DA-AGENT-001 --quiet-auth --no-open --output .local/setup/agents/{AGENT_ID}/flightcheck/DA-AGENT-001
python scripts/flightcheck/cli.py --checkpoint ENV-CAPACITY-001 --quiet-auth --no-open --output .local/setup/agents/{AGENT_ID}/flightcheck/ENV-CAPACITY-001
python scripts/flightcheck/cli.py --checkpoint "DA-CONN-*" --quiet-auth --no-open --output .local/setup/agents/{AGENT_ID}/flightcheck/DA-CONN
python scripts/flightcheck/cli.py --checkpoint DA-CONTENT-001 --quiet-auth --no-open --output .local/setup/agents/{AGENT_ID}/flightcheck/DA-CONTENT-001
```

After each run, even when that FlightCheck exits nonzero, apply its result to canonical setup state:

```text
python scripts/setup_existing_da.py maintain-flightcheck --agent-id "{AGENT_ID}" --checkpoint DA-AGENT-001 --results .local/setup/agents/{AGENT_ID}/flightcheck/DA-AGENT-001/results.json
python scripts/setup_existing_da.py maintain-flightcheck --agent-id "{AGENT_ID}" --checkpoint ENV-CAPACITY-001 --results .local/setup/agents/{AGENT_ID}/flightcheck/ENV-CAPACITY-001/results.json
python scripts/setup_existing_da.py maintain-flightcheck --agent-id "{AGENT_ID}" --checkpoint "DA-CONN-*" --results .local/setup/agents/{AGENT_ID}/flightcheck/DA-CONN/results.json
python scripts/setup_existing_da.py maintain-flightcheck --agent-id "{AGENT_ID}" --checkpoint DA-CONTENT-001 --results .local/setup/agents/{AGENT_ID}/flightcheck/DA-CONTENT-001/results.json
```

Parse every `DA_SETUP_FLIGHTCHECK_JSON:` result. Its `state`, `connectReady`, `activeStep`, and `failureCauses` are the runtime-readiness verdict. Use the matching FlightCheck rows for maker-facing evidence and remediation. After attachment, the next maker-facing success surface is the final runtime-readiness table after all four checks have been attempted. Render an earlier surface when maker action is required or an operation prevents later checks from running. Do not use a FlightCheck result to roll back a completed maker-facing checklist stage.

For `DA-CONN-*`, setup applies these outcomes:

- `Passed` and `Warning` evidence completes connection readiness. Include the warning disclaimer when exact logical-to-physical mapping is unavailable.
- `Skipped` completes connection readiness when the agent declares no native logical connection references.
- `NotConfigured` keeps connection readiness blocked. Present **Connection required** and the action needed to create or expose a matching physical connection.
- `Failed` keeps connection readiness blocked. Present **Connection needs attention** and the observed unhealthy connection state.
- `Error` keeps connection readiness blocked. Present **Connection check unavailable** and the authentication, permission, or service remediation.

`ENV-CAPACITY-001` remains a programmatic gate. Non-queryable governance prerequisites are outside this read-only check; disclose that limitation without treating it as a setup policy or a downstream `/connect` deferral.

## Interpret results

Canonical setup state is authoritative for each agent's setup progress and readiness. Local workspace materialization is complete when attachment reports `connectionStatus: workspace-ready`, canonical workspace evidence is present, and `SETUP-07` is `done`. Runtime readiness is complete only when every step in that agent's canonical record is `done` and the final `DA_SETUP_FLIGHTCHECK_JSON:` reports `connectReady: true`.

Canonical state records native environment access, capacity, binding readiness, and baseline content readiness as automated FlightCheck evidence. Only preferred-solution configuration remains skipped because it does not apply to the DA-only path.

Before materialization completes, render an incomplete `SETUP-03` as **Establish an editable Dev agent** and an incomplete `SETUP-07` as **Materialize the local workspace**. After materialization completes, render any blocked capacity, connection, or content step only in the runtime-readiness table. Explain each unmet prerequisite in maker language and offer the bounded remediation supported by that evidence.

If content was synced to the local workspace but the returned result is not workspace-ready and supplies no specific failure cause, keep **Materialize the local workspace** current and show:

> The agent content was synced to your local workspace, but the workspace is not ready to connect. Setup is not complete and has stopped.

Do not invent a cause or run another operation without new maker intent.

After successful materialization and after all four setup-owned FlightChecks have been attempted, build the agent link from `DA_EXISTING_DEV_SETUP_JSON:` and build the runtime-readiness table from the applied FlightCheck results and canonical state. Render both even when `connectReady` is false.

Infer a concise user-friendly product name from the authoritative product or agent display name when its meaning is unambiguous. For example, render `Employee Self-Service IT` as `Employee Self-Service (IT)` and `Employee Self-Service HR` as `Employee Self-Service (HR)`. If a friendly form is not clear, use the authoritative backend display name unchanged. Never use a schema name or agent ID as link text.

Build the exact agent URL as `{COPILOT_STUDIO_ORIGIN}/environments/{ENVIRONMENT_ID}/bots/{AGENT_ID}/overview`, using the validated Copilot Studio origin for the selected service ring and the exact environment and agent IDs from setup evidence. Never link to the environment's agent-list page.

**Message:**

Your local workspace is ready for authoring. The remote agent is available at [{USER_FRIENDLY_PRODUCT_NAME}]({ACTUAL_AGENT_URL}) in Microsoft Copilot Studio.

### Runtime readiness

| Check                | Status                          | Details                                  |
| -------------------- | ------------------------------- | ---------------------------------------- |
| Agent access         | {agent access status}           | {agent access evidence summary}          |
| Environment capacity | {environment capacity status}   | {environment capacity evidence summary}  |
| Connections          | {connections status}            | {connections evidence summary}           |
| Agent content        | {agent content status}          | {agent content evidence summary}         |
| **Overall**          | **{overall readiness status}**  | **{maker-facing readiness summary}**     |

**End message.**

Use the same five rows and order in every runtime-readiness table:

- `Passed` is **✅ Ready**.
- An accepted `DA-CONN-*` `Warning` is **⚠️ Ready with limitation** and retains its warning disclaimer.
- `DA-CONN-*` `Skipped` because the agent declares no logical connection references is **➖ Not required**.
- `NotConfigured` or `Failed` is **⛔ Action required**.
- `Error` or an unavailable check is **⚠️ Check unavailable**.
- A check without current evidence is **⬜ Not checked**.

Use the most consequential current evidence when a checkpoint has multiple rows: **Action required**, then **Check unavailable**, then **Ready with limitation**, then **Not required**, then **Ready**. When `connectReady` is true and no accepted warning remains, render Overall as **✅ Ready**. When `connectReady` is true with an accepted warning, render it as **⚠️ Ready with limitations**. When `connectReady` is false after materialization, render it as **⚠️ Needs attention** and state that local authoring is ready while the reported runtime prerequisites remain. Do not add inferred warnings or place publishing, connector installation, promotion, product-extension configuration, or non-queryable governance requirements in this table.

This report is a factual handoff, not another readiness gate. If the maker disputes a fact, inspect the underlying operation evidence rather than changing canonical state conversationally. Then present the shared completion choices from `SKILL.md`.

Preserve service status, error code, request ID, and local projection-failure evidence for diagnosis. In ordinary maker-facing copy, explain the specific service or conversion failure in plain language without exposing raw technical output. Do not replace it with a generic setup error.

For an identity or authorization failure, rerun the same operation with `--select-account`. Use `--tenant-id` only when the maker supplies the tenant that owns the target and understands that tenant selection does not grant access.

## Refresh changed content

An unchanged rerun verifies the remote snapshot without overwriting local files.

If the remote snapshot changed, or the existing workspace uses an older projection, ask:

> The local workspace differs from the current agent snapshot. Refresh will create a checkpoint and replace the managed agent files; it will not merge them.

Offer exactly:

- **Checkpoint and refresh**
- **Keep local files unchanged**

Continue only after the maker explicitly selects **Checkpoint and refresh**:

```text
python scripts/setup_existing_da.py attach \
  --environment-id "{ENVIRONMENT_ID}" \
  --tenant-id "{TENANT_ID}" \
  --host "{VALIDATED_HOST}" \
  --ring "{RING}" \
  --api-version "{API_VERSION}" \
  --agent-id "{AGENT_ID}" \
  --refresh
```

Report the returned checkpoint number. Do not imply a three-way merge.
