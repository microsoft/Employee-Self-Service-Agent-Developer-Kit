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


def test_folder_redirect_provides_manual_guidance_before_an_attempt() -> None:
    instructions = _instructions()
    normalized = " ".join(instructions.split())

    manual_steps = normalized.index("**Open the Maker Kit workspace manually:**")
    attempt_message = normalized.index("**Want me to try?**")
    attempt_choice = normalized.index('"title": "Attempt to open the Maker Kit"')
    manual_choice = normalized.index('"title": "I’ll open it manually"')
    open_workspace = normalized.index('code --new-window "<absolute Maker Kit path>"')
    dispatch_request = normalized.index(
        'code chat --reuse-window "<original request>"'
    )

    assert manual_steps < attempt_message < attempt_choice < manual_choice
    assert manual_choice < open_workspace < dispatch_request
    assert '"message": ""' in instructions
    assert '"title": "ADK Maker Kit Recovery"' in instructions
    assert '"description": "Choose how to continue"' in instructions
    assert '"title": "Attempt to open the Maker Kit"' in instructions
    assert '"title": "I’ll open it manually"' in instructions
    assert '"title": "Next step"' not in instructions
    assert "This chat will remain available" in normalized
    assert "This requires the new Maker Kit window to remain" in normalized
    assert "focused until the attempt finishes" in normalized
    assert "Do not switch to another VS Code window" in normalized
    assert "wait for the newly opened Maker Kit window to finish loading" in normalized
    assert "Do not run the two commands concurrently." in normalized
    assert "adding, removing, or rewriting any text" in normalized
    assert "Do not add guard text, setup instructions, or other framing" in normalized


def test_automatic_attempt_does_not_claim_delivery_without_confirmation() -> None:
    instructions = _instructions()
    normalized = " ".join(instructions.split())

    open_progress = normalized.index("Opening the Maker Kit workspace")
    focus_warning = normalized.index("Keep the new Maker Kit window focused")
    send_progress = normalized.index("Sending your prompt to a fresh Maker Kit chat")
    accepted = normalized.index(
        "VS Code accepted your prompt. Check the new Maker Kit window."
    )
    confirmation = normalized.index(
        '"description": "Did your prompt appear in a fresh Maker Kit chat?"'
    )

    assert open_progress < focus_warning < send_progress < accepted < confirmation
    assert "Your prompt was transferred" not in normalized
    assert "keep the current chat available" in normalized


def test_prompt_confirmation_supports_success_retry_and_manual_exit() -> None:
    instructions = _instructions()
    normalized = " ".join(instructions.split())

    confirmed = normalized.index('"title": "Yes, continue there"')
    retry = normalized.index('"title": "No, try again"')
    manual = normalized.index('"title": "No, let me handle it manually"')

    assert confirmed < retry < manual
    assert "repeat the complete attempt beginning with path validation" in normalized
    assert "Each retry requires the user's explicit selection" in normalized
    assert "Do not retry automatically." in normalized
    assert "Use the manual steps above." in normalized
    assert "Do not claim that the prompt appeared" in normalized
    assert "`File` → `Open Folder…`" in instructions
