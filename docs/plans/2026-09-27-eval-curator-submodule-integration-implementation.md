# Eval Curator Submodule Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `development/reference/executing-plans-guide.md` to implement this plan task-by-task.

**Goal:** Let ESS Maker Kit users run `/evaluate`, invoke the pinned `EvalsCuratorForAgent` skill against local knowledge documents, and continue through the Maker Kit's existing validation, review, push, run, and results lifecycle.

**Architecture:** Prepare the curator repository with a small, versioned host-integration contract, then add it to the Maker Kit as a Git submodule at `solutions/ess-maker-skills/vendor/evals-curator`. A thin Maker Kit wrapper validates the submodule, reads and follows the curator skill using the active GitHub Copilot session, remaps output paths into the Maker Kit workspace, and hands completed artifacts to existing evaluation lifecycle skills. No second LLM runtime is introduced.

**Tech Stack:** Git submodules, Markdown-based GitHub Copilot skills and prompts, Python 3.11, PyYAML, pytest, existing Maker Kit evaluation scripts, Power Platform/Dataverse push tooling.

**Design:** `docs/plans/2026-09-27-eval-curator-submodule-integration-design.md`

---

## Task 1: Add a host-integration contract to EvalsCuratorForAgent

Complete this task in the `EvalsCuratorForAgent` repository before pinning the resulting commit in the Maker Kit.

**Files:**

- Create: `integration/host-contract.json`
- Create: `scripts/test_host_contract.py`
- Modify: `skills/curate-evals/SKILL.md`
- Modify: `README.md`

### Step 1: Write the failing contract test

Create `scripts/test_host_contract.py`:

```python
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "integration" / "host-contract.json"
SKILL_PATH = REPO_ROOT / "skills" / "curate-evals" / "SKILL.md"


def test_host_contract_declares_supported_entry_points():
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    assert contract == {
        "schemaVersion": 1,
        "skillPath": "skills/curate-evals/SKILL.md",
        "structuralValidatorPath": "scripts/check_eval_artifacts.py",
        "defaultOutputRoot": "workspace/evaluations",
        "supportsHostOutputOverride": True,
        "supportsHostLifecycleHandoff": True,
    }


def test_skill_documents_host_overrides():
    skill = SKILL_PATH.read_text(encoding="utf-8")

    assert "## Host integration contract" in skill
    assert "`hostOutputRoot`" in skill
    assert "`hostLifecycleHandoff`" in skill
    assert "the host's paths take precedence" in skill
    assert "do not run this skill's local-only wrap-up" in skill
```

### Step 2: Run the test to verify it fails

Run from `C:\Users\rarame\repos\EvalsCuratorForAgent`:

```powershell
python -m pytest scripts\test_host_contract.py -v
```

Expected: FAIL because `integration\host-contract.json` and the host-integration instructions do not exist.

### Step 3: Create the machine-readable host contract

Create `integration/host-contract.json`:

```json
{
  "schemaVersion": 1,
  "skillPath": "skills/curate-evals/SKILL.md",
  "structuralValidatorPath": "scripts/check_eval_artifacts.py",
  "defaultOutputRoot": "workspace/evaluations",
  "supportsHostOutputOverride": true,
  "supportsHostLifecycleHandoff": true
}
```

### Step 4: Add host override rules to the curator skill

Add a `## Host integration contract` section near the top of `skills/curate-evals/SKILL.md`, before Step 1. It must define:

- `hostOutputRoot`: optional path supplied by the host. When present, replace every `workspace/evaluations` destination with this path.
- `hostLifecycleHandoff`: optional host-owned instructions to run after generation and structural validation.
- Host paths take precedence over the curator's default paths.
- The curator still owns source reading, topic confirmation, grounded generation, synchronized artifact writing, preview, structural validation, and its quality rubric.
- When `hostLifecycleHandoff` is present, stop after returning a structured summary of validated sets and do not run the local-only Step 10 wording that says pushing is unavailable.
- The host contract must not weaken required user confirmations or grounding guarantees.

