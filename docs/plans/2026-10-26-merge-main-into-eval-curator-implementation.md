# Merge main into eval-curator branch Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `development/reference/executing-plans-guide.md` to implement this plan task-by-task.

**Goal:** Merge 204 commits of `origin/main` into `feature/eval-curator-direct-integration` (PR #358) without losing the curator-integration feature, reconciling main's new Compare-Meaning-only evaluation policy with the curator's dual-grader output.

**Architecture:** One `git merge origin/main` on the branch, resolved file-by-file per `docs/plans/2026-10-26-merge-main-into-eval-curator-design.md`. `evaluation_csv.py` takes main's structural rewrite as its base with a resurrected, Source-URL-aware table function shared by both CSV generation and handoff validation. A new host-write step in `curate/SKILL.md` strips the extra grader from curator output so it satisfies main's new policy, backed by a deterministic code-level check in `eval_curator_handoff.py`. Single merge commit, then one follow-up commit for the grader-policy fix, then push.

**Tech Stack:** Python 3.12, pytest, git merge (no rebase).

---

### Task 0: Start the merge and confirm expected conflict set

**Files:** none yet — this just starts the merge and inspects state.

**Step 1:** Confirm working tree is clean.

Run: `git status --short`
Expected: no output.

**Step 2:** Start the merge.

Run: `git merge origin/main`
Expected: exits non-zero, reports conflicts in exactly these 6 files:
- `solutions/ess-maker-skills/.github/prompts/evaluate.prompt.md`
- `solutions/ess-maker-skills/README.md`
- `solutions/ess-maker-skills/scripts/evaluation_csv.py`
- `solutions/ess-maker-skills/scripts/flightcheck/graph_client.py`
- `solutions/ess-maker-skills/src/skills/evaluations/generate/SKILL.md`
- `solutions/ess-maker-skills/src/skills/evaluations/update/SKILL.md`
- `tests/fixtures/cassettes/INDEX.md`

**Step 3:** Confirm no other files conflict.

Run: `git status --short | grep "^UU"`
Expected: exactly the 6 paths above (7 with `tests/fixtures/cassettes/INDEX.md`).

If the conflict set differs from this list, STOP — main may have changed again since the design doc was written; re-run the `git merge-tree --write-tree HEAD origin/main` dry-run from the design doc and re-evaluate before continuing.

---

### Task 1: Resolve `graph_client.py` (mechanical union)

**Files:**
- Modify: `solutions/ess-maker-skills/scripts/flightcheck/graph_client.py` (conflict region inside `GraphClient.__init__` and `GraphClient.authenticate`)
- Test: `tests/flightcheck/test_graph_client.py`

**Step 1: Resolve the conflict**

Combine both sides' additions to `__init__` and `authenticate`:

```python
class GraphClient:
    """Lightweight Microsoft Graph client with MSAL interactive auth."""

    def __init__(self, tenant_id: str, *, strict_reads: bool = False):
        self.tenant_id = tenant_id
        self.strict_reads = strict_reads
        self._token: str | None = None
        self.signed_in_username: str | None = None

    def authenticate(
        self,
        extra_scopes: list[str] | None = None,
        preferred_username: str | None = None,
    ) -> str:
        """Acquire a Graph access token, reusing the shared MSAL cache.

        ``extra_scopes`` lets a specific call site (e.g. connected-KB search)
        request additional admin-consent scopes beyond the default
        ``GRAPH_SCOPES``, without bundling them into every FlightCheck Graph
        check's token request. See ``SEARCH_SCOPES`` for the rationale.
        """
        scopes = GRAPH_SCOPES + list(extra_scopes) if extra_scopes else GRAPH_SCOPES
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        cache = msal.SerializableTokenCache()
        cache_path = os.path.join(".local", ".token_cache.bin")

        if os.path.exists(cache_path):
            with open(cache_path, "r") as f:
                cache.deserialize(f.read())

        app = msal.PublicClientApplication(
            GRAPH_CLIENT_ID, authority=authority, token_cache=cache
        )

        accounts = app.get_accounts()
        preferred = str(preferred_username or "").casefold()
        selected_account = next(
            (
                account for account in accounts
                if str(account.get("username") or "").casefold()
                == preferred
            ),
            accounts[0] if accounts and not preferred else None,
        )
        result = None
        if selected_account is not None:
            result = app.acquire_token_silent(
                scopes,
                account=selected_account,
            )

        if not result or "access_token" not in result:
            print("Opening browser for Microsoft Graph sign-in...")
            selected_account = None
            interactive_options = {"prompt": "select_account"}
            if preferred_username:
                interactive_options["login_hint"] = preferred_username
            result = app.acquire_token_interactive(
                scopes,
                **interactive_options,
            )

        if "access_token" not in result:
            error = result.get("error", "unknown_error")
            raise RuntimeError(f"Graph authentication failed ({error}).")

        _persist_token_cache(cache, cache_path)

        self._token = result["access_token"]
        claims = result.get("id_token_claims", {}) or {}
        self.signed_in_username = (
            claims.get("preferred_username")
            or claims.get("upn")
            or (selected_account or {}).get("username")
        )
        return self._token
```

Keep every other part of main's rewrite (`strict_reads` behavior in `get`/`get_all`, the `SEARCH_SCOPES` constant and comment block from our branch) untouched — those regions do not conflict.

Run: `git diff --check solutions/ess-maker-skills/scripts/flightcheck/graph_client.py`
Expected: no conflict markers reported.

**Step 2: Stage it**

Run: `git add solutions/ess-maker-skills/scripts/flightcheck/graph_client.py`

**Step 3: Confirm the resurrected test still matches**

`tests/flightcheck/test_graph_client.py::test_external_item_scope_is_requested` (added in PR #358's review-fix commit) should still pass unmodified — it only asserts on `SEARCH_SCOPES`/`GRAPH_SCOPES` membership, unaffected by this change.

Run: `py -3.12 -m pytest tests/flightcheck/test_graph_client.py -q`
Expected: all pass. If main added its own new tests for `preferred_username`/`strict_reads` elsewhere in this file, they must also pass unmodified — do not edit test expectations to make this pass; if something fails, the resolved source (not the test) is wrong.

---

### Task 2: Resolve `evaluation_csv.py` (structural — main's base + resurrected table function)

**Files:**
- Modify: `solutions/ess-maker-skills/scripts/evaluation_csv.py`
- Modify: `solutions/ess-maker-skills/scripts/eval_curator_handoff.py:188` (not conflicted, but breaks — fix in the same step)
- Test: `tests/scripts/test_evaluation_csv.py`, `tests/scripts/test_eval_curator_handoff.py`

**Step 1: Take main's full file as the resolution starting point**

Run: `git show origin/main:solutions/ess-maker-skills/scripts/evaluation_csv.py > solutions/ess-maker-skills/scripts/evaluation_csv.py`

**Step 2: Re-add the Source-URL-aware table function**

Insert this function after `_grader` (which main kept) and before `_multi_turn_pairs`:

```python
def _row_source_url(document: dict[str, Any]) -> str:
    extension_data = document.get("extensionData")
    source_url = extension_data.get("sourceUrl") if isinstance(
        extension_data, dict
    ) else None
    return source_url if isinstance(source_url, str) else ""


def _single_turn_csv_table(
    parent: dict[str, Any],
    single_turn_docs: list[tuple[dict[str, Any], Path]],
) -> tuple[list[str], list[dict[str, str]]]:
    source_rows: list[dict[str, Any]] = []
    for document, _ in single_turn_docs:
        document_rows = document.get("rows")
        source_url = _row_source_url(document)
        if isinstance(document_rows, list):
            for row in document_rows:
                if not isinstance(row, dict):
                    continue
                enriched_row = dict(row)
                enriched_row["_sourceUrl"] = source_url
                source_rows.append(enriched_row)

    method, passing_score = _grader(parent, source_rows)
    headers = ["Prompt", "Expected response", "Test Method Type"]
    if passing_score is not None:
        headers.append("Passing Score")
    has_source_url = any(row.get("_sourceUrl") for row in source_rows)
    if has_source_url:
        headers.append("Source URL")

    export_rows = []
    for row in source_rows:
        export_row = {
            "Prompt": _formula_safe(row.get("input")),
            "Expected response": _formula_safe(row.get("expectedOutput")),
            "Test Method Type": method,
        }
        if passing_score is not None:
            export_row["Passing Score"] = passing_score
        if has_source_url:
            export_row["Source URL"] = _formula_safe(row.get("_sourceUrl") or "")
        export_rows.append(export_row)
    return headers, export_rows


def evaluation_csv_table(
    set_folder: str | Path,
) -> tuple[list[str], list[dict[str, str]]]:
    """Return the exact table for an exclusively single-turn EvaluationSet."""
    folder = Path(set_folder)
    parent, case_documents = _set_documents(folder)
    single_turn_docs = [
        (document, path)
        for document, path in case_documents
        if document_kind(document, context=str(path)) == "EvaluationData"
    ]
    if len(single_turn_docs) != len(case_documents):
        raise EvaluationCSVError(
            f"Evaluation set is not exclusively single-turn: {folder}"
        )
    return _single_turn_csv_table(parent, single_turn_docs)
```

**Step 3: Make `generate_set_csv`'s single-turn branch call this function instead of its inline row-building**

In `generate_set_csv`, replace the inline block that builds `rows`/`headers`/writes rows for the single-turn case with a call to `_single_turn_csv_table(parent, single_turn_docs)`, so CSV generation and `evaluation_csv_table()` (used by the handoff validator) can never drift. Keep main's `content = io.StringIO(...)` / `_write_export(...)` atomic-write plumbing — only replace the row/header construction, not the write mechanism.

**Step 4: Fix `eval_curator_handoff.py`'s call site**

`solutions/ess-maker-skills/scripts/eval_curator_handoff.py:188` already calls `evaluation_csv.evaluation_csv_table(folder)` — no change needed there now that the function exists again. Confirm with:

Run: `grep -n "evaluation_csv_table" solutions/ess-maker-skills/scripts/eval_curator_handoff.py`
Expected: line 188 (`headers, rows = evaluation_csv.evaluation_csv_table(folder)`) unchanged.

**Step 5: Check for conflict markers and stage**

Run: `git diff --check solutions/ess-maker-skills/scripts/evaluation_csv.py`
Expected: clean.

Run: `git add solutions/ess-maker-skills/scripts/evaluation_csv.py`

**Step 6: Run existing tests**

Run: `py -3.12 -m pytest tests/scripts/test_evaluation_csv.py tests/scripts/test_eval_curator_handoff.py -q`
Expected: all pass, including `test_evaluation_csv.py` cases that exercise `Source URL` column behavior (from PR #358) and any new cases main added for `strict=True`/`EvaluationMethodError`.

If `test_evaluation_csv.py` on main added assertions importing `evaluation_method_policy` directly, those are unaffected by this resolution (that module is main-only, carried over as a clean add — verify with `git status --short solutions/ess-maker-skills/scripts/evaluation_method_policy.py`, expect `A` for added, not `U` for unmerged).

---

### Task 3: Resolve remaining doc/text conflicts (main's version as base)

**Files:**
- Modify: `solutions/ess-maker-skills/.github/prompts/evaluate.prompt.md`
- Modify: `solutions/ess-maker-skills/README.md`
- Modify: `solutions/ess-maker-skills/src/skills/evaluations/generate/SKILL.md`
- Modify: `solutions/ess-maker-skills/src/skills/evaluations/update/SKILL.md`
- Modify: `tests/fixtures/cassettes/INDEX.md`

**Step 1: For each file, take main's version, then re-apply our branch's small addition on top**

For each file, run:

```bash
MB=$(git merge-base HEAD origin/main)
git diff "$MB" HEAD -- <file>    # see exactly what our branch added
git show origin/main:<file> > <file>   # take main's version as the base
```

Then manually re-apply the small diff shown by the first command into the file now containing main's content. Since our branch's changes to these 5 files were each small (per the design doc's diff stats: evaluate.prompt.md +7/-2, README.md +68/-56, generate/SKILL.md +4 lines only, update/SKILL.md +169/-30, INDEX.md +1/-1), locate the equivalent section in main's rewritten version by searching for nearby anchor text (section headings, surrounding sentences) rather than assuming identical line numbers.

**Step 2: Verify no reference to the retired dual-grader pattern**

Run: `grep -n "GeneralQualityGrader" solutions/ess-maker-skills/src/skills/evaluations/generate/SKILL.md solutions/ess-maker-skills/src/skills/evaluations/update/SKILL.md`

If our re-applied text mentions `GeneralQualityGrader` as a default for single-turn sets, update it to match main's Compare-Meaning-only framing (multi-turn-only use of `GeneralQualityGrader` is still valid per main's `create/SKILL.md`; only the single-turn-set default changed).

**Step 3: Check for conflict markers and stage**

Run:
```bash
git diff --check solutions/ess-maker-skills/.github/prompts/evaluate.prompt.md solutions/ess-maker-skills/README.md solutions/ess-maker-skills/src/skills/evaluations/generate/SKILL.md solutions/ess-maker-skills/src/skills/evaluations/update/SKILL.md tests/fixtures/cassettes/INDEX.md
```
Expected: clean.

Run:
```bash
git add solutions/ess-maker-skills/.github/prompts/evaluate.prompt.md solutions/ess-maker-skills/README.md solutions/ess-maker-skills/src/skills/evaluations/generate/SKILL.md solutions/ess-maker-skills/src/skills/evaluations/update/SKILL.md tests/fixtures/cassettes/INDEX.md
```

---

### Task 4: Finish the merge and run the full suite

**Step 1: Confirm nothing is left unresolved**

Run: `git status --short | grep "^U"`
Expected: no output.

**Step 2: Commit the merge**

Run:
```bash
git commit -m "$(cat <<'EOF'
Merge origin/main into feature/eval-curator-direct-integration

Reconciles 204 commits of main (including the Compare-Meaning-only
evaluation authoring redesign from 3b9b2cfa) with the curator
integration feature from PR #358. evaluation_csv.py takes main's
structural rewrite (atomic writes, document_kind, strict validation)
with evaluation_csv_table() restored for the handoff validator,
carrying forward the Source URL column fix. graph_client.py unions
both sides' authenticate() additions (extra_scopes + preferred_username).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

**Step 3: Run the full suite**

Run: `py -3.12 -m pytest tests/ -q`
Expected: same 14 pre-existing failures confirmed unrelated earlier (`test_installer_launch.py`, `test_installer_maker_profile.py`, `test_da_setup_router.py`), no new failures.

If new failures appear outside those 14, STOP and diagnose before proceeding — do not continue to Task 5 with a red suite.

---

### Task 5: Align curator output with main's Compare-Meaning-only policy

**Files:**
- Modify: `solutions/ess-maker-skills/src/skills/evaluations/curate/SKILL.md` (handoff write step, additive — do not edit `curate/curator/curate-evals.md`)
- Modify: `solutions/ess-maker-skills/scripts/eval_curator_handoff.py`
- Test: `tests/scripts/test_eval_curator_handoff.py`

**Step 1: Write the failing test**

Add to `tests/scripts/test_eval_curator_handoff.py` (near `_valid_handoff`, following its existing fixture style):

```python
def test_validate_handoff_rejects_dual_grader_set_folder(tmp_path):
    workspace = _workspace(tmp_path)
    exports = workspace / "exports"
    set_folder = workspace / "dual-grader"
    set_folder.mkdir(parents=True)
    exports.mkdir()
    (set_folder / "dual.mcs.yml").write_text(
        "kind: EvaluationSet\n"
        "displayName: Dual Grader\n"
        "graders:\n"
        "  - kind: GeneralQualityGrader\n"
        "  - kind: CompareMeaningGrader\n"
        "    threshold: 0.7\n",
        encoding="utf-8",
    )
    (set_folder / "case.mcs.yml").write_text(
        "kind: EvaluationData\n"
        "rows:\n"
        "  - input: How?\n"
        "    expectedOutput: Like this\n",
        encoding="utf-8",
    )

    with pytest.raises(eval_curator_handoff.CuratorHandoffError) as exc:
        evaluation_csv.generate_set_csv(set_folder, exports, timestamp="20260927", strict=True)

    assert "Compare Meaning" in str(exc.value) or "CompareMeaningGrader" in str(exc.value)
```

Note: adjust the exception type/import to whatever `validate_evaluation_documents` actually raises (`evaluation_method_policy.EvaluationMethodError` per Task 2's inspection) — this test's job is to confirm a dual-grader curator-shaped set is rejected by main's existing policy, proving the gap exists before Step 2 closes it at the authoring-instruction level.

Run: `py -3.12 -m pytest tests/scripts/test_eval_curator_handoff.py::test_validate_handoff_rejects_dual_grader_set_folder -v`
Expected: PASS already (main's `validate_evaluation_documents` already rejects this) — this test documents the policy as a guard, not a gap to fix in code. If it does NOT raise, main's policy enforcement is not wired where expected; stop and re-investigate before Step 2.

**Step 2: Add the host-write step to `curate/SKILL.md`**

In `solutions/ess-maker-skills/src/skills/evaluations/curate/SKILL.md`, immediately after the existing "2b — conditional citation-adherence cases" section (around line 307, ending "...follow the same vendored Step 6 artifact shape as every other set."), add:

```markdown
**2c — enforce Compare Meaning-only grading.** This is another additive
host write-responsibility, layered on top of the vendored Step 6 artifact
shape **without editing the curator** body. The vendored curator template
writes both a `GeneralQualityGrader` and a `CompareMeaningGrader` entry
under each generated EvaluationSet's `graders` list. The ADK evaluation
feature now supports Compare Meaning only (see
`solutions/ess-maker-skills/scripts/evaluation_method_policy.py`). During
the same Step 6 write pass, remove the `GeneralQualityGrader` entry from
the `graders` list of every generated EvaluationSet parent `.mcs.yml`,
leaving exactly one `CompareMeaningGrader` entry with its threshold
unchanged. Do this for every set regardless of category — never leave
more than one grader, and never leave `GeneralQualityGrader` as the sole
grader for a single-turn set.
```

**Step 3: Add a deterministic code-level backstop in `eval_curator_handoff.py`**

In `_validate_set_folder` (around line 187, right before the `evaluation_csv.evaluation_csv_table(folder)` call), the call to `evaluation_csv_table` does not itself validate grader count — it only builds the CSV table. Add an explicit grader check so a curator run that didn't follow the SKILL.md instruction in Step 2 fails loudly at handoff time instead of silently producing a two-grader set:

```python
    try:
        headers, rows = evaluation_csv.evaluation_csv_table(folder)
    except evaluation_csv.EvaluationCSVError as exc:
        raise CuratorHandoffError(
            "invalid_set_folder",
            "Set folder artifacts could not be converted to an evaluation CSV.",
        ) from exc
```

Change to call `evaluation_method_policy.validate_evaluation_documents` first, with the parent/case documents already read in this function, surfacing a `CuratorHandoffError` with error code `invalid_set_folder` on an `EvaluationMethodError`. Re-use the `parent`/`yaml_documents`-equivalent structures already parsed in this function rather than re-reading the files.

**Step 4: Run the test from Step 1 again, now against the handoff path**

Run: `py -3.12 -m pytest tests/scripts/test_eval_curator_handoff.py -q`
Expected: all pass, including the new test, now exercising `eval_curator_handoff.validate_handoff`'s own rejection path (not just `evaluation_csv.generate_set_csv`'s).

**Step 5: Commit**

Run:
```bash
git add solutions/ess-maker-skills/src/skills/evaluations/curate/SKILL.md solutions/ess-maker-skills/scripts/eval_curator_handoff.py tests/scripts/test_eval_curator_handoff.py
git commit -m "$(cat <<'EOF'
fix(evaluations): align curator handoff with Compare-Meaning-only policy

The vendored curator template writes both GeneralQualityGrader and
CompareMeaningGrader; main's evaluation_method_policy now requires
exactly one CompareMeaningGrader. Add a host-write step (curate/SKILL.md
2c) instructing the agent to strip the extra grader during Step 6, and
a deterministic validate_evaluation_documents check in
eval_curator_handoff.py so a non-compliant handoff fails loudly instead
of silently producing a rejected-by-policy set.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Final verification and push

**Step 1: Run the full suite one more time**

Run: `py -3.12 -m pytest tests/ -q`
Expected: same 14 pre-existing unrelated failures only.

**Step 2: Manual diff review**

Run: `git log --oneline -3` to confirm the merge commit + the grader-policy commit are both present, then review the merge commit's full diff for the 7 touched files plus `eval_curator_handoff.py`:

Run: `git show --stat HEAD~1` (the merge commit) and `git show HEAD` (the grader-policy commit) — read through both for anything unexpected.

**Step 3: Push**

Run: `git push personal feature/eval-curator-direct-integration`

**Step 4: Note on PR #358**

Run: `gh pr comment 358 --body "Brought this branch current with origin/main (204 commits), including main's Compare-Meaning-only evaluation authoring redesign (3b9b2cfa). Curator-generated sets now have the extra GeneralQualityGrader stripped before handoff so they satisfy the new policy. See docs/plans/2026-10-26-merge-main-into-eval-curator-design.md for the full reconciliation plan."`

---

## Execution Handoff

Plan complete and saved to `docs/plans/2026-10-26-merge-main-into-eval-curator-implementation.md`. Two execution options:

1. **Subagent-Driven (this session)** - I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Parallel Session (separate)** - Open a new session with `executing-plans`, batch execution with checkpoints.

Which approach?
