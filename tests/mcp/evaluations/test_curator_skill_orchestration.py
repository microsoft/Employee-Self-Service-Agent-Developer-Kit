# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Opt-in model evaluation for the knowledge-source curator orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import json
from pathlib import Path

import pytest

from tests.mcp.evaluations.skill_eval import (
    AGENT_INSTRUCTIONS_PATH,
    CURATOR_SKILL_PATH,
    DISPATCHER_SKILL_PATH,
    EVALUATE_PROMPT_PATH,
    KNOWLEDGE_PATH,
    MAKER_VALIDATOR_SKILL_PATH,
    QUALITY_FIX_FLOW_PATH,
    STRUCTURAL_VALIDATOR_PATH,
    SYNTHETIC_REPO_ROOT,
    SYNTHETIC_SOLUTION_ROOT,
    UPDATE_SKILL_PATH,
    WRAPPER_SKILL_PATH,
    EvalTurn,
    FakeEvaluationWorkspace,
    RecordedCall,
    session_options,
    tool_contracts,
    run_eval,
)


def _ready_backend() -> FakeEvaluationWorkspace:
    backend = FakeEvaluationWorkspace()
    backend.contract_by_name = {
        contract.name: contract for contract in tool_contracts()
    }
    return backend


def _matching_read_index(
    calls: Sequence[RecordedCall],
    expected_path: str,
    *,
    after_index: int | None = None,
    before_index: int | None = None,
) -> int | None:
    return next(
        (
            index
            for index, call in enumerate(calls)
            if call.name == "read_file"
            and (after_index is None or index > after_index)
            and (before_index is None or index < before_index)
            and FakeEvaluationWorkspace.path_matches(
                call.arguments["path"], expected_path
            )
        ),
        None,
    )


def _missing_required_read_paths(
    calls: Sequence[RecordedCall],
    required_paths: Sequence[str],
    *,
    before_index: int | None = None,
) -> list[str]:
    return [
        path
        for path in required_paths
        if _matching_read_index(calls, path, before_index=before_index) is None
    ]