Add this exact handoff shape:

```text
Curator handoff:
- outputRoot: <resolved output root>
- sets:
  - name: <display name>
    folder: <absolute or host-relative set folder>
    csv: <CSV path>
    caseCount: <count>
    qualityScore: <1-5>
- structuralValidation: passed
- qualityValidation: passed|review|failed
```

### Step 5: Document hosted use

Update `README.md` to state that:

- The repository can be consumed directly or pinned as a Git submodule.
- A host reads `integration/host-contract.json`, follows `skillPath`, supplies `hostOutputRoot`, and resumes at `hostLifecycleHandoff`.
- The skill still uses the host's active LLM session; the submodule does not require Claude CLI or separate model credentials.

### Step 6: Run curator tests

Run:

```powershell
python -m pytest scripts -v
```

Expected: all curator tests pass.

### Step 7: Commit the curator contract

```powershell
git add integration\host-contract.json scripts\test_host_contract.py skills\curate-evals\SKILL.md README.md
git commit -m "feat: add host contract for eval curation"
```

Record the resulting commit SHA for Task 2.

---

## Task 2: Add the curator repository as a pinned Maker Kit submodule

Complete this and all remaining tasks in `Employee-Self-Service-Agent-Developer-Kit`.

**Files:**

- Create: `.gitmodules`
- Add submodule: `solutions/ess-maker-skills/vendor/evals-curator`

### Step 1: Add the submodule at the approved path

Run from the Maker Kit repository root:

```powershell
git submodule add https://github.com/rarame_microsoft/EvalsCuratorForAgent.git solutions/ess-maker-skills/vendor/evals-curator
git -C solutions/ess-maker-skills/vendor/evals-curator checkout <TASK-1-COMMIT-SHA>
```

Expected:

- `.gitmodules` maps `solutions/ess-maker-skills/vendor/evals-curator` to the curator repository.
- The submodule gitlink points to the exact Task 1 commit.

### Step 2: Verify the pinned contract

Run:

```powershell
Get-Content solutions\ess-maker-skills\vendor\evals-curator\integration\host-contract.json
git submodule status
```

Expected:

- Contract has `schemaVersion` 1.
- Submodule status shows the Task 1 commit without a leading `-` or `+`.

### Step 3: Commit the submodule

```powershell
git add .gitmodules solutions\ess-maker-skills\vendor\evals-curator
git commit -m "build(evaluations): pin eval curator submodule"
```

---

## Task 3: Make setup and CI initialize the submodule

**Files:**

- Modify: `setup/Install-EssAdk.ps1`
- Modify: `setup/install-ess-adk.sh`
- Modify: `setup/Install-EssAdk.Tests.ps1`
- Modify: `.github/workflows/ci.yml`
- Create: `tests/setup/test_curator_submodule_setup.py`

### Step 1: Write failing setup contract tests

Create `tests/setup/test_curator_submodule_setup.py`:

```python
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_INSTALLER = REPO_ROOT / "setup" / "Install-EssAdk.ps1"
UNIX_INSTALLER = REPO_ROOT / "setup" / "install-ess-adk.sh"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_windows_installer_initializes_submodules():
    text = WINDOWS_INSTALLER.read_text(encoding="utf-8")
    assert "submodule update --init --recursive" in text


def test_unix_installer_initializes_submodules():
    text = UNIX_INSTALLER.read_text(encoding="utf-8")
    assert "submodule update --init --recursive" in text


def test_ci_checks_out_submodules():
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert "submodules: recursive" in text
```

### Step 2: Run the tests to verify they fail

Run:

```powershell
python -m pytest tests\setup\test_curator_submodule_setup.py -v
```

Expected: three failures because setup and CI do not initialize submodules.

