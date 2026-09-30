# Eval Curator Direct Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `development/reference/executing-plans-guide.md` to implement this plan task-by-task.

**Goal:** Integrate the `EvalsCuratorForAgent` knowledge-source curation workflow into the ESS Maker Kit by vendoring its two used files directly (no Git submodule), wired through the existing `/evaluate` dispatcher and lifecycle.

**Architecture:** Vendor the curator skill body and structural validator under `src/skills/evaluations/curate/curator/`. A `curate/SKILL.md` wrapper confirms the two vendored files exist, reads the curator skill at its fixed path, runs the hosted generation flow, then hands validated artifacts to the existing Maker Kit validation → review → update → push → run lifecycle. The provenance-independent handoff safety script and the dispatcher route port unchanged from the prior submodule branch.

**Tech Stack:** Markdown skill files (CRLF, prettier + markdownlint), Python 3.12 helper scripts, pytest documentation-assertion tests. Repo is CRLF-native.

---

## Source of truth for ported content

Files marked **port verbatim** are copied from branch `feature/eval-curator-submodule-integration` and are already reviewed there. The two vendored curator files come from that branch's populated submodule at `solutions/ess-maker-skills/vendor/evals-curator/`:

- skill body: `vendor/evals-curator/skills/curate-evals/SKILL.md` → vendored as `curator/curate-evals.md`
- validator: `vendor/evals-curator/scripts/check_eval_artifacts.py` → vendored as `curator/check_eval_artifacts.py`

All new/edited files must be CRLF. After editing any `.md`, run prettier + markdownlint per AGENTS.md.

---

## Task 1: Vendor the two curator files

**Files:**
- Create: `solutions/ess-maker-skills/src/skills/evaluations/curate/curator/curate-evals.md`
- Create: `solutions/ess-maker-skills/src/skills/evaluations/curate/curator/check_eval_artifacts.py`
- Test: `tests/scripts/test_curator_vendored_files.py`

**Step 1: Write the failing test**

```python
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CURATOR = (
    REPO_ROOT
    / "solutions/ess-maker-skills/src/skills/evaluations/curate/curator"
)


def test_vendored_curator_files_present():
    assert (CURATOR / "curate-evals.md").is_file()
    assert (CURATOR / "check_eval_artifacts.py").is_file()


def test_vendored_skill_is_host_adapted():
    body = (CURATOR / "curate-evals.md").read_text(encoding="utf-8")
    # Host-override language distinguishes the adapted copy from the origin skill.
    assert "Host paths take precedence" in body
    assert "structuralValidatorPath" in body


def test_vendored_validator_is_the_structural_checker():
    src = (CURATOR / "check_eval_artifacts.py").read_text(encoding="utf-8")
    assert "--evaluation-folder" in src
    assert "EvaluationSet" in src
```

**Step 2: Run test to verify it fails**

Run: `cd solutions/ess-maker-skills && py -3.12 -m pytest ../../tests/scripts/test_curator_vendored_files.py -v`
Expected: FAIL (files do not exist yet).

**Step 3: Create the vendored files**

Copy verbatim (preserve CRLF) from the submodule branch's populated submodule:
- `vendor/evals-curator/skills/curate-evals/SKILL.md` → `curator/curate-evals.md`
- `vendor/evals-curator/scripts/check_eval_artifacts.py` → `curator/check_eval_artifacts.py`

**Step 4: Run test to verify it passes**

Run: same as Step 2. Expected: PASS.

**Step 5: Commit**

```bash
git add solutions/ess-maker-skills/src/skills/evaluations/curate/curator tests/scripts/test_curator_vendored_files.py
git commit -m "feat(evaluations): vendor curator skill and validator in-repo"
```

---

## Task 2: Author the curate wrapper (no submodule preflight)

**Files:**
- Create: `solutions/ess-maker-skills/src/skills/evaluations/curate/SKILL.md`
- Test: `tests/scripts/test_evaluation_curator_routing.py` (port + rewrite the submodule assertion)

**Step 1: Write/port the failing tests**

Port `test_evaluation_curator_routing.py` verbatim from the submodule branch, then replace `test_curator_wrapper_uses_submodule_contract_without_duplication` with `test_curator_wrapper_reads_vendored_files_without_duplication`, asserting:
- wrapper references `curator/curate-evals.md` and `curator/check_eval_artifacts.py`
- wrapper references `src/skills/evaluations/curate/curator/check_eval_artifacts.py` as `structuralValidatorPath`
- wrapper says "Confirm both files exist" and has an actionable "curator is not available in this workspace" error
- `submodule`, `eval_curator_submodule`, `skillPath`, `host-contract` do NOT appear
- retains "never duplicate the curator instructions" and "active GitHub Copilot session"

