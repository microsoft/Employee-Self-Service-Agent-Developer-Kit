# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the eval-driven topic scenario utility."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
import yaml

import eval_scenario


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = (
    _REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "skills"
    / "topics"
    / "create-eval-driven"
    / "eval-scenario.schema.json"
)


def _simple_scenario() -> dict:
    return {
        "schemaVersion": 2,
        "id": "bereavement-leave-info",
        "name": "Bereavement leave guidance",
        "intent": "Explain the approved bereavement leave process.",
        "topicType": "informational",
        "phase": 1,
        "persona": "employee",
        "sourceContent": "Use the approved HR guidance and support link.",
        "evals": [
            {
                "category": "directTrigger",
                "input": "What should I do if I need bereavement leave?",
                "expectedOutput": "Returns the approved guidance and support link.",
            },
            {
                "category": "nonTrigger",
                "input": "How much vacation do I have?",
                "expectedOutput": "Does not invoke the bereavement leave topic.",
                "required": False,
            },
            {
                "category": "downstreamError",
                "condition": "The approved source is unavailable.",
                "expectedOutput": "Explains that the guidance is unavailable.",
            },
        ],
    }


def _schema_accepts(scenario: dict) -> bool:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(scenario, schema)
    except jsonschema.ValidationError:
        return False
    return True


def _python_accepts(scenario: dict) -> bool:
    try:
        eval_scenario.validate_scenario(scenario)
    except eval_scenario.ScenarioValidationError:
        return False
    return True


def test_validate_scenario_accepts_phase_one_contract():
    eval_scenario.validate_scenario(_simple_scenario())


def test_validate_scenario_rejects_update_fields():
    scenario = _simple_scenario()
    scenario["changeType"] = "update"
    scenario["targetTopic"] = "ExistingTopic"

    with pytest.raises(eval_scenario.ScenarioValidationError) as exc_info:
        eval_scenario.validate_scenario(scenario)

    assert "scenario: unknown field 'changeType'" in exc_info.value.errors
    assert "scenario: unknown field 'targetTopic'" in exc_info.value.errors


def test_validate_scenario_requires_source_content_for_informational_topic():
    scenario = _simple_scenario()
    scenario.pop("sourceContent")

    with pytest.raises(eval_scenario.ScenarioValidationError) as exc_info:
        eval_scenario.validate_scenario(scenario)

    assert (
        "sourceContent is required for informational topics"
        in exc_info.value.errors
    )


def test_validate_scenario_rejects_phase_two_and_integration_fields():
    scenario = _simple_scenario()
    scenario["phase"] = 2
    scenario["integration"] = {
        "system": "workday",
        "operation": "read",
        "scenarioName": "getBalance",
    }

    with pytest.raises(eval_scenario.ScenarioValidationError) as exc_info:
        eval_scenario.validate_scenario(scenario)

    assert "phase must be 1 for eval-driven simple topics" in exc_info.value.errors
    assert "scenario: unknown field 'integration'" in exc_info.value.errors


def test_create_command_routes_topics_to_eval_driven_skill():
    prompt = (
        _REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / ".github"
        / "prompts"
        / "create.prompt.md"
    ).read_text(encoding="utf-8")
    instructions = (
        _REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / ".github"
        / "copilot-instructions.md"
    ).read_text(encoding="utf-8")

    skill_path = "src/skills/topics/create-eval-driven/SKILL.md"
    assert skill_path in prompt
    assert skill_path in instructions
    assert "scenario YAML file" in prompt
    assert "evaluation YAML files" in prompt


def test_create_command_preserves_legacy_integration_path():
    prompt = (
        _REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / ".github"
        / "prompts"
        / "create.prompt.md"
    ).read_text(encoding="utf-8")

    integration_rule = prompt.index(
        "involving Workday,\n   ServiceNow, SAP"
    )
    simple_rule = prompt.index("asks to create a **simple topic**")

    assert integration_rule < simple_rule
    assert "src/skills/topics/create/SKILL.md" in prompt


