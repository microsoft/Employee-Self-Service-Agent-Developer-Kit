# Connected-KB Mode Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `development/reference/executing-plans-guide.md` to implement this plan task-by-task.

**Goal:** Enable connected-KB mode for the `/evaluate` curator route by lifting the wrapper's local-file-only clamp, adding an ask-first mode selection, and covering the connected-KB sequence with a mocked harness test — without editing the vendored curator body.

**Architecture:** Changes are confined to `curate/SKILL.md` (wrapper), `dispatcher/SKILL.md`, `README.md`, `evaluate.prompt.md`, and the test files. The vendored `curator/curate-evals.md` stays byte-identical; its Steps 3b/3c already implement connected-KB retrieval. The wrapper asks local-vs-connected up front, then hands off to the curator body which branches on mode.

**Tech Stack:** Markdown skill files (CRLF), pytest doc-assertion tests, and a Python fake-harness (`skill_eval.py`) extended with search/fetch tool contracts.

**Branch:** continues on `feature/eval-curator-direct-integration` (stacked on the direct-integration work; PR #358). CRLF-native repo — every file written programmatically must be CRLF (`sed -i 's/\r*$/\r/'` after Write).

---

## Task 1: Update wrapper doc-assertion test (RED)

**Files:**
- Test: `tests/scripts/test_evaluation_curator_routing.py`

**Step 1: Edit the v1-boundary test to assert the new behavior.**
Rename `test_curator_wrapper_defines_host_parameters_and_local_v1_boundary` → `test_curator_wrapper_defines_host_parameters_and_mode_selection`. Replace `assert "local-file mode only for v1" in normalized_lower` with:
```python
    # Wrapper asks the maker to choose local vs connected knowledge base first.
    assert "connected knowledge base" in normalized_lower
    assert "local files" in normalized_lower or "local folder" in normalized_lower
    assert "local-file mode only for v1" not in normalized_lower
```
Keep the `hostOutputRoot`/`hostLifecycleHandoff`/`knowledge source`/`agent instructions` assertions.

**Step 2: Run — expect FAIL** (wrapper still says local-only).
`cd solutions/ess-maker-skills && py -3.12 -m pytest ../../tests/scripts/test_evaluation_curator_routing.py -k "mode_selection" -v`

**Step 3: Commit the RED test** (allowed — TDD): `git add`; commit `test(evaluations): assert curate wrapper offers mode selection (RED)` with the Fable trailer.

---

## Task 2: Lift the clamp in the wrapper (GREEN)

**Files:**
- Modify: `solutions/ess-maker-skills/src/skills/evaluations/curate/SKILL.md`

**Step 1: Edit the intro (lines ~9-12).** Replace the "Use local-file mode only for v1" paragraph with text describing that curation accepts a local folder/files OR a connected knowledge base (e.g. ServiceNow/SharePoint) reachable via a search/fetch tool, and that the agent-instructions file is required in both modes.

**Step 2: Rewrite Step 1 (input collection) to ask mode first.** Before asking for inputs, add: "Ask the maker whether to curate from **local files/folder** or their **connected knowledge base**. Then collect only the inputs that mode needs: for local, a folder/files path; for connected, confirm the knowledge base (and which tool, if more than one is available). The agent-instructions file is required in both modes." Preserve the one-at-a-time / wait-for-answer discipline.

**Step 3: Remove the "Keep version 1 in local-file mode only." clamp (line ~73).** Replace with: "Let the vendored curator's input-mode selection proceed in the mode the maker chose (local-file or connected-KB). The active GitHub Copilot session must perform the curator's grounding, generation, preview, structural validation, and quality rules."

**Step 4: CRLF, then run the mode-selection test — expect PASS.**
`cd solutions/ess-maker-skills && py -3.12 -m pytest ../../tests/scripts/test_evaluation_curator_routing.py -k "mode_selection" -v`
Also run the full routing file and note any now-failing dispatcher/README tests (fixed in Tasks 3-4).

**Step 5: prettier + markdownlint (best-effort) on the wrapper. Commit** `feat(evaluations): enable connected-KB mode in curate wrapper` with Fable trailer.

---

## Task 3: Generalize the dispatcher route + its test

**Files:**
- Modify: `solutions/ess-maker-skills/src/skills/evaluations/dispatcher/SKILL.md`
- Test: `tests/scripts/test_evaluation_curator_routing.py`

**Step 1: Update the dispatcher route test** so `"local knowledge source"`-type assertions accept both source types (e.g. assert the route mentions "connected knowledge base" alongside local). Run — expect FAIL.

**Step 2: Edit `dispatcher/SKILL.md`** so the knowledge-source route wording covers both local documents and a connected knowledge base, routing both to `curate/SKILL.md`. Do not change the topic-grounded / catalogue-grounded routing.

**Step 3: CRLF; run the dispatcher tests — expect PASS. prettier/markdownlint. Commit** `feat(evaluations): route connected-KB curation through dispatcher` with Fable trailer.

---

## Task 4: Update the maker README + its test

**Files:**
- Modify: `solutions/ess-maker-skills/README.md`
- Test: `tests/scripts/test_evaluation_curator_routing.py`

**Step 1: Update the README test** to assert both local and connected knowledge-base sources are documented. Run — expect FAIL.

**Step 2: Edit `README.md`** curation-source description to mention both a local knowledge source and a connected knowledge base (ServiceNow/SharePoint). Keep "vendored curator" language; no "submodule"/"pinned".

**Step 3: CRLF; run — expect PASS. prettier/markdownlint. Commit** `docs(evaluations): document connected-KB curation source` with Fable trailer.

---

## Task 5: Check/adjust evaluate.prompt.md

**Files:**
- Modify (if needed): `solutions/ess-maker-skills/.github/prompts/evaluate.prompt.md`

**Step 1:** Read it. If it implies "local documents only" for curation, adjust to mention both modes, consistent with the wrapper. If it's already source-agnostic, leave it and note that.
**Step 2:** Run the full routing test file — expect all PASS. If evaluate.prompt.md changed, CRLF + prettier/markdownlint.
**Step 3: Commit** (only if changed) `docs(evaluations): note connected-KB in evaluate prompt` with Fable trailer.

---

## Task 6: Extend the fake harness with search/fetch tools

**Files:**
- Modify: `tests/mcp/evaluations/skill_eval.py`

**Step 1:** Add two `ToolContract` entries — `search` and `fetch` — to `tool_contracts()`, mirroring the existing `read_file`/`run_command` contract shape.

**Step 2:** Add an in-memory KB fixture: a small dict of fake articles (id → {title, body}) spanning 2-3 subjects, plus a simple keyword-match search over titles/bodies returning ranked {title, snippet, id}. Put a deliberately un-matched subject aside so a zero-result topic can be exercised.

**Step 3:** Add `invoke()` branches: `search` records `kind="search"` and returns ranked results for the query; `fetch` records `kind="fetch"` and returns the article body for the id (or a skip-marker for a missing id). Preserve all existing behavior.

**Step 4:** No test asserts the harness directly yet — but run the existing orchestration tests to confirm the additions didn't break them:
`cd solutions/ess-maker-skills && py -3.12 -m pytest ../../tests/mcp/evaluations/test_curator_skill_orchestration.py -v` (expect 17 passed, 1 skipped, unchanged).

**Step 5: CRLF. Commit** `test(evaluations): add search/fetch fakes to eval harness` with Fable trailer.

---

## Task 7: Mocked connected-KB behavioral tests (RED→GREEN)

**Files:**
- Test: `tests/mcp/evaluations/test_curator_skill_orchestration.py`

**Step 1: Write two tests** using the extended harness:

`test_connected_kb_discovers_topics_then_grounds_before_generation`:
- Drive a connected-mode curation turn against the fake search/fetch backend.
- Assert ordering: at least one `kind="search"` (discovery) call precedes topic confirmation, and for a confirmed topic a targeted `search`+`fetch` precedes the first eval-set `write` for that topic (mirror the existing `read_index < first_write_index` idiom with fetch indices).
- Assert written cases reference only fixture content (no invented facts).

`test_connected_kb_zero_result_topic_generates_no_cases`:
- Configure the fixture so a targeted topic search returns nothing.
- Assert no eval-set `write` occurs for that topic and the run flags the zero-result (skip-not-fabricate).

**Step 2: Run — expect FAIL** first (if the tests are written before any harness wiring they depend on) or PASS if Task 6 fully enables them; iterate until both pass deterministically. These are synthetic-workspace tests (no live network), so they must run in CI without credentials.

**Step 3:** Run the full orchestration file — expect prior 17 + 2 new = 19 passed, 1 skipped.

**Step 4: CRLF. Commit** `test(evaluations): cover connected-KB discovery, grounding, zero-result` with Fable trailer.

---

## Task 8: Full sweep + push

**Step 1:** Run the whole curator/eval suite:
`cd solutions/ess-maker-skills && py -3.12 -m pytest ../../tests/scripts/test_evaluation_curator_routing.py ../../tests/mcp/evaluations/test_curator_skill_orchestration.py ../../tests/scripts/test_curator_vendored_files.py ../../tests/scripts/test_eval_curator_handoff.py ../../tests/scripts/test_evaluation_csv.py -v`
Expect all green (+ the one live-skip).

**Step 2:** Confirm the vendored body is still byte-identical to what's on the branch (`git diff` shows no change to `curator/curate-evals.md`).

**Step 3:** Confirm all new commits carry the `Claude Fable 5` trailer (audit as in the prior task).

**Step 4:** Push to `personal` and let the existing PR #358 update (these commits stack on the same branch). Report the updated PR.

---

## Notes for the executor

- Vendored `curator/curate-evals.md` must NOT be edited in any task. If a test seems to need a body change, stop and re-check — the capability is already there.
- The connected-KB tests must be synthetic/offline (fake search/fetch), runnable in CI without a real backend. The mock proves sequence, not real-backend result-shape compatibility — that's the live dry-run's job (note it in the test module docstring).
- CRLF on every file. Fable trailer on every commit.
