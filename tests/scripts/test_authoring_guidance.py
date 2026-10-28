# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Focused ownership and retirement checks for authoring guidance."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOLUTION = ROOT / "solutions" / "ess-maker-skills"


def _read(relative: str) -> str:
    return (SOLUTION / relative).read_text(encoding="utf-8")


def test_create_and_update_prompts_route_to_normal_topic_owners():
    create = _read(".github/prompts/create.prompt.md")
    update = _read(".github/prompts/update.prompt.md")

    assert "src/skills/topics/create/SKILL.md" in create
    assert "src/skills/topics/update/SKILL.md" in update
    assert "crafted-response" not in create
    assert "crafted-response" not in update
    assert "scenario/materializer" in create
    assert "eval-driven save/materialization" in update


def test_topic_owners_use_yaml_adapters_and_separate_instruction_approval():
    create = _read("src/skills/topics/create/SKILL.md")
    update = _read("src/skills/topics/update/SKILL.md")

    assert "topic_authoring.py create --draft" in create
    assert "topic_authoring.py update --draft" in update
    assert "agent_instructions.py update --draft" in create
    assert "agent_instructions.py update --draft" in update
    assert "separate approvals" in create
    assert "separate topic and instruction approvals" in update
    assert "Do not activate or publish" in create
    assert "Do not activate or publish" in update
    assert "conversation acceptance as pending" in create
    assert "conversation acceptance as pending" in update


def test_eval_driven_aliases_are_thin_and_scenario_lifecycle_is_retired():
    create = _read("src/skills/topics/create-eval-driven/SKILL.md")
    update = _read("src/skills/topics/update-eval-driven/SKILL.md")

    assert "provisional compatibility alias" in create
    assert "provisional compatibility alias" in update
    assert "src/skills/topics/create/SKILL.md" in create
    assert "src/skills/topics/update/SKILL.md" in update
    assert "eval_scenario.py" not in create + update
    assert not (SOLUTION / "scripts" / "eval_scenario.py").exists()
    assert not (
        SOLUTION
        / "src"
        / "skills"
        / "topics"
        / "create-eval-driven"
        / "eval-scenario.schema.json"
    ).exists()


def test_flow_and_retired_workday_routes_are_notice_only():
    create = _read("src/skills/workflows/create/SKILL.md")
    update = _read("src/skills/workflows/update/SKILL.md")
    workday = _read("src/skills/setup/workday/create-new-topic.md")

    for guidance in (create, update):
        assert "outside ADK" in guidance
        assert "Do not" in guidance
        assert "runtime testing" in guidance
    assert "does not author custom topics or template configurations" in workday
    assert "src/skills/setup/workday-da/" in workday


def test_evaluation_handoff_uses_remote_context_without_overwriting_drafts():
    dispatcher = _read("src/skills/evaluations/dispatcher/SKILL.md")
    create = _read("src/skills/evaluations/create/SKILL.md")

    assert "topic_authoring.py list" in dispatcher
    assert "never overwrite the working topic drafts" in dispatcher
    assert "current remote inventory/content" in create
    assert "without overwriting local drafts" in create


def test_crafted_response_owner_is_removed_and_global_routing_is_current():
    instructions = _read(".github/copilot-instructions.md")

    assert not (SOLUTION / "src/skills/topics/crafted-response/SKILL.md").exists()
    assert "src/skills/topics/crafted-response/SKILL.md" not in instructions
    assert "src/skills/topics/create/SKILL.md" in instructions
    assert "src/skills/topics/update/SKILL.md" in instructions
