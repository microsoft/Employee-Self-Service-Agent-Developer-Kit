# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Regression tests for the one-shot installer's auto-/setup launch behavior.

PR #144 changed the final step of `setup/Install-EssAdk.ps1` (Windows) and
`setup/install-ess-adk.sh` (macOS) from "open VS Code at the workspace" to
"open VS Code at the workspace AND submit `/setup` in Copilot Chat" using the
`code chat <prompt>` CLI subcommand shipped in VS Code 1.102 (June 2025).

The behavioral guarantees we want to protect against accidental regression are:

  1. The launcher invokes `code chat /setup` (not just `code <workspace>`).
  2. The invocation runs from inside the kit workspace directory, because
     `code chat` opens the chat panel in *whatever workspace VS Code resolves
     from cwd* — if we don't cd into the workspace first the chat opens in
     the wrong (or no) workspace and `/setup` either fails or runs against
     the wrong folder.
  3. There is a fallback path: when `code chat` exits non-zero (e.g. an
     older VS Code that predates the subcommand), we still open the
     workspace and print manual `/setup` instructions so the install does
     not silently leave the user with no VS Code window.
  4. The workspace's `.vscode/settings.json` suppresses the startup editor
     so the Welcome tab does not sit in front of the chat prompt on
     subsequent opens (`workbench.startupEditor: "none"`).

These tests are static-text assertions: they read the installer scripts as
text and assert the key patterns are present. They deliberately do not spawn
the installers or stub `code` on PATH (the installers run network installs of
Homebrew / Python / git / VS Code / pip deps — out of scope for unit tests,
and the auto-launch step was already validated by hand on a freshly
reinstalled VS Code per the PR conversation). The goal here is to catch a
later refactor that removes or breaks any of (1)-(4) above.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PS1_PATH = REPO_ROOT / "setup" / "Install-EssAdk.ps1"
BASH_PATH = REPO_ROOT / "setup" / "install-ess-adk.sh"
README_PATH = REPO_ROOT / "setup" / "README.md"
WORKSPACE_SETTINGS_PATH = (
    REPO_ROOT / "solutions" / "ess-maker-skills" / ".vscode" / "settings.json"
)


@pytest.fixture(scope="module")
def ps1_text() -> str:
    return PS1_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ps1_launch_section(ps1_text: str) -> str:
    """The PowerShell installer's '# 7. Launch' section as a single string.

    Slicing to just this section keeps the assertions tight: a coincidental
    'code chat' string elsewhere in the file (e.g. a banner or comment in an
    unrelated section) cannot satisfy these tests.
    """
    match = re.search(
        r"# 7\. Launch\s*\r?\n.*?(?=\r?\n# -+\r?\n# \d+\.|\r?\nWrite-Host\s+\"`nDone\.)",
        ps1_text,
        flags=re.DOTALL,
    )
    assert match, "could not locate '# 7. Launch' section in Install-EssAdk.ps1"
    return match.group(0)


@pytest.fixture(scope="module")
def bash_text() -> str:
    return BASH_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def bash_launch_section(bash_text: str) -> str:
    """The Bash installer's '# 8. Launch ...' section as a single string."""
    match = re.search(
        r"# 8\. Launch VS Code.*?(?=\r?\necho \"\"\r?\necho -e \"\$\{GREEN\}=== ESS Maker Kit ready)",
        bash_text,
        flags=re.DOTALL,
    )
    assert match, "could not locate '# 8. Launch VS Code' section in install-ess-adk.sh"
    return match.group(0)


# ---------------------------------------------------------------------------
# PowerShell installer (Install-EssAdk.ps1)
# ---------------------------------------------------------------------------


