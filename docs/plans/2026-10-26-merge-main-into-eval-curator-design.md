# Design: Merge `origin/main` into `feature/eval-curator-direct-integration`

**Date:** 2026-10-26
**Branch:** `feature/eval-curator-direct-integration` (PR #358)
**Status:** Approved

## Problem

`feature/eval-curator-direct-integration` is 204 commits behind `origin/main`.
A trial merge (`git merge-tree --write-tree HEAD origin/main`) surfaces 6
textual conflicts. One of those conflicts (`evaluation_csv.py`) hides a
deeper, non-textual incompatibility: main's commit `3b9b2cfa` ("unify
authoring, review, and run workflows") introduced a repo-wide policy —
enforced by a new `evaluation_method_policy.py` module — that all evaluation
sets must use exactly one `CompareMeaningGrader` and may not contain
multi-turn cases. Our curator feature (vendored `curate-evals.md` template)
still emits the older two-grader shape (`GeneralQualityGrader` +
`CompareMeaningGrader`). Merging this branch is therefore not a pure
textual-conflict exercise; it requires reconciling two evaluation-authoring
contracts without losing either side's functionality.

## Decisions

1. **Merge, not rebase.** `git merge origin/main` on the branch directly.
   Rebase would force-push and invalidate PR #358's existing review/CI
   history; `git merge --abort` gives an exact, zero-cleanup rollback until
   the merge commit lands.
2. **Manual, semantic conflict resolution.** Each conflict is read for
   intent on both sides and hand-merged, not auto-resolved by taking one
   side wholesale.
3. **Align the curator with main's new Compare-Meaning-only policy**
   (rather than exempting it or deferring the file). This matches main's
   declared product direction and avoids leaving two permanently divergent
   evaluation-authoring contracts in the repo.
4. **Full test suite + manual diff review** after resolution, before
   pushing.

## Per-file resolution plan

| File | Resolution |
|---|---|
| `solutions/ess-maker-skills/scripts/flightcheck/graph_client.py` | Mechanical union. Both sides added a new parameter to `authenticate()`: ours added `extra_scopes` (to request `SEARCH_SCOPES` only for connected-KB search, per PR #358's review fix); main added `preferred_username` + account-selection logic + `signed_in_username` tracking. Combine into one signature; compute the effective `scopes` list first (`GRAPH_SCOPES + extra_scopes` when supplied) and feed it through main's account-selection/interactive-auth logic in place of the bare `GRAPH_SCOPES` constant. |
| `solutions/ess-maker-skills/scripts/evaluation_csv.py` | Structural. Take main's rewrite as the base (atomic temp-file writes via `_write_export`, `document_kind`/`EvaluationMethodError` integration, single-EvaluationSet-parent guard, sorted glob, new `main()` CLI entrypoint, `strict` parameter on `generate_set_csv`/`regenerate_evaluation_exports`) — it is a strict superset of correctness fixes over our branch's version. Re-introduce a table-building function equivalent to our branch's `evaluation_csv_table()` (deleted on main when the row-building logic was inlined into `generate_set_csv`), built on top of main's `_set_documents`/`document_kind`, carrying forward our PR #358 fix: a `Source URL` column populated from each case's `extensionData.sourceUrl`, present only when at least one case supplies one. This function must be the single source of truth shared between `generate_set_csv`'s single-turn CSV writing and the handoff validator, so the two can never drift (the same principle underlying PR #358's original blocker #1). |
| `solutions/ess-maker-skills/scripts/eval_curator_handoff.py` | Not flagged as conflicting (branch-only file, so git sees it as a clean add) but it calls `evaluation_csv.evaluation_csv_table()`, which main deleted. Update the call site to use the resurrected table function from the resolved `evaluation_csv.py`. |
| `solutions/ess-maker-skills/src/skills/evaluations/curate/SKILL.md` (handoff write step) | Add a new host-write step, in the same spirit as the existing step 2a (Source URL citation) — an additive responsibility layered on top of the vendored Step 6 artifact shape, **without editing the vendored `curate-evals.md` body**. This step strips the `GeneralQualityGrader` entry from the `graders` list in the written `.mcs.yml` during the same Step 6 write pass, leaving exactly one `CompareMeaningGrader`, so curator-produced sets satisfy main's `validate_evaluation_documents` policy. No multi-turn cleanup is needed: curator never emits `MultiTurnEvaluationCase` (confirmed by inspection of `curate-evals.md`). |
| `solutions/ess-maker-skills/.github/prompts/evaluate.prompt.md`, `solutions/ess-maker-skills/README.md`, `solutions/ess-maker-skills/src/skills/evaluations/generate/SKILL.md`, `solutions/ess-maker-skills/src/skills/evaluations/update/SKILL.md`, `tests/fixtures/cassettes/INDEX.md` | Take main's version as the structural base (each is a much larger rewrite, part of the same unify-authoring redesign), then re-apply our branch's specific small additions on top. Verify none of the re-applied text references the now-retired dual-grader/`GeneralQualityGrader`-by-default pattern for single-turn sets. |

Files that auto-merged cleanly (no conflict, verified non-overlapping):
`create/SKILL.md`, `dispatcher/SKILL.md`, `run/SKILL.md`,
`tests/flightcheck/test_graph_client.py`, `tests/scripts/test_evaluation_csv.py`.

## Verification plan

1. Resolve conflicts in dependency order: `graph_client.py` →
   `evaluation_csv.py` → `eval_curator_handoff.py` fix → curate grader-strip
   step → remaining doc files.
2. Add new test coverage (not just preserve old tests):
   - `eval_curator_handoff.py` validates correctly against main's rewritten
     `evaluation_csv.py`, including the Source URL column round-trip.
   - The new curator grader-stripping step removes `GeneralQualityGrader`
     and leaves exactly one `CompareMeaningGrader`, so curator output passes
     `evaluation_method_policy.validate_evaluation_documents`.
   - `graph_client.authenticate()`'s combined signature: `extra_scopes` and
     `preferred_username` each work independently and together.
3. Run the full suite (`py -3.12 -m pytest tests/ -q`). Expect the same 14
   pre-existing, unrelated failures (installer/maker-profile/DA-setup tests)
   confirmed present on `origin/main` independent of this merge; no new
   failures.
4. Manual diff review of all resolved/follow-up files for silent semantic
   loss.
5. Commit the merge with a message describing the reconciliation (not a
   bare "merge main"); push to `personal/feature/eval-curator-direct-integration`.
6. Note on PR #358 that the branch was brought current with main's
   evaluation-authoring redesign, for reviewers.

## Out of scope

- Changing the vendored `curate-evals.md` curator body itself.
- Revisiting whether Compare-Meaning-only is the right policy — that
  decision was already made on main; this merge only aligns with it.
- Rebasing (ruled out — see Decisions).
