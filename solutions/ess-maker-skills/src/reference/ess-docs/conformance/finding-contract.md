# Conformance finding contract

The shared **finding contract** for every conformance lens the `topics/review` skill runs — Power Fx
topic-local, dangling `Global.*`, UX contract, ISV conformance, ISV integration pattern, and ServiceNow
config/topic. Each lens produces findings in this one shape so the review can rank, locate, and
de-duplicate them uniformly. The individual lens docs describe **what** each looks for; this doc defines
**how** a confirmed finding is scored and reported.

Findings are **advisory prose** in the response — no lens writes anything to disk. This is the internal
(structured) contract; the customer-facing translation is Step 7 of the `topics/review` skill.

## Precision bar

Report a finding only at **≥80% confidence** that:

1. The cited site actually contains the claimed pattern — re-read the site (expression text, card body, or
   detector output) before reporting. This is where reviewer hallucinations surface.
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

## Finding IDs

Each lens uses its own prefix so findings are distinguishable and stable across runs. IDs are
`<PREFIX>-NNN` (for example `BTPF-001`).

| Prefix | Lens |
| --- | --- |
| `BTPF` | Power Fx topic-local |
| `BTDG` | Dangling `Global.*` |
| `BTUX` | UX contract |
| `BTIC` | ISV conformance |
| `BTIP` | ISV integration pattern |
| `BTCF` | ServiceNow config/topic |

## Output format

**Locators (important).** The fix is applied in the chat panel, not by a human navigating to a line — so
cite each site by its **stable node identity**, which is what a fixer keys on: the action's `id:`, its
`displayName:` (if present), and its action `kind:`. Include a short excerpt (the expression, the card
field, or the reported name) so the target is unambiguous. A line number is **best-effort context only**,
never the primary locator — line numbers drift and the agentic read does not track them reliably.

```text
<PREFIX>-NNN — <one-line summary>
  Severity:     HIGH | MEDIUM | LOW
  Reachability: REACHABLE_NORMAL_UI | REACHABLE_NORMAL_UI_WITH_DATA_PRECONDITION | NOT_REACHABLE_VIA_BOT_UI | OPERATOR_OR_HYGIENE_ONLY
  Site(s):
    - kind=<action kind>  id=<node id>  displayName=<node displayName, if any>  detail=<short excerpt>  (~line <N>)
    - (additional sites if multi-site)
  What's wrong:   <1-3 sentence anti-pattern explanation>
  Why it matters: <observable user/operator impact>
  Concrete fix:   <the canonical Fix for the flagging heuristic (see its lens doc), made specific to this site>
  Fix targets:    <the node id(s) the fix edits or the node it inserts before/after — so the fixer can act>
```

Each lens doc carries a canonical **Fix** next to the heuristic that owns it. Fill `Concrete fix` from
that pattern, specialized to the site — this keeps the suggested fix ESS-correct and lets `/update` apply
it directly (it maps the finding's `<PREFIX>` back to the lens doc via the table above).

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
