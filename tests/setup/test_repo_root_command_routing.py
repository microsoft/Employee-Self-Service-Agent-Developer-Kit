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
    normalized = " ".join(instructions.split())

    direct_check = instructions.index("first check whether both of these direct")
    direct_outcome = instructions.index("the Maker Kit is already the active")
    nested_check = instructions.index(
        "Otherwise, check whether both of these nested"
    )

    assert direct_check < direct_outcome < nested_check
    assert "Do not apply the folder-selection guidance in this file" in normalized
    assert "- `.github/prompts/` contains at least one `*.prompt.md` file." in instructions
    assert "- `src/skills/` exists." in instructions


def test_folder_redirect_offers_a_confirmed_action_handoff() -> None:
    instructions = _instructions()
    normalized = " ".join(instructions.split())

    offer = normalized.index("Offer **Open the Maker Kit in a new chat**")
    confirmation = normalized.index("ask for explicit confirmation")
    open_workspace = normalized.index('code --new-window "<absolute Maker Kit path>"')
    dispatch_request = normalized.index(
        'code chat --reuse-window "<original request>"'
    )

    assert offer < confirmation < open_workspace < dispatch_request
    assert "wait for the newly opened Maker Kit window to finish loading" in normalized
    assert "Do not run the two commands concurrently." in normalized
    assert "adding, removing, or rewriting any text" in normalized
    assert "Do not add guard text, setup instructions, or other framing" in normalized
    assert "stop processing the request in the current chat" in normalized


def test_action_handoff_retains_a_manual_fallback() -> None:
    instructions = _instructions()
    normalized = " ".join(instructions.split())

    decline = normalized.index("If the user declines")
    failure = normalized.index("If path validation or either command fails")
    fallback = normalized.index("Fall back to this manual guidance")
    fresh_chat = normalized.index(
        "After VS Code reopens, start a new Copilot chat and enter the request"
    )

    assert decline < failure < fallback < fresh_chat
    assert "do not claim that the request was transferred" in normalized
    assert "`File` → `Open Folder…`" in instructions