### Step 3: Initialize the submodule in the Windows installer

After the clone/update block in `setup/Install-EssAdk.ps1`, add a post-clone dependency step that:

1. Skips when `-SkipClone` is active and the repository path does not exist.
2. Runs:

   ```powershell
   git -C $repoPath submodule sync --recursive
   git -C $repoPath submodule update --init --recursive
   ```

3. Treats failure as a setup error because knowledge-source curation would otherwise be partially installed.
4. Prints a success message naming the curator dependency without exposing repository credentials.

### Step 4: Initialize the submodule in the Unix installer

After the clone/update block in `setup/install-ess-adk.sh`, add:

```bash
git -C "$REPO_PATH" submodule sync --recursive
GIT_TERMINAL_PROMPT=0 git -C "$REPO_PATH" submodule update --init --recursive
```

Fail with an actionable message if either command fails.

### Step 5: Extend installer smoke tests

Update `setup/Install-EssAdk.Tests.ps1` to assert:

- The Windows installer contains `submodule update --init --recursive`.
- The command targets `$repoPath`.
- Initialization occurs after clone/update and before dependent tooling is used.

### Step 6: Configure CI checkout

For each `actions/checkout@v6` step in `.github/workflows/ci.yml`, add:

```yaml
with:
  submodules: recursive
```

Do not add credential persistence beyond the workflow's existing defaults.

### Step 7: Run setup tests

Run:

```powershell
python -m pytest tests\setup\test_curator_submodule_setup.py -v
pwsh -NoProfile -File setup\Install-EssAdk.Tests.ps1
```

Expected: all tests pass.

### Step 8: Commit setup support

```powershell
git add setup\Install-EssAdk.ps1 setup\install-ess-adk.sh setup\Install-EssAdk.Tests.ps1 .github\workflows\ci.yml tests\setup\test_curator_submodule_setup.py
git commit -m "build(evaluations): initialize curator submodule"
```

---

## Task 4: Add a deterministic curator-submodule preflight helper

**Files:**

- Create: `solutions/ess-maker-skills/scripts/eval_curator_submodule.py`
- Create: `tests/scripts/test_eval_curator_submodule.py`

### Step 1: Write failing preflight tests

Create `tests/scripts/test_eval_curator_submodule.py` with tests for:

```python
def test_status_returns_resolved_contract_paths(tmp_path):
    # Arrange a fake vendor/evals-curator tree with contract + referenced files.
    # Invoke main(["status", "--repo-root", str(tmp_path)]).
    # Assert exit 0 and JSON fields:
    # available=true, schemaVersion=1, skillPath, structuralValidatorPath.


def test_status_fails_when_submodule_is_uninitialized(tmp_path):
    # Create the submodule directory without contract files.
    # Assert exit 2 and errorCode="submodule_not_initialized".


def test_status_rejects_unsupported_contract_version(tmp_path):
    # Write schemaVersion=2.
    # Assert exit 2 and errorCode="unsupported_contract_version".


def test_status_rejects_paths_outside_submodule(tmp_path):
    # Set skillPath="../../outside.md".
    # Assert exit 2 and errorCode="invalid_contract_path".
```

Use `capsys` and parse stdout as JSON. Do not test by matching human console text.

### Step 2: Run the tests to verify they fail

Run:

```powershell
python -m pytest tests\scripts\test_eval_curator_submodule.py -v
```

Expected: FAIL because `eval_curator_submodule.py` does not exist.

### Step 3: Implement the preflight helper

Implement these functions:

