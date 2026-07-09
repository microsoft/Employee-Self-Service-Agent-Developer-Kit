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

**Check the runtime heuristics before finalizing reachability.** ESS runtime behavior is documented in
`../runtime/confirmed-runtime-heuristics.md` (authoritative) and `../runtime/pending-runtime-heuristics.md`
(provisional), synced by `scripts/sync_runtime_heuristics.py`. A confirmed rule can move a finding to
`NOT_REACHABLE_VIA_BOT_UI` (cap at LOW) even when a purely structural read looks HIGH — for example, the
AI-orchestration layer emitting a "no data" message on an empty parse, or an OnError/`*System*` topic
terminating the dialog stack so code after it never runs. Apply confirmed rules directly; apply pending
rules with caution and say so. If the docs are absent, score structurally and note that runtime calibration
was unavailable.

**When a heuristic caps a finding to unreachable and you drop it, leave a breadcrumb.** If a runtime
heuristic reclassifies a would-be finding to `NOT_REACHABLE_VIA_BOT_UI` and you decide it is an intentional,
centrally-handled design (so you surface **no** finding — e.g. an ungated `ParseValue` in a topic that
delegates to a shared `*System*` orchestrator), record it in the catalog's `suppressions` array rather than
letting it vanish. Each entry is a lightweight stub — `{ "id", "site", "suppressed_by": "<heuristic-id>" }`
(the script fills `date`) — **not** a finding: no severity / root_cause / concrete_fix (there is nothing to
fix), no evidence hash, no cross-run merge. It is written per run (overwritten each time the lens
re-evaluates), kept out of `issues`, and **never shown to the maker**. Its sole purpose is auditability: it
distinguishes a site that was *evaluated and correctly suppressed* from one that was *never analyzed*, so a
0-finding review is legible after the fact.

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
that pattern, specialized to the site — this keeps the suggested fix ESS-correct. The fix travels **with
the finding** (its `Concrete fix` field), so whoever acts on it — the customer, or `/update` — has the fix
in hand without re-deriving it.

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

## Persisted form (catalog + resolution ledger)

`/review` persists findings via `scripts/merge_findings.py` into two gitignored, workspace-scoped artifacts
under `.local/review-findings/`, following the ESS hardening-analyzer's model scoped to the maker workflow:

- **`<solution>-catalog.json`** — the findings catalog for a review **scope** (the `solution` field). The
  scope is whatever was reviewed: a single topic today, a whole ISV or solution later. Nothing here assumes
  one topic — a finding's `files[]` can span several files, so widening the review needs no schema change.
  (The field is named `solution` to stay valid against the ESS analyzer's ledger schema; its value is the
  scope reviewed.)
- **`resolved-issue-ledger.jsonl`** — a shared, append-only log of resolution evidence (one JSON line per
  resolved finding). Each row carries `solution` + `issue_id`, the `resolution` outcome, and `resolved_by`
  — the actor that produced it (`maker` for a dismissal, `update-skill` for a tool fix, `review-skill` when
  `/review` confirms a fix during reconcile; caller-settable, default `review-skill`). The same semantic id
  can legitimately appear under different scopes, so this ledger is keyed by **(`solution`, `issue_id`)**:
  any future resolution match against it must scope by `solution`, never `issue_id` alone, or one scope's
  resolution would wrongly clear another's. A finding belongs to exactly one catalog per scope.

Each catalog finding is this contract serialized, plus the analyzer's cross-run fields:

```json
{
  "id": "missing-issuccess-branch",
  "title": "Flow result not checked before parse",
  "severity": "HIGH",
  "reachability": "confirmed",
  "root_cause": "The ParseValue runs without a preceding isSuccess = false branch.",
  "concrete_fix": "Add an isSuccess = false ConditionGroup before the parse.",
  "verification": "static",
  "files": [{ "path": "workspace/agents/<slug>/topics/<name>.mcs.yml", "lines": [188] }],
  "status": "active",
  "evidence_stale": false,
  "evidence_hashes": [{ "file": "workspace/agents/<slug>/topics/<name>.mcs.yml", "sha256": "…" }],
  "first_seen": "2026-07-08T18:00:00Z",
  "last_seen": "2026-07-08T19:30:00Z"
}
```

- **`id`** is a stable kebab-case behavior-describing slug and is the cross-run identity — reused across
  runs (read the prior catalog with `merge_findings.py --solution <solution> --show` and reuse the exact prior
  slug for a finding you recognize; never invent a new slug for a previously-identified finding).
- **`status`** (assigned by the script, not the agent) is `active` or `resolved`. `resolved` requires a
  matching `resolved-issue-ledger.jsonl` entry, whose `resolution` records *why*: `fixed` (the code was
  corrected), `not-a-bug` (the maker dismissed it as a false positive), or `wont-fix` (acknowledged,
  declined). A finding not re-detected this run stays `active` (absence is never resolution, because LLM
  coverage is nondeterministic). A finding **resolved this run** appears once as `resolved`, then the **next
  run prunes it** from the catalog — the ledger is its permanent record. A pruned finding reopens as a fresh
  `active` finding only if its code changes and it is re-detected.
- **`verification`** is `static` (decidable from the authored files — every current lens) or
  `needs-runtime-test` (only confirmable by running the bot). A `needs-runtime-test` finding is the explicit
  hand-off to Layer-3 runtime testing: generate an assertion case rather than a `/update` edit. The script
  defaults it to `static` when a finding omits it.
- **`evidence_hashes` / `evidence_stale`** make staleness deterministic. The script stores a sha256 of each
  file a finding implicates. When a finding is not re-detected, the script compares the stored hashes to the
  files' current hashes: all match → still `active` (the code is unchanged, so the finding stands); any
  mismatch → `active` with `evidence_stale: true` — the code moved, so **re-verify** (read the site; if the
  node is gone, resolve it by writing a ledger entry). This is objective, not an LLM judgment.
- The customer-facing report presents the **active** set; call out `evidence_stale` findings as "previously
  flagged, code has since changed — worth confirming."
- The catalog also carries a top-level **`suppressions`** array (sibling to `issues`) — the per-run,
  internal-only audit breadcrumbs described under the reachability rubric above. No report or `/update`
  consumer reads it; it exists only to make a 0-finding run auditable.
