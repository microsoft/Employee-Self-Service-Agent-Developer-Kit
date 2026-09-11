# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Structural guards for the non-DA-GA setup retirement."""

from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _REPO_ROOT / "solutions" / "ess-maker-skills"
_FOUNDATION = (
    _SOLUTION / "src" / "skills" / "foundation-setup" / "SKILL.md"
)
_PROMPTS = _SOLUTION / ".github" / "prompts"
_INSTRUCTIONS = _SOLUTION / ".github" / "copilot-instructions.md"


def test_setup_stops_at_explicit_unavailable_surface() -> None:
    foundation = _FOUNDATION.read_text(encoding="utf-8")
    setup_prompt = (_PROMPTS / "setup.prompt.md").read_text(
        encoding="utf-8"
    )

    assert "There is no supported foundation setup path" in foundation
    assert "Setup is not available in this build" in foundation
    assert "Do not run setup" in foundation
    assert "src/skills/foundation-setup/SKILL.md" in setup_prompt
    assert "src/skills/onboarding" not in setup_prompt


def test_retired_setup_implementation_is_absent() -> None:
    retired_paths = (
        "scripts/setup_state.py",
        "scripts/install_ess_agent.py",
        "scripts/ess_connection_binding.py",
        "scripts/preferred_solution.py",
        "scripts/backup_template_configs.py",
        "scripts/restore_template_configs.py",
        "src/reference/ess-agent-installation/config.json",
        "src/reference/solution-catalog.md",
        "src/skills/onboarding/SKILL.md",
        "src/skills/foundation-setup/install-starters.md",
        "src/skills/backup-template-configs/SKILL.md",
        "src/skills/restore-template-configs/SKILL.md",
    )

    for path in retired_paths:
        assert not (_SOLUTION / path).exists(), path


def test_retired_commands_keep_explicit_public_stubs() -> None:
    for name in (
        "backup-template-configs.prompt.md",
        "restore-template-configs.prompt.md",
    ):
        prompt = (_PROMPTS / name).read_text(encoding="utf-8")
        assert "no longer supported" in prompt, name
        assert "retired" in prompt, name
        assert "SKILL.md" not in prompt, name
        assert "scripts/" not in prompt, name


def test_global_routing_has_no_deleted_skill_references() -> None:
    instructions = _INSTRUCTIONS.read_text(encoding="utf-8")

    assert "setup is not available in this build" in instructions
    assert "src/skills/backup-template-configs" not in instructions
    assert "src/skills/restore-template-configs" not in instructions


def test_flightcheck_discovery_has_no_product_catalog_dependency() -> None:
    discover = (
        _SOLUTION / "scripts" / "discover.py"
    ).read_text(encoding="utf-8")

    assert "--url" in discover
    assert "SELECTED_AGENT_JSON:" in discover
    assert "install_ess_agent" not in discover
    assert "availableInstallations" not in discover