```python
SUPPORTED_SCHEMA_VERSION = 1


def resolve_submodule(repo_root: Path) -> Path:
    return repo_root / "solutions" / "ess-maker-skills" / "vendor" / "evals-curator"


def load_contract(submodule_root: Path) -> dict:
    # Read integration/host-contract.json.
    # Validate schemaVersion and required string/boolean fields.
    # Resolve referenced paths and require them to remain under submodule_root.


def build_status(repo_root: Path) -> dict:
    # Return available, schemaVersion, submoduleRoot, skillPath,
    # structuralValidatorPath, defaultOutputRoot, and supported capabilities.


def main(argv: list[str] | None = None) -> int:
    # Support: status --repo-root <path>
    # Print exactly one JSON object to stdout.
    # Return 0 on success and 2 for expected setup/contract errors.
```

Expected success payload:

```json
{
  "available": true,
  "schemaVersion": 1,
  "submoduleRoot": "<absolute path>",
  "skillPath": "<absolute path>",
  "structuralValidatorPath": "<absolute path>",
  "defaultOutputRoot": "workspace/evaluations",
  "supportsHostOutputOverride": true,
  "supportsHostLifecycleHandoff": true
}
```

Expected error payload:

```json
{
  "available": false,
  "errorCode": "submodule_not_initialized",
  "message": "Initialize dependencies with: git submodule update --init --recursive"
}
```

### Step 4: Run the focused tests

Run:

```powershell
python -m pytest tests\scripts\test_eval_curator_submodule.py -v
```

Expected: all tests pass.

### Step 5: Run lint

Run:

```powershell
ruff check solutions\ess-maker-skills\scripts\eval_curator_submodule.py tests\scripts\test_eval_curator_submodule.py
```

Expected: no findings.

### Step 6: Commit the helper

```powershell
git add solutions\ess-maker-skills\scripts\eval_curator_submodule.py tests\scripts\test_eval_curator_submodule.py
git commit -m "feat(evaluations): validate curator submodule contract"
```

---

## Task 5: Add the Maker Kit curator wrapper and routing

**Files:**

- Create: `solutions/ess-maker-skills/src/skills/evaluations/curate/SKILL.md`
- Modify: `solutions/ess-maker-skills/src/skills/evaluations/dispatcher/SKILL.md`
- Modify: `solutions/ess-maker-skills/.github/prompts/evaluate.prompt.md`
- Create: `tests/scripts/test_evaluation_curator_routing.py`

### Step 1: Write failing routing tests

Create `tests/scripts/test_evaluation_curator_routing.py`:

```python
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SOLUTION = REPO_ROOT / "solutions" / "ess-maker-skills"
DISPATCHER = SOLUTION / "src" / "skills" / "evaluations" / "dispatcher" / "SKILL.md"
WRAPPER = SOLUTION / "src" / "skills" / "evaluations" / "curate" / "SKILL.md"
EVALUATE_PROMPT = SOLUTION / ".github" / "prompts" / "evaluate.prompt.md"


def test_dispatcher_routes_local_knowledge_sources_to_curator():
    text = DISPATCHER.read_text(encoding="utf-8")
    assert "src/skills/evaluations/curate/SKILL.md" in text
    assert "local knowledge source" in text
    assert "agent-instructions file" in text
    assert text.index("local knowledge source") < text.index("Matching topic found")


def test_evaluate_prompt_offers_knowledge_source_curation():
    text = EVALUATE_PROMPT.read_text(encoding="utf-8")
    assert "curate from a knowledge source" in text
    assert "src/skills/evaluations/dispatcher/SKILL.md" in text


def test_wrapper_invokes_the_pinned_curator_skill():
    text = WRAPPER.read_text(encoding="utf-8")
    assert "python scripts/eval_curator_submodule.py status" in text
    assert "skillPath" in text
    assert "Read the returned curator skill in full" in text
    assert "workspace/evaluations" in text
    assert "src/skills/evaluations/validate/SKILL.md" in text
    assert "src/skills/evaluations/update/SKILL.md" in text
```

### Step 2: Run the routing tests to verify they fail

Run:

```powershell
python -m pytest tests\scripts\test_evaluation_curator_routing.py -v
```

Expected: FAIL because the wrapper and routes do not exist.

