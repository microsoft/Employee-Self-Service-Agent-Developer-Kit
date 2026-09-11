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
_WORKDAY_SETUP = _SOLUTION / "src" / "skills" / "setup" / "SKILL.md"


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
        "src/reference/ess-agent-installation/config.json",
        "src/reference/solution-catalog.md",
        "src/skills/onboarding/SKILL.md",
        "src/skills/foundation-setup/install-starters.md",
    )

    for path in retired_paths:
        assert not (_SOLUTION / path).exists(), path


def test_hybrid_workday_config_commands_remain_bounded() -> None:
    surfaces = {
        "backup-template-configs.prompt.md": (
            "scripts/backup_template_configs.py",
            "src/skills/backup-template-configs/SKILL.md",
        ),
        "restore-template-configs.prompt.md": (
            "scripts/restore_template_configs.py",
            "src/skills/restore-template-configs/SKILL.md",
        ),
    }

    for name, (script_path, skill_path) in surfaces.items():
        prompt = (_PROMPTS / name).read_text(encoding="utf-8")
        skill = (_SOLUTION / skill_path).read_text(encoding="utf-8")
        assert (_SOLUTION / script_path).is_file(), name
        assert (_SOLUTION / skill_path).is_file(), name
        assert skill_path in prompt, name
        assert "hybrid Workday" in prompt, name
        assert "hybrid Workday" in skill, name
        assert "preferred solution" in skill, name


def test_global_routing_preserves_only_hybrid_workday_config_tools() -> None:
    instructions = _INSTRUCTIONS.read_text(encoding="utf-8")

    assert "setup is not available in this build" in instructions
    assert "src/skills/backup-template-configs/SKILL.md" in instructions
    assert "src/skills/restore-template-configs/SKILL.md" in instructions


def test_workday_setup_stops_at_unimplemented_hybrid_boundary() -> None:
    text = _WORKDAY_SETUP.read_text(encoding="utf-8")

    assert "Hybrid Workday extension setup is not available" in text
    assert "Do not run the retained Workday setup playbooks" in text
    assert "install_ess_agent.py" not in text
    assert "ess_connection_binding.py" not in text
    assert "preferred_solution.py" not in text


def test_flightcheck_discovery_has_no_product_catalog_dependency() -> None:
    discover = (
        _SOLUTION / "scripts" / "discover.py"
    ).read_text(encoding="utf-8")

    assert "--url" in discover
    assert "SELECTED_AGENT_JSON:" in discover
    assert "install_ess_agent" not in discover
    assert "availableInstallations" not in discover
