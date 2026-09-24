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

    assert "src/skills/connect/SKILL.md" in prompt
    assert "Extension setup is not yet available" not in prompt
    assert "Do not require aggregate `connect_ready`" in prompt
    assert all(
        step in prompt
        for step in ("SETUP-01", "SETUP-02.1", "SETUP-03", "SETUP-04", "SETUP-07")
    )
    assert "`activeAgent` slug" in prompt
    assert "`botId`" in prompt
    assert "src/skills/connect/servicenow-da/SKILL.md" in router
    assert "releaseLine" in router


def test_global_gate_allows_connection_blocked_foundation() -> None:
    instructions = (
        _SOLUTION / ".github" / "copilot-instructions.md"
    ).read_text(encoding="utf-8")

    assert "Do not require aggregate `connect_ready`" in instructions
    assert all(
        step in instructions
        for step in ("SETUP-01", "SETUP-02.1", "SETUP-03", "SETUP-04", "SETUP-07")
    )
    assert "read `.local/setup/config.json` and `.local/config.json`" in instructions
    assert "`activeAgent`" in instructions
    assert "`botId`" in instructions
    assert "`/connect servicenow` is available" in instructions