### Step 3: Create the wrapper skill

Create `solutions/ess-maker-skills/src/skills/evaluations/curate/SKILL.md` with these required sections:

1. **Purpose and boundary**
   - Knowledge-source-grounded creation only.
   - GitHub Copilot is the reasoning host.
   - Never copy the curator instructions into this wrapper.

2. **Preflight**
   - Run:

     ```text
     python scripts/eval_curator_submodule.py status
     ```

   - Parse the JSON result.
   - On failure, show its `message` and stop.
   - Read the returned `skillPath` in full.

3. **Host parameters**
   - `hostOutputRoot = workspace/evaluations`
   - `hostLifecycleHandoff = Maker Kit validation, review, promotion, scoped push, and run lifecycle`
   - Preserve local-file mode for the first version.
   - Require both a knowledge source and an agent-instructions file.

4. **Invoke curator workflow**
   - Follow the curator skill's grounding, topic confirmation, generation, preview, structural validation, and quality rules.
   - Use the returned structural validator path.
   - Do not use the curator's local-only wrap-up.

5. **Maker Kit handoff**
   - Invoke `src/skills/evaluations/validate/SKILL.md` for each generated set.
   - Follow `src/skills/evaluations/quality-fix-flow.md`.
   - Present the existing local/reviewer/push choices.
   - For configured-agent promotion and scoped push, route to the applicable workspace-set flow in `src/skills/evaluations/update/SKILL.md`.
   - Do not duplicate push commands or review metadata rules.

6. **Failure handling**
   - Missing input: ask one question and wait.
   - Missing/incompatible submodule: stop.
   - Partial or failed validation: keep local and block handoff.

### Step 4: Update the dispatcher

Before configured-topic matching, add a route for explicit local knowledge-source requests:

- Indicators include a local folder/file path plus a request to generate or curate evaluation tests from those documents.
- Require an agent-instructions file; ask for it if absent.
- Route directly to `src/skills/evaluations/curate/SKILL.md`.
- Do not route a plain named scenario with no documents to the curator; retain catalogue-grounded behavior.
- Do not route a configured topic request to the curator unless the user explicitly asks to ground it in supplied documents.

### Step 5: Update `/evaluate`

Change the initial create wording in `.github/prompts/evaluate.prompt.md` so users can choose:

- Create from configured agent behavior or a named ESS scenario.
- Curate from a local knowledge source and agent instructions.

Both choices continue through the dispatcher. Do not add a second slash command.

### Step 6: Run routing tests

Run:

```powershell
python -m pytest tests\scripts\test_evaluation_curator_routing.py -v
```

Expected: all tests pass.

### Step 7: Commit routing and wrapper

```powershell
git add solutions\ess-maker-skills\src\skills\evaluations\curate\SKILL.md solutions\ess-maker-skills\src\skills\evaluations\dispatcher\SKILL.md solutions\ess-maker-skills\.github\prompts\evaluate.prompt.md tests\scripts\test_evaluation_curator_routing.py
git commit -m "feat(evaluations): route knowledge curation to submodule"
```

---

## Task 6: Add lifecycle contract guards

**Files:**

- Modify: `tests/scripts/test_evaluation_curator_routing.py`
- Modify: `solutions/ess-maker-skills/src/skills/evaluations/curate/SKILL.md`

### Step 1: Add failing lifecycle assertions

Add tests that require the wrapper to:

```python
def test_wrapper_preserves_existing_mutation_gates():
    text = WRAPPER.read_text(encoding="utf-8")
    assert "explicit user approval" in text
    assert "python scripts/push.py --only" in text
    assert "--dry-run" in text
    assert "Do not copy push logic" in text
    assert "evaluation_promotion.py promote" in text


def test_wrapper_blocks_incomplete_curator_runs():
    text = WRAPPER.read_text(encoding="utf-8")
    assert "structuralValidation: passed" in text
    assert "qualityValidation" in text
    assert "do not promote or push" in text
```

