# Prompt-based card maker API

This module supplies the typed API adapter, MCP tools, and Card Prompts widget
contract. The Vorpal widget provides card prompt management and authoring.
Workspace configuration registers the server for local use.
To launch with the existing Python environment, run `python server.py` from this
directory; dependencies are declared in `requirements.txt`.

## Local Vorpal debugging

Open `solutions\ess-maker-skills` as the VS Code workspace. In its
`.vscode\mcp.json`, add `servers["ess-prompt-cards"]` using the same Python
executable as `ess-landing-page-config`, `args: ["server.py"]`, and
`cwd: "${workspaceFolder}\\src\\mcp\\agentconfig_prompt_cards"`. Set that
server's `env.VORPAL_WIDGET_ORIGIN` to `https://localhost`.

For a separate worktree, set `cwd` to that worktree's absolute
`solutions\ess-maker-skills\src\mcp\agentconfig_prompt_cards` directory.
Each checkout keeps its authoring sign-in cache in
`src\mcp\agentconfig_core\.local\msal_token_cache.bin`; complete browser
sign-in for the checkout serving the widget.

Set the worktree's `.local/config.json` `dataverseEndpoint` to the intended
maker environment. That endpoint binds authoring sign-in to its tenant.
A single cached authoring account is reused silently; several cached accounts
require browser account selection.

Run `npm run dev` from the local Vorpal checkout's `Client\Vorpal` folder.
Its HTTPS preview server must serve
`https://localhost/mcp-widget/prompt-cards/widget.js` with a trusted certificate
covering `localhost`. The Vorpal and Jabberwocky dev servers share port 443;
run only the intended widget server on that port.

Use **MCP: List Servers** in VS Code to start or restart `ess-prompt-cards`,
then ask chat to call `open_prompt_cards` with the target Employee Agent's
`titleId`. Use the verified landing-page title ID, not the Dataverse bot ID.
The opener reads real saved definitions. Row mutations and Save order
write to the authenticated tenant's backend, so use a test agent.

Authoring sign-in runs on a worker thread. API tools, audience search, and
saved-group name resolution share one client-initialization lock. MCP resource
reads remain responsive while browser sign-in is pending. The worker holds the
lock through initialization even when the requesting tool call is cancelled;
subsequent tool calls wait for and reuse the initialized client.

After editing Vorpal code, wait for the watch build and request a fresh widget.
The compose widget creates enabled definitions with Submit and disabled
definitions with Save for later. Both actions require a nonblank Name and
employee request. Cancel discards the form. A failed save retains
the form for review and reconciliation. Edit updates the selected definition;
Duplicate opens a creation form with its authored properties and a name prefixed
with "Copy of ". The localized name is truncated to 80 UTF-16 code units at a
complete Unicode code point. Edit preserves the definition ID and saved order.
Saved audience tags resolve their directory names while retaining the targeting IDs.

## Wire contract

Server: `ess-prompt-cards`. Resource:
`ui://widget/prompt-cards/PromptCards.html`, loading
`/mcp-widget/prompt-cards/widget.js` from the existing Vorpal widget origin
(`VORPAL_WIDGET_ORIGIN` overrides it). The shell has no direct API connection.

| Tool | Inputs |
|---|---|
| `open_prompt_cards` | `titleId` |
| `list_prompt_card_definitions` | `tenantId`, `titleId` |
| `create_prompt_card_definition` | scope, `definition` |
| `search_audience_groups` | `query` |
| `resolve_audience_groups` | `groupIds` (1–15 nonempty UUIDs) |
| `update_prompt_card_definition` | scope, `definitionId`, `patch` |
| `reorder_prompt_card_definitions` | scope, `definitions: [{definitionId, sortOrder}]` |
| `delete_prompt_card_definition` | scope, `definitionId` |

Scope means `tenantId` and `titleId`. The opener derives tenant scope from the
authenticated token; subsequent definition calls must supply that tenant and
the same title. Audience tools derive directory identity from authentication.
The server rejects a tenant mismatch and addresses only the supplied
title's collection. Widgets must retain their opening scope, reject mismatched
results, and never replace that scope from a later tool result. Authorization
and agent access remain server-enforced.

Definitions use camelCase: `definitionId`, `definitionName`, `dataPrompt`,
`presentationGuidance`, `audience`, `isDisabled`, `sortOrder`.
Response audiences are always arrays (null or omitted becomes `[]`).
Create accepts all but the server-assigned `definitionId`; patch accepts only
changed writable fields. Omitted patch fields stay unchanged; explicit `null`
clears presentation/audience. Null or empty audience means all agent users.
Unknown authored properties, empty patches, invalid IDs, and invalid reorder
batches are rejected. There are no action, follow-up, or scheduling properties.

Successful `structuredContent`:
- Open/list: `{tenantId, titleId, definitions}` — complete maker baseline,
  including disabled definitions and every audience.
- Reorder: `{tenantId, titleId, definitions}` — **updated definitions only**,
  sorted by order then ID, not necessarily the complete collection. Merge by
  ID or reload. Response identities and orders must match the requested batch.
