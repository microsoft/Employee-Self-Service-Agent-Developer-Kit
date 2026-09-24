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
    assert "src/skills/connect/servicenow-da/SKILL.md" in router
    assert "releaseLine" in router