@pytest.mark.live
def test_curator_confirms_topics_then_writes_and_validates_without_push(tmp_path) -> None:
    backend = FakeEvaluationWorkspace()

    asyncio.run(
        run_eval(
            backend,
            [
                EvalTurn(
                    "/evaluate knowledge-source curation using "
                    f"{KNOWLEDGE_PATH} and {AGENT_INSTRUCTIONS_PATH}."
                ),
                EvalTurn("Generate the Leave policy topic only."),
            ],
            tmp_path,
        )
    )

    calls = backend.calls
    preflight_index = next(
        (index for index, call in enumerate(calls) if call.kind == "preflight"),
        None,
    )
    assert preflight_index is not None, "Missing curator preflight call."
    curator_read_index = _matching_read_index(calls, CURATOR_SKILL_PATH)
    assert curator_read_index is not None, "Missing curator skill read."
    first_write_index = next(
        (index for index, call in enumerate(calls) if call.name == "write_file"),
        None,
    )
    assert first_write_index is not None, "Missing evaluation artifact write."

    assert preflight_index < curator_read_index < first_write_index, (
        "Expected preflight, curator skill read, and first artifact write in order; "
        f"got preflight={preflight_index}, curator_read={curator_read_index}, "
        f"first_write={first_write_index}."
    )
    assert not any(call.name == "write_file" and call.turn == 0 for call in calls)

    required_reads = (KNOWLEDGE_PATH, AGENT_INSTRUCTIONS_PATH, CURATOR_SKILL_PATH)
    observed_reads = {
        call.arguments["path"].replace("\\", "/")
        for call in calls[:first_write_index]
        if call.name == "read_file"
    }
    missing_required_reads = _missing_required_read_paths(
        calls, required_reads, before_index=first_write_index
    )
    assert not missing_required_reads, (
        "Missing required reads before the first artifact write: "
        f"{missing_required_reads}; observed={sorted(observed_reads)}."
    )

    writes = [call for call in calls if call.name == "write_file"]
    assert writes
    assert all(call.turn == 1 for call in writes)
    assert all(
        call.arguments["path"].replace("\\", "/").startswith(
            "workspace/evaluations/"
        )
        for call in writes
    )
    assert any(call.arguments["path"].endswith(".mcs.yml") for call in writes)
    assert any(call.arguments["path"].endswith(".csv") for call in writes)
    generated_folders = backend.generated_set_folders()
    assert generated_folders, "Expected at least one generated evaluation set."
    last_write_index = max(
        index for index, call in enumerate(calls) if call.name == "write_file"
    )

    validations = [
        (index, call)
        for index, call in enumerate(calls)
        if call.kind in {"structural_validation", "maker_kit_validation"}
    ]
    assert validations, "Missing validation calls."
    assert last_write_index < validations[0][0], (
        "The curator flow writes all YAML and CSV artifacts before validation; "
        f"got last_write={last_write_index}, first_validation={validations[0][0]}."
    )

    validations_by_set: dict[str, list[tuple[int, RecordedCall]]] = {
        folder: [] for folder in generated_folders
    }
    for index, call in validations:
        command_folder = FakeEvaluationWorkspace.evaluation_folder_from_command(
            call.arguments["command"]
        )
        matching_folder = next(
            (
                folder
                for folder in generated_folders
                if command_folder
                in {
                    folder,
                    str(SYNTHETIC_REPO_ROOT / folder).replace("\\", "/"),
                }
            ),
            None,
        )
        assert matching_folder is not None, (
            f"{call.kind} must target a generated evaluation set; "
            f"got={command_folder}, generated={sorted(generated_folders)}."
        )
        validations_by_set[matching_folder].append((index, call))

    first_maker_kit_index = next(
        index for index, call in validations if call.kind == "maker_kit_validation"
    )
    for folder in generated_folders:
        final_set_write = max(
            index
            for index, call in enumerate(calls)
            if call.name == "write_file"
            and call.arguments["path"].replace("\\", "/").startswith(f"{folder}/")
            and call.arguments["path"].replace("\\", "/").endswith(".mcs.yml")
        )
        set_validations = validations_by_set[folder]
        structural_index = next(
            (
                index
                for index, call in set_validations
                if call.kind == "structural_validation" and index > final_set_write
            ),
            None,
        )
        assert structural_index is not None, (
            f"Missing structural validation after final write for {folder}."
        )
        assert structural_index < first_maker_kit_index, (
            "Every generated set must pass structural validation before initial "
            f"Maker Kit validation; got set={folder}, "
            f"structural={structural_index}, maker_kit={first_maker_kit_index}."
        )
        maker_kit_index = next(
            (
                index
                for index, call in set_validations
                if call.kind == "maker_kit_validation"
                and index > structural_index
            ),
            None,
        )
        assert maker_kit_index is not None, (
            f"Missing Maker Kit validation after structural validation for {folder}."
        )

    maker_validator_read_index = _matching_read_index(
        calls,
        MAKER_VALIDATOR_SKILL_PATH,
        before_index=first_maker_kit_index,
    )
    assert maker_validator_read_index is not None, "Missing Maker validator skill read."
    assert maker_validator_read_index < first_maker_kit_index, (
        "Maker validator skill must be read before initial Maker Kit validation; "
        f"got validator_read={maker_validator_read_index}, "
        f"maker_kit={first_maker_kit_index}."
    )
    assert not any(call.kind == "push" for call in calls)