def test_create_command_gives_explicit_evaluation_intent_precedence():
    prompt = (
        _REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / ".github"
        / "prompts"
        / "create.prompt.md"
    ).read_text(encoding="utf-8")

    evaluation_rule = prompt.index(
        "explicitly asks to create or generate an **evaluation**"
    )
    topic_rule = prompt.index("explicitly asks to create a **topic**")

    assert evaluation_rule < topic_rule
    assert "Do this even" in prompt
    assert "when the request also contains evaluation file paths" in prompt
    assert "create a **topic from these evals**" in prompt
    assert "**evaluation test set**" in prompt


def test_eval_driven_skill_is_create_only():
    skill = (
        _REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / "src"
        / "skills"
        / "topics"
        / "create-eval-driven"
        / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "## Step 4: Generate the topic" in skill
    assert "Write the new topic" in skill
    assert "src/skills/topics/update/SKILL.md" not in skill
    assert "changeType" not in skill
    assert "Phase 1 topics" in skill
    assert "src/skills/topics/create/SKILL.md` unchanged" in skill
    assert ".local/eval-driven/drafts/{scenario-id}.scenario.yaml" in skill
    assert "only after approval" in skill
    assert "src/skills/topics/test/SKILL.md" in skill
    assert "python scripts/push.py --force-delete" in skill
    assert "future automated eval-level validation pipeline" in skill


def test_update_command_routes_simple_topics_and_preserves_integrations():
    prompt = (
        _REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / ".github"
        / "prompts"
        / "update.prompt.md"
    ).read_text(encoding="utf-8")
    update_skill = (
        _REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / "src"
        / "skills"
        / "topics"
        / "update-eval-driven"
        / "SKILL.md"
    ).read_text(encoding="utf-8")

    legacy_rule = prompt.index("Workday, ServiceNow, SAP")
    eval_rule = prompt.index("simple informational, clarification")

    assert legacy_rule < eval_rule
    assert "src/skills/topics/update-eval-driven/SKILL.md" in prompt
    assert "src/skills/topics/update/SKILL.md` unchanged" in update_skill
    assert "Never create a second topic file" in update_skill
    assert "If no scenario-owned evals exist" in update_skill
    assert ".local/eval-driven/drafts/{scenario-id}.scenario.yaml" in update_skill
    assert "before approval" in update_skill
    assert "If more than one manifest matches, stop before making changes" in (
        update_skill
    )
    assert "never select one silently" in update_skill
    assert "src/skills/topics/test/SKILL.md" in update_skill
    assert "python scripts/push.py --force-delete" in update_skill
    assert "future automated eval-level validation pipeline" in update_skill


def test_checked_in_schema_is_valid_json():
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))

    assert schema["properties"]["schemaVersion"]["const"] == 2
    assert schema["properties"]["phase"]["const"] == 1
    assert "topicType" in schema["required"]
    assert "integration" not in schema["properties"]
    assert schema["properties"]["evals"]["minItems"] == 1


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda scenario: scenario, True),
        (lambda scenario: scenario.pop("sourceContent"), False),
        (
            lambda scenario: scenario["evals"][0].update(
                {"turns": [{"input": "More detail"}]}
            ),
            False,
        ),
        (
            lambda scenario: scenario.update(
                {"topicType": "clarification"}
            )
            or scenario.pop("sourceContent"),
            True,
        ),
        (lambda scenario: scenario.update({"phase": True}), False),
        (lambda scenario: scenario.update({"name": "   "}), False),
        (lambda scenario: scenario.update({"intent": "\t"}), False),
        (lambda scenario: scenario.update({"sourceContent": "\n"}), False),
        (lambda scenario: scenario.update({"references": ["   "]}), False),
        (
            lambda scenario: scenario.update(
                {
                    "dependencyChecks": [
                        {"condition": " ", "behavior": "Block generation"}
                    ]
                }
            ),
            False,
        ),
        (
            lambda scenario: scenario["evals"][0].update({"input": "   "}),
            False,
        ),
        (
            lambda scenario: scenario["evals"][0].update(
                {"expectedOutput": "\t"}
            ),
            False,
        ),
    ],
)
def test_json_schema_and_python_validator_have_parity(mutate, expected):
    scenario = _simple_scenario()
    mutate(scenario)

    assert _schema_accepts(scenario) is expected
    assert _python_accepts(scenario) is expected


