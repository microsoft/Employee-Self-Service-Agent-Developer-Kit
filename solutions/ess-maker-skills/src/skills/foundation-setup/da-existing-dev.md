<!-- Copyright (c) Microsoft Corporation. Licensed under the MIT License. -->
# Set Up an Existing DA Dev Agent

This is the current DA-GA setup path. It connects this ADK workspace to an existing editable DA Dev agent. Do not run the Dataverse foundation steps, request a Dataverse URL, create a preferred solution, or start Dataverse MCP.

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

Do not ask the maker for a service ring. Recognized Copilot Studio hostname text selects `prod`, `preprod`, or `test`; the supplied network location is never used as an API destination. Other target text and direct IDs default to `prod`. Use an explicit `preprod` or `test` override only when a Microsoft internal maker supplies a target without recognized Copilot Studio hostname text.

If the URL identifies an agent, continue directly to validation and attach:

```text
python scripts/setup_existing_da.py attach \
  --target-url "{COPILOT_STUDIO_AGENT_URL}"
```

The first URL-based run lets the maker select an account. Before running it, tell the maker to select the identity they use to open this agent in Copilot Studio and to choose **Use another account** if that identity is not shown. The authenticated access token supplies the tenant identity. Do not infer a tenant from an environment ID or ask the maker for a tenant ID before authentication.

After every attach attempt, parse `DA_EXISTING_DEV_DIAGNOSTIC_JSON:` before handling a terminal error. When `environmentStatus` is `accessible` and `agentStatus` is `not-found`, environment access has been established and only the supplied agent failed direct lookup. Do not enter organization recovery from this state.

If the diagnostic returns agents, show only their display names and explain:

> I can connect to the target environment, but I could not find the agent from the supplied URL. Here are the editable agents visible to this identity.

Ask the maker to choose one of the returned agents by display name. Also provide the recovery choices defined below. Do not offer **Stop setup** as a prominent recovery option in this intermediate state.

For a selected agent or known agent ID, rerun `attach` with the diagnostic's internal environment ID, resolved ring, selected internal agent ID, and internal `tenantId`:

```text
python scripts/setup_existing_da.py attach \
  --environment-id "{INTERNAL_ENVIRONMENT_ID}" \
  --ring "{RING}" \
  --agent-id "{AGENT_ID}" \
  --tenant-id "{INTERNAL_TENANT_ID}"
```

Never display the diagnostic tenant ID. Direct lookup and Dev-realm validation remain authoritative. If `targetListed` is true, do not silently select the listed entry; report the inconsistent lookup result and stop before creating connection state.

If the diagnostic returns no agents, explain:

> I can connect to the target environment, but the supplied agent was not found and no agents are discoverable to this identity. Agent lists can be incomplete, so use a known agent ID if you have one. Otherwise, switch to the identity you use to open the expected agent in Copilot Studio.

Ask **How should I retry the connection?** with these choices in this order:

1. **Switch environments**
2. **Switch identities**
3. **Enter a known agent ID**

Allow **Custom answer** through the question's freeform response. Do not add **Stop setup** to this intermediate recovery prompt. Do not repeat tenant recovery or infer that an empty list proves the environment has no agents.

For **Switch environments**, use the ring resolved from recognized Copilot Studio hostname text and the diagnostic's internal tenant ID:

```text
python scripts/setup_existing_da.py list-environments \
  --target-url "{ORIGINAL_COPILOT_STUDIO_URL}" \
  --tenant-id "{INTERNAL_TENANT_ID}"
```