def test_synthetic_preflight_exposes_valid_host_contract() -> None:
    backend = _ready_backend()

    call = backend.invoke(
        "run_command",
        {
            "command": (
                "py -3.12 scripts/eval_curator_submodule.py status "
                "--repo-root ../.."
            )
        },
    )

    assert call.kind == "preflight"
    assert not call.failed
    payload = json.loads(call.result["stdout"])
    assert payload["available"] is True
    skill_path = payload["skillPath"].replace("\\", "/")
    structural_validator_path = payload["structuralValidatorPath"].replace("\\", "/")
    synthetic_root = str(SYNTHETIC_REPO_ROOT).replace("\\", "/")
    assert Path(payload["skillPath"]).is_absolute()
    assert Path(payload["structuralValidatorPath"]).is_absolute()
    assert skill_path.startswith(f"{synthetic_root}/")
    assert structural_validator_path.startswith(f"{synthetic_root}/")
    assert skill_path.endswith(f"/solutions/ess-maker-skills/{CURATOR_SKILL_PATH}")
    assert structural_validator_path.endswith(
        f"/solutions/ess-maker-skills/{STRUCTURAL_VALIDATOR_PATH}"
    )
    assert payload["supportsHostOutputOverride"] is True
    assert payload["supportsHostLifecycleHandoff"] is True


def test_synthetic_workspace_ignores_csv_exports_when_validating_set() -> None:
    backend = _ready_backend()

    rejected = backend.invoke(
        "write_file", {"path": "outside.yml", "content": "synthetic"}
    )
    traversal = backend.invoke(
        "write_file",
        {
            "path": "workspace/evaluations/../../outside.yml",
            "content": "synthetic",
        },
    )
    written = backend.invoke(
        "write_file",
        {
            "path": "workspace/evaluations/leave/leave.mcs.yml",
            "content": "kind: EvaluationSet",
        },
    )
    child = backend.invoke(
        "write_file",
        {
            "path": "workspace/evaluations/leave/carryover.mcs.yml",
            "content": "kind: EvaluationData",
        },
    )
    exported = backend.invoke(
        "write_file",
        {
            "path": "workspace/evaluations/exports/20260927_Leave.csv",
            "content": "Prompt,Expected response,Test Method Type,Passing Score",
        },
    )
    structural = backend.invoke(
        "run_command",
        {
            "command": (
                f'python "{STRUCTURAL_VALIDATOR_PATH}" '
                '--evaluation-folder="workspace/evaluations/leave"'
            )
        },
    )
    backend.invoke("read_file", {"path": MAKER_VALIDATOR_SKILL_PATH})
    quality = backend.invoke(
        "run_command",
        {
            "command": (
                "python scripts/evaluate_evals.py "
                '--evaluation-folder "workspace/evaluations/leave"'
            )
        },
    )

    assert rejected.failed
    assert traversal.failed
    assert not written.failed
    assert not child.failed
    assert not exported.failed
    assert backend.generated_set_folders() == {"workspace/evaluations/leave"}
    assert structural.kind == "structural_validation"
    assert quality.kind == "maker_kit_validation"


def test_synthetic_validators_reject_unrelated_generated_set() -> None:
    backend = _ready_backend()
    backend.invoke(
        "write_file",
        {
            "path": "workspace/evaluations/leave/leave.mcs.yml",
            "content": "kind: EvaluationSet",
        },
    )
    backend.invoke("read_file", {"path": MAKER_VALIDATOR_SKILL_PATH})

    structural = backend.invoke(
        "run_command",
        {
            "command": (
                f'python "{STRUCTURAL_VALIDATOR_PATH}" '
                '--evaluation-folder "workspace/evaluations/benefits"'
            )
        },
    )
    quality = backend.invoke(
        "run_command",
        {
            "command": (
                "python scripts/evaluate_evals.py "
                "--evaluation-folder=workspace/evaluations/benefits"
            )
        },
    )

    assert structural.failed
    assert "generated evaluation set" in structural.result["stderr"]
    assert quality.failed
    assert "generated evaluation set" in quality.result["stderr"]


