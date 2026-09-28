# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Opt-in model evaluation for the knowledge-source curator orchestration."""

from __future__ import annotations

import asyncio
import json

import pytest

from tests.mcp.evaluations.skill_eval import (
    AGENT_INSTRUCTIONS_PATH,
    CURATOR_SKILL_PATH,
    KNOWLEDGE_PATH,
    MAKER_VALIDATOR_SKILL_PATH,
    STRUCTURAL_VALIDATOR_PATH,
    EvalTurn,
    FakeEvaluationWorkspace,
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


@pytest.mark.live
def test_curator_confirms_topics_then_writes_and_validates_without_push(tmp_path) -> None:
    backend = FakeEvaluationWorkspace()

    result = asyncio.run(
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
        index for index, call in enumerate(calls) if call.kind == "preflight"
    )
    curator_read_index = next(
        index
        for index, call in enumerate(calls)
        if call.name == "read_file"
        and call.arguments["path"].replace("\\", "/") == CURATOR_SKILL_PATH
    )
    first_write_index = next(
        index for index, call in enumerate(calls) if call.name == "write_file"
    )

    assert preflight_index < curator_read_index < first_write_index
    assert all(call.turn == 0 for call in calls[: first_write_index])
    assert not any(call.name == "write_file" and call.turn == 0 for call in calls)
    assert "?" in result.replies[0]

    required_reads = {KNOWLEDGE_PATH, AGENT_INSTRUCTIONS_PATH, CURATOR_SKILL_PATH}
    observed_reads = {
        call.arguments["path"].replace("\\", "/")
        for call in calls[:first_write_index]
        if call.name == "read_file"
    }
    assert required_reads <= observed_reads

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

    structural = [call for call in calls if call.kind == "structural_validation"]
    maker_kit = [call for call in calls if call.kind == "maker_kit_validation"]
    assert structural
    assert maker_kit
    assert min(calls.index(call) for call in structural) > first_write_index
    assert min(calls.index(call) for call in maker_kit) > first_write_index
    maker_validator_read_index = next(
        index
        for index, call in enumerate(calls)
        if call.name == "read_file"
        and call.arguments["path"].replace("\\", "/")
        == MAKER_VALIDATOR_SKILL_PATH
    )
    assert maker_validator_read_index < min(calls.index(call) for call in maker_kit)
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
    assert payload["skillPath"] == CURATOR_SKILL_PATH
    assert payload["structuralValidatorPath"] == STRUCTURAL_VALIDATOR_PATH
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
                '--evaluation-folder "workspace/evaluations/leave"'
            )
        },
    )
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
