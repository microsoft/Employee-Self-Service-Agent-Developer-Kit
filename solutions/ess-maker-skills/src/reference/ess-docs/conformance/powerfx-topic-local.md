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

## Heuristics (topic-local)

- **Self-referential record literals.** Record-literal fields where the value is the unqualified field
  name — `{ID: ID, Name: Name}`. Almost always an intended `ID: currentRecord.ID` (or similar) that was
  left dangling, so the field silently binds to itself / blank.
- **Power Fx string-literal quote-run quirks.** Doubled double-quotes are escape syntax: `"a""b"` is the
  3-char string `a"b`, and `""""""` (six quotes) is the 2-char string `""`, **not** an empty string. An
  equality check `value = """"""` does **not** test for empty. Count quote-runs carefully — miscounting is
  the exact class of error this catches.
- **`ParseValue` / `ParseJSON` without an `isSuccess` gate (structural half).** When a topic calls a
  flow/dialog that returns `isSuccess`, then runs `ParseValue`/`ParseJSON` on the response **without a
  preceding branch on `isSuccess = false`**, a schema mismatch (API drift) silently produces blanks
  downstream. Flag when the parse site is **not** inside/after an `isSuccess = true` guard.
- **Flow failure-branch gaps (structural half).** A `BeginDialog`/`InvokeFlowAction` call site whose
  result path has **no `isSuccess = false` (or equivalent failure) branch** — the topic continues with
  empty data on failure and the user gets no error. Flag the missing failure branch.
- **Hardcoded environment-specific values.** GUID-like literals, agent IDs, environment IDs, connection
  IDs, model IDs (`aIModelId`), and flow IDs (`flowId`) written inline in the topic. These are
  environment-bound and should be resolved by the platform (connection references / solution-aware
  bindings), not hardcoded — hardcoding breaks on import to another environment.
- **String/numeric parsing without explicit guards.** `Find()` / `Substring()` / `Text(Value(...))`
  chains on user-supplied strings with no length/format pre-check — throws or misparses on unexpected
  input.
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