def test_synthetic_validators_accept_each_generated_set() -> None:
    backend = _ready_backend()
    for set_name in ("leave", "benefits"):
        backend.invoke(
            "write_file",
            {
                "path": f"workspace/evaluations/{set_name}/eval.mcs.yml",
                "content": "kind: EvaluationSet",
            },
        )
    backend.invoke(
        "write_file",
        {
            "path": "workspace/evaluations/exports/20260927_Leave.csv",
            "content": "Prompt,Expected response,Test Method Type,Passing Score",
        },
    )
    backend.invoke("read_file", {"path": MAKER_VALIDATOR_SKILL_PATH})

    for set_name in ("leave", "benefits"):
        structural = backend.invoke(
            "run_command",
            {
                "command": (
                    f'python "{STRUCTURAL_VALIDATOR_PATH}" '
                    f'--evaluation-folder "workspace/evaluations/{set_name}"'
                )
            },
        )
        assert structural.kind == "structural_validation"

    for set_name in ("leave", "benefits"):
        quality = backend.invoke(
            "run_command",
            {
                "command": (
                    "python scripts/evaluate_evals.py "
                    f'--evaluation-folder "workspace/evaluations/{set_name}"'
                )
            },
        )

        assert quality.kind == "maker_kit_validation"


def test_maker_validation_requires_structural_gate_for_same_set() -> None:
    backend = _ready_backend()
    for set_name in ("leave", "benefits"):
        backend.invoke(
            "write_file",
            {
                "path": f"workspace/evaluations/{set_name}/eval.mcs.yml",
                "content": "kind: EvaluationSet",
            },
        )
    backend.invoke("read_file", {"path": MAKER_VALIDATOR_SKILL_PATH})
    backend.invoke(
        "run_command",
        {
            "command": (
                f'python "{STRUCTURAL_VALIDATOR_PATH}" '
                '--evaluation-folder "workspace/evaluations/leave"'
            )
        },
    )

    quality = backend.invoke(
        "run_command",
        {
            "command": (
                "python scripts/evaluate_evals.py "
                '--evaluation-folder "workspace/evaluations/benefits"'
            )
        },
    )

    assert quality.failed
    assert "same evaluation set" in quality.result["stderr"]


def test_maker_validation_waits_for_all_generated_sets_to_pass_structure() -> None:
    backend = _ready_backend()
    for set_name in ("leave", "benefits"):
        backend.invoke(
            "write_file",
            {
                "path": f"workspace/evaluations/{set_name}/eval.mcs.yml",
                "content": "kind: EvaluationSet",
            },
        )
    backend.invoke("read_file", {"path": MAKER_VALIDATOR_SKILL_PATH})
    backend.invoke(
        "run_command",
        {
            "command": (
                f'python "{STRUCTURAL_VALIDATOR_PATH}" '
                '--evaluation-folder "workspace/evaluations/leave"'
            )
        },
    )
    leave_quality_command = (
        "python scripts/evaluate_evals.py "
        '--evaluation-folder "workspace/evaluations/leave"'
    )

    before_all_structural = backend.invoke(
        "run_command", {"command": leave_quality_command}
    )

    assert before_all_structural.failed
    assert "every generated evaluation set" in before_all_structural.result["stderr"]

    backend.invoke(
        "run_command",
        {
            "command": (
                f'python "{STRUCTURAL_VALIDATOR_PATH}" '
                '--evaluation-folder "workspace/evaluations/benefits"'
            )
        },
    )
    leave_quality = backend.invoke(
        "run_command", {"command": leave_quality_command}
    )
    benefits_quality = backend.invoke(
        "run_command",
        {
            "command": (
                "python scripts/evaluate_evals.py "
                '--evaluation-folder "workspace/evaluations/benefits"'
            )
        },
    )

    assert leave_quality.kind == "maker_kit_validation"
    assert not leave_quality.failed
    assert benefits_quality.kind == "maker_kit_validation"
    assert not benefits_quality.failed