- Create/update: `{tenantId, titleId, definition}`.
- Delete: `{tenantId, titleId, definitionId, deleted: true}`.
- Audience search: `{status: "success", groups: [{id, displayName, mail, isValid}],
  exhausted, pagesExamined}`. This uses the authenticated directory account;
  tool arguments and results are independent of tenant/title widget scope.
- Audience names: `{status: "success", groups: [{id, displayName, mail, isValid}]}`
  in requested ID order. Missing or ineligible groups keep their IDs with
  `displayName: "Unavailable group"` and `isValid: false`.

All mutation tools are app-only; list is model/app; open is model-visible with
the Card Prompts widget resource. The opener reads the saved card prompt collection.
Save for later is a real create/update with `isDisabled: true`; Submit uses
`false`. Creation accepts a name of at most 80 UTF-16 code units, a data prompt
of at most 2,000, optional presentation guidance of at most 1,000, and at most
15 audience group IDs. Required text fields must be nonblank. A sort-only save
must not alter disabled state.

## Audience discovery

The adapter imports Org Announcements' `GraphDirectoryClient` from
`agentconfig_org_announcements/graph_directory_client.py`, sourced from
[the audience-discovery implementation](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/pull/271)
and its [promotion branch](https://github.com/microsoft/Employee-Self-Service-Agent-Developer-Kit/pull/359).
The directory module and its offline regression suite accompany the adapter.

The eligibility policy matches Org Announcements: static security groups,
mail-enabled security groups, and classic distribution groups are offered.
Microsoft 365/Unified and dynamic-membership groups are excluded. Search
deduplicates IDs, returns at most 20 eligible groups, and examines at most three
50-item Graph pages. `exhausted` distinguishes complete results from a bounded
search. The backend remains authoritative for audience validity.

`search_audience_groups` is read-only and model/app-visible. It returns
`isError: true` and `{status: "failure", code, retryable}` on failure.
Search errors and telemetry contain fixed diagnostic categories, never group
names, IDs, query text, or provider-authored error details.

`resolve_audience_groups` is app-only, read-only, and idempotent. It uses the
same authenticated directory client, eligibility rules, and failure contract.
The shared client's bounded five-minute metadata cache serves resolved names.
Lookup failures propagate as failures; successful lookups mark missing groups
unavailable and preserve their targeting IDs. The widget offers retry after a
failed lookup and requires resolved, valid selections before saving.

Graph uses separate delegated `Directory.Read.All` consent with the established
Graph Command Line Tools public client and solution-root
`.local/.token_cache.bin` cache populated by `/setup`. Token acquisition first
tries the captured authoring tenant/account silently, then opens browser sign-in.
After a Graph 401, the next request forces a refresh for that same account.
The failed Graph request returns an authentication-required error; the retry
validates the refreshed token's identity before accessing the directory.
The Graph token must match both the authenticated AgentConfiguration `tid` and
`oid`; consent and Conditional Access remain tenant requirements. The optional
`GRAPH_ACCESS_TOKEN` environment variable accepts a matching delegated Graph
token for local testing. Substrate credentials remain specific to that resource.
Directory clients are reused for the captured account; identity changes retire
the captured client after its in-flight searches finish.

## Definition API failures

Definition read/write failures use `isError: true` and
`{tenantId, titleId, errors: [{code, message, retryable, httpStatus?}], outcome?}`.
If authentication cannot be resolved, `tenantId` is null, never the unverified
input tenant.
Ambiguous mutation outcomes use `unknown`; reorder failures use `partial`
because writes are non-atomic. Preserve local edits and reload/reconcile before
retrying. Never blindly replay a create. Transport and gateway failures are not
retried for creates/reorders; the shared core still handles explicit rejection
(429) and one same-account authentication refresh. Error messages and telemetry
never include authored prompts or audience IDs. MCP argument-schema failures
are protocol validation errors and occur before the scoped handler.

## Backend and release prerequisites

The adapter reuses `agentconfig_core` authentication/retry behavior and the
landing-page client's v1.1 tenant/EmployeeAgents paths and case conversion.
It uses the maker `GetAllDefinitions()` function, not audience-filtered reader
routes, and sends no OData query options.

The backend must enable `EnablePromptBasedCards`. The delegated maker must pass
`ReadWriteEmployeeAgentContent` (orgsettings read/write scope, qualifying admin,
or agent owner/collaborator) for an existing tenant and agent. This slice does
not implement FlightCheck integration or a prompt-safety validation endpoint.
Prompt-safety validation is an upstream release prerequisite, not a local
validation guarantee. Offline tests verify the source-backed controller
contract; they do not establish deployment availability or live authorization.
The widget checks a maximum of 50 definitions, including disabled card prompts,
before creation or duplication. Edit remains available at the limit.
Server-side enforcement of that collection limit is a separate
WeveNova prerequisite; this adapter's field validation does not enforce a
concurrent collection cap.

Operation telemetry uses the existing API-call emitter with fixed operation
names, outcome, and duration only. The app-only `report_client_events` bridge
uses the existing Vorpal telemetry envelope and shared SDK validation;
`appName: "PromptCards"` requires no additional allowlist.