**Step 2: Run to verify it fails**

Run: `cd solutions/ess-maker-skills && py -3.12 -m pytest ../../tests/scripts/test_evaluation_curator_routing.py -v`
Expected: FAIL (wrapper does not exist / still asserts submodule text).

**Step 3: Write the wrapper**

Author `curate/SKILL.md` with: Step 1 (require both inputs, one at a time), Step 2 (confirm the two vendored files exist at fixed paths; stop with actionable error if missing; then read `curator/curate-evals.md` in full), Step 3 (run hosted flow with `hostOutputRoot`, `hostLifecycleHandoff`, and `structuralValidatorPath=src/skills/evaluations/curate/curator/check_eval_artifacts.py`), Step 4 (accept only complete handoff, validate via `eval_curator_handoff.py`, Maker Kit validation, maker review choice, route through update skill). Do not reintroduce any submodule/contract handshake.

**Step 4: Run to verify it passes**

Run: same as Step 2. Expected: PASS. Then prettier + markdownlint on the file.

**Step 5: Commit**

```bash
git add solutions/ess-maker-skills/src/skills/evaluations/curate/SKILL.md tests/scripts/test_evaluation_curator_routing.py
git commit -m "feat(evaluations): add direct-integration curate wrapper"
```

---

## Task 3: Port the handoff safety script (verbatim)

**Files:**
- Create: `solutions/ess-maker-skills/scripts/eval_curator_handoff.py`
- Test: `tests/scripts/test_eval_curator_handoff.py`

**Step 1: Port the test** verbatim from the submodule branch.

**Step 2: Run to verify it fails**

Run: `cd solutions/ess-maker-skills && py -3.12 -m pytest ../../tests/scripts/test_eval_curator_handoff.py -v`
Expected: FAIL (script missing).

**Step 3: Port the script** verbatim from the submodule branch (it is provenance-independent — path traversal, junction/reparse escape, and `workspace/evaluations` containment guards).

**Step 4: Run to verify it passes**

Run: same as Step 2. Expected: PASS (all handoff-safety cases).

**Step 5: Commit**

```bash
git add solutions/ess-maker-skills/scripts/eval_curator_handoff.py tests/scripts/test_eval_curator_handoff.py
git commit -m "feat(evaluations): add curator handoff path-safety validator"
```

---

## Task 4: Port the CSV export change (verbatim)

**Files:**
- Modify: `solutions/ess-maker-skills/scripts/evaluation_csv.py`
- Test: `tests/scripts/test_evaluation_csv.py`

**Step 1: Port the test** verbatim.

**Step 2: Run to verify it fails**

Run: `cd solutions/ess-maker-skills && py -3.12 -m pytest ../../tests/scripts/test_evaluation_csv.py -v`
Expected: FAIL (mixed-CSV export behavior not present on main).

**Step 3: Port the script change** verbatim.

**Step 4: Run to verify it passes**

Run: same as Step 2. Expected: PASS.

**Step 5: Commit**

```bash
git add solutions/ess-maker-skills/scripts/evaluation_csv.py tests/scripts/test_evaluation_csv.py
git commit -m "feat(evaluations): support mixed CSV exports for curator sets"
```

---

## Task 5: Port dispatcher + adjacent skill guards (verbatim)

**Files:**
- Modify: `solutions/ess-maker-skills/src/skills/evaluations/dispatcher/SKILL.md`
- Modify: `solutions/ess-maker-skills/src/skills/evaluations/create/SKILL.md`
- Modify: `solutions/ess-maker-skills/src/skills/evaluations/generate/SKILL.md`
- Modify: `solutions/ess-maker-skills/src/skills/evaluations/run/SKILL.md`
- Modify: `solutions/ess-maker-skills/src/skills/evaluations/update/SKILL.md`
- Test: `tests/scripts/test_evaluation_curator_routing.py` (routing assertions from Task 2 also cover the dispatcher)

**Step 1: Confirm routing tests reference dispatcher/create/generate**

The routing test already asserts the dispatcher route to `curate/SKILL.md`, and that `create` and `generate` routes are preserved. These fail until the skills are ported.

**Step 2: Run to verify relevant assertions fail**

Run: `cd solutions/ess-maker-skills && py -3.12 -m pytest ../../tests/scripts/test_evaluation_curator_routing.py -v`
Expected: dispatcher-route assertions FAIL.

**Step 3: Port the five skill edits** verbatim from the submodule branch (all are provenance-independent: dispatcher gains the knowledge-source route; create/generate gain scope-boundary guards; run gains eligible-set handoff; update gains preselected-set/Flow R1 handoff).

