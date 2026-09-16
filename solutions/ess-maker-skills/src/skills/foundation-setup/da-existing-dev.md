<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Set Up an Existing DA Dev Agent

Connect this ADK workspace to an existing editable DA Dev agent. Do not run the Dataverse setup path, request a Dataverse URL, create a preferred solution, or start Dataverse MCP.

Use one Power Platform environment and one active platform per ADK workspace. If setup already identifies another platform, environment, or agent, direct the maker to a separate workspace.

## Connect from the agent URL

Ask for the URL of the agent in Copilot Studio. A complete agent URL is preferred because it identifies the environment and agent without tenant-wide inventory.

Run:

```text
python scripts/setup_existing_da.py attach \
  --target-url "{COPILOT_STUDIO_AGENT_URL}"
```

Before the first run, tell the maker to select the identity they use to open the agent. The access token supplies the tenant identity; do not infer it from the environment ID.

Recognized Copilot Studio hostnames select `prod`, `preprod`, or `test`. Other target text defaults to `prod`; use an explicit non-production `--ring` only when the supplied target does not identify its ring.

The command validates the exact agent identity and Dev configuration, fetches the authoritative component change set, converts supported authoring components with the Microsoft Object Model serializer, and materializes the local workspace. It persists canonical setup progress with an atomic file write before materialization and records `connect_ready: true` only after the workspace and operational configuration are complete.

If Object Model dependencies are missing, run:

```text
python scripts/install_agentbuilder_object_model.py
```

This prerequisite check runs before authentication or remote agent validation. Report it as a local prerequisite failure, then rerun the same attach command after installation.

## Inspect without attaching

Use these independent read-only operations when another setup path needs to select or validate a target:

```text
python scripts/setup_existing_da.py inspect-agent \
  --target-url "{COPILOT_STUDIO_AGENT_URL}"

python scripts/setup_existing_da.py validate-agent \
  --target-url "{COPILOT_STUDIO_AGENT_URL}"
```

`inspect-agent` returns the service-owned route realm. `validate-agent` verifies one exact editable Dev agent without writing setup state or workspace files.

If the maker provides an environment URL without an agent ID, list visible Dev-realm candidates:

```text
python scripts/setup_existing_da.py list-agents \
  --target-url "{COPILOT_STUDIO_ENVIRONMENT_URL}"
```

Show candidate display names and ask the maker to choose one. Validate only the selected candidate through `validate-agent` or `attach`. A missing list entry is not proof that a directly addressable agent is absent; accept a known agent ID and validate it directly.

## Interpret results

Treat setup as complete only when `DA_EXISTING_DEV_SETUP_JSON:` reports both `connectionStatus: workspace-ready` and `connectReady: true`.

The canonical state uses the eight foundation step IDs from main. Steps whose DA checks are not implemented yet are recorded as `done` with `mode: "skipped"` and a specific reason. Treat those records as explicit current-release waivers, not evidence that a check ran. `SETUP-04` is permanently skipped because preferred-solution configuration does not apply to the DA-only path; the FlightCheck and MOS-owned skips are temporary and may be reopened by later workstreams.

If setup stops after canonical progress is written, inspect `active_step`, that step's state, and its `failure_causes`. Preserve those facts in the response and rerun only the bounded operation selected by the maker. Do not edit canonical setup state by hand or claim readiness while `connect_ready` is false.

On success, report:

> **{agent display name}** is set up as the editable Dev agent. Its agent configuration, global variables, and topics are available in the local workspace.

Do not claim that DA push, publish, server-backed validation, or optional product extensions are configured.

Preserve service status, error code, request ID, and local projection-failure evidence. Do not replace a specific service or conversion failure with a generic setup error.

For an identity or authorization failure, rerun the same operation with `--select-account`. Use `--tenant-id` only when the maker supplies the tenant that owns the target and understands that tenant selection does not grant access.

## Refresh changed content

An unchanged rerun verifies the remote snapshot without overwriting local files.

If the remote snapshot changed, or the existing workspace uses an older projection, explain that refresh will checkpoint the current local workspace and replace its managed files. Continue only after explicit approval:

```text
python scripts/setup_existing_da.py attach \
  --target-url "{COPILOT_STUDIO_AGENT_URL}" \
  --refresh
```

Report the returned checkpoint number. Do not imply a three-way merge.
