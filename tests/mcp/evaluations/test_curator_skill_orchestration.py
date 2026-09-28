# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Opt-in model evaluation for the knowledge-source curator orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
import json
from pathlib import Path, PurePosixPath

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
    generated_folders = {
        "/".join(
            PurePosixPath(call.arguments["path"].replace("\\", "/")).parts[:3]
        )
        for call in writes
    }
    assert len(generated_folders) == 1, (
        "Expected writes for exactly one generated evaluation set; "
        f"found {sorted(generated_folders)}."
    )
    generated_folder = next(iter(generated_folders))
    last_write_index = max(
        index for index, call in enumerate(calls) if call.name == "write_file"
    )

    structural_index = next(
        (
            index
            for index, call in enumerate(calls)
            if call.kind == "structural_validation"
        ),
        None,
    )
    assert structural_index is not None, "Missing structural validation call."
    maker_kit_index = next(
        (
            index
            for index, call in enumerate(calls)
            if call.kind == "maker_kit_validation"
        ),
        None,
    )
    assert maker_kit_index is not None, "Missing Maker Kit validation call."
    assert last_write_index < structural_index < maker_kit_index, (
        "All writes must finish before structural and Maker Kit validation; "
        f"got last_write={last_write_index}, structural={structural_index}, "
        f"maker_kit={maker_kit_index}."
    )
    structural_folder = FakeEvaluationWorkspace.evaluation_folder_from_command(
        calls[structural_index].arguments["command"]
    )
    maker_kit_folder = FakeEvaluationWorkspace.evaluation_folder_from_command(
        calls[maker_kit_index].arguments["command"]
    )
    allowed_validation_folders = {
        generated_folder,
        str(SYNTHETIC_REPO_ROOT / generated_folder).replace("\\", "/"),
    }
    assert structural_folder in allowed_validation_folders, (
        "Structural validator must target the generated evaluation set folder; "
        f"expected={generated_folder}, got={structural_folder}."
    )
    assert maker_kit_folder in allowed_validation_folders, (
        "Maker Kit validator must target the generated evaluation set folder; "
        f"expected={generated_folder}, got={maker_kit_folder}."
    )
    maker_validator_read_index = _matching_read_index(
        calls,
        MAKER_VALIDATOR_SKILL_PATH,
        after_index=last_write_index,
        before_index=maker_kit_index,
    )
    assert maker_validator_read_index is not None, "Missing Maker validator skill read."
    assert last_write_index < maker_validator_read_index < maker_kit_index, (
        "Maker validator skill must be read after generation and before Maker Kit "
        "validation; "
        f"last_write={last_write_index}, "
        f"got validator_read={maker_validator_read_index}, "
        f"maker_kit={maker_kit_index}."
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


def test_synthetic_workspace_records_only_scoped_writes_and_validations() -> None:
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


def test_synthetic_validators_reject_writes_across_multiple_sets() -> None:
    backend = _ready_backend()
    for set_name in ("leave", "benefits"):
        backend.invoke(
            "write_file",
            {
                "path": f"workspace/evaluations/{set_name}/eval.mcs.yml",
                "content": "kind: EvaluationSet",
            },
        )

    structural = backend.invoke(
        "run_command",
        {
            "command": (
                f'python "{STRUCTURAL_VALIDATOR_PATH}" '
                '--evaluation-folder "workspace/evaluations/leave"'
            )
        },
    )

    assert structural.failed
    assert "exactly one generated evaluation set" in structural.result["stderr"]


def test_maker_validation_requires_post_generation_skill_read_and_structural_gate() -> None:
    backend = _ready_backend()
    backend.invoke("read_file", {"path": MAKER_VALIDATOR_SKILL_PATH})
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

    before_post_generation_read = backend.invoke("run_command", {"command": command})
    backend.invoke("read_file", {"path": MAKER_VALIDATOR_SKILL_PATH})
    before_structural = backend.invoke("run_command", {"command": command})

    assert before_post_generation_read.failed
    assert "after generation" in before_post_generation_read.result["stderr"]
    assert before_structural.failed
    assert "structural validation" in before_structural.result["stderr"]


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
    structural = backend.invoke(
        "run_command",
        {
            "command": (
                f'python "{validator_path}" '
                '--evaluation-folder "workspace/evaluations/leave"'
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
