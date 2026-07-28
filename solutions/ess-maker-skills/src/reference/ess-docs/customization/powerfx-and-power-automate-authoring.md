# Power Fx + Power Automate: authoring flow-backed agent topics

> Authoring reference for Copilot Studio agent topics that call a **custom Power Automate flow** and consume its output in **Power Fx** — dynamic option lists, typed tables, or status/success handling. It covers the type-safety constraints that make a flow's output usable inside a topic, plus the ADK deploy/verify loop that makes an authored flow agent-invocable. Read this when authoring or editing a topic that reads data back from a custom flow. Backend-agnostic — for backend-specific routing and field mapping, follow the cross-links below.

## Required architecture (non-negotiable constraints)

These reflect platform behavior — deviating causes silent data loss or a non-functional topic.

1. **Fetch data through a flow, then type it in the topic — never bind raw flow/connector output to UI or Power Fx.** A connector's list/query operation returns an untyped (`Any`) dynamic table; an Adaptive Card `Input.ChoiceSet` (or any Power Fx that indexes columns) needs design-time-known field types the untyped output cannot provide in-topic. Have the flow **serialize its result to a string** (stringify the payload) and declare that response field as `type: string`; the topic then `ParseValue`s the string into a typed record/table it can bind. Do **not** bind connector or flow output directly to a card or a column reference.

2. **Route the flow call through a system-style topic.** Wrap the flow's `InvokeFlowAction` in a dedicated backend topic with a clean input/output contract that owns error handling; the user-facing topic calls it via `BeginDialog`. This is an ESS authoring invariant — see [authoring-invariants.md](authoring-invariants.md).

3. **Return and honor a status code + success flag.** The flow returns a success boolean and a status code declared as JSON-schema **`type: number`, not `integer`** (`integer` resolves to an unusable type in Power Fx). The system-style topic checks the success flag: handle a no-data status (e.g. 404) softly, otherwise route to the agent's global error handler (`OnError`) so a failure surfaces a message instead of hanging.

4. **If the topic submits back through the ESS orchestrator, map every field.** A field the topic collects but does not map is **silently dropped** from the request. The mapping is an ESS template-config concern — see [isv-integration-pattern.md](../conformance/isv-integration-pattern.md).

## Guardrails / pitfalls to avoid

- **Do not** use JSON-schema `integer` for a numeric flow output consumed by a topic — use `number`.
- **Do not** reference unqualified column names in a `ForAll`/lookup over an untyped table — type the variable first via `ParseValue` from the flow's string output.
- **Do not** leave a flow `Response` action as `kind: PowerApp` in an agent flow — it must be `kind: Skills`, or the output binding breaks at publish. (`push` auto-corrects this on the pushed payload with a notice; the on-disk source is left unchanged.)
- **Do not** omit a submitted field from the orchestrator field mapping — unmapped = silently dropped.
- **Do not** expose a generic list/read connector as a generatively-invocable agent tool; keep connector use inside a purpose-built flow with a fixed table/query, and scope the service-account read permissions tightly.
- **Do not** name a new system topic file in kebab-case. A topic's schemaname is derived from its filename **verbatim** and is **immutable** once created; the caller references it by its exact (typically mixed-case) schemaname in `BeginDialog`. Name the file to match the reference exactly, or the reference dangles at publish. `push` warns on a kebab schemaname but cannot auto-fix it — the original casing is unrecoverable from kebab.

## Deploy & verify the flow (ADK tooling)

An authored flow is not agent-invocable until it is registered and activated. `/push` handles this end to end — it preserves the flow's client `workflowId`, sets `modernflowtype=1`, creates and binds a flow-scoped connection reference, links the flow to its invoking system topic (`botcomponent_workflow`), coerces every `Response` action to `kind:Skills`, and activates it.

After pushing:

1. **Publish** — pushed **topic** changes only go live once the agent is published (a flow's `clientdata` edits are live immediately). Run `python scripts/publish.py` — see [publish.md](../deployment/publish.md).
2. **Validate** — confirm the flow is runtime-invocable: `python scripts/validate.py "<your flow name>"` checks it is activated, `modernflowtype=1`, all Response actions are `kind:Skills`, has a bound flow-scoped connection reference, and is linked to a system topic.
3. **Repair** — activation triggers live connector-schema validation, so if the backing service is unreachable (e.g. hibernating) registration can fail transiently. Re-drive it with `python scripts/push.py --repair` once the service is reachable.