**Step 4: Run to verify it passes**

Run: same as Step 2. Expected: PASS. Then prettier + markdownlint on all five `.md` files.

**Step 5: Commit**

```bash
git add solutions/ess-maker-skills/src/skills/evaluations/dispatcher/SKILL.md solutions/ess-maker-skills/src/skills/evaluations/create/SKILL.md solutions/ess-maker-skills/src/skills/evaluations/generate/SKILL.md solutions/ess-maker-skills/src/skills/evaluations/run/SKILL.md solutions/ess-maker-skills/src/skills/evaluations/update/SKILL.md
git commit -m "feat(evaluations): route knowledge-source curation through dispatcher"
```

---

## Task 6: Port the skill-orchestration test, de-submodule its assertions

**Files:**
- Create: `tests/mcp/evaluations/__init__.py`
- Create: `tests/mcp/evaluations/test_curator_skill_orchestration.py`

**Step 1: Port both files** verbatim, then rewrite the three submodule-specific assertions:
- the `py -3.12 scripts/eval_curator_submodule.py status` expectation → assert the wrapper confirms vendored files at fixed paths
- the `payload["skillPath"]` absolute-path assertions → assert the wrapper reads `curator/curate-evals.md` and passes the fixed `structuralValidatorPath`

**Step 2: Run to verify it fails**

Run: `cd solutions/ess-maker-skills && py -3.12 -m pytest ../../tests/mcp/evaluations/test_curator_skill_orchestration.py -v`
Expected: FAIL until wrapper (Task 2) and de-submoduled assertions align.

**Step 3: Make assertions match the vendored design** (edit the ported test only; no product code changes).

**Step 4: Run to verify it passes**

Run: same as Step 2. Expected: PASS.

**Step 5: Commit**

```bash
git add tests/mcp/evaluations/__init__.py tests/mcp/evaluations/test_curator_skill_orchestration.py
git commit -m "test(evaluations): cover curator orchestration without submodule"
```

---

## Task 7: Port supporting doc/config edits (verbatim, minus submodule bits)

**Files:**
- Modify: `solutions/ess-maker-skills/.github/prompts/evaluate.prompt.md`
- Modify: `solutions/ess-maker-skills/README.md`
- Modify: `setup/README.md` (only if it references curation, NOT submodule init)
- Modify: `tests/README.md`

**Step 1:** Port the `evaluate.prompt.md` edit (offers curate-from-knowledge-source via the dispatcher). Port README curation mentions. **Do NOT port any `git submodule update --init` instructions** — there is no submodule in this design.

**Step 2: Run the routing test** (it asserts `evaluate.prompt.md` offers the curator route).

Run: `cd solutions/ess-maker-skills && py -3.12 -m pytest ../../tests/scripts/test_evaluation_curator_routing.py::test_evaluate_prompt_offers_curator_creation_through_dispatcher -v`
Expected: PASS after the prompt edit.

**Step 3:** prettier + markdownlint on every edited `.md`.

**Step 4: Commit**

```bash
git add solutions/ess-maker-skills/.github/prompts/evaluate.prompt.md solutions/ess-maker-skills/README.md setup/README.md tests/README.md
git commit -m "docs(evaluations): document knowledge-source curation route"
```

---

## Task 8: Full test sweep + PR

**Step 1: Run the full evaluation test suite**

Run: `cd solutions/ess-maker-skills && py -3.12 -m pytest ../../tests -k "curator or evaluation or eval" -v`
Expected: all PASS; zero references to submodule scaffolding remain.

**Step 2: Confirm no submodule artifacts leaked**

Run: `git ls-files | grep -iE "gitmodules|vendor/evals-curator|eval_curator_submodule" ; echo "exit: $?"`
Expected: no matches.

**Step 3: Push and open PR**

Push `feature/eval-curator-direct-integration`; open a PR to `main` describing the direct-integration approach and noting it is an alternative to the submodule branch. End the PR description with the required attribution line.

---

## Notes for the executor

- A stash named "ad-hoc direct-integration impl (pre-plan)" already contains a correct first pass at Tasks 1-6. You may `git stash show -p` to reference exact content, but implement task-by-task with tests so each commit is guarded. If you adopt stashed content wholesale, still run each task's test before committing.
- The vendored `curate-evals.md` keeps its own internal `workspace/evaluations` defaults; the wrapper's host parameters override them at runtime. Do not edit the vendored body except to fix a broken reference.
- CRLF everywhere. When a Python generator writes files, follow `skills/docs/line-endings.md`.