def test_maker_validation_requires_skill_read_before_initial_validation() -> None:
    backend = _ready_backend()
    backend.invoke(
        "write_file",
        {
            "path": "workspace/evaluations/leave/leave.mcs.yml",
            "content": "kind: EvaluationSet",
        },
    )
    command = (
        "python scripts/evaluate_evals.py "
        '--evaluation-folder "workspace/evaluations/leave"'
    )

    backend.invoke(
        "run_command",
        {
            "command": (
                f'python "{STRUCTURAL_VALIDATOR_PATH}" '
                '--evaluation-folder "workspace/evaluations/leave"'
            )
        },
    )
    before_skill_read = backend.invoke("run_command", {"command": command})

    assert before_skill_read.failed
    assert "must be read before Maker Kit validation" in before_skill_read.result[
        "stderr"
    ]


def test_maker_validation_does_not_require_skill_reread_after_quality_fix() -> None:
    backend = _ready_backend()
    backend.invoke(
        "write_file",
        {
            "path": "workspace/evaluations/leave/leave.mcs.yml",
            "content": "kind: EvaluationSet",
        },
    )
    backend.invoke("read_file", {"path": MAKER_VALIDATOR_SKILL_PATH})
    structural_command = (
        f'python "{STRUCTURAL_VALIDATOR_PATH}" '
        '--evaluation-folder "workspace/evaluations/leave"'
    )
    backend.invoke("run_command", {"command": structural_command})
    backend.invoke(
        "write_file",
        {
            "path": "workspace/evaluations/leave/carryover.mcs.yml",
            "content": "kind: EvaluationData",
        },
    )
    quality_command = (
        "python scripts/evaluate_evals.py "
        '--evaluation-folder "workspace/evaluations/leave"'
    )
    stale_structural = backend.invoke(
        "run_command", {"command": quality_command}
    )
    backend.invoke("run_command", {"command": structural_command})
    quality = backend.invoke("run_command", {"command": quality_command})

    assert stale_structural.failed
    assert "after its final write" in stale_structural.result["stderr"]
    assert quality.kind == "maker_kit_validation"
    assert not quality.failed


def test_synthetic_workspace_exposes_wrapper_reads_as_read_only() -> None:
    backend = _ready_backend()

    evaluate_prompt = backend.invoke("read_file", {"path": EVALUATE_PROMPT_PATH})
    dispatcher_skill = backend.invoke("read_file", {"path": DISPATCHER_SKILL_PATH})
    wrapper_skill = backend.invoke("read_file", {"path": WRAPPER_SKILL_PATH})
    quality_flow = backend.invoke("read_file", {"path": QUALITY_FIX_FLOW_PATH})
    update_skill = backend.invoke("read_file", {"path": UPDATE_SKILL_PATH})

    assert not evaluate_prompt.failed
    assert not dispatcher_skill.failed
    assert not wrapper_skill.failed
    assert not quality_flow.failed
    assert not update_skill.failed
    read_only_paths = (
        EVALUATE_PROMPT_PATH,
        DISPATCHER_SKILL_PATH,
        WRAPPER_SKILL_PATH,
        CURATOR_SKILL_PATH,
        KNOWLEDGE_PATH,
        AGENT_INSTRUCTIONS_PATH,
        MAKER_VALIDATOR_SKILL_PATH,
        QUALITY_FIX_FLOW_PATH,
        UPDATE_SKILL_PATH,
    )
    before = dict(backend.files)
    for path in read_only_paths:
        rejected_write = backend.invoke(
            "write_file",
            {"path": path, "content": "synthetic"},
        )
        assert rejected_write.failed, f"Expected read-only synthetic path: {path}"
    assert backend.files == before