### Step 2: Run the focused tests to verify they fail

Run:

```powershell
python -m pytest tests\scripts\test_evaluation_curator_routing.py -v
```

Expected: the new lifecycle assertions fail.

### Step 3: Tighten the wrapper handoff

Add explicit rules:

- Accept the curator handoff only when `structuralValidation` is `passed`.
- Always run the Maker Kit validator even if the curator quality gate passed.
- Never infer approval from topic confirmation or case preview.
- Reuse `evaluation_promotion.py promote` for workspace-to-agent staging.
- Use scoped `push.py --only "evaluations/{set}/*"` commands only.
- Require dry-run review and explicit approval before `--yes`.
- Preserve workspace source until successful push cleanup.
- Do not copy the implementation details from `update/SKILL.md`; route to that flow so there is one source of truth.

### Step 4: Run lifecycle tests

Run:

```powershell
python -m pytest tests\scripts\test_evaluation_curator_routing.py -v
```

Expected: all tests pass.

### Step 5: Commit lifecycle guards

```powershell
git add solutions\ess-maker-skills\src\skills\evaluations\curate\SKILL.md tests\scripts\test_evaluation_curator_routing.py
git commit -m "fix(evaluations): preserve curator review and push gates"
```

---

## Task 7: Document the integrated workflow

**Files:**

- Modify: `solutions/ess-maker-skills/README.md`
- Modify: `setup/README.md`
- Modify: `solutions/ess-maker-skills/src/skills/evaluations/generate/SKILL.md`
- Modify: `solutions/ess-maker-skills/src/skills/evaluations/create/SKILL.md`

### Step 1: Add Maker Kit documentation

In the evaluation feature section of `solutions/ess-maker-skills/README.md`, document the three generation sources:

| Source | When used |
|---|---|
| Configured agent topics | Validate behavior already present in the active agent |
| Local knowledge source + agent instructions | Curate grounded knowledge and instruction-adherence tests through the pinned curator |
| Bundled ESS catalogue | Seed tests for a named ESS scenario without configured topics or documents |

State that all three produce native `.mcs.yml` plus CSV artifacts and can use the existing review, push, run, and results lifecycle.

### Step 2: Document dependency initialization

In `setup/README.md`, add troubleshooting for:

```powershell
git submodule sync --recursive
git submodule update --init --recursive
```

Explain that these commands restore the pinned curator dependency when a manual clone omitted submodules.

### Step 3: Clarify existing generator boundaries

In `generate/SKILL.md`, state that it remains the bundled-catalogue generator and must not handle user-supplied document folders.

In `create/SKILL.md`, state that it remains configured-topic-grounded and must not absorb the curator's document-grounding workflow.

These are boundary notes only; do not duplicate curator rules.

### Step 4: Review documentation formatting

Run:

```powershell
git diff --check
```

Expected: no whitespace errors.

### Step 5: Commit documentation

```powershell
git add solutions\ess-maker-skills\README.md setup\README.md solutions\ess-maker-skills\src\skills\evaluations\generate\SKILL.md solutions\ess-maker-skills\src\skills\evaluations\create\SKILL.md
git commit -m "docs(evaluations): explain knowledge-source curation"
```

---

## Task 8: Add a model-driven orchestration test

This test is opt-in and billable, matching the existing landing-page skill evaluation pattern.

**Files:**

- Create: `tests/mcp/evaluations/__init__.py`
- Create: `tests/mcp/evaluations/skill_eval.py`
- Create: `tests/mcp/evaluations/test_curator_skill_orchestration.py`
- Modify: `tests/README.md`

### Step 1: Create a synthetic skill-eval harness

Model the harness on `tests/mcp/agentconfig/skill_eval.py`. Disable production MCP connections and expose synthetic tools for:

