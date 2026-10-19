# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Skill contracts for the maker-facing Planner orchestration."""

import json
import re
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2] / "solutions" / "ess-maker-skills" / "src" / "skills"


def _text(name):
    return (SKILLS / name).read_text(encoding="utf-8")


def test_plan_orientation_precedes_questions_and_permissions():
    text = _text("planner/SKILL.md")
    assert text.index("## Orient the maker") < text.index("## Gate")
    for phrase in ("A plan is your ESS rollout checklist", "not just", "resume", "share and activate", "pending"):
        assert phrase in text
    assert "tool approval" in _text("planner/sync.md").lower() or "Host trust" in text


def test_scenario_and_system_choices_explain_consequences_and_deferral():
    text = _text("planner/interview.md")
    forms = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", text, re.S)]
    assert len(forms) == 2
    for form in forms:
        question = form[0]
        assert question["multiSelect"] is True
        assert question["allowFreeformInput"] is True
        assert any(option["label"] == "Not sure yet" for option in question["options"])
        assert all(len(option["description"]) > 50 for option in question["options"])
    assert "add-system --area <scenario-id> --pending" in text
    assert "do not substitute SharePoint" in text
    assert "already-clear choices instead of reconfirming them" in text


def test_planner_evaluations_generate_in_flow_with_existing_safety_gates():
    text = _text("planner/evaluate.md")
    assert "--group evaluationCase" in text
    for path in ("topics/create-eval-driven/SKILL.md", "evaluations/create/SKILL.md"):
        assert f"src/skills/{path}" in text
        assert (SKILLS / path).is_file()
    assert "push approval" in " ".join(text.split())
    assert "not a test run" in _text("planner/SKILL.md")
    assert "Generate only missing coverage" in text
    handoff = _text("evaluations/create/SKILL.md")
    assert "Planner handoff: reuse the supplied scope" in handoff
    assert "Do not ask the maker to invoke `/evaluate` separately" in handoff


def test_shared_completion_requires_state_output_readback_and_explicit_activation():
    text = _text("planner/capture.md")
    assert "state **and the expected output" in text
    assert "Never publish or activate" in text
    assert "no partial-output write endpoint" in text
    assert "set_project_plan_task_state" in text
    assert "preserve the original ETag" in text
