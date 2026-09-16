<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->

# Set Up an Existing DA Dev Agent

Connect this ADK workspace to an existing editable DA Dev agent. Do not run the Dataverse setup path, request a Dataverse URL, create a preferred solution, or start Dataverse MCP.

Use one Power Platform environment and one active platform per ADK workspace. If setup already identifies another platform, environment, or agent, direct the maker to a separate workspace.

## Connect from the agent URL

Ask for the URL of the agent in Copilot Studio. A complete agent URL is preferred because it identifies the environment and agent without tenant-wide inventory.

Use a current-invocation `DA_AGENT_ROUTE_JSON:` result when the parent setup
router already inspected the supplied agent. Otherwise, use the shared
authorization message from `SKILL.md`, then inspect the agent before attachment:

```text
python scripts/setup_existing_da.py inspect-agent \
  --target-url "{COPILOT_STUDIO_AGENT_URL}"
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
  --target-url "{COPILOT_STUDIO_AGENT_URL}"
```

The access token supplies the tenant identity; do not infer it from the environment ID.

Recognized Copilot Studio hostnames select `prod`, `preprod`, or `test`. Other target text defaults to `prod`; use an explicit non-production `--ring` only when the supplied target does not identify its ring.

The command validates the exact agent identity and Dev configuration, fetches the authoritative component change set, converts supported authoring components with the Microsoft Object Model serializer, and materializes the local workspace. It persists canonical setup progress with an atomic file write before materialization and records `connect_ready: true` only after the workspace and operational configuration are complete.

If Object Model dependencies are missing, run:

```text
python scripts/install_agentbuilder_object_model.py
```

This prerequisite check runs before authentication or remote agent validation. Report it as a local prerequisite failure, then rerun the same attach command after installation.

## Inspect without attaching

Use these independent read-only operations when setup needs to classify, select, or validate a target:

```text
python scripts/setup_existing_da.py inspect-agent \
  --target-url "{COPILOT_STUDIO_AGENT_URL}"

python scripts/setup_existing_da.py validate-agent \
  --target-url "{COPILOT_STUDIO_AGENT_URL}"
```

`inspect-agent` returns the service-owned route realm. `validate-agent` verifies one exact editable Dev agent without writing setup state or workspace files. Do not run `validate-agent` immediately before `attach` merely to create another visible step; `attach` performs its own exact validation.

If the maker provides an environment URL without an agent ID, list visible Dev-realm candidates:

```text
python scripts/setup_existing_da.py list-agents \
  --target-url "{COPILOT_STUDIO_ENVIRONMENT_URL}"
```

Show candidate display names and ask the maker to choose one. Validate only the selected candidate through `validate-agent` or `attach`. A missing list entry is not proof that a directly addressable agent is absent; accept a known agent ID and validate it directly.

## Interpret results

Treat setup as complete only when `DA_EXISTING_DEV_SETUP_JSON:` reports both `connectionStatus: workspace-ready` and `connectReady: true`.

Canonical state tracks eight foundation records. Checks outside DA foundation setup are recorded with `mode: "skipped"` and a specific reason. Treat those records as explicit waivers, not evidence that a check ran. Preferred-solution configuration does not apply to the DA-only path. Environment FlightCheck, product installation, binding, and product-readiness evidence belong to their owning product setup capabilities.

If setup stops after canonical progress is written, inspect `active_step`, that step's state, and its `failure_causes`. Preserve those facts as diagnostic evidence, but translate them into maker language: `SETUP-03` maps to **Establish an editable Dev agent** and `SETUP-07` maps to **Materialize the local workspace**. Explain a specific unmet prerequisite plainly without showing an internal step ID or raw technical output. Rerun only the bounded operation selected by the maker. Do not edit canonical setup state by hand or claim readiness while `connect_ready` is false.

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

This report is a factual handoff, not another readiness gate. If the maker disputes a fact, inspect the underlying operation evidence rather than changing canonical state conversationally.

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
  --target-url "{COPILOT_STUDIO_AGENT_URL}" \
  --refresh
```

Report the returned checkpoint number. Do not imply a three-way merge.