- Reading the submodule contract.
- Reading the curator skill.
- Reading sample knowledge and agent instructions.
- Recording requested file writes.
- Recording validator invocations.

Do not access a live agent, tenant, or user documents.

### Step 2: Write the orchestration scenario

Add one live-marked case:

1. User asks `/evaluate` to curate tests from the curator sample knowledge folder and sample agent instructions.
2. Synthetic preflight reports a valid schema version.
3. The model reads the curator skill before generating cases.
4. The model asks for topic confirmation before writing artifacts.
5. After confirmation, the model writes under `workspace/evaluations`.
6. The model invokes structural and Maker Kit validation.
7. The model does not push without a separate explicit approval turn.

Assert tool-call ordering rather than exact prose.

### Step 3: Run the offline routing tests

Run:

```powershell
python -m pytest tests\scripts\test_evaluation_curator_routing.py tests\scripts\test_eval_curator_submodule.py -v
```

Expected: all tests pass.

### Step 4: Run the opt-in model test

Run only when GitHub Copilot model access is configured:

```powershell
$env:COPILOT_CLI_EXTRACT_DIR = Join-Path $PWD ".local\skill-evals\copilot-runtime"
python -m copilot download-runtime
python -m pytest tests\mcp\evaluations\test_curator_skill_orchestration.py --run-live -v
```

Expected: the model follows the curator-read, topic-confirmation, artifact-generation, validation, and no-unapproved-push sequence.

### Step 5: Document the optional test

Update `tests/README.md` with prerequisites, command, billing note, and the fact that it uses only synthetic files and tools.

### Step 6: Commit orchestration coverage

```powershell
git add tests\mcp\evaluations tests\README.md
git commit -m "test(evaluations): cover curator skill orchestration"
```

---

## Task 9: Run the full verification suite

**Files:**

- No new files expected.

### Step 1: Verify submodule state

Run:

```powershell
git submodule status
python solutions\ess-maker-skills\scripts\eval_curator_submodule.py status
```

Expected: pinned commit is clean and status JSON reports `available: true`.

### Step 2: Run focused evaluation tests

Run:

```powershell
python -m pytest tests\scripts\test_eval_curator_submodule.py tests\scripts\test_evaluation_curator_routing.py tests\scripts\test_eval_scenario.py tests\scripts\test_evaluation_review_routing.py -v
```

Expected: all tests pass.

### Step 3: Run lifecycle script tests

Run:

```powershell
python -m pytest tests\scripts --ignore=tests\scripts\test_installer_launch.py --ignore=tests\scripts\test_installer_maker_profile.py -q
```

Expected: all enforced lifecycle tests pass.

### Step 4: Run installer tests

Run:

```powershell
pwsh -NoProfile -File setup\Install-EssAdk.Tests.ps1
python -m pytest tests\setup\test_curator_submodule_setup.py -v
```

Expected: all installer tests pass.

### Step 5: Run lint and syntax checks

Run:

```powershell
ruff check solutions\ess-maker-skills\scripts solutions\ess-maker-skills\src\mcp tests\scripts\test_eval_curator_submodule.py tests\scripts\test_evaluation_curator_routing.py tests\setup\test_curator_submodule_setup.py
python -m compileall -q solutions\ess-maker-skills\scripts solutions\ess-maker-skills\src\mcp
```

Expected: no lint or syntax failures.

### Step 6: Verify repository status

Run:

```powershell
git status --short
git submodule status
```

Expected: no uncommitted files and the submodule points to the approved curator commit.

---

## Execution Handoff

Plan complete and saved to `docs/plans/2026-09-27-eval-curator-submodule-integration-implementation.md`. Execute it in a dedicated worktree.

Two execution options:

1. **Subagent-Driven (this session)** — dispatch a fresh subagent per task and review between tasks.
2. **Parallel Session (separate)** — open a new session in the worktree and follow `development/reference/executing-plans-guide.md` with checkpoints.

