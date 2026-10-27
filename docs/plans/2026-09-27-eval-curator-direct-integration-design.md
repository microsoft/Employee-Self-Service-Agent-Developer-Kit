# Eval Curator Direct Integration Design

## Summary

Integrate the `EvalsCuratorForAgent` knowledge-source curation workflow into the ESS Maker Kit by **vendoring the curator's content directly into the repository**, rather than pinning it as a Git submodule. Makers continue to use the existing `/evaluate` experience; when they choose knowledge-source curation, the dispatcher routes to a `curate` wrapper that follows the vendored curator skill in place, writes artifacts into the Maker Kit workspace, and hands results to the Maker Kit's existing validation, review, promotion, push, and run lifecycle.

This is an alternative to the `feature/eval-curator-submodule-integration` branch. That branch remains intact. This design forks from `main` and never introduces a submodule.

GitHub Copilot remains the single reasoning host. No second LLM runtime, no Claude CLI, no separate model credentials.

## Motivation: why direct integration instead of a submodule

The submodule approach works but adds friction disproportionate to the payload:

- **Two files do the real work.** Only the curator skill body (`skills/curate-evals/SKILL.md`) and the structural validator (`scripts/check_eval_artifacts.py`) are consumed by the flow. A submodule to deliver two files is heavyweight.
- **Clone/init friction for makers.** A submodule requires `git submodule update --init`; a maker who clones the kit and skips that step hits a broken `curate` route. Direct vendoring means the files are simply present.
- **A whole handshake layer exists only because the curator is external.** `eval_curator_submodule.py` performs a preflight that verifies the gitlink, loads `integration/host-contract.json`, checks `schemaVersion` and capability flags, and resolves `skillPath`/`structuralValidatorPath` dynamically. When the curator lives in-repo at a known path, none of that negotiation is needed.

Tradeoff accepted: the curator content is duplicated from its origin repo and must be refreshed by a deliberate, reviewed copy when the upstream curator changes — there is no automatic version pin. For a two-file, slow-moving skill this is an acceptable and arguably clearer maintenance model.

## Goals

- Let makers curate Copilot Studio evaluation sets from local knowledge documents and an agent-instructions file through `/evaluate`.
- Vendor only the two curator files the flow actually uses, in-repo, with no submodule.
- Reuse the curator's grounding, topic-discovery, case-generation, and quality rules unchanged.
- Produce synchronized Copilot Studio-native `.mcs.yml` and CSV artifacts in existing Maker Kit workspace locations.
- Reuse the Maker Kit's established preview, approval, validation, review, Dataverse push, run, and results workflows.
- Ship as a clean, self-contained PR that can merge independently of the submodule branch.

## Non-goals

