<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Connect an Existing DA Dev Agent

Use this path when the maker wants to connect this ADK workspace to an existing editable DA Dev agent. Do not run the Dataverse foundation steps, request a Dataverse URL, create a preferred solution, or start Dataverse MCP.

This path supports one Power Platform environment and one active platform per ADK workspace. If the command reports existing setup for another platform, tell the maker to open or create a separate ADK workspace and stop.

## Resume

Run:

```text
python scripts/setup_existing_da.py status
```

Parse `DA_EXISTING_DEV_STATUS_JSON:`.

- When status is `not-started`, continue to target identification.
- When status is `connected` or `acquired`, rerun the attach command using the persisted tenant, environment, host, ring, API version, and agent identity. Do not ask the maker to select them again.
- When status is `workspace-ready`, rerun attach with the persisted identity so it verifies the remote snapshot and repairs a missing local workspace configuration. An unchanged result must not overwrite local files.

Do not display persisted IDs, API hosts, service rings, API versions, state names, or state paths.

## Identify the target

Ask the maker for the URL of the existing editable agent in Copilot Studio. A URL copied from the agent's browser page is preferred because it identifies both the environment and agent without tenant-wide inventory permissions.

Do not ask the maker for a service ring. A Copilot Studio URL selects `prod`, `preprod`, or `test` from its trusted hostname. Other URLs and direct IDs default to `prod`. Use an explicit `preprod` or `test` override only when a Microsoft internal maker supplies a target without a Copilot Studio URL.

If the URL identifies an agent, continue directly to validation and attach:

```text
python scripts/setup_existing_da.py attach \
  --target-url "{COPILOT_STUDIO_AGENT_URL}"
```

The first URL-based run lets the maker select an account. The authenticated access token supplies the tenant identity. Do not infer a tenant from an environment ID or ask the maker for a tenant ID before authentication.

If a guest maker cannot authenticate to the target tenant, let them provide that tenant's ID explicitly and rerun the same command with `--tenant-id`. Treat it as an override to authenticate, not as identity evidence; the direct API lookup and Dev validation remain mandatory.

## Choose the agent

If the maker supplies a Power Apps environment URL or a Copilot Studio environment URL that does not identify an agent, run:

```text
python scripts/setup_existing_da.py list-agents \
  --target-url "{POWER_PLATFORM_ENVIRONMENT_URL}"
```

Parse `DA_AGENT_LIST_JSON:`. Show only the returned agent display names. Do not classify the agents as HR, IT, Hub, package, solution, or extension types.

Ask the maker to select one agent by its display name. Also offer **Enter a known agent ID**. If discovery returns no agents, explain that directly addressable agents can be absent from the list and offer known-agent-ID entry immediately.

Then validate and attach:

```text
python scripts/setup_existing_da.py attach \
  --target-url "{POWER_PLATFORM_ENVIRONMENT_URL}" \
  --agent-id "{AGENT_ID}"
```

For a Microsoft internal non-production target whose URL does not identify its ring, append `--ring preprod` or `--ring test` to both commands.

If the maker cannot provide a usable URL, offer production environment inventory as an optional fallback:

```text
python scripts/setup_existing_da.py list-environments
```

Explain that this inventory covers only the tenant selected during Power Platform sign-in and is not a cross-tenant or non-production-ring inventory. Also offer direct environment-ID entry. Use the selected or entered environment ID with the existing `list-agents` and `attach` commands.

## Validate and attach

The command must explicitly validate the Dev realm and matching agent identity before persisting the connection. A selected agent that resolves to another realm or identity is a hard failure.

Parse `DA_EXISTING_DEV_SETUP_JSON:`. When `connectionStatus` is `workspace-ready`, show:

**{agent display name}** is connected as the editable Dev agent. Its available topics are in your local workspace and ready for customization.

If the result reports unprojected component kinds, add:

Some agent settings were retained safely but are not editable through this ADK version yet.

Do not claim that DA push, publish, server-backed validation, or optional product extensions are configured by this path.

## Repair a changed workspace

If attach reports that the Dev snapshot changed, do not overwrite the workspace automatically. Explain that refresh will save a reversible checkpoint and then replace the active agent files with the latest Dev snapshot.

Ask the maker whether to refresh. Continue only with explicit approval, then rerun the attach command with `--refresh`.

When refresh succeeds, tell the maker that the workspace was refreshed and identify the checkpoint number returned by the command. Do not implement or imply a three-way merge.