class TestPowerShellInstallerAutoLaunch:
    def test_launch_section_invokes_code_chat_with_setup_prompt(
        self, ps1_launch_section: str
    ) -> None:
        """Guarantee (1): the launcher calls `code chat /setup`.

        Matches `& $code.Source chat '/setup'` (or `"/setup"`), allowing the
        wrapper to be `Invoke-Native` or any other call style. Without this
        invocation we'd be back to just opening VS Code without firing /setup.
        """
        assert re.search(
            r"\$code\.Source\s+chat\s+['\"]/setup['\"]",
            ps1_launch_section,
        ), (
            "PowerShell installer no longer invokes `code chat /setup` in the "
            "launch section — PR #144's auto-/setup behavior is broken."
        )

    def test_launch_section_pushes_into_workspace_before_chat(
        self, ps1_launch_section: str
    ) -> None:
        """Guarantee (2): the chat call runs from inside $workspace.

        `code chat` resolves the workspace from cwd, so the chat invocation
        must be preceded by `Push-Location $workspace` (and balanced by a
        `Pop-Location`). If somebody refactors to `& $code chat /setup`
        without the cd, the chat panel will open in whatever directory the
        installer was launched from — typically the user's home dir or a
        bootstrap temp dir — and /setup either fails or runs against the
        wrong workspace.

        The launch section may have multiple Push-Location / Pop-Location
        blocks (e.g. one for the stock-VS Code path and one for the
        maker-profile path). The chat invocation must be sandwiched
        between SOME Push-Location $workspace and a following Pop-Location.
        """
        chat_match = re.search(
            r"\$code\.Source\s+chat\s+['\"]/setup['\"]", ps1_launch_section
        )
        assert chat_match, "no `code chat /setup` invocation found in launch section"

        # Find the nearest preceding Push-Location $workspace.
        push_positions = [
            m.start()
            for m in re.finditer(
                r"^\s*Push-Location\s+\$workspace",
                ps1_launch_section,
                flags=re.MULTILINE,
            )
            if m.start() < chat_match.start()
        ]
        assert push_positions, (
            "`code chat /setup` is not preceded by a `Push-Location $workspace` "
            "in its branch — the chat will open in the wrong directory"
        )

        # Find the nearest following Pop-Location.
        pop_positions = [
            m.start()
            for m in re.finditer(
                r"^\s*\}?\s*finally\s*\{\s*Pop-Location|^\s*Pop-Location",
                ps1_launch_section,
                flags=re.MULTILINE,
            )
            if m.start() > chat_match.start()
        ]
        assert pop_positions, (
            "`code chat /setup` is not followed by a `Pop-Location` in its branch"
        )

    def test_launch_section_falls_back_when_code_chat_fails(
        self, ps1_launch_section: str
    ) -> None:
        """Guarantee (3): non-zero exit from `code chat` triggers a fallback.

        The fallback must (a) still open VS Code at the workspace with
        `Start-Process` and (b) tell the user to run /setup manually. Without
        this branch, an older VS Code that doesn't understand the `chat`
        subcommand would leave the user with no window and no instructions.
        """
        assert re.search(r"\$LASTEXITCODE", ps1_launch_section) or re.search(
            r"\$chatExit", ps1_launch_section
        ), "launch section must capture and check the exit code of `code chat`"
        assert re.search(
            r"Start-Process\s+-FilePath\s+\$code\.Source\s+-ArgumentList\s+@\(\$workspace\)",
            ps1_launch_section,
        ), (
            "fallback branch must open VS Code at the workspace via "
            "Start-Process when `code chat` fails"
        )
        assert re.search(
            r"run\s+/setup\s+manually|open Copilot Chat.*run /setup",
            ps1_launch_section,
            flags=re.IGNORECASE,
        ), (
            "fallback branch must instruct the user how to run /setup "
            "manually (older-VS-Code escape hatch)"
        )

    def test_skiplaunch_flag_still_short_circuits_the_launch_block(
        self, ps1_launch_section: str
    ) -> None:
        """The -SkipLaunch flag must continue to bypass auto-/setup.

        CI / unattended re-installs rely on -SkipLaunch to avoid opening
        VS Code at all; if PR #144's launch rewrite accidentally removed the
        gate, every CI run would try to spawn VS Code.
        """
        assert re.search(
            r"if\s*\(\s*-not\s+\$SkipLaunch\s*\)", ps1_launch_section
        ), "launch block must still be gated on -not $SkipLaunch"

    def test_help_synopsis_documents_auto_setup_behavior(self, ps1_text: str) -> None:
        """The script's comment-based help should mention the auto-/setup.

        The synopsis is what users see when they run `Get-Help Install-EssAdk.ps1`.
        If the implementation auto-launches /setup but the help still claims
        it only opens the workspace, users won't know to expect the chat
        panel.
        """
        assert re.search(
            r"requests\s+`?/setup`?\s+in\s+Copilot\s+Chat",
            ps1_text,
            flags=re.IGNORECASE,
        ), "Install-EssAdk.ps1 help comment should mention auto-/setup"


# ---------------------------------------------------------------------------
# Bash installer (install-ess-adk.sh)
# ---------------------------------------------------------------------------


