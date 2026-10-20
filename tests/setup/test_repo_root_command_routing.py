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

    reason = normalized.index(
        "Your prompt needs the Maker Kit workspace so the correct prompts and skills"
    )
    confirmation = normalized.index("**Continue in a new Maker Kit chat?**")
    open_choice = normalized.index('"title": "Open the Maker Kit and continue"')
    manual_choice = normalized.index('"title": "Show manual steps instead"')
    open_workspace = normalized.index('code --new-window "<absolute Maker Kit path>"')
    dispatch_request = normalized.index(
        'code chat --reuse-window "<original request>"'
    )

    assert reason < confirmation < open_choice < manual_choice
    assert manual_choice < open_workspace < dispatch_request
    assert "first send this standalone message" in normalized
    assert '"message": ""' in instructions
    assert '"title": "ADK Maker Kit Recovery"' in instructions
    assert '"description": "Choose how to continue"' in instructions
    assert '"title": "Open the Maker Kit and continue"' in instructions
    assert '"title": "Show manual steps instead"' in instructions
    assert '"title": "Next step"' not in instructions
    assert "set a distinct field description for the inner prompt" in normalized
    assert "labeled options instead of a boolean prompt" in normalized
    assert "transfer your prompt unchanged" in normalized
    assert "wait for the newly opened Maker Kit window to finish loading" in normalized
    assert "Do not run the two commands concurrently." in normalized
    assert "adding, removing, or rewriting any text" in normalized
    assert "Do not add guard text, setup instructions, or other framing" in normalized
    assert "stop processing the request in the current chat" in normalized


def test_action_handoff_uses_informative_progress_and_completion_copy() -> None:
    instructions = _instructions()
    normalized = " ".join(instructions.split())

    open_progress = normalized.index("Opening the Maker Kit workspace")
    transfer_progress = normalized.index(
        "Transferring your prompt to a fresh Maker Kit chat"
    )
    completion = normalized.index(
        "Your prompt was transferred to a fresh chat in the Maker Kit window."
    )

    assert open_progress < transfer_progress < completion
    assert "Continue there." in normalized


def test_action_handoff_retains_a_manual_fallback() -> None:
    instructions = _instructions()
    normalized = " ".join(instructions.split())

    decline = normalized.index("declines, or skips the confirmation")
    failure = normalized.index("If path validation or either command fails")
    fallback = normalized.index("Fall back to the same manual guidance")
    fresh_chat = normalized.index(
        "After VS Code reopens, start a new Copilot chat and enter your prompt"
    )

    assert decline < failure < fallback < fresh_chat
    assert "do not claim that the request was transferred" in normalized
    assert "`File` → `Open Folder…`" in instructions