def test_normalize_native_evals_builds_valid_traceable_contract(tmp_path: Path):
    eval_folder = tmp_path / "badge-evals"
    eval_folder.mkdir()
    parent = eval_folder / "badge-evals.mcs.yml"
    parent.write_text(
        yaml.safe_dump(
            {
                "kind": "EvaluationSet",
                "displayName": "Badge evals",
                "graders": [
                    {"kind": "GeneralQualityGrader"},
                    {"kind": "CompareMeaningGrader", "threshold": 0.8},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    single = eval_folder / "001-paraphrase.mcs.yml"
    single.write_text(
        yaml.safe_dump(
            {
                "kind": "EvaluationData",
                "rows": [
                    {
                        "input": "My badge is damaged",
                        "expectedOutput": "Explains the replacement process.",
                    },
                    {
                        "input": "I need help with my access card",
                        "expectedOutput": "Explains the replacement process.",
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    multi = eval_folder / "002-clarification.mcs.yml"
    multi.write_text(
        yaml.safe_dump(
            {
                "kind": "MultiTurnEvaluationCase",
                "activities": [
                    {
                        "activity": {"value": {"from": {"role": "user"}}},
                        "text": ["I need badge help"],
                    },
                    {
                        "activity": {"value": {"from": {"role": "agent"}}},
                        "text": ["Asks whether it is lost, stolen, or damaged."],
                    },
                    {
                        "activity": {"value": {"from": {"role": "user"}}},
                        "text": ["It was stolen"],
                    },
                    {
                        "activity": {"value": {"from": {"role": "agent"}}},
                        "text": ["Tells the employee to contact Security first."],
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    scenario = eval_scenario.normalize_native_evals(
        [eval_folder],
        "office-badge-replacement",
        "Office Badge Replacement",
        "Explain the office badge replacement process.",
        "clarification",
        "employee",
    )

    assert _schema_accepts(scenario)
    assert _python_accepts(scenario)
    assert len(scenario["evals"]) == 3
    assert scenario["evals"][0]["category"] == "paraphrase"
    assert scenario["evals"][0]["threshold"] == 0.8
    assert scenario["evals"][1]["threshold"] == 0.8
    assert scenario["evals"][2]["category"] == "clarification"
    assert scenario["evals"][2]["turns"][1]["input"] == "It was stolen"
    assert len(scenario["references"]) == 3
    assert parent.resolve().as_posix() in scenario["references"]
    assert single.resolve().as_posix() in scenario["references"]
    assert multi.resolve().as_posix() in scenario["references"]


def test_normalize_command_writes_approved_contract_input(tmp_path: Path):
    eval_file = tmp_path / "001-directtrigger.mcs.yml"
    eval_file.write_text(
        yaml.safe_dump(
            {
                "kind": "EvaluationData",
                "rows": [
                    {
                        "input": "How do I replace my badge?",
                        "expectedOutput": "Returns the approved badge guidance.",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "scenario.yaml"

    result = eval_scenario.main(
        [
            "normalize",
            str(eval_file),
            "--id",
            "office-badge-replacement",
            "--name",
            "Office Badge Replacement",
            "--intent",
            "Explain the office badge replacement process.",
            "--topic-type",
            "informational",
            "--persona",
            "employee",
            "--source-content",
            "Use the approved Facilities and Security guidance.",
            "--output",
            str(output),
        ]
    )

    assert result == 0
    scenario = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert scenario["sourceContent"] == (
        "Use the approved Facilities and Security guidance."
    )
    assert scenario["evals"][0]["category"] == "directTrigger"


def test_main_reports_filesystem_errors_without_traceback(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    eval_file = tmp_path / "001-directtrigger.mcs.yml"
    eval_file.write_text(
        yaml.safe_dump(
            {
                "kind": "EvaluationData",
                "rows": [
                    {
                        "input": "How do I replace my badge?",
                        "expectedOutput": "Returns the approved badge guidance.",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    def fail_write(path, value):
        raise OSError("disk is read-only")

    monkeypatch.setattr(eval_scenario, "_write_yaml", fail_write)

    result = eval_scenario.main(
        [
            "normalize",
            str(eval_file),
            "--id",
            "office-badge-replacement",
            "--name",
            "Office Badge Replacement",
            "--intent",
            "Explain the office badge replacement process.",
            "--topic-type",
            "informational",
            "--persona",
            "employee",
            "--source-content",
            "Use the approved Facilities and Security guidance.",
            "--output",
            str(tmp_path / "scenario.yaml"),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "ERROR: filesystem operation failed: disk is read-only" in captured.err
    assert "Traceback" not in captured.err


def test_normalize_native_evals_rejects_unsupported_kind(tmp_path: Path):
    invalid = tmp_path / "topic.mcs.yml"
    invalid.write_text("kind: AdaptiveDialog\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported evaluation kind"):
        eval_scenario.normalize_native_evals(
            [invalid],
            "office-badge-replacement",
            "Office Badge Replacement",
            "Explain the office badge replacement process.",
            "clarification",
            "employee",
        )


def test_validate_scenario_reports_all_actionable_errors():
    scenario = _simple_scenario()
    scenario["id"] = "Not Valid"
    scenario["topicType"] = "unknown"
    scenario["evals"][0].pop("expectedOutput")

    with pytest.raises(eval_scenario.ScenarioValidationError) as exc_info:
        eval_scenario.validate_scenario(scenario)

    assert "id must be lowercase kebab-case" in exc_info.value.errors
    assert "topicType must be one of:" in "\n".join(exc_info.value.errors)
    assert (
        "evals[1].expectedOutput is required for input evaluations"
        in exc_info.value.errors
    )


def test_materialize_writes_native_evals_and_runtime_manifest(tmp_path: Path):
    scenario = _simple_scenario()
    scenario["evals"].insert(
        2,
        {
            "category": "clarification",
            "turns": [
                {
                    "input": "I need leave help.",
                    "expectedOutput": "Asks which type of leave the employee needs.",
                },
                {
                    "input": "Bereavement leave.",
                    "expectedOutput": "Returns the approved bereavement guidance.",
                },
            ],
        },
    )

    agent_folder = tmp_path / "workspace" / "agents" / "mock-agent"
    topic_file = agent_folder / "topics" / "BereavementLeaveInfo.mcs.yml"
    topic_file.parent.mkdir(parents=True)
    topic_file.write_text("kind: AdaptiveDialog\n", encoding="utf-8")
    runtime_output = tmp_path / ".local" / "eval-driven" / "runtime-manifest.json"

    manifest = eval_scenario.materialize_scenario(
        scenario,
        agent_folder,
        topic_file,
        runtime_output,
    )

    single_parent = (
        agent_folder
        / "evaluations"
        / "eval-driven-bereavement-leave-info"
        / "eval-driven-bereavement-leave-info.mcs.yml"
    )
    direct_child = single_parent.parent / "001-directtrigger.mcs.yml"
    multi_parent = (
        agent_folder
        / "evaluations"
        / "eval-driven-bereavement-leave-info-multi-turn"
        / "eval-driven-bereavement-leave-info-multi-turn.mcs.yml"
    )
    multi_child = multi_parent.parent / "003-clarification.mcs.yml"

    assert yaml.safe_load(single_parent.read_text())["kind"] == "EvaluationSet"
    assert yaml.safe_load(direct_child.read_text())["kind"] == "EvaluationData"
    assert yaml.safe_load(multi_parent.read_text())["graders"] == [
        {"kind": "GeneralQualityGrader"}
    ]
    assert yaml.safe_load(multi_child.read_text())["kind"] == (
        "MultiTurnEvaluationCase"
    )

    runtime = json.loads(runtime_output.read_text())
    assert runtime == manifest
    assert runtime["scenario"]["operation"] == "create"
    assert runtime["scenario"]["topicType"] == "informational"
    assert runtime["topic"]["path"] == "topics/BereavementLeaveInfo.mcs.yml"
    assert len(runtime["evals"]) == 4
    assert runtime["evals"][1]["required"] is False
    assert runtime["evals"][3]["condition"] == "The approved source is unavailable."
    assert runtime["evals"][3]["nativeEvalPath"] is None


def test_materialize_update_targets_existing_topic_and_refreshes_owned_evals(
    tmp_path: Path,
):
    scenario = _simple_scenario()
    scenario["id"] = "office-badge-replacement"
    scenario["name"] = "Office Badge Replacement"
    scenario["intent"] = "Explain the updated office badge replacement process."

    agent_folder = tmp_path / "workspace" / "agents" / "mock-agent"
    topic_file = agent_folder / "topics" / "OfficeBadgeReplacement.mcs.yml"
    topic_file.parent.mkdir(parents=True)
    topic_file.write_text("kind: AdaptiveDialog\n", encoding="utf-8")
    generated_folder = (
        agent_folder / "evaluations" / "eval-driven-office-badge-replacement"
    )
    generated_folder.mkdir(parents=True)
    stale_file = generated_folder / "999-stale.mcs.yml"
    stale_file.write_text("kind: EvaluationData\n", encoding="utf-8")

    manifest = eval_scenario.materialize_scenario(
        scenario,
        agent_folder,
        topic_file,
        tmp_path / "runtime-manifest.json",
        operation="update",
    )

    assert manifest["scenario"]["operation"] == "update"
    assert manifest["topic"]["path"] == "topics/OfficeBadgeReplacement.mcs.yml"
    assert not stale_file.exists()
    assert topic_file.exists()
    assert len(list((agent_folder / "topics").glob("*.mcs.yml"))) == 1


def test_materialize_rejects_unknown_operation(tmp_path: Path):
    agent_folder = tmp_path / "agent"
    topic_file = agent_folder / "topics" / "Topic.mcs.yml"
    topic_file.parent.mkdir(parents=True)
    topic_file.write_text("kind: AdaptiveDialog\n", encoding="utf-8")

    with pytest.raises(ValueError, match="operation must be one of"):
        eval_scenario.materialize_scenario(
            _simple_scenario(),
            agent_folder,
            topic_file,
            tmp_path / "manifest.json",
            operation="delete",
        )


def test_materialize_rejects_topic_outside_agent_folder(tmp_path: Path):
    agent_folder = tmp_path / "agent"
    agent_folder.mkdir()
    topic_file = tmp_path / "outside.mcs.yml"
    topic_file.write_text("kind: AdaptiveDialog\n", encoding="utf-8")

    with pytest.raises(ValueError, match="inside the agent folder"):
        eval_scenario.materialize_scenario(
            _simple_scenario(),
            agent_folder,
            topic_file,
            tmp_path / "manifest.json",
        )


def test_materialize_removes_stale_files_from_owned_scenario_folder(tmp_path: Path):
    scenario = _simple_scenario()
    agent_folder = tmp_path / "agent"
    topic_file = agent_folder / "topics" / "Topic.mcs.yml"
    topic_file.parent.mkdir(parents=True)
    topic_file.write_text("kind: AdaptiveDialog\n", encoding="utf-8")
    generated_folder = (
        agent_folder / "evaluations" / "eval-driven-bereavement-leave-info"
    )
    generated_folder.mkdir(parents=True)
    stale_file = generated_folder / "999-stale.mcs.yml"
    stale_file.write_text("kind: EvaluationData\n", encoding="utf-8")
    sibling_folder = (
        agent_folder
        / "evaluations"
        / "eval-driven-bereavement-leave-info-regional"
    )
    sibling_folder.mkdir(parents=True)
    sibling_file = sibling_folder / "keep.mcs.yml"
    sibling_file.write_text("kind: EvaluationData\n", encoding="utf-8")

    eval_scenario.materialize_scenario(
        scenario,
        agent_folder,
        topic_file,
        tmp_path / "manifest.json",
    )

    assert not stale_file.exists()
    assert (
        generated_folder / "001-directtrigger.mcs.yml"
    ).exists()
    assert sibling_file.exists()


def test_materialize_uses_distinct_folders_for_close_thresholds(tmp_path: Path):
    scenario = _simple_scenario()
    scenario["evals"][0]["threshold"] = 0.700
    scenario["evals"][1]["threshold"] = 0.704
    agent_folder = tmp_path / "agent"
    topic_file = agent_folder / "topics" / "Topic.mcs.yml"
    topic_file.parent.mkdir(parents=True)
    topic_file.write_text("kind: AdaptiveDialog\n", encoding="utf-8")

    eval_scenario.materialize_scenario(
        scenario,
        agent_folder,
        topic_file,
        tmp_path / "manifest.json",
    )

    first_folder = (
        agent_folder
        / "evaluations"
        / "eval-driven-bereavement-leave-info-t0d7"
    )
    second_folder = (
        agent_folder
        / "evaluations"
        / "eval-driven-bereavement-leave-info-t0d704"
    )
    first_parent = first_folder / f"{first_folder.name}.mcs.yml"
    second_parent = second_folder / f"{second_folder.name}.mcs.yml"

    assert yaml.safe_load(first_parent.read_text())["graders"][1]["threshold"] == 0.7
    assert yaml.safe_load(second_parent.read_text())["graders"][1]["threshold"] == 0.704
    assert (first_folder / "001-directtrigger.mcs.yml").exists()
    assert (second_folder / "002-nontrigger.mcs.yml").exists()


def test_materialize_rejects_linked_generated_folder(tmp_path: Path):
    scenario = _simple_scenario()
    agent_folder = tmp_path / "agent"
    topic_file = agent_folder / "topics" / "Topic.mcs.yml"
    topic_file.parent.mkdir(parents=True)
    topic_file.write_text("kind: AdaptiveDialog\n", encoding="utf-8")
    external_folder = tmp_path / "external"
    external_folder.mkdir()
    external_file = external_folder / "keep.mcs.yml"
    external_file.write_text("kind: EvaluationData\n", encoding="utf-8")
    generated_folder = (
        agent_folder
        / "evaluations"
        / "eval-driven-bereavement-leave-info"
    )
    generated_folder.parent.mkdir(parents=True)
    if sys.platform == "win32":
        result = subprocess.run(
            [
                "cmd",
                "/c",
                "mklink",
                "/J",
                str(generated_folder),
                str(external_folder),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            pytest.skip(f"directory junctions are unavailable: {result.stderr}")
    else:
        try:
            generated_folder.symlink_to(external_folder, target_is_directory=True)
        except OSError as exc:
            pytest.skip(f"directory links are unavailable: {exc}")

    with pytest.raises(
        ValueError,
        match="generated evaluation folder cannot be a link",
    ):
        eval_scenario.materialize_scenario(
            scenario,
            agent_folder,
            topic_file,
            tmp_path / "manifest.json",
        )

    assert external_file.exists()
