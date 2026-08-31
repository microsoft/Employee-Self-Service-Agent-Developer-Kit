---
name: landing-page-config
description: >-
  Configure an ESS landing page through the AgentConfiguration MCP server.
  Use for branding and accent colors, quick links, starter prompts, Stay Up
  to Date, Quick Access, reading the agent name or icon, deleting all landing
  page configuration, and any call to the ess-landing-page-config MCP server.
---

# Landing Page Configuration

Orchestrate landing-page configuration through the AgentConfiguration MCP
server. Guide the maker through complete, safe section updates without relying
only on individual tool descriptions.

## Setup-state check

For every request that reads or configures a tenant's landing page, read
`.local/config.json` before resolving a target or calling an MCP tool.

If the file does not exist, or its `setup` value is not `"complete"`, show:

> Welcome to the ESS Maker Kit. Before using `/landing-page`, type `/setup` to set up your environment.

and STOP.

Reuse the loaded configuration during target resolution. Requests that only ask
what a landing-page setting controls do not require local setup; follow
**Explain landing-page settings** directly.

## MCP availability check

Before any request that requires an AgentConfiguration MCP tool, inspect the
tools available in the current conversation for the
`ess-landing-page-config` server.

When its tools are available, continue to **Resolve the target**.

When its tools are unavailable:

1. Run:

   ```text
   python scripts/mcp_config.py validate --server ess-landing-page-config
   ```

2. Parse `MCP_CONFIG_STATUS_JSON:`:
   - `configured`: follow **Start the landing-page MCP server**.
   - `missing-file` or `missing-server`: run:

     ```text
     python scripts/mcp_config.py materialize-defaults
     ```

     Parse `MCP_CONFIG_RESULT_JSON:` and confirm
     `ess-landing-page-config` appears in `addedServers`, or run `validate`
     again and confirm its status is `configured`. Then follow **Start the
     landing-page MCP server**.
   - command failure or any other result: show the exact error and stop. Do not
     replace malformed JSON or overwrite an existing configuration.

### Start the landing-page MCP server

Show:

> The landing-page MCP server is configured, but its tools are not available in
> this chat yet.
>
> 1. Press `Ctrl+Shift+P`.
> 2. Run `MCP: List Servers`.
> 3. Select `ess-landing-page-config`.
> 4. Choose `Start`.
>
> Type `done` when the server shows `Running`.

Wait for the maker. When they confirm, inspect the available tools again. If
the tools are available, continue the original request. If they remain
unavailable, tell the maker to reload the VS Code window, rerun
`/landing-page`, and stop.

## Hard rules

1. Route every call to the `ess-landing-page-config` MCP server through this
   skill.
2. Use AgentConfiguration MCP tools for server access. Do not call the backing
   REST/OData API directly.
3. Use a `titleId` supplied by the maker when available. Otherwise, use the
   target agent's `titleId` from `.local/config.json`. Never substitute its
   Dataverse `botId`.
4. When `titleId` is absent from the target agent's local entry, resolve it
   through `list_agent_configs` or `search_agents`, then persist the verified
   value in `.local/config.json` before continuing. A match from
   `list_agent_configs` already has a configuration. A match found only through
   `search_agents` must be initialized through `create_agent_config`.
5. When `titleId` is available from `.local/config.json`, do not call
   `list_agent_configs` or `search_agents`. Call `get_agent_config` once to
   establish whether its configuration exists. After a successful read or
   creation, assume it continues to exist and do not repeat a preflight read
   before each widget.
6. When the maker supplies exact values or an exact deterministic change, use
   the direct-update flow. Read and merge the current section only when the
   requested change does not provide its complete replacement. Call
   `update_agent_config` directly, report the successful update, and do not open
   an editing widget.
7. When the maker wants to explore, choose, review, or edit a widget-supported
   section without supplying an exact change, call that surface's `open_*` tool.
   The widget loads the current section and owns editing, validation,
   confirmation, and publishing.
