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
    SYNTHETIC_KB_ARTICLES,
    SYNTHETIC_KB_EMPTY_SUBJECT,
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

# The connected-KB tests below (test_connected_kb_*) are offline/synthetic:
# they manually drive `backend.invoke(...)` against the fake `search`/`fetch`
# tools and the SYNTHETIC_KB_ARTICLES fixture to prove the curator's
# connected-KB CALL SEQUENCE (discovery search -> targeted search+fetch
# grounding -> eval-set write; skip fetch/write on zero search results). They
# run in CI with no credentials and do NOT invoke a real model, so they do
# NOT prove that a real connected knowledge-base backend returns
# result/content shapes compatible with what the curator expects — closing
# that gap is left to a live manual dry-run (mirrors the design's Layer-3
# caveat).


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
    curator_read_index = _matching_read_index(calls, CURATOR_SKILL_PATH)
    assert curator_read_index is not None, "Missing curator skill read."
    first_write_index = next(
        (index for index, call in enumerate(calls) if call.name == "write_file"),
        None,
    )
    assert first_write_index is not None, "Missing evaluation artifact write."

    assert curator_read_index < first_write_index, (
        "Expected curator skill read before first artifact write; "
        f"got curator_read={curator_read_index}, "
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
    maker_attempts = [
        (index, call)
        for index, call in enumerate(calls)
        if call.validator_type == "maker_kit"
    ]
    assert maker_attempts, "Missing Maker Kit validation attempt."
    ordering_violations = backend.maker_validation_ordering_violations()
    assert not ordering_violations, (
        "Maker Kit validation was attempted before every generated set had current "
        "successful structural validation after its final write: "
        f"{ordering_violations}"
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

    first_maker_kit_index = maker_attempts[0][0]
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
    assert structural.validator_type == "structural"
    assert "generated evaluation set" in structural.result["stderr"]
    assert quality.failed
    assert quality.validator_type == "maker_kit"
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
    assert before_all_structural.validator_type == "maker_kit"
    assert "every generated evaluation set" in before_all_structural.result["stderr"]
    premature_violations = backend.maker_validation_ordering_violations()
    assert len(premature_violations) == 1
    assert "workspace/evaluations/benefits" in premature_violations[0]

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
    assert backend.maker_validation_ordering_violations() == premature_violations


def test_maker_ordering_uses_set_state_at_each_attempt_after_rewrite() -> None:
    backend = _ready_backend()
    evaluation_folder = "workspace/evaluations/leave"
    evaluation_path = f"{evaluation_folder}/eval.mcs.yml"
    structural_command = (
        f'python "{STRUCTURAL_VALIDATOR_PATH}" '
        f'--evaluation-folder "{evaluation_folder}"'
    )
    maker_command = (
        "python scripts/evaluate_evals.py "
        f'--evaluation-folder "{evaluation_folder}"'
    )
    backend.invoke(
        "write_file",
        {"path": evaluation_path, "content": "kind: EvaluationSet"},
    )
    backend.invoke("read_file", {"path": MAKER_VALIDATOR_SKILL_PATH})
    backend.invoke("run_command", {"command": structural_command})
    first_maker = backend.invoke("run_command", {"command": maker_command})

    backend.invoke(
        "write_file",
        {"path": evaluation_path, "content": "kind: EvaluationSet\nrevision: 2"},
    )
    backend.invoke("run_command", {"command": structural_command})
    second_maker = backend.invoke("run_command", {"command": maker_command})

    assert not first_maker.failed
    assert not second_maker.failed
    assert backend.maker_validation_ordering_violations() == []


def test_maker_ordering_applies_new_set_barrier_only_to_later_attempts() -> None:
    backend = _ready_backend()
    leave_folder = "workspace/evaluations/leave"
    benefits_folder = "workspace/evaluations/benefits"
    leave_maker_command = (
        "python scripts/evaluate_evals.py "
        f'--evaluation-folder "{leave_folder}"'
    )
    backend.invoke(
        "write_file",
        {
            "path": f"{leave_folder}/eval.mcs.yml",
            "content": "kind: EvaluationSet",
        },
    )
    backend.invoke("read_file", {"path": MAKER_VALIDATOR_SKILL_PATH})
    backend.invoke(
        "run_command",
        {
            "command": (
                f'python "{STRUCTURAL_VALIDATOR_PATH}" '
                f'--evaluation-folder "{leave_folder}"'
            )
        },
    )
    first_maker = backend.invoke(
        "run_command", {"command": leave_maker_command}
    )

    backend.invoke(
        "write_file",
        {
            "path": f"{benefits_folder}/eval.mcs.yml",
            "content": "kind: EvaluationSet",
        },
    )
    premature_maker = backend.invoke(
        "run_command", {"command": leave_maker_command}
    )
    backend.invoke(
        "run_command",
        {
            "command": (
                f'python "{STRUCTURAL_VALIDATOR_PATH}" '
                f'--evaluation-folder "{benefits_folder}"'
            )
        },
    )
    retry_maker = backend.invoke(
        "run_command", {"command": leave_maker_command}
    )

    violations = backend.maker_validation_ordering_violations()
    assert not first_maker.failed
    assert premature_maker.failed
    assert not retry_maker.failed
    assert len(violations) == 1
    assert "call 5" in violations[0]
    assert benefits_folder in violations[0]


def test_maker_ordering_retains_premature_failure_after_successful_retry() -> None:
    backend = _ready_backend()
    evaluation_folder = "workspace/evaluations/leave"
    maker_command = (
        "python scripts/evaluate_evals.py "
        f'--evaluation-folder "{evaluation_folder}"'
    )
    backend.invoke(
        "write_file",
        {
            "path": f"{evaluation_folder}/eval.mcs.yml",
            "content": "kind: EvaluationSet",
        },
    )
    backend.invoke("read_file", {"path": MAKER_VALIDATOR_SKILL_PATH})
    premature_maker = backend.invoke("run_command", {"command": maker_command})
    premature_violations = backend.maker_validation_ordering_violations()

    backend.invoke(
        "run_command",
        {
            "command": (
                f'python "{STRUCTURAL_VALIDATOR_PATH}" '
                f'--evaluation-folder "{evaluation_folder}"'
            )
        },
    )
    retry_maker = backend.invoke("run_command", {"command": maker_command})

    assert premature_maker.failed
    assert not retry_maker.failed
    assert len(premature_violations) == 1
    assert "call 2" in premature_violations[0]
    assert backend.maker_validation_ordering_violations() == premature_violations


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


def test_connected_kb_discovers_topics_then_grounds_before_generation() -> None:
    backend = _ready_backend()

    discovery_queries = ("password access", "leave time off")
    for query in discovery_queries:
        discovery = backend.invoke("search", {"query": query})
        assert discovery.kind == "search"
        if query == "password access":
            discovery_ids = [result["id"] for result in discovery.result]
            assert "kb0001" in discovery_ids or "kb0003" in discovery_ids

    targeted_search = backend.invoke("search", {"query": "PTO rollover"})
    assert targeted_search.kind == "search"
    assert targeted_search.result
    matched_ids = [result["id"] for result in targeted_search.result]
    assert matched_ids == ["kb0004"]

    fetch = backend.invoke("fetch", {"id": "kb0004"})
    assert fetch.kind == "fetch"
    assert not fetch.failed
    assert fetch.result["body"] == SYNTHETIC_KB_ARTICLES["kb0004"]["body"]
    assert "40 hours" in fetch.result["body"]

    write = backend.invoke(
        "write_file",
        {
            "path": "workspace/evaluations/pto/pto.mcs.yml",
            "content": "kind: EvaluationSet",
        },
    )
    assert not write.failed

    calls = backend.calls
    search_calls = [call for call in calls if call.kind == "search"]
    assert len(search_calls) == len(discovery_queries) + 1
    fetch_index = next(
        index for index, call in enumerate(calls) if call.kind == "fetch"
    )
    write_index = next(
        index for index, call in enumerate(calls) if call.kind == "write"
    )
    assert fetch_index < write_index, (
        "Expected grounding fetch before the eval-set write for the topic; "
        f"got fetch={fetch_index}, write={write_index}."
    )


def test_connected_kb_zero_result_topic_generates_no_cases() -> None:
    backend = _ready_backend()

    empty_search = backend.invoke(
        "search", {"query": SYNTHETIC_KB_EMPTY_SUBJECT}
    )

    assert empty_search.kind == "search"
    assert not empty_search.failed
    assert empty_search.result == []

    # A well-behaved connected-KB flow does not fetch or write for a topic
    # whose search returned nothing: skip, don't fabricate.
    calls = backend.calls
    assert not any(call.kind == "fetch" for call in calls)
    assert not any(call.kind == "write" for call in calls)


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
