# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Public command-discovery contracts for Workday setup."""

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOLUTION = _REPO_ROOT / "solutions" / "ess-maker-skills"
_PROMPTS = _SOLUTION / ".github" / "prompts"


def _normalize(text: str) -> str:
    return " ".join(text.split())


def test_connect_workday_prompt_preselects_workday() -> None:
    prompt = (_PROMPTS / "connect-workday.prompt.md").read_text(
        encoding="utf-8"
    )
    normalized = _normalize(prompt)

    assert "Connect the active ESS HR agent to Workday" in prompt
    assert ".github/prompts/connect.prompt.md" in prompt
    assert "workday` supplied as the selected" in prompt
    assert "without asking which system to connect" in normalized


def test_menu_exposes_specific_and_generic_connect_commands() -> None:
    menu = (_PROMPTS / "menu.prompt.md").read_text(encoding="utf-8")

    assert "| `/connect-workday` | Connect the active ESS HR agent to Workday |" in menu
    assert "| `/connect` | Choose an available integration |" in menu


def test_repo_root_redirect_recognizes_connect_workday() -> None:
    instructions = (_REPO_ROOT / ".github" / "copilot-instructions.md").read_text(
        encoding="utf-8"
    )

    assert "- `/connect-workday`" in instructions


def test_readme_documents_da_scope_and_target_deployment() -> None:
    readme = (_SOLUTION / "README.md").read_text(encoding="utf-8")
    normalized = _normalize(readme)

    assert "this release supports the **ESS HR Agent**" in readme
    assert "ESS IT Agent is not supported" in readme
    assert "scripts/alm/README.md" in readme
    assert "signed-in end-to-end Workday scenario" in normalized


def test_connect_workday_bypasses_runtime_readiness_gate() -> None:
    instructions = (
        _SOLUTION / ".github" / "copilot-instructions.md"
    ).read_text(encoding="utf-8")
    normalized = _normalize(instructions)

    assert "typed `/connect` or `/connect-workday`" in normalized
    assert "even when runtime `connect_ready` is false" in normalized


def test_connect_workday_instruction_routes_to_architecture_aware_connect() -> None:
    instructions = (
        _SOLUTION / ".github" / "copilot-instructions.md"
    ).read_text(encoding="utf-8")
    normalized = _normalize(instructions)

    assert (
        "(`/connect workday` or `/connect-workday`) | "
        "`src/skills/connect/SKILL.md`"
    ) in normalized
    assert (
        "Provision/connect the Workday setup environment (`/connect workday`) "
        "| `src/skills/setup/SKILL.md`"
    ) not in normalized
