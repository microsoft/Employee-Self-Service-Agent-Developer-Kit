# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Repository-root routing contracts for the ESS Maker Kit."""

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_INSTRUCTIONS = _REPO_ROOT / ".github" / "copilot-instructions.md"


def _instructions() -> str:
    return _INSTRUCTIONS.read_text(encoding="utf-8")


def test_active_maker_workspace_takes_precedence_over_nested_discovery() -> None:
    instructions = _instructions()

    direct_check = instructions.index("first check whether both of these direct")
    direct_outcome = instructions.index(
        "the Maker Kit is already the active\nworkspace"
    )
    nested_check = instructions.index(
        "Otherwise, check whether both of these nested"
    )

    assert direct_check < direct_outcome < nested_check
    assert "Do not apply the folder-selection guidance in this file" in instructions
    assert "- `.github/prompts/` contains at least one `*.prompt.md` file." in instructions
    assert "- `src/skills/` exists." in instructions


def test_folder_redirect_requires_a_fresh_chat() -> None:
    instructions = _instructions()
    normalized = " ".join(instructions.split())

    assert (
        "After VS Code reopens, start a new Copilot chat and enter the request"
        in normalized
    )
