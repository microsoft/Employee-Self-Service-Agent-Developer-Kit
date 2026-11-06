# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Planner hooks in DA-GA setup and the Copilot CLI setup entry point."""

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _REPO_ROOT / "solutions" / "ess-maker-skills"


def _normalized(relative: str) -> str:
    return " ".join((_SOLUTION / relative).read_text(encoding="utf-8").split())


def test_setup_targets_the_saved_plan_environment() -> None:
    text = _normalized("src/skills/foundation-setup/SKILL.md")

    assert "python scripts/planner/cli.py setup-status" in text
    assert "non-empty `environment.environmentId`" in text
    assert "Never create or select a different environment for that plan" in text


def test_setup_offers_planning_only_without_a_saved_plan() -> None:
    text = _normalized("src/skills/foundation-setup/SKILL.md")
    choice = text.split("- **Plan my ESS rollout first** —", 1)[1].split(
        "- **Help me decide**", 1
    )[0]

    assert "only when the plan check found no saved plan" in choice
    assert "end this setup request" in choice
    assert "src/skills/planner/SKILL.md" in choice
    assert '"Plan my ESS rollout first" when `/setup` offered it' in _normalized(
        ".github/prompts/planner.prompt.md"
    )


def test_cli_setup_skill_follows_the_da_setup_prompt() -> None:
    text = _normalized(".github/skills/setup/SKILL.md")

    assert "Read `.github/prompts/setup.prompt.md`" in text
    assert "src/skills/foundation-setup/SKILL.md" in text
    assert "Do not route to Dataverse foundation or onboarding playbooks" in text
    assert "src/skills/onboarding" not in text
    assert "It never creates a Power Platform environment" in text
    assert (_SOLUTION / ".github" / "prompts" / "setup.prompt.md").is_file()
