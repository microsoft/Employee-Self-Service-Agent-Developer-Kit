# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _ROOT / "solutions" / "ess-maker-skills"


def test_da_servicenow_connect_routes_to_prototype_skill() -> None:
    prompt = (
        _SOLUTION / ".github" / "prompts" / "connect.prompt.md"
    ).read_text(encoding="utf-8")
    router = (
        _SOLUTION / "src" / "skills" / "connect" / "SKILL.md"
    ).read_text(encoding="utf-8")
    normalized_prompt = " ".join(prompt.split())

    assert "src/skills/connect/SKILL.md" in prompt
    assert "Extension setup is not yet available" not in prompt
    assert "`authoring_ready: true`" in prompt
    assert "ignore" in prompt
    assert "`connect_ready`" in prompt
    assert "`activeAgent` slug" in prompt
    assert "`botId`" in prompt
    assert "Skip completed steps" in prompt
    assert "Waiting for maker input" in prompt
    assert "never require the maker to invoke" in prompt
    assert "Do not inspect `.local/connect/steps.md` before" in prompt
    assert "start with that skill's live `inspect` contract" in prompt
    assert "src/skills/connect/servicenow-da/SKILL.md" in router
    assert "any entry in `agents`" in router
    assert "`releaseLine: da`" in router
    assert "emit_capability.py connect --connector servicenow" in router
    assert "HRSD/ITSM" in router
    assert "explicit HRSD or ITSM product profile" in router
    assert "do not gate this invocation" in normalized_prompt
    assert "lists the live ESS HR/IT agents" in prompt


def test_global_gate_allows_connection_blocked_foundation() -> None:
    instructions = (
        _SOLUTION / ".github" / "copilot-instructions.md"
    ).read_text(encoding="utf-8")

    assert "`authoring_ready` equal to `true`" in instructions
    assert "This is the only readiness marker" in instructions
    assert "Ignore `connect_ready`" in instructions
    assert "let the invoked command resolve" in instructions
    assert "`/connect servicenow` is available" in instructions


def test_da_servicenow_skill_is_resumable_across_maker_questions() -> None:
    skill = (
        _SOLUTION
        / "src"
        / "skills"
        / "connect"
        / "servicenow-da"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    normalized = " ".join(skill.split())

    assert "Run `inspect` at the beginning of every invocation" in skill
    assert "Before every step, check its current live evidence" in skill
    assert "do not repeat its question or operation" in skill
    assert "Always ask the maker to confirm their current state" in normalized
    assert "cannot be verified by the available APIs" in normalized
    assert "never sufficient to skip the current confirmation" in normalized
    assert (
        "does not require the maker to invoke `/connect servicenow` again"
        in normalized
    )
    assert "Never interpret a repeated `/connect servicenow` invocation" in skill
    assert "If the host reports that the maker is unavailable" in skill
    assert "Do not select a choice" in skill
    assert "Use **Task completed** only after a passing Test pane result" in skill
    assert "record-parameter-sharing --status enabled" in skill
    assert "record-parameter-sharing --status not-exposed" in skill
    assert "Employee Self-Service (HR) -> ServiceNow HRSD" in skill
    assert "Employee Self-Service (IT) -> ServiceNow ITSM" in skill
    assert "python scripts/connect_servicenow_da.py list-agents" in skill
    assert "Do not change" in skill
    assert "`.local/config.json` or its `activeAgent`" in skill
    assert "customer custom topics" in normalized
    assert "profile.agentDisplayName" in skill
    assert "profile.testPrompt" in skill
