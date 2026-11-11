# Power Fx + Power Automate: authoring flow-backed agent topics

> Authoring reference for Copilot Studio agent topics that consume an existing **Power Automate flow** through **Power Fx**, including dynamic option lists, typed tables, and status/success handling. Read this when editing a topic that reads flow output. Flow authoring, deployment, registration, and repair take place outside ADK. For backend-specific routing and field mapping, follow the cross-links below.

## Required architecture (non-negotiable constraints)

These reflect platform behavior — deviating causes silent data loss or a non-functional topic.

1. **Fetch data through a flow, then type it in the topic — never bind raw flow/connector output to UI or Power Fx.** A connector's list/query operation returns an untyped (`Any`) dynamic table; an Adaptive Card `Input.ChoiceSet` (or any Power Fx that indexes columns) needs design-time-known field types the untyped output cannot provide in-topic. Have the flow **serialize its result to a string** (stringify the payload) and declare that response field as `type: string`; the topic then `ParseValue`s the string into a typed record/table it can bind. Do **not** bind connector or flow output directly to a card or a column reference.

2. **Route the flow call through a system-style topic.** Wrap the flow's `InvokeFlowAction` in a dedicated backend topic with a clean input/output contract that owns error handling; the user-facing topic calls it via `BeginDialog`. This is an ESS authoring invariant — see [authoring-invariants.md](authoring-invariants.md).

3. **Return and honor a status code + success flag.** The flow returns a success boolean and a status code declared as JSON-schema **`type: number`, not `integer`** (`integer` resolves to an unusable type in Power Fx). The system-style topic checks the success flag: handle a no-data status (e.g. 404) softly, otherwise route to the agent's global error handler (`OnError`) so a failure surfaces a message instead of hanging.

4. **If the topic submits back through the ESS orchestrator, map every field.** A field the topic collects but does not map is **silently dropped** from the request. The mapping is an ESS template-config concern — see [isv-integration-pattern.md](../conformance/isv-integration-pattern.md).

## Guardrails / pitfalls to avoid

- **Do not** use JSON-schema `integer` for a numeric flow output consumed by a topic — use `number`.
- **Do not** reference unqualified column names in a `ForAll`/lookup over an untyped table — type the variable first via `ParseValue` from the flow's string output.
- **Do not** leave a flow `Response` action as `kind: PowerApp` in an agent flow: it must be `kind: Skills`, or the output binding breaks at publish. Correct flow definitions outside ADK.
- **Do not** omit a submitted field from the orchestrator field mapping — unmapped = silently dropped.
- **Do not** expose a generic list/read connector as a generatively-invocable agent tool; keep connector use inside a purpose-built flow with a fixed table/query, and scope the service-account read permissions tightly.
- **Preserve exact topic filename casing.** Creation derives the schema suffix from the filename verbatim. Use the verified schema in `BeginDialog` references so the caller identifies the intended topic.
- **Do not** treat an automatically-inferred input as merely blank-or-present. An inferred/automatic input can be **error-valued**, not just empty, and `IsBlank()` is not a safe guard because evaluating the value can **fail before** the branch is reached. Validate the input explicitly (e.g. `IsError()` plus a type/format check) **before** any `Split`, `First`, card binding, or flow invocation that consumes it — put the validation ahead of the first expression that reads the value, not inside the consumer.
- **Do not** render a card until every value and table it binds has a valid **type** and an **initialized** value. A card that binds an unparsed, error-valued, or not-yet-typed table fails at render/publish (see the `ParseValue`-typing rule above); initialize and type each bound variable in a step that runs before the `AdaptiveCardPrompt`.

## Existing flow dependencies

Use the installed flow's actual input/output contract when authoring a topic. Complete flow authoring, registration, activation, and repair in Power Automate or the supported product-extension setup, outside general ADK authoring.

Read-only inspection remains separate from deployment. When requested and its independent target/authentication prerequisites are satisfied, `python scripts/validate.py "<flow name>"` reports the existing registration state. It does not repair it.

Save topic changes through the normal topic owner. Publication is separately approved; consult [topic-publication-advisories.md](topic-publication-advisories.md) before session-led pre-publication assistance.