8. Treat every provided config section as a bulk replacement:
   - An omitted section remains unchanged.
   - A provided section replaces the complete section.
   - An empty section resets or clears that section.
9. Merge add/remove/reorder/toggle requests into the current section and submit
   the complete resulting section for chat-driven surfaces.
10. Before a model-driven branding update containing colors, run
   `python scripts/validate_branding.py` for each changed theme.
11. Treat failed contrast validation as advisory. Warn the maker, show the
   result, and require explicit confirmation before submitting that color.
12. Send only `name` and `accentColor` for each theme. The server derives
    `hoverColor` and `activeColor`.
13. Confirm section clears and branding resets before writing. An exact
    replacement list or CSV supplied by the maker authorizes that replacement
    without another confirmation.
14. Use the `update_agent_config` response as the operation result. It contains
    the updated configuration and success information, so do not perform a
    follow-up read.
15. After calling an `open_*` tool, let the widget issue
    `update_agent_config`. Do not issue a duplicate model-driven update.
16. Call at most one `open_*` tool per turn.
17. Treat the agent name and icon as read-only. You may report the name and
    display the icon, but never include either in an update payload or imply
    that the AgentConfiguration server can edit them.
18. Treat a 404 from the initial `get_agent_config` as an uninitialized
    landing-page configuration. Treat a later 404 after existence was
    established as a configuration deleted elsewhere. Both follow the
    creation flow below without rediscovering `titleId`.
19. After `list_agent_configs` or `search_agents` returns an unambiguous local
   match, do not respond to the maker or continue to another MCP call until
   the resolved `titleId` is persisted and verified in `.local/config.json`
   according to **Persist a discovered title ID**.
20. When `open_starter_prompts` returns no starter prompts, tell the maker that
    the widget opened with a default set of starter prompts. Explain that they
    can edit and publish the defaults or publish them as-is.
21. `delete_agent_config` removes every landing-page configuration section and
    restores the default landing-page experience. It is destructive. Always
    explain that effect and obtain explicit confirmation immediately before
    calling it, even when the maker's initial request already said to delete or
    reset all landing-page configuration.
22. When the maker asks what a setting controls for employees, follow
    **Explain landing-page settings**. Use Microsoft Learn for end-user behavior
    only; use this skill and the MCP tool contracts for configuration behavior.

## Resolve the target

For a request to remove all landing-page configuration, follow **Delete all
landing-page configuration**. That flow does not create or read a configuration
before deleting it.

1. Use the `.local/config.json` loaded by **Setup-state check** to identify the
   local target:
   - For the active agent, use the backward-compatible `agent` object.
   - For another locally configured agent, match its `agents` entry by `slug`,
     `botId`, or unambiguous `name`.
2. Use a `titleId` supplied explicitly by the maker. Otherwise, use the target
   entry's `titleId` when present.
3. When `titleId` was supplied or already stored, call `get_agent_config` once
   with that value. Do not call `list_agent_configs` or `search_agents`.
   - On success, reuse the returned configuration when the current request
     needs it and treat the configuration as existing for the rest of the
     flow.
   - On 404, follow **Create or recreate missing configuration**.
4. When `titleId` is still unknown, call `list_agent_configs` and match
   its configured agents against the target agent name.
5. When `list_agent_configs` returns an unambiguous match:
   - Persist its `titleId` according to **Persist a discovered title ID**.
   - Treat the configuration as existing. Do not call `get_agent_config` merely
     to verify it before opening a widget.
6. When there is no configured match, call `search_agents` with a distinctive
   substring of the target agent name. The server does not require a
   three-character minimum.
7. Use an unambiguous search result's `titleId`. When multiple candidates
   match, ask the maker to choose. When none match, follow **Target unavailable
   to AgentConfiguration** and stop.
8. Persist the search result's `titleId` according to
   **Persist a discovered title ID**, then follow
   **Create or recreate missing configuration**. Do not call
   `get_agent_config` between search and creation.

Do not guess the identifier from the agent name, schema name, `botId`, Teams
app ID, or manifest ID.