Parse `DA_ENVIRONMENT_LIST_JSON:`. Show only environment display names and do not display environment or tenant IDs. Exclude the current environment from the switch list. Ask the maker to select another environment. Then run `list-agents` with the selected internal environment ID, resolved ring, and same internal tenant ID, and continue through [Choose the agent](#choose-the-agent). If no other environments are visible, say so and return to the same four recovery choices.

For **Switch identities**, use the existing `list-organizations` identity-recovery flow below. Remind the maker to choose **Use another account**.

For **Enter a known agent ID**, retry `attach` in the current environment using the diagnostic's internal tenant ID and the entered ID. This bypasses agent-list display or discovery defects but does not bypass direct lookup or Dev-realm validation.

For **Custom answer**, follow the maker's freeform recovery request without weakening agent identity or Dev-realm validation.

If direct lookup returns `ObjectNotFound` without the accessible-environment diagnostic, environment access was not established. Explain:

> I could not confirm access to the target environment with the selected account. The most likely fix is to switch to the account you use to open this agent in Copilot Studio. I will reopen sign-in and list the organizations available to that account. In the browser, choose **Use another account** if the correct identity is not shown.

Then run:

```text
python scripts/setup_existing_da.py list-organizations
```

Parse `DA_ORGANIZATION_LIST_JSON:`. Show only the returned organization display names and domains. Do not display organization IDs or ask the maker to copy one.

Ask the maker to select the organization that owns the Copilot Studio agent. Before retrying, explain that another sign-in may appear and they must select an identity that can open the agent in Copilot Studio. Use the selected entry's internal `id` to rerun the original attach command with `--tenant-id` and `--select-account`. Treat that ID as an authentication target, not as agent identity evidence; the direct API lookup and Dev validation remain mandatory.

If the targeted retry returns the accessible-environment diagnostic, use the agent-selection recovery above instead of continuing organization recovery. If it returns `ObjectNotFound` without that diagnostic, do not conclude that the identity is absent from the tenant. It may lack access to the environment or agent. Explain that switching to a user who can open the agent in Copilot Studio is the recommended recovery and that a tenant ID only selects an organization; it does not grant access.

Ask the maker to choose:

- **Switch to another identity — recommended**
- **Use this identity with a specific tenant ID**
- **Stop setup**

For **Switch to another identity**, rerun `list-organizations`, remind the maker to choose **Use another account**, and repeat organization selection and targeted attach with `--select-account`.

For the tenant-ID fallback, explain that it should be used only when the identity they will select is already a member or guest with access to the target environment and agent. Tell them to select the target environment in Power Apps and open **Settings → Session details** to copy **Tenant ID**. After they provide it, rerun the original attach command with `--tenant-id` and `--select-account`, and tell them to sign in with the identity that can open the agent in Copilot Studio.

## Choose the agent

If the maker supplies a Power Apps environment URL or a Copilot Studio environment URL that does not identify an agent, run:

```text
python scripts/setup_existing_da.py list-agents \
  --target-url "{POWER_PLATFORM_ENVIRONMENT_URL}"
```

Parse `DA_AGENT_LIST_JSON:`. Show only the returned agent display names. Do not classify the agents as HR, IT, Hub, package, solution, or extension types.

The command filters the broad environment inventory using each listed agent's direct `realm` metadata and returns only explicit Dev agents. Do not show excluded Test, Prod, or unspecified-realm agents. If `unverifiedAgentCount` is greater than zero, say that some listed agents could not be verified as editable Dev agents and were omitted; offer **Enter a known agent ID** to cover stale inventory or display defects.

Ask the maker to select one agent by its display name. Also offer **Enter a known agent ID**. If discovery returns no Dev agents, explain that directly addressable Dev agents can be absent from the list and offer known-agent-ID entry immediately.

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

Dialog components are converted through the Microsoft Object Model serializer. If one dialog cannot be converted, setup must retain and report that dialog while continuing with every dialog that converted successfully. A converter infrastructure failure or a result with no convertible dialogs is a hard failure.

Parse `DA_EXISTING_DEV_SETUP_JSON:`. When `connectionStatus` is `workspace-ready`, show:

**{agent display name}** is set up as the editable Dev agent. Its available topics are in your local workspace and ready for customization.

Treat setup as complete only when the result also reports `setupStatus` as
`complete`. The command writes `.local/setup/config.json` only after the
workspace and active-agent configuration are ready.

If the result reports unprojected component kinds or a nonzero `unprojectedDialogCount`, add:

Some agent content was retained safely in the fetched snapshot but is not editable through this ADK version yet.

Do not claim that DA push, publish, server-backed validation, or optional product extensions are configured by this path.

## Repair a changed workspace

If attach reports that the Dev snapshot changed, do not overwrite the workspace automatically. Explain that refresh will save a reversible checkpoint and then replace the active agent files with the latest Dev snapshot.

Ask the maker whether to refresh. Continue only with explicit approval, then rerun the attach command with `--refresh`.

When refresh succeeds, tell the maker that the workspace was refreshed and identify the checkpoint number returned by the command. Do not implement or imply a three-way merge.
