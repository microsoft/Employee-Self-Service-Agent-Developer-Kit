# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Planner hooks in DA-GA setup, setup routing, and the Copilot CLI setup entry."""

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _REPO_ROOT / "solutions" / "ess-maker-skills"


def _normalized(relative: str) -> str:
    return " ".join((_SOLUTION / relative).read_text(encoding="utf-8").split())


def _routes() -> str:
    return _normalized(".github/copilot-instructions.md").split(
        "### Setup gate for all other requests", 1
    )[0]


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


def test_routing_runs_silently_in_one_pass() -> None:
    routes = _routes()

    assert "**silently, in one pass**" in routes
    assert "do not narrate them" in routes


def test_only_direct_setup_invocations_route_to_setup() -> None:
    routes = _routes()

    assert "explicitly asked to run setup" not in _normalized(
        ".github/copilot-instructions.md"
    )
    assert "gave the direct setup invocation `run setup`" in routes
    assert (
        '"set up ESS for the first time", "deploy ESS", "where do I start", '
        '"how do I get started" — is not a setup route; it follows the setup '
        "gate below"
    ) in routes
    assert 'Do NOT use for open-ended "set up ESS"' in _normalized(
        ".github/skills/setup/SKILL.md"
    )


def test_assigned_setup_task_enters_setup_from_natural_language() -> None:
    routes = _routes()
    foundation = _normalized("src/skills/foundation-setup/SKILL.md").split(
        "## Setup state sources", 1
    )[0]

    assert 'If the user says "start setup" in natural language' in _normalized(
        "src/skills/planner/mytasks.md"
    )
    assert (
        'a natural-language request to start it ("start setup") enters setup '
        "the same way"
    ) in routes
    assert "treat the request exactly like `/setup`" in foundation
    assert "never ask the maker to retype it as a command" in foundation
    assert "so Planner can return to that task afterward" in foundation
    assert "A plan assignment is not proof of access" in foundation