## Target unavailable to AgentConfiguration

When `list_agent_configs` has no configured match and `search_agents` returns no
matching tenant-visible agent:

1. Do not guess a `titleId` or call `create_agent_config`.
2. Tell the maker:

   > I couldn't find **{agent name}** among your tenant's available Employee
   > Self-Service agents. Confirm the agent name. If it is correct, publish the
   > agent from Copilot Studio, submit it for admin approval, and have an
   > administrator deploy it to your organization. Then return to
   > `/landing-page`.

3. When the maker asks whether the kit handles deployment, explain that
   foundation setup can install and extract a supported ESS agent in the
   selected Power Platform environment. Publishing from Copilot Studio,
   submitting for admin approval, and deploying through Integrated apps are
   separate maker and administrator steps.
4. Stop. Do not continue to configuration creation or another discovery call.

## Persist a discovered title ID

Treat `titleId` as an optional field on the existing local agent object. A
configured agent retains its established fields:

```json
{
  "name": "Employee Self-Service HR",
  "botId": "<Dataverse bot ID>",
  "titleId": "<MetaOS title ID>",
  "schemaName": "msdyn_copilotforemployeeselfservicehr",
  "isManaged": true,
  "slug": "employee-self-service-hr",
  "folder": "workspace/agents/employee-self-service-hr"
}
```

After `list_agent_configs` or `search_agents` returns an unambiguous match:

1. Read the complete `.local/config.json`.
2. Find the target entry in `agents`. Match the already-selected local target by
   `botId` when available, then by `slug`. Use `name` only when it is
   unambiguous. When the active target exists only in the backward-compatible
   `agent` object, copy that complete object into `agents` before adding
   `titleId`; this migrates the legacy shape without inventing agent fields.
3. Add or replace only that entry's `titleId`.
4. When the target is active, also add or replace `agent.titleId`. Treat the
   target as active when its `slug` equals `activeAgent` or its `botId`/`slug`
   matches the backward-compatible `agent` object.
5. Preserve the `agents` array, the complete `agent` object, every other agent
   field, and every top-level config field.
6. Write valid JSON back to `.local/config.json`.

**Completion gate:** Reread `.local/config.json` after writing it. When a local
target exists, do not respond or continue until the matching `agents` entry
contains the resolved `titleId` and, for the active target, `agent.titleId`
contains the same value.

Do not create a partial `agents` entry from an MCP result. When no matching local
entry exists, use the resolved `titleId` for the current request, but do not
invent `botId`, `schemaName`, `isManaged`, `slug`, or `folder`.

## Explain landing-page settings

