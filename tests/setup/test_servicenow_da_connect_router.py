# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _ROOT / "solutions" / "ess-maker-skills"


def test_da_servicenow_connect_routes_to_hrsd_lifecycle() -> None:
    prompt = (
        _SOLUTION / ".github" / "prompts" / "connect.prompt.md"
    ).read_text(encoding="utf-8")
    router = (
        _SOLUTION / "src" / "skills" / "connect" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "src/skills/connect/SKILL.md" in prompt
    assert "Extension setup is not yet available" not in prompt
    assert "`authoring_ready: true`" in prompt
    assert "Ignore" in prompt
    assert "`connect_ready`" in prompt
    assert "`activeAgent` slug" in prompt
    assert "`botId`" in prompt
    assert "Skip completed steps" in prompt
    assert "Waiting for maker input" in prompt
    assert "never require the maker to invoke" in prompt
    assert "Do not inspect `.local/connect/steps.md` before" in prompt
    assert "a DA ServiceNow route starts\nwith its provider lifecycle" in prompt
    assert "src/skills/connect/servicenow-da-hrsd/SKILL.md" in router
    assert "servicenow-da-hrsd/agents/<agent-slug>/lifecycle.json" in router
    assert "releaseLine" in router
    assert "emit_capability.py connect --connector servicenow" in router

    interactive_router = (
        _SOLUTION / "src" / "skills" / "connect" / "step1.md"
    ).read_text(encoding="utf-8")
    dispatch = interactive_router.index(
        "src/skills/connect/servicenow-da-hrsd/SKILL.md"
    )
    legacy_read = interactive_router.index(
        "Check if `.local/connect/servicenow/steps.md` exists."
    )
    assert dispatch < legacy_read
    assert 'releaseLine: "da"' in interactive_router
    assert "gptagent_copilotforemployeeselfservicehr" in interactive_router
    assert "do not inspect or create `.local/connect/servicenow/` state" in (
        interactive_router
    )


def test_global_gate_allows_connection_blocked_foundation() -> None:
    instructions = (
        _SOLUTION / ".github" / "copilot-instructions.md"
    ).read_text(encoding="utf-8")

    assert "`authoring_ready` equal to `true`" in instructions
    assert "This is the only readiness marker" in instructions
    assert "Ignore `connect_ready`" in instructions
    assert "let the invoked command resolve" in instructions
    assert "`/connect servicenow` is available" in instructions


def test_da_servicenow_skill_uses_shared_lifecycle_and_maker_actions() -> None:
    skill = (
        _SOLUTION
        / "src"
        / "skills"
        / "connect"
        / "servicenow-da-hrsd"
        / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "connect/shared/lifecycle-runner.md" in skill
    assert 'PROVIDER = "servicenow-da-hrsd"' in skill
    assert "topic mutation and publish require" in skill

    actions = (
        _SOLUTION
        / "src"
        / "skills"
        / "connect"
        / "servicenow-da-hrsd"
        / "actions"
    )
    agent = (actions / "connect-agent.md").read_text(encoding="utf-8")
    parameter = (actions / "configure-parameter-sharing.md").read_text(
        encoding="utf-8"
    )
    test = (actions / "test-connection.md").read_text(encoding="utf-8")
    topics = (actions / "prepare-topics.md").read_text(encoding="utf-8")
    assert "record-agent-connection" in agent
    assert "ACTION_RESULT = \"cancelled\"" in agent
    assert "record-parameter-sharing --status enabled" in parameter
    assert "record-parameter-sharing --status not-exposed" in parameter
    assert 'ACTION_RESULT = "recorded"' in test
    assert "safely rolled-back update is still a failed action" in topics
    assert "committed" in topics
    assert "already-active" in topics
    assert "vscode_askQuestions" in topics
    assert "while the\n  question is pending" in topics
    assert "Absence of\n  an answer is not cancellation" in topics
    assert "explicitly selects\n  **Not now**" in topics
