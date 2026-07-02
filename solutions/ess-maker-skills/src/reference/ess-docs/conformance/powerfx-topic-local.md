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
precision bar and reachability rubric decide what becomes a finding.

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

## Precision bar

Report a finding only at **≥80% confidence** that:

1. The cited expression actually contains the claimed pattern (re-read the expression text before
   reporting — this is where reviewer hallucinations surface).
2. The pattern is a real defect, not an intentional design choice.
3. Either the bug is user-reachable through normal chat UI with normal auth (HIGH/MEDIUM), or it is real
   code/operator-level damage (LOW).

When the same anti-pattern occurs at multiple sites, **report one finding with all sites listed**, not N
findings.

## Reachability scoring (dominant input to severity)

- **REACHABLE_NORMAL_UI** — a normal user with normal auth doing what the topic is built to do hits this
  path. -> HIGH (or MEDIUM if user-visible impact is small).
- **REACHABLE_NORMAL_UI_WITH_DATA_PRECONDITION** — reachable via normal UI but needs a specific data
  state. -> MEDIUM.
- **NOT_REACHABLE_VIA_BOT_UI** — upstream-gated; only reachable via flow-direct invocation, a race
  window, or a future code change. Real bug, no user impact today. -> LOW.
- **OPERATOR_OR_HYGIENE_ONLY** — dead code, redundant writes, hardcoded IDs with no runtime user impact.
  -> LOW.

## Output format

Report findings as a numbered list using `BTPF-NNN` IDs (Bot Topic Power Fx).

**Locators (important).** The fix is applied in the chat panel, not by a human navigating to a line —
so cite each site by its **stable node identity**, which is what a fixer keys on: the action's `id:`,
its `displayName:` (if present), and its action `kind:`. Include the short expression excerpt so the
target is unambiguous. A line number is **best-effort context only**, never the primary locator (line
numbers drift and the agentic read does not track them reliably).

```text
BTPF-NNN — <one-line summary>
  Severity:     HIGH | MEDIUM | LOW
  Reachability: REACHABLE_NORMAL_UI | REACHABLE_NORMAL_UI_WITH_DATA_PRECONDITION | NOT_REACHABLE_VIA_BOT_UI | OPERATOR_OR_HYGIENE_ONLY
  Site(s):
    - kind=<action kind>  id=<node id>  displayName=<node displayName, if any>  expr=<short excerpt>  (~line <N>)
    - (additional sites if multi-site)
  What's wrong:   <1-3 sentence anti-pattern explanation>
  Why it matters: <observable user/operator impact>
  Concrete fix:   <specific proposed change — Power Fx snippet or YAML edit>
  Fix targets:    <the node id(s) the fix edits or the node it inserts before/after — so the fixer can act>
```

Sort findings HIGH -> MEDIUM -> LOW. After the list, emit a **Defense-in-depth** section for real
anti-patterns whose sites all scored `NOT_REACHABLE_VIA_BOT_UI` or `OPERATOR_OR_HYGIENE_ONLY`, so
reviewers prioritize reachable bugs first:

```text
## Defense in depth (no reachable user impact today)

DiD-NNN — <one-line summary>
  Pattern:   <anti-pattern name>
  Site(s):   <topic file>:<line>, ...
  Rationale: <why it's worth fixing despite no current reachability>
```

## What this lens does NOT do

- Does not analyze adaptive-card field/visibility contracts (that is the UX lens), plugin C#, or workflow
  JSON action graphs.
- Does not evaluate dead/dangling `Global.*` or upstream/downstream error-code coverage — those need
  cross-topic + reference data and are handled by a separate reference-aware check.
- Does not build an AST — token/expression-level reading only.
- Findings are **advisory prose** in the response; this lens writes nothing to disk.