Use [Customize the Employee Self-Service agent](https://learn.microsoft.com/en-us/microsoft-365/copilot/employee-self-service/customize#configure-employee-self-service-branding-and-landing-page-content-in-the-microsoft-365-admin-center)
as the source for what these settings control in the end-user experience. Read
only these sections:

- **Configure categorized starter prompts**
- **Configure accent colors**
- **Configure quick links**
- **Configure Stay up to date**
- **Configure Quick Access**

The page describes another administration surface. Do not use or repeat its
navigation, upload, save, role, or configuration instructions. This skill and
the MCP tool contracts define how configuration is performed here.

| Setting | What it controls for employees |
|---|---|
| Categorized starter prompts | Show common ways to engage with the agent, communicate its capabilities, and guide employees into the right scenarios. Tenant-level categorized prompts override starter prompts from Copilot Studio. |
| Accent colors | Style buttons, links, chat bubbles, and loading indicators in light and dark themes. Default Copilot colors apply when unset. |
| Quick links | Surface important tenant resources directly on the landing page. No quick links appear when the list is empty. |
| Stay up to date | Show a personalized carousel of actionable cards for in-progress ticket status, required follow-ups, and time-sensitive tasks. Employees can select a card to start a related conversation. Cards come from configured ticket-related sources and do not create or modify tickets. |
| Quick Access | Show personalized, high-frequency information cards, such as time-off balance/status, upcoming paid holidays, and service anniversaries. Employees can select a card to start a conversation. |

## Start a guided configuration

When the maker asks to configure or set up the landing page:

1. Resolve the target and establish that its configuration exists.
2. Obtain the complete current configuration:
   - Reuse a successful `get_agent_config` or `create_agent_config` result.
   - When resolution used `list_agent_configs`, call `get_agent_config` because
     the guided summary needs the complete configuration.
3. Present the current state:

   | Area | Show | End-user effect |
   |---|---|---|
   | Branding | Configured light/dark accent colors, or defaults | Styles buttons, links, chat bubbles, and loading indicators |
   | Quick links | Link count and ordered labels | Gives direct access to important tenant resources |
   | Starter prompts | Category count and prompts per category | Shows agent capabilities and guides employees into common scenarios |
   | Stay up to date | Enabled or disabled | Surfaces personalized ticket updates, follow-ups, and time-sensitive tasks |
   | Quick Access | Enabled or disabled | Surfaces high-frequency personal information as selectable cards |
   | Agent identity | Read-only name and whether an icon is available | Identifies the agent in the employee experience |

4. Ask which area the maker wants to configure.
5. Complete one area at a time. Do not repeat `get_agent_config` before opening
   each selected widget.

## Route the request

| Intent | Tool flow |
|---|---|
| View or summarize current configuration | Resolve the target and establish existence -> use an available full config result or call `get_agent_config` |
| View the agent name | Resolve the target and establish existence -> use an available full config result or call `get_agent_config` -> report the read-only name |
| Show the agent icon | Resolve `titleId` -> `view_agent_icon`; the tool displays the read-only PNG |
| Apply exact branding/accent values | Resolve the target and establish existence -> get current branding only when a merge is required -> validate changed colors -> `update_agent_config` -> report success |
| Explore or edit branding without exact values | Resolve the target and establish existence -> `open_accent_color`; the widget validates and publishes |
| Apply an exact quick-links list/CSV or deterministic link change | Resolve the target and establish existence -> get current links only when a merge is required -> validate the complete result -> `update_agent_config` -> report success |
| Explore or edit quick links without an exact change | Resolve the target and establish existence -> `open_quick_links`; the widget validates and publishes |
| Apply an exact starter-prompts list/CSV or deterministic prompt change | Resolve the target and establish existence -> get current pivots only when a merge is required -> validate the complete result -> `update_agent_config` -> report success |
| Explore or edit starter prompts without an exact change | Resolve the target and establish existence -> `open_starter_prompts`; the widget supplies defaults when empty, then validates and publishes |
| Update insight cards or another surface without an editor | Resolve the target and establish existence -> use an available full config result or call `get_agent_config` -> merge and validate complete affected section(s) -> `update_agent_config` |
| Remove all landing-page configuration | Follow **Delete all landing-page configuration** |
| Update the agent name or icon | Explain that the field is read-only and do not call an update tool |

The maker does not need to name a tool explicitly. A request such as "change my
accent color" opens the corresponding editor because the value is still open.
A request such as "change my light accent color to `#CCAA00`" supplies an exact
change and uses `update_agent_config` directly.

## Route exact changes directly

An exact change provides enough information to compute the complete replacement
deterministically. Examples include:

- a specific accent color;
- a complete quick-links or starter-prompts list;
- a CSV file containing the complete replacement list;
- "add this prompt to the HR category";
- "remove the Benefits link";
- "move this prompt before that prompt"; or
- explicit insight-card toggle values.

For an exact change:

1. Resolve the target and establish that its configuration exists.
2. Determine whether the request supplies the complete section:
   - For a complete list, complete nested array, or CSV replacement, validate and
     use it directly.
   - For one field, append, remove, reorder, or toggle, reuse an available full
     configuration result or call `get_agent_config`, then read the affected
     section and merge the requested change.
3. Validate the complete resulting section. Branding follows the contrast flow.
4. Call `update_agent_config` with only the affected complete section.
5. Use the tool result as the operation result and tell the maker the update was
   made. Do not call an `open_*` tool and do not perform a follow-up read.

For "add this prompt to the HR category":

1. Obtain the current complete `pivots` array.
2. Match the HR category by an unambiguous category `displayName`. Ask the maker
   to choose when no category or multiple categories match.
3. Append the validated prompt to that category's
   `conversationStarterPrompts`.
4. Submit the entire resulting `pivots` array through `update_agent_config`.

Exact requests still obey destructive confirmation rules for section clears,
branding resets, and `delete_agent_config`, plus explicit confirmation after an
advisory contrast failure.

## Delete all landing-page configuration

Deletion removes the complete saved landing-page configuration and restores the
default landing-page experience. It does not edit or remove the local agent
entry or its stored `titleId`.

1. Use the `.local/config.json` loaded by **Setup-state check** to identify the
   local target.
2. Resolve `titleId` without creating or reading a configuration:
   - Use a maker-supplied `titleId` or the target entry's stored `titleId`.
   - When `titleId` is absent, call `list_agent_configs` and match the target
     agent. Persist an unambiguous match according to
     **Persist a discovered title ID**.
   - When `list_agent_configs` has no matching configured agent, tell the maker
     that the default landing-page experience is already active. Do not call
     `search_agents`, `create_agent_config`, or `delete_agent_config`.
3. Explain that deletion removes branding, quick links, starter prompts, and
   insight-card settings and restores their defaults.
4. Obtain explicit confirmation immediately before the delete call. The
   original delete request does not satisfy this confirmation.
5. Call `delete_agent_config` once with `titleId`.
6. On success, tell the maker that all landing-page configuration was removed
   and the default experience was restored. Keep the stored `titleId`.
7. When delete returns 404, explain that the configuration is already absent
   and the default experience is active. Do not create or recreate it.

## Create or recreate missing configuration

Use this flow after `search_agents` resolves an agent absent from
`list_agent_configs`, when the initial `get_agent_config` returns 404, or when a
later `get_agent_config` or `open_*` call returns 404:

1. Keep the known `titleId`. Do not repeat `list_agent_configs` or
   `search_agents`.
2. Explain the applicable state:
   - After search or the initial stored-ID read, the landing page has not been
     configured yet.
   - After a prior successful read, creation, or widget open, the configuration
     was deleted elsewhere and can be recreated.
3. Offer to call `create_agent_config` with the resolved `titleId`. If the
   maker's original request was read-only, get confirmation before calling it.
   A request to set up, configure, or update the landing page already authorizes
   initialization, so continue without asking again.
4. After successful creation, treat the configuration as existing. Do not call
   `get_agent_config` merely to verify the creation.
5. Continue the maker's original request:
   - For a request to view or summarize configuration, present the
     configuration returned by `create_agent_config`.
   - For a request handled by an `open_*` editor, call the originally requested
     `open_*` tool with the initialized `titleId`.
   - For another update, use the created configuration as the current state,
     merge the requested change, and continue the normal update flow.

`create_agent_config` can initialize only a supported primary Employee
Self-Service agent: the main ESS Core, IT, or HR agent, including supported
declarative versions. If creation reports that the selected agent is not an ESS
agent, explain that landing-page configuration is available only for those
primary ESS agents. General agents and attached subagents are ineligible. For
any other creation failure, surface the actual error.

## Build update payloads

`update_agent_config` takes `titleId` and a `config` object. Include the complete
new value for each affected section. Omit every unaffected section.

## Branding

Accent colors control end-user styling for buttons, links, chat bubbles, and
loading indicators in light and dark themes. Default Copilot colors apply when
branding is unset.

1. Read the current branding section.
2. Track the theme colors the maker requested to change.
3. Normalize changed colors to uppercase `#RRGGBB`.
4. Merge the changes into the complete current `theming` array.
5. Validate only the changed colors:

   ```powershell
   # Light only
   python scripts/validate_branding.py --light "#RRGGBB"

   # Dark only
   python scripts/validate_branding.py --dark "#RRGGBB"

   # Both
   python scripts/validate_branding.py --light "#RRGGBB" --dark "#RRGGBB"
   ```

6. Interpret the exit code:
   - `0`: every changed color meets WCAG AA; continue.
   - `1`: one or more changed colors have low contrast. Show the ratio,
     background, and required ratio, then ask whether to publish.
   - `2`: invalid input. Correct it before continuing.
7. Submit the complete merged section:

   ```json
   {
     "titleId": "<titleId>",
     "config": {
       "branding": {
         "theming": [
           { "name": "light", "accentColor": "#RRGGBB" },
           { "name": "dark", "accentColor": "#RRGGBB" }
         ]
       }
     }
   }
   ```

The backend allows at most five theme entries and theme names up to 30
characters. This experience uses the `light` and `dark` themes.

Reset branding by submitting `branding: { "theming": [] }` after confirmation.
A reset does not run contrast validation.

## Quick links

Quick links give employees direct access to important tenant resources from the
landing page. The presence of quick-link entries controls whether quick links
appear.

Validate the complete replacement array before writing:

- Maximum links: 10.
- `displayText`: non-empty, maximum 300 characters.
- `address`: non-empty, maximum 2,000 characters.
- `address`: absolute HTTPS URL.

Add, remove, and reorder operations use read-merge-write. A supplied list
replaces the complete array after confirmation. Clearing sends:

```json
{
  "titleId": "<titleId>",
  "config": {
    "quickLinksConfig": {
      "quickLinks": []
    }
  }
}
```

## Starter prompts

Categorized starter prompts show employees common ways to engage with the agent
and guide them into the right scenarios. These tenant-level prompts override
starter prompts configured in Copilot Studio.

When `open_starter_prompts` returns an empty or absent `pivots` array, the widget
opens with a default set of starter prompts. Accompany the widget with:

> No starter prompts are configured yet, so the editor is showing a default
> set. You can update and publish them, or publish them as-is.

Validate the complete replacement array before writing:

- Maximum pivots: 10.
- Pivot `displayName`: non-null, maximum 35 characters.
- Maximum prompts per pivot: 12.
- Prompt `title`: non-null, maximum 128 characters.
- Prompt `displayText`: non-null, maximum 4,000 characters.

Add, remove, and reorder operations use read-merge-write. Clearing sends
`pivots: []`.

## Insight cards

The insight-card section contains both controls:

- **Stay up to date** surfaces personalized, actionable cards for in-progress
  ticket status, required follow-ups, and time-sensitive tasks. Employees can
  select a card to start a related conversation. The cards use configured
  ticket-related sources and do not create or modify tickets.
- **Quick Access** surfaces high-frequency personal information, such as
  time-off balance/status, upcoming paid holidays, and service anniversaries.
  Employees can select a card to start a conversation.

Read the current section, merge the requested toggle, and submit both values
together:

```json
{
  "titleId": "<titleId>",
  "config": {
    "insightCardsConfig": {
      "isStayUpToDateEnabled": true,
      "isQuickAccessEnabled": false
    }
  }
}
```

## Display the read-only agent icon

1. Resolve `titleId`.
2. Call `view_agent_icon`. The tool returns text plus MCP `image` content so the
   host displays the PNG directly in the conversation.
3. When the tool reports that the agent has no custom icon, explain that to the
   maker.
4. Do not call `get_agent_config`, decode base64, write a local file, open a
   widget, or issue an update for this read-only request.

## Errors

- Authorization/403: explain that the maker needs permission to read and write
  Employee Agent configurations.
- Tenant gating: explain that landing-page configuration is unavailable for
  the tenant.
- Missing configuration/404: follow **Create or recreate missing
  configuration**.
- Ineligible agent during creation: explain that landing-page configuration is
  available only for a supported primary ESS Core, IT, or HR agent.
- Validation failure: show the field-specific server message.
- Tool failure: surface the error and do not report the update as successful.