def test_synthetic_workspace_accepts_absolute_contract_paths() -> None:
    backend = _ready_backend()
    skill_path = (
        SYNTHETIC_REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / Path(CURATOR_SKILL_PATH)
    )
    validator_path = (
        SYNTHETIC_REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / Path(STRUCTURAL_VALIDATOR_PATH)
    )

    curator_skill = backend.invoke("read_file", {"path": str(skill_path)})
    backend.invoke(
        "write_file",
        {
            "path": "workspace/evaluations/leave/leave.mcs.yml",
            "content": "kind: EvaluationSet",
        },
    )
    evaluation_folder = (
        SYNTHETIC_REPO_ROOT / "workspace" / "evaluations" / "leave"
    )
    structural = backend.invoke(
        "run_command",
        {
            "command": (
                f'python "{validator_path}" '
                f'--evaluation-folder "{evaluation_folder}"'
            )
        },
    )

    assert not curator_skill.failed
    assert structural.kind == "structural_validation"


def test_path_matches_accepts_relative_key_and_exact_absolute_path() -> None:
    exact_absolute = SYNTHETIC_SOLUTION_ROOT / CURATOR_SKILL_PATH
    repo_key = f"solutions/ess-maker-skills/{CURATOR_SKILL_PATH}"
    repo_absolute = SYNTHETIC_REPO_ROOT / repo_key

    assert FakeEvaluationWorkspace.path_matches(
        CURATOR_SKILL_PATH, CURATOR_SKILL_PATH
    )
    assert FakeEvaluationWorkspace.path_matches(
        str(exact_absolute), CURATOR_SKILL_PATH
    )
    assert FakeEvaluationWorkspace.path_matches(repo_key, CURATOR_SKILL_PATH)
    assert FakeEvaluationWorkspace.path_matches(str(repo_absolute), repo_key)


def test_path_matches_rejects_wrong_root_suffix_and_parent_traversal() -> None:
    wrong_root = SYNTHETIC_REPO_ROOT / CURATOR_SKILL_PATH
    fabricated = Path("C:/fabricated") / CURATOR_SKILL_PATH
    traversal = SYNTHETIC_SOLUTION_ROOT / "nested" / ".." / CURATOR_SKILL_PATH

    assert not FakeEvaluationWorkspace.path_matches(
        str(wrong_root), CURATOR_SKILL_PATH
    )
    assert not FakeEvaluationWorkspace.path_matches(
        str(fabricated), CURATOR_SKILL_PATH
    )
    assert not FakeEvaluationWorkspace.path_matches(
        f"../{CURATOR_SKILL_PATH}", CURATOR_SKILL_PATH
    )
    assert not FakeEvaluationWorkspace.path_matches(
        str(traversal), CURATOR_SKILL_PATH
    )


@pytest.mark.parametrize("authoritative_absolute", [False, True])
def test_read_gate_helpers_accept_authoritative_paths(
    authoritative_absolute: bool,
) -> None:
    backend = _ready_backend()
    required_paths = (
        KNOWLEDGE_PATH,
        AGENT_INSTRUCTIONS_PATH,
        CURATOR_SKILL_PATH,
        MAKER_VALIDATOR_SKILL_PATH,
    )
    for path in required_paths:
        read_path = str(SYNTHETIC_SOLUTION_ROOT / path) if authoritative_absolute else path
        backend.invoke("read_file", {"path": read_path})

    assert _matching_read_index(backend.calls, CURATOR_SKILL_PATH) is not None
    assert _missing_required_read_paths(backend.calls, required_paths) == []
    assert _matching_read_index(backend.calls, MAKER_VALIDATOR_SKILL_PATH) is not None


def test_session_options_disable_host_and_production_connections(tmp_path) -> None:
    tools = [object()]
    allowed = object()

    options = session_options("evaluation-model", tools, allowed, tmp_path)

    assert options["tools"] is tools
    assert options["available_tools"] is allowed
    assert options["enable_config_discovery"] is False
    assert options["enable_skills"] is False
    assert options["enable_file_hooks"] is False
    assert options["enable_host_git_operations"] is False
    assert options["enable_session_store"] is False
    assert options["memory"] == {"enabled": False}
    assert options["mcp_servers"] == {}
    assert options["custom_agents"] == []
    assert options["plugin_directories"] == []
