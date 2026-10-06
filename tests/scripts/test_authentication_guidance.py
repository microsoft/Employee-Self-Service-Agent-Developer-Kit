# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Contract tests for first-run authentication guidance."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_README = REPO_ROOT / "setup" / "README.md"
MAKER_README = REPO_ROOT / "solutions" / "ess-maker-skills" / "README.md"
WINDOWS_INSTALLER = REPO_ROOT / "setup" / "Install-EssAdk.ps1"
MAC_INSTALLER = REPO_ROOT / "setup" / "install-ess-adk.sh"
WALKTHROUGH_ROOT = (
    REPO_ROOT / "tools" / "ess-maker-profile" / "extension" / "walkthrough"
)


def test_setup_readme_distinguishes_authentication_boundaries() -> None:
    text = SETUP_README.read_text(encoding="utf-8")

    assert "## Authentication prompts" in text
    assert "**GitHub Copilot sign-in**" in text
    assert "**Power Platform sign-in**" in text
    assert "does not grant access to Power Platform" in text
    assert "Microsoft work account that can access the target Power Platform" in text


def test_setup_readme_preserves_flightcheck_only_exception() -> None:
    text = SETUP_README.read_text(encoding="utf-8")

    assert (
        "**FlightCheck-only mode does not require VS Code, GitHub, or GitHub Copilot.**"
        in text
    )
    assert "It still opens the Microsoft sign-in required" in text


def test_maker_readme_links_to_detailed_authentication_guidance() -> None:
    text = MAKER_README.read_text(encoding="utf-8")

    assert "**Accounts used during setup:**" in text
    assert "GitHub Copilot authentication does not grant Power Platform access" in text
    assert "../../setup/README.md#authentication-prompts" in text


def test_installers_use_matching_purpose_specific_guidance() -> None:
    windows = WINDOWS_INSTALLER.read_text(encoding="utf-8")
    mac = MAC_INSTALLER.read_text(encoding="utf-8")
    expected = (
        "When VS Code asks you to sign in to GitHub Copilot, use the GitHub account "
        "that has your Copilot access. This enables Copilot Chat, where you run "
        "/setup."
    )
    work_account = (
        "Microsoft work account that can access the target Power Platform "
        "environment and agent. GitHub sign-in does not grant Power Platform access."
    )

    assert expected in windows
    assert expected in mac
    assert work_account in windows
    assert work_account in mac
    assert windows.count("Write-AuthenticationGuidance") == 2
    assert mac.count("print_authentication_guidance") == 2


def test_first_run_walkthrough_names_the_power_platform_account() -> None:
    files = (
        "connect.md",
        "getting-started.md",
        "introduction.md",
        "overview.md",
    )

    for name in files:
        text = (WALKTHROUGH_ROOT / name).read_text(encoding="utf-8")
        normalized = " ".join(text.split())
        assert "Microsoft work account" in normalized, name
        assert "GitHub Copilot sign-in" in normalized, name
