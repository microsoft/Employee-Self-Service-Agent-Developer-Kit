from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
SKILL = (
    ROOT / "solutions" / "ess-maker-skills" / "src" / "skills" / "topics"
    / "import-oss-draft"
)
SPEC = importlib.util.spec_from_file_location(
    "oss_import_draft_plan", SKILL / "scripts" / "plan_import.py"
)
assert SPEC is not None and SPEC.loader is not None
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)


def test_actual_samples_are_planned_without_enabling_apply():
    plan = planner.build_plan(
        ROOT / "samples" / "WorkdayDeclarativeAgentGA", select_all=True
    )
    assert plan["selectedScenarioCount"] == plan["availableScenarioCount"] == 16
    assert plan["sharedTemplateCount"] == 22
    assert plan["networkRequests"] == plan["liveWrites"] == 0
    assert plan["applyAllowed"] is False
    assert len(plan["sharedTemplateKeys"]) == len(set(plan["sharedTemplateKeys"]))
    assert all(len(topic["sha256"]) == 64 for topic in plan["topics"])


def test_explicit_subset_does_not_add_other_scenarios():
    plan = planner.build_plan(
        ROOT / "samples" / "WorkdayDeclarativeAgentGA", ["WorkdayGetEducation"]
    )
    assert [topic["scenario"] for topic in plan["topics"]] == ["WorkdayGetEducation"]
    assert plan["sharedTemplateCount"] == 22
    assert plan["applyAllowed"] is False


@pytest.mark.parametrize("selection", [
    ["missing-topic"], ["WorkdayGetEducation", "WorkdayGetEducation"],
])
def test_unknown_or_duplicate_selection_fails(selection):
    with pytest.raises(planner.PlanError):
        planner.build_plan(ROOT / "samples" / "WorkdayDeclarativeAgentGA", selection)


def test_nested_else_actions_are_inventoried():
    document = yaml.safe_load("""
beginDialog:
  actions:
    - kind: ConditionGroup
      elseActions:
        - kind: AnswerQuestionWithAI
""")
    assert [node["kind"] for node in planner.action_nodes(document)] == [
        "ConditionGroup", "AnswerQuestionWithAI"
    ]


def test_unapproved_ai_action_is_reported(tmp_path):
    path = tmp_path / "topic.yaml"
    path.write_text(
        "kind: AdaptiveDialog\nbeginDialog:\n  actions:\n"
        "    - kind: ConditionGroup\n      elseActions:\n"
        "        - kind: AnswerQuestionWithAI\n",
        encoding="utf-8",
    )
    _, info = planner.read_dialog(path, tmp_path.resolve())
    assert info["unapprovedActionKinds"] == ["AnswerQuestionWithAI"]


def test_dialog_path_outside_samples_root_is_rejected(tmp_path):
    root = tmp_path / "samples"
    root.mkdir()
    outside = tmp_path / "topic.yaml"
    outside.write_text("kind: AdaptiveDialog\n", encoding="utf-8")
    with pytest.raises(planner.PlanError, match="escapes"):
        planner.read_dialog(outside, root.resolve())


def test_unknown_root_fails_instead_of_falling_back(tmp_path):
    with pytest.raises(planner.PlanError, match="No Employee/Manager"):
        planner.build_plan(tmp_path, select_all=True)


def test_skill_is_an_explicit_draft_with_no_registered_command():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    metadata = yaml.safe_load(text.split("---", 2)[1])
    assert metadata["name"] == "workday-oss-import-draft"
    assert metadata["description"]
    assert "does not implement a create-topic client" in " ".join(text.split())
    assert "AnswerQuestionWithAI" in text
    assert not (
        ROOT / "solutions" / "ess-maker-skills" / ".github" / "prompts"
        / "import-oss.prompt.md"
    ).exists()
