# ServiceNow ITSM — Create Ticket with runtime dependent dropdowns

> Authoring reference for adding **runtime dependent dropdowns** to a ServiceNow ITSM Create Ticket topic: Category → Subcategory (filtered live from `sys_choice`) plus a Configuration Item picker sourced from the caller's assigned `cmdb_ci` devices. Read this when creating or updating a Create Ticket topic that needs live, dependent option lists rather than hardcoded choices. It carries the platform-behavior constraints and pitfalls that apply on every such change regardless of environment.

## Required architecture (non-negotiable constraints)

These reflect platform behavior — deviating causes silent data loss or non-functional dropdowns.

1. **Fetch options through a flow, not a direct connector call.** ServiceNow list operations return an untyped (`Any`) dynamic table. An Adaptive Card `Input.ChoiceSet` requires design-time-known field types, which the connector output cannot provide in-topic. The flow must serialize its result to a **string** (e.g., stringify the connector `result`) and declare the response field as `type: string`. The topic then `ParseValue`s that string into a typed table. Do **not** attempt to bind connector output directly to a card dropdown.

2. **Route the flow call through a system-style topic.** Wrap the flow's `InvokeFlowAction` in a dedicated backend topic that exposes a clean input/output contract and owns error handling. The user-facing (UI) topic calls this system-style topic via `BeginDialog`. This mirrors the module's existing UI-topic → system-topic → flow convention.

3. **Return and honor a status code + success flag.** The flow returns `issuccessful` (boolean) and `statuscode` (**JSON-schema `type: number`, not `integer`** — `integer` resolves to an unusable type in Power Fx). The system-style topic checks `IsSuccessful = false`: on a no-data status (e.g., 404) handle softly; otherwise route to the agent's global error handler (`OnError`) so failures surface a message instead of hanging.

4. **Map every submitted field in the template config.** The create request body is built by mapping the topic's `InputParameters` to ServiceNow columns **solely** via the template config's `InputFieldMapping.UserParameters` list. Any field not listed is **silently dropped**. Ensure `category → category`, `subcategory → subcategory`, and the configuration item → `cmdb_ci` are all present, in addition to the standard fields (`short_description`, `description`, `contact_type`, `caller_id`).

## Template config field mapping (verify)

Confirm the CreateTicket `InputFieldMapping.UserParameters` maps every submitted field, including **subcategory** and the **configuration item (`cmdb_ci`)**; any field not listed is silently dropped from the create request.

## Guardrails / pitfalls to avoid

- **Do not** use JSON-schema `integer` for a numeric flow output consumed by a topic — use `number`.
- **Do not** rely on unqualified column names in a `ForAll` over an untyped table — type the variable first (via `ParseValue` from the flow's string).
- **Do not** omit any submitted field from the template config `UserParameters` — unmapped = silently dropped.
- **Do not** expose a generic "List Records"/read connector as a generatively-invocable agent tool; keep any connector use inside a purpose-built flow with fixed table/query, and scope the ServiceNow service-account read permissions tightly.
- **Do not** name the new system topic file in kebab-case. A topic's schemaname is derived from its filename **verbatim** and is **immutable** once created; the UI topic references the system topic by **PascalCase** schemaname in `BeginDialog`. Name the file to match the reference exactly (e.g. `ServiceNowITSMSystemGetCreateTicketOptions.mcs.yml`), or the reference will dangle at publish. `push` warns when a new topic gets a kebab schemaname, but cannot auto-fix it (the ISV casing — `ITSM`, `HRSD` — is unrecoverable from kebab).

## Deployment & verification (ADK tooling)

`/push` handles agent-flow registration end to end for a flow authored per the constraints above — it preserves the flow's client `workflowId`, sets `modernflowtype=1`, creates and binds a flow-scoped connection reference, links the flow to its invoking system topic (`botcomponent_workflow`), and activates it. It also **auto-corrects** every flow `Response` action to `kind:Skills` (an agent flow requires this; `kind:PowerApp` breaks the output binding at publish), so a mis-authored Response is fixed on push with a notice.

After pushing:

1. **Publish** — pushed **topic** changes only go live in the test pane/runtime after the agent is published (flow `clientdata` edits are live immediately). Run `python scripts/publish.py`.
2. **Validate** — confirm the new flow is runtime-invocable with `python scripts/validate.py "Get Create Ticket Options"`: it verifies the flow is activated, `modernflowtype=1`, all Response actions are `kind:Skills`, has a bound flow-scoped connection reference, and is linked to a system topic. Activation triggers live connector-schema validation, so if the backing ServiceNow instance is unreachable (e.g. hibernating), activation can fail transiently — re-run once it is reachable.
