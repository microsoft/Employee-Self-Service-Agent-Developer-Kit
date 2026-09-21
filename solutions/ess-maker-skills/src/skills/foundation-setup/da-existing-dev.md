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

After every successful `attach` or unchanged existing-workspace resume, run all four setup-owned FlightChecks for the exact agent.

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

Parse every `DA_SETUP_FLIGHTCHECK_JSON:` result. Its `state`, `connectReady`, `activeStep`, and `failureCauses` are the setup verdict. Render the owning setup stage from that verdict and use the matching FlightCheck rows for maker-facing evidence and remediation.

For `DA-CONN-*`, setup applies these outcomes:

- `Passed` and `Warning` evidence completes connection readiness. Include the warning disclaimer when exact logical-to-physical mapping is unavailable.
- `Skipped` completes connection readiness when the agent declares no native logical connection references.
- `NotConfigured` keeps connection readiness blocked. Present **Connection required** and the action needed to create or expose a matching physical connection.
- `Failed` keeps connection readiness blocked. Present **Connection needs attention** and the observed unhealthy connection state.
- `Error` keeps connection readiness blocked. Present **Connection check unavailable** and the authentication, permission, or service remediation.

`ENV-CAPACITY-001` remains a programmatic gate. Non-queryable governance prerequisites are outside this read-only check; disclose that limitation without treating it as a setup policy or a downstream `/connect` deferral.

## Interpret results

Canonical setup state is authoritative for each agent's setup progress and completion. Setup for the active agent is complete when attachment reports `connectionStatus: workspace-ready`, every step in that agent's canonical record is `done`, and the final `DA_SETUP_FLIGHTCHECK_JSON:` reports `connectReady: true`.

Canonical state records native environment access, capacity, binding readiness, and baseline content readiness as automated FlightCheck evidence. Only preferred-solution configuration remains skipped because it does not apply to the DA-only path.

When canonical setup state is incomplete, render the stage identified by `active_step` with its state and `failure_causes`. Translate `SETUP-03` to **Establish an editable Dev agent** and `SETUP-07` to **Materialize the local workspace**. Explain the unmet prerequisite in maker language and offer the bounded remediation for that evidence.

If content was synced to the local workspace but the returned result is not workspace-ready and supplies no specific failure cause, keep **Materialize the local workspace** current and show:

> The agent content was synced to your local workspace, but the workspace is not ready to connect. Setup is not complete and has stopped.

Do not invent a cause or run another operation without new maker intent.

On success, build this report only from `DA_EXISTING_DEV_SETUP_JSON:`. Use a friendly environment name only when an authoritative operation returned one; otherwise say `Selected Power Platform environment`. Render empty `unprojectedComponentKinds` as `None` and a missing checkpoint as `Not required`.

**Message:**

Your ESS agent workspace is ready.

| Item                       | Result                                                                 |
| -------------------------- | ---------------------------------------------------------------------- |
| Editable Dev agent         | **{agent display name}**                                               |
| Starting point             | Existing editable Dev                                                  |
| Target environment         | **{friendly environment name or Selected Power Platform environment}** |
| Local workspace            | `{workspace folder}`                                                   |
| Topics synced              | {topic count}                                                          |
| Global variables synced    | {variable count}                                                       |
| Other retained components  | {unprojected component summary or None}                                |
| Local checkpoint           | {checkpoint number or Not required}                                    |

Not performed by foundation setup:

- publishing or promotion;
- connector installation and authentication;
- product-extension configuration;
- server-backed validation of unpublished local changes.

**End message.**

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