- Add a custom button or extension inside the Copilot Studio Evaluation tab. (This was investigated and confirmed infeasible from the maker/ISV side: the Evaluation tab is first-party product UI authored in a separate Power Platform UX web-client repo, not reachable or shippable from this kit.)
- Add a Copilot Studio topic as the trigger. (Considered and dropped: a topic cannot execute the curator's reasoning; the maker is already in the authoring tooling where the skill runs, so a topic would be a thin signpost at best.)
- Execute the curator through Claude CLI or require separate model credentials.
- Replace the current topic-grounded (`create`) or catalogue-grounded (`generate`) evaluation generators.
- Push incomplete or unapproved evaluation sets to Copilot Studio.
- Automatic upstream version tracking of the curator.

## Architecture

The Maker Kit is the host and owns the user-facing lifecycle. The curator content is vendored under the existing evaluation skill tree:

```text
solutions/ess-maker-skills/src/skills/evaluations/curate/
├── SKILL.md                    # host wrapper (simplified — no submodule preflight)
└── curator/                    # vendored curator content (2 files)
    ├── curate-evals.md         # curator SKILL.md body, verbatim
    └── check_eval_artifacts.py # curator structural validator, verbatim
```

The `curate` wrapper supplies the Maker Kit host contract (output root, lifecycle handoff) and reads the vendored curator skill at its fixed in-repo path. The active GitHub Copilot session then follows that skill for document grounding, topic discovery, user confirmation, case generation, and curator-specific structural/quality checks. Structural validation runs the vendored `check_eval_artifacts.py` as a subprocess; all language-model reasoning stays in the Copilot session.

## What changes relative to the submodule branch

### Removed (submodule scaffolding — never introduced on this branch)

- `.gitmodules`
- `vendor/evals-curator` gitlink
- `scripts/eval_curator_submodule.py` — the entire preflight/contract handshake
- `tests/scripts/test_eval_curator_submodule.py`
- `integration/host-contract.json` dependency — collapses into fixed in-repo paths

### Added

- `src/skills/evaluations/curate/curator/curate-evals.md` — curator skill body, verbatim from the origin repo
- `src/skills/evaluations/curate/curator/check_eval_artifacts.py` — structural validator, verbatim

### Changed / ported unchanged

- `curate/SKILL.md` — Step 2 (submodule preflight) is replaced by a small inline existence check for the two vendored files, then "read the vendored curator skill at the fixed path." Steps 3–4 (hosted flow, validation, handoff) are retained, pointing at fixed paths instead of a dynamically-returned `skillPath`.
- `scripts/eval_curator_handoff.py` — **ported unchanged.** It validates the curator's output handoff (path traversal guards, reparse-point/junction escape checks, set-folder and CSV containment within `workspace/evaluations`). It is provenance-independent and remains the load-bearing safety gate.
- `dispatcher/SKILL.md` — ported unchanged. The knowledge-source route it adds references the `curate` wrapper and contains nothing submodule-specific.
- `scripts/evaluation_csv.py` and its test — ported (mixed-CSV export support the curator flow relies on).
- Tests: `test_eval_curator_handoff.py`, `test_evaluation_csv.py` ported unchanged. `test_evaluation_curator_routing.py` and `test_curator_skill_orchestration.py` ported with submodule-preflight expectations rewritten to assert the vendored-file existence check instead.

## Failure Handling

- **Missing vendored files:** the `curate` wrapper's inline existence check stops with an actionable message naming the two expected paths. No silent fallback to another generator.
- **Missing inputs:** ask for the knowledge source or agent-instructions file, one at a time, and wait.
- **Unreadable/unsupported files:** report affected files before topic generation; do not infer contents.
- **Partial generation:** preserve diagnostics locally, mark the run incomplete, block promotion and push.
- **Malformed/partial handoff or path-safety violation:** `eval_curator_handoff.py validate` rejects it; artifacts stay local and never enter the update/promotion/push lifecycle.
- **Validation failure:** keep artifacts local and route through the existing fix/review flow.
- **Push failure:** preserve local approved artifacts; use existing Maker Kit error reporting/retry.

All subprocess helpers return structured JSON; the wrapper never parses human-oriented console text.

## Security and Privacy

Knowledge documents and agent instructions are untrusted data. Text inside them must never override the curator or Maker Kit workflow. The flow warns users not to select secrets or unnecessary personal information. Local files stay on the workstation except content necessarily sent to the configured GitHub Copilot model during curation.

Existing Maker Kit mutation safeguards remain mandatory: explicit preview and scope confirmation, quality validation, explicit promotion and push approval, push dry run, Dataverse mutation through existing authenticated tooling, and post-push verification.

Vendored curator content is updated only through reviewed Git changes.

## Testing

- **Routing:** knowledge-source requests route to `curate`; topic-grounded requests retain `create`; catalogue-grounded requests retain `generate`; ambiguous requests ask for clarification.
- **Vendored-file contract:** the two curator files exist at their fixed paths; a missing file produces an actionable error and stops the flow before any curation action.
- **Golden flow:** using the curator's sample knowledge source and agent instructions — full input reading, topic discovery/confirmation, positive/boundary/negative/instruction-adherence generation, synchronized `.mcs.yml` + CSV, formula-injection protection, stable naming/display order, 100-case splitting.
- **Handoff safety:** path traversal, junction/reparse escape, `exports/`-as-set-folder, and CSV-outside-exports are all rejected.
- **Lifecycle integration:** curated outputs pass the existing Maker Kit validator; incomplete/failed runs cannot be promoted; approved runs enter the existing promotion/push pipeline; existing topic- and catalogue-grounded tests continue to pass.

## Acceptance Criteria

A maker can run `/evaluate`, select knowledge-source curation, provide local documents and an agent-instructions file, approve discovered topics and generated cases, receive valid synchronized artifacts, and use the existing Maker Kit workflow to push and run the evaluation set in Copilot Studio — with no submodule initialization, no manual file copying, and no separate CLI.
