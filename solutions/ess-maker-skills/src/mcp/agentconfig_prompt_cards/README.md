# Prompt-based card maker API

PR 1 supplies the typed API adapter, MCP tools, and Recipes widget contract.
It does not register a maker command or install the server in workspace defaults.
The widget bundle, recipe authoring UI, and routing/packaging ship separately.
To launch with the existing Python environment, run `python server.py` from this
directory; dependencies are declared in `requirements.txt`.

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
| `update_prompt_card_definition` | scope, `definitionId`, `patch` |
| `reorder_prompt_card_definitions` | scope, `definitions: [{definitionId, sortOrder}]` |
| `delete_prompt_card_definition` | scope, `definitionId` |

Scope means `tenantId` and `titleId`. The opener derives tenant scope from the
authenticated token; subsequent calls must supply that tenant and the same
title. The server rejects a tenant mismatch and addresses only the supplied
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

All mutation tools are app-only; list is model/app; open is model-visible with
the widget resource. The opener is read-only and never creates a draft recipe.
Save for later is a real create/update with `isDisabled: true`; regular
definition save uses `false`. A sort-only save must not alter disabled state.

Failures use `isError: true` and
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

Operation telemetry uses the existing API-call emitter with fixed operation
names, outcome, and duration only. The app-only `report_client_events` bridge
uses the existing Vorpal telemetry envelope and shared SDK validation;
`appName: "PromptCards"` requires no additional allowlist.
