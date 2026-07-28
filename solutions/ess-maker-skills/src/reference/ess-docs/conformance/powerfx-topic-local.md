# Power Fx topic-local conformance analysis

Analysis guidance for the **Power Fx expression** checks used by the `topics/review` skill. These checks
find bugs expressed **inside the Power Fx expressions of a single authored topic** — read directly from
the one `.mcs.yml` file, needing only the topic itself.

> **Scope:** the checks below are each decidable from the authored `.mcs.yml` alone (plus, at most, the
> other topics in the maker's own agent folder). Do not attempt checks that need data beyond the topic —
> **dead/dangling `Global.*`** (needs the agent's declared variables) and **upstream/downstream
> error-code coverage** (needs the shared workflow's emitted error strings) are **not covered here**.

## How to run this lens

You are invoked with the path to one authored topic (`{agent.folder}/topics/{Name}.mcs.yml`). Read the
whole file. Walk every Power Fx expression (any value beginning with `=`, and expression bodies inside
`AdaptiveCardPrompt.card` / `AdaptiveCardTemplate.cardContent`). Evaluate each against the heuristics
below. This is a **judgment lens**, not a closed rule set — each heuristic is a starting question; the
precision bar and reachability rubric in the shared
[`finding-contract.md`](finding-contract.md) decide what becomes a finding.

**Severity rests on structure first; runtime heuristics corroborate.** The LOW-caps below are grounded in a
**structurally visible** fact — that the topic delegates its backend call to a shared `*System*` orchestrator
(the ESS pattern: a `BeginDialog` into a `*System*` topic that owns the call, failure handling, and response
shaping). That delegation is readable from the topic itself, so **apply the caps whether or not the runtime
docs are present**. The cap assumes the delegation target is an **unmodified shared `*System*`/OnError topic
that follows the ESS pattern** — that is what makes central failure handling a safe inference from the caller
alone. If the target is not a `*System*`-named shared topic, or the maker has modified the shared system
topic, that assumption does not hold: score the finding on its own structure rather than applying the cap.
When `../runtime/confirmed-runtime-heuristics.md` (synced by
`scripts/sync_runtime_heuristics.py`) is available, read it to corroborate and refine (notably the
AI-orchestration "no data" behavior and OnError dialog termination); `../runtime/pending-runtime-heuristics.md`
is provisional — apply with caution. Check for these docs with a **direct filesystem test of the exact path**
(the `runtime/` folder is gitignored, so a workspace/indexed search reports a present doc as missing — that
false-absent would silently deny the corroboration to internal makers who have the docs synced). When the
runtime docs are absent, still apply the structural caps and
note that runtime corroboration was unavailable — do **not** fall back to structural-HIGH on the delegated
pattern.

## Value syntax (read before flagging any string)

Copilot Studio node values come in two syntaxes; misreading one for the other is a common false-positive
source, so classify the value **before** applying any string heuristic below:

- **Power Fx expression** — the value **starts with `=`** (e.g. `value: =Topic.ServiceNowData`,
  `value: =PlainText(Topic.CaseDetails.Description)`). Only these are Power Fx; the string heuristics apply to
  their expression text.
- **Text-with-variables (template string)** — a value that does **not** start with `=` (typical on
  `SetTextVariable`, and on message `text:` / `speak:`). Here `{Topic.X}`, `{Global.X}`, `{System.X}` are
  **runtime substitution placeholders**, not literals. `value: "HR Case #{Topic.CaseDetails.CaseNumber}"`
  dynamically interpolates the case number at runtime — it is **not** "the title hardcoded instead of using
  the case number," and `{...}` interpolation is **never** a hardcoded/literal-string bug. Do not flag it.
  (Real hardcoding is a *fixed* value with no `{...}` where a dynamic one is expected, or an environment-bound
  literal — see "Hardcoded environment-specific values" below.)

## Heuristics (topic-local)

- **Unqualified field value in a record literal (hygiene).** A record-literal field whose value is a bare
  field name — `{ID: ID}` — while its siblings in the same literal explicitly qualify their source (e.g.
  `Expiration_Date: currentRecord.Expiration_Date`). A record-literal value is evaluated in the **enclosing**
  scope, not the record's own fields, so this is **not** self-referential and does **not** silently bind to
  blank: inside a `ForAll`/`With` row the bare name resolves to that row's in-scope field (it works), and if
  no such field is in scope Power Fx raises a name error at author time. When a sibling binds
  `currentRecord: ThisRecord`, the bare `ID` and `currentRecord.ID` are the **same value** — so qualifying it
  is a no-op for correctness. Treat this as a **LOW / hygiene** consistency nit (bare vs qualified siblings; a
  future inner-scope binding of the same name could shadow it), never a "comes through blank" data bug, and
  do not raise severity on it. **Fix:** qualify the value to match its siblings (e.g. `ID: currentRecord.ID`).
- **Power Fx string-literal quote-run quirks.** Doubled double-quotes are escape syntax: `"a""b"` is the
  3-char string `a"b`, and `""""""` (six quotes) is the 2-char string `""`, **not** an empty string. An
  equality check `value = """"""` does **not** test for empty. Count quote-runs carefully — miscounting is
  the exact class of error this catches.
- **`ParseValue` / `ParseJSON` without an `isSuccess` gate (structural half).** When a topic calls a
  flow/dialog that returns `isSuccess`, then runs `ParseValue`/`ParseJSON` on the response **without a
  preceding branch on `isSuccess = false`**, a schema mismatch (API drift) silently produces blanks
  downstream. Flag when the parse site is **not** inside/after an `isSuccess = true` guard. **Severity rests
  on how the response was obtained:** when the topic uses the standard `ParseValue → ForAll → response-table`
  pattern and **delegates the call to a shared `*System*` orchestrator topic** (structurally visible — the ESS
  pattern), failure is handled centrally and the AI-orchestration layer emits a "no data" message, so the
  finding is `NOT_REACHABLE_VIA_BOT_UI`, **cap at LOW** (the confirmed runtime heuristics corroborate this;
  apply the cap even without them). Reserve higher severity for a topic that parses a response it fetched
  **directly** (no shared orchestrator) or that renders a hardcoded card regardless of data. **Fix:** for the
  delegated (LOW) case the shared error path already prevents the blank from reaching the user — the finding is
  informational; optionally gate the parse on `isSuccess = true` for clarity, but do **not** add a local error
  handler (that duplicates the shared path — see `../customization/authoring-invariants.md`). For the
  **direct**-call case, move the parse inside an `isSuccess = true` branch or add an `isSuccess = false`
  ConditionGroup before it. For the authoring-side type-safety rules behind a correct parse (untyped flow
  output → stringify → `ParseValue` into a typed table, and `number` not `integer` for the status code), see
  `../customization/powerfx-and-power-automate-authoring.md`.
- **Flow failure-branch gaps (structural half).** A `BeginDialog`/`InvokeFlowAction` call site whose
  result path has **no `isSuccess = false` (or equivalent failure) branch** — the topic continues with
  empty data on failure. Flag the missing failure branch, but **score on structure**: if the call is a
  `BeginDialog` into a shared `*System*`/OnError topic that terminates or centrally handles failure
  (structurally visible), code after it is `NOT_REACHABLE_VIA_BOT_UI` (**cap at LOW**, applied with or without
  the runtime docs) — do not claim "the user gets no error." Reserve higher severity for a **direct** flow
  call that ignores `isSuccess`, or a **write** that proceeds on unverified success. **Fix:** for the delegated
  (LOW) case the shared error path already handles the failure and stops the dialog — the finding is
  informational and the topic should **not** add its own failure branch (that reimplements the shared path —
  see `../customization/authoring-invariants.md`). Only for a **direct** flow call add an `isSuccess = false`
  ConditionGroup after the call with an error `SendActivity` that stops the flow.
- **Hardcoded environment-specific values.** GUID-like literals, agent IDs, environment IDs, connection
  IDs, model IDs (`aIModelId`), and flow IDs (`flowId`) written inline in the topic. These are
  environment-bound and should be resolved by the platform (connection references / solution-aware
  bindings), not hardcoded — hardcoding breaks on import to another environment. **Fix:** replace the
  literal with a connection reference or environment variable the platform resolves per environment.
  (This is about environment-bound IDs only — a `{Topic.X}`/`{Global.X}` placeholder in a text-with-variables
  value is dynamic substitution, not hardcoding; see "Value syntax" above.)
- **String/numeric parsing without explicit guards.** `Find()` / `Substring()` / `Text(Value(...))`
  chains **on user-supplied strings** with no length/format pre-check — throws or misparses on unexpected
  input. **Scope this narrowly to user input:** it does **not** fire on `ParseValue` / `ParseJSON` of a
  trusted orchestrator/backend response (that is the parse-before-success heuristic above — reachability-
  capped, not this one), nor on outbound request construction like `JSON(Table(...))` in a `BeginDialog`
  parameter binding (building the request, not parsing input). Flag only a `Find`/`Substring`/`Value`-style
  parse whose operand traces to a user-entered value. **Fix:** add an `IsBlank`/length/format pre-check before
  the parse and branch on the invalid case.
- **Write-then-refetch-then-lookup-by-mutable-key.** A `SetVariable` that writes via an Update call,
  then a later `BeginDialog` re-fetches the list, then a `LookUp` matches by a user-supplied text key —
  a race window between write and refetch plus lookup-key-collision risk.
- **Brittle name/text matching.** Direct `=` comparison or `Find()` on user-facing text (names, error
  messages). Domain judgment — flag low-severity unless you can argue a concrete user-visible failure.
- **Numeric range caps that may reject valid inputs.** `<=` / `<` against a small constant on a
  domain-valued quantity (years, count). Domain judgment — only flag if the cap plausibly rejects a
  realistic valid case (retry-counter caps are **not** bugs).

## Reporting

This lens uses the `BTPF` finding-ID prefix. Apply the precision bar, reachability scoring, output format,
and Defense-in-depth conventions from the shared [`finding-contract.md`](finding-contract.md). Locate each
finding by the action's node identity (`id` / `displayName` / `kind`) with a short expression excerpt.

## What this lens does NOT do

- Does not analyze adaptive-card field/visibility contracts (that is the UX lens), plugin C#, or workflow
  JSON action graphs.
- Does not evaluate dead/dangling `Global.*` or upstream/downstream error-code coverage — those need
  cross-topic + reference data and are handled by a separate reference-aware check.
- Does not build an AST — token/expression-level reading only.
- Findings are **advisory prose** in the response; this lens writes nothing to disk.