class TestBashInstallerAutoLaunch:
    def test_launch_section_invokes_code_chat_with_setup_prompt(
        self, bash_launch_section: str
    ) -> None:
        """Guarantee (1) for macOS: the launcher calls `code chat /setup`."""
        assert re.search(
            r'"\$CODE_CMD"\s+chat\s+"/setup"', bash_launch_section
        ), (
            "Bash installer no longer invokes `$CODE_CMD chat /setup` in "
            "the launch section — PR #144's auto-/setup behavior is broken."
        )

    def test_launch_section_cds_into_workspace_before_chat(
        self, bash_launch_section: str
    ) -> None:
        """Guarantee (2) for macOS: the chat call runs from $WORKSPACE_PATH.

        Bash uses a subshell + `&&` chain so the cd does not leak into the
        rest of the installer's environment; the pattern must be
        `(cd "$WORKSPACE_PATH" && "$CODE_CMD" chat "/setup")` (with optional
        `if (...)` wrapper for set -e compatibility).
        """
        assert re.search(
            r'\(\s*cd\s+"\$WORKSPACE_PATH"\s*&&\s*"\$CODE_CMD"\s+chat\s+"/setup"\s*\)',
            bash_launch_section,
        ), (
            "Bash installer must wrap the chat invocation in a subshell "
            "`(cd \"$WORKSPACE_PATH\" && \"$CODE_CMD\" chat \"/setup\")` so "
            "the chat opens in the kit workspace"
        )

    def test_launch_section_falls_back_when_code_chat_fails(
        self, bash_launch_section: str
    ) -> None:
        """Guarantee (3) for macOS: failure of `code chat` triggers a fallback.

        Because the script runs under `set -euo pipefail`, the chat call must
        be wrapped in an `if ...; then ...; else ...; fi` so a non-zero exit
        from `code chat` does not abort the whole installer. The fallback
        must still open VS Code at $WORKSPACE_PATH and surface manual
        /setup instructions.
        """
        assert re.search(
            r"if\s*\(\s*cd\s+\"\$WORKSPACE_PATH\"\s*&&\s*\"\$CODE_CMD\"\s+chat",
            bash_launch_section,
        ), (
            "chat invocation must be inside an `if (...)` so set -e doesn't "
            "abort the installer when `code chat` returns non-zero"
        )
        assert re.search(r"else\b", bash_launch_section), (
            "launch section must include an `else` branch for the chat-failed "
            "case"
        )
        assert re.search(
            r'"\$CODE_CMD"\s+"\$WORKSPACE_PATH"', bash_launch_section
        ), (
            "fallback branch must still open VS Code at $WORKSPACE_PATH "
            "(`\"$CODE_CMD\" \"$WORKSPACE_PATH\"`)"
        )
        assert re.search(
            r"run\s+/setup",
            bash_launch_section,
            flags=re.IGNORECASE,
        ), "fallback branch must instruct the user how to run /setup manually"

    def test_header_comment_documents_auto_setup_behavior(self, bash_text: str) -> None:
        """The script header should advertise the auto-/setup behavior."""
        assert re.search(
            r"/setup\s+in\s+Copilot\s+Chat", bash_text, flags=re.IGNORECASE
        ), "install-ess-adk.sh header comment should mention auto-/setup"


# ---------------------------------------------------------------------------
# Workspace settings (suppress Welcome tab)
# ---------------------------------------------------------------------------


class TestWorkspaceSettingsSuppressWelcomeTab:
    def test_settings_json_is_valid_json(self) -> None:
        """settings.json must remain parseable — a broken JSON file would
        cause VS Code to ignore *all* workspace settings, not just the new
        one we added.
        """
        try:
            json.loads(WORKSPACE_SETTINGS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:  # pragma: no cover — descriptive failure
            pytest.fail(f"{WORKSPACE_SETTINGS_PATH} is not valid JSON: {exc}")

    def test_startup_editor_is_none(self) -> None:
        """Guarantee (4): the workspace suppresses the Welcome tab.

        Without this setting, every `code chat /setup` run that reuses an
        existing window would show the Welcome tab on top of the chat panel
        on subsequent opens, hiding the /setup prompt.

        Note: this setting does NOT suppress the application-level first-run
        Welcome on a brand-new VS Code install (that's gated by global
        state, not workspace settings). It does suppress the tab on every
        subsequent open of the kit workspace, which is the common case.
        """
        settings = json.loads(WORKSPACE_SETTINGS_PATH.read_text(encoding="utf-8"))
        assert settings.get("workbench.startupEditor") == "none", (
            'workspace settings.json must set "workbench.startupEditor": '
            '"none" so the Welcome tab does not sit on top of the /setup '
            "chat prompt"
        )


# ---------------------------------------------------------------------------
# Documentation (setup/README.md)
# ---------------------------------------------------------------------------


class TestSetupReadmeDocumentsAutoLaunch:
    def test_readme_mentions_auto_setup(self) -> None:
        """setup/README.md should tell users to expect /setup to auto-run.

        Otherwise users will be confused when the chat panel pops up
        unprompted, or will manually re-run /setup and end up with two
        in-flight requests.
        """
        text = README_PATH.read_text(encoding="utf-8")
        assert re.search(
            r"automatically\s+(?:run|launch|request|open).*?/setup|/setup.*?(?:automatically|auto-?(?:run|launch))",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        ), "setup/README.md should mention that /setup runs automatically"
