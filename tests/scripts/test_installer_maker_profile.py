# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Regression tests for the one-shot installer's ESS Maker Profile install.

The one-shot installers (`setup/Install-EssAdk.ps1` on Windows,
`setup/install-ess-adk.sh` on macOS) bundle the PoC "ESS Maker Profile" VS
Code extension and install it from the cloned repo so the customer lands in
a chat-first, big-button layout instead of the stock VS Code UI. The
extension lives at `tools/ess-maker-profile/extension/ess-maker-profile-*.vsix`
and activates on startup, so once it's installed the existing
`code chat /setup` launch step (covered by test_installer_launch.py) picks
up the new layout automatically.

The behavioral guarantees we want to protect against accidental regression:

  1. The bundled `.vsix` file exists on disk in the repo at the path the
     installer looks for.
  2. The PowerShell installer runs the vsix install **after** the clone
     (section 5c or later), not before — the file isn't available
     pre-clone, so an install attempt before section 5 would silently
     no-op.
  3. The PowerShell installer skips the vsix install in FlightCheck-only
     mode and when -SkipExtensions or -SkipMakerProfile is passed.
  4. The bash installer's extensions section installs the vsix from the
     cloned repo, also gated on the FlightCheck-only and
     SKIP_MAKER_PROFILE flags.
  5. Both installers fall back gracefully (warn + continue) if the vsix
     install fails — the user should not be left with no usable layout.

These are static-text assertions, same style as test_installer_launch.py:
read the installer scripts as text and assert the key patterns are present.
The actual end-to-end behavior (extension installs into VS Code, layout
applies) was validated by hand: see PR description.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PS1_PATH = REPO_ROOT / "setup" / "Install-EssAdk.ps1"
BASH_PATH = REPO_ROOT / "setup" / "install-ess-adk.sh"
VSIX_DIR = REPO_ROOT / "tools" / "ess-maker-profile" / "extension"


@pytest.fixture(scope="module")
def ps1_text() -> str:
    return PS1_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ps1_maker_section(ps1_text: str) -> str:
    """The PowerShell installer's '# 5c. ESS Maker Profile ...' section.

    Sliced to just this section so a coincidental string elsewhere
    (e.g. the .SYNOPSIS doc block or section 4's marketplace install)
    cannot satisfy these tests.
    """
    match = re.search(
        r"# 5c\. ESS Maker Profile.*?(?=\r?\n# -+\r?\n# \d+\.)",
        ps1_text,
        flags=re.DOTALL,
    )
    assert match, "could not locate '# 5c. ESS Maker Profile' section in Install-EssAdk.ps1"
    return match.group(0)


@pytest.fixture(scope="module")
def bash_text() -> str:
    return BASH_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ps1_launch_section(ps1_text: str) -> str:
    """The PowerShell installer's '# 7. Launch' section.

    Sliced to just this section so coincidental matches elsewhere
    (e.g. the .SYNOPSIS doc block) cannot satisfy the launch-branch
    assertions.
    """
    match = re.search(
        r"# 7\. Launch.*?(?=\r?\nWrite-Host\s+\"`nDone)",
        ps1_text,
        flags=re.DOTALL,
    )
    assert match, "could not locate '# 7. Launch' section in Install-EssAdk.ps1"
    return match.group(0)


# ---------------------------------------------------------------------------
# Bundled .vsix on disk
# ---------------------------------------------------------------------------


class TestBundledVsix:
    def test_vsix_file_exists(self) -> None:
        """Guarantee (1): a .vsix matching the glob the installer uses is
        present in the repo. Without this file both installers silently
        skip the maker-profile install and the user gets stock VS Code.
        """
        matches = sorted(VSIX_DIR.glob("ess-maker-profile-*.vsix"))
        assert matches, (
            f"no ess-maker-profile-*.vsix under {VSIX_DIR.relative_to(REPO_ROOT)} — "
            "the installers will silently skip the chat-first layout"
        )
        # Sanity: not an empty placeholder file. The 0.4.0 PoC is ~14 KB;
        # require at least 1 KB so a stub committed by accident still fails.
        assert matches[0].stat().st_size > 1024, (
            f"{matches[0].name} is suspiciously small "
            f"({matches[0].stat().st_size} bytes) — looks like a placeholder"
        )


# ---------------------------------------------------------------------------
# PowerShell installer (Install-EssAdk.ps1)
# ---------------------------------------------------------------------------


class TestPowerShellInstallerMakerProfile:
    def test_section_runs_after_clone_not_before(self, ps1_text: str) -> None:
        """Guarantee (2): the maker-profile install runs AFTER section 5
        (clone). Before the clone, $repoPath doesn't contain the vsix
        and the install would silently skip every time.
        """
        clone_pos = ps1_text.find("# 5. Clone repo")
        maker_pos = ps1_text.find("# 5c. ESS Maker Profile")
        assert clone_pos != -1, "# 5. Clone repo section missing"
        assert maker_pos != -1, "# 5c. ESS Maker Profile section missing"
        assert maker_pos > clone_pos, (
            "maker-profile install must run after the clone; "
            f"clone at offset {clone_pos}, maker at {maker_pos}"
        )

    def test_section_runs_before_launch(self, ps1_text: str) -> None:
        """Reinforces (2): the install must complete before VS Code is
        launched, otherwise `code chat /setup` runs against the stock
        layout and the extension only kicks in on the user's NEXT open.
        """
        maker_pos = ps1_text.find("# 5c. ESS Maker Profile")
        launch_pos = ps1_text.find("# 7. Launch")
        assert maker_pos != -1 and launch_pos != -1
        assert maker_pos < launch_pos, (
            "maker-profile install must run before the launch section"
        )

    def test_section_skipped_when_flightcheck_only(
        self, ps1_maker_section: str
    ) -> None:
        """Guarantee (3a): FlightCheck-only installs do not need (and
        explicitly do not run) VS Code, so the maker-profile install
        must be gated on `-not $FlightCheckOnly`.
        """
        assert re.search(
            r"-not\s+\$FlightCheckOnly",
            ps1_maker_section,
        ), "maker-profile section is not gated on -not $FlightCheckOnly"

    def test_section_respects_skip_extensions(
        self, ps1_maker_section: str
    ) -> None:
        """Guarantee (3b): -SkipExtensions skips ALL extension installs,
        marketplace and bundled-vsix alike. A user who opts out of one
        almost certainly wants to opt out of both."""
        assert re.search(
            r"-not\s+\$SkipExtensions",
            ps1_maker_section,
        ), "maker-profile section is not gated on -not $SkipExtensions"

    def test_section_respects_skip_maker_profile(
        self, ps1_maker_section: str
    ) -> None:
        """Guarantee (3c): -SkipMakerProfile is the dedicated escape
        hatch for users who want the marketplace extensions but the
        stock VS Code layout (kit developers, IT-locked-down boxes)."""
        assert re.search(
            r"-not\s+\$SkipMakerProfile",
            ps1_maker_section,
        ), "maker-profile section is not gated on -not $SkipMakerProfile"

    def test_skip_maker_profile_param_is_declared(self, ps1_text: str) -> None:
        """The -SkipMakerProfile switch must be declared in the param()
        block; otherwise the conditional above silently treats it as
        always-false and the escape hatch is dead."""
        assert re.search(
            r"\[switch\]\s+\$SkipMakerProfile",
            ps1_text,
        ), "[switch] $SkipMakerProfile is not declared in param()"

    def test_section_invokes_install_extension_on_vsix(
        self, ps1_maker_section: str
    ) -> None:
        """The actual install action: `code --install-extension <vsix> --force`.
        Without --force, a re-install of the same version is a no-op and
        a downgrade is rejected — both common during dev iteration."""
        assert re.search(
            r"code\s+--install-extension\s+\$vsix\.FullName\s+--force",
            ps1_maker_section,
        ), "section does not call `code --install-extension <vsix> --force`"

    def test_section_globs_vsix_for_version_bumps(
        self, ps1_maker_section: str
    ) -> None:
        """Resolving the vsix by a wildcard glob (not a hard-coded
        filename) means bumping the PoC from 0.4.0 -> 0.5.0 by replacing
        the file does not require an installer code change."""
        assert "ess-maker-profile-*.vsix" in ps1_maker_section, (
            "vsix is not resolved via the ess-maker-profile-*.vsix glob — "
            "a version bump will break the install"
        )

    def test_section_falls_back_gracefully_on_failure(
        self, ps1_maker_section: str
    ) -> None:
        """Guarantee (5): a vsix install failure must NOT abort the
        install. The user still gets a working stock VS Code; only the
        chat-first layout is missing."""
        # Look for a "non-fatal" warning string near a `Write-Warn2`
        # at the failure branch. The exact wording is allowed to drift
        # but the intent ("don't blow up the install") must be preserved.
        assert re.search(
            r"Write-Warn2.*non-fatal",
            ps1_maker_section,
            flags=re.IGNORECASE,
        ), "no `Write-Warn2 ... non-fatal` on the failure branch"


# ---------------------------------------------------------------------------
# Bash installer (install-ess-adk.sh)
# ---------------------------------------------------------------------------


class TestBashInstallerMakerProfile:
    def test_skip_maker_profile_env_var_declared(self, bash_text: str) -> None:
        """SKIP_MAKER_PROFILE is the bash equivalent of -SkipMakerProfile.
        Must be defaulted via `${SKIP_MAKER_PROFILE:-false}` so an
        unset env var doesn't trip `set -u`."""
        assert re.search(
            r'SKIP_MAKER_PROFILE="\$\{SKIP_MAKER_PROFILE:-false\}"',
            bash_text,
        ), "SKIP_MAKER_PROFILE is not declared with the :-false default"

    def test_install_runs_after_clone(self, bash_text: str) -> None:
        """Bash installer clones in section 4, so installing the vsix in
        section 6 (extensions) is fine — the file is on disk. But pin
        the ordering so a future reshuffle that moves the extensions
        section ahead of clone is caught immediately."""
        clone_pos = bash_text.find("# 4. Clone repository")
        # The vsix install is inside section 6's extensions block; key off
        # the unique REPO_PATH/tools/ess-maker-profile path it references.
        install_pos = bash_text.find("$REPO_PATH/tools/ess-maker-profile")
        assert clone_pos != -1, "# 4. Clone repository section missing"
        assert install_pos != -1, "maker-profile install snippet missing"
        assert install_pos > clone_pos, (
            "vsix install must reference $REPO_PATH AFTER the clone, "
            f"but install at {install_pos} precedes clone at {clone_pos}"
        )

    def test_install_skipped_when_skip_maker_profile(self, bash_text: str) -> None:
        """The vsix install branch must be gated on SKIP_MAKER_PROFILE."""
        assert re.search(
            r'\[\[\s*"\$SKIP_MAKER_PROFILE"\s*!=\s*"true"\s*\]\]',
            bash_text,
        ), "vsix install is not gated on SKIP_MAKER_PROFILE != true"

    def test_install_invokes_code_install_extension(self, bash_text: str) -> None:
        """Actual install action mirrors the marketplace extensions:
        `$CODE_CMD --install-extension <vsix> --force`."""
        assert re.search(
            r'"\$CODE_CMD"\s+--install-extension\s+"\$MAKER_VSIX"\s+--force',
            bash_text,
        ), "no `$CODE_CMD --install-extension $MAKER_VSIX --force` invocation"

    def test_install_globs_vsix_for_version_bumps(self, bash_text: str) -> None:
        """Same as PowerShell: resolve the vsix by glob, not by hard-coded
        version string."""
        assert "ess-maker-profile-*.vsix" in bash_text, (
            "bash installer does not glob ess-maker-profile-*.vsix"
        )

    def test_install_warns_but_continues_on_failure(self, bash_text: str) -> None:
        """Guarantee (5) on the bash side: failure must warn + continue,
        not abort. The marketplace REQUIRED_EXTENSIONS list does
        `err + exit 1` on failure; the maker-profile install must NOT."""
        # Slice to just the maker-profile branch: from the
        # "ESS Maker Profile" comment up to the start of section 7.
        match = re.search(
            r"# ESS Maker Profile.*?(?=\r?\n# -+\r?\n# 7\.)",
            bash_text,
            flags=re.DOTALL,
        )
        assert match, "could not locate maker-profile branch in bash installer"
        snippet = match.group(0)
        assert "exit 1" not in snippet, (
            "maker-profile failure path should not `exit 1` — "
            "must warn and continue so the install still produces a "
            "working stock VS Code"
        )
        # The failure branch calls `warn "ESS Maker Profile install failed ..."`.
        assert re.search(
            r'warn\s+"ESS Maker Profile install failed',
            snippet,
        ), (
            "maker-profile failure path must call "
            '`warn "ESS Maker Profile install failed ..."` on failure'
        )


# ---------------------------------------------------------------------------
# Launch branch when MakerProfile is installed
# ---------------------------------------------------------------------------
#
# When the ESS Maker Profile extension is installed, it takes over /setup
# orchestration: on activation it opens a chat editor in the editor area
# (full width) and injects /setup itself via clipboard paste. The installer
# must therefore launch VS Code WITHOUT `code chat /setup` in that case —
# otherwise we get two competing chat surfaces (one from CLI in the aux
# bar, one from the extension in the editor area).
#
# These tests pin the branching in both installers so a future refactor
# that "simplifies" the launch back to a single unconditional
# `code chat /setup` is caught immediately.


class TestPowerShellInstallerLaunchBranchesOnMakerProfile:
    def test_sets_maker_profile_installed_flag_on_success(
        self, ps1_text: str
    ) -> None:
        """The launch branch keys off `$script:MakerProfileInstalled`.
        That flag must be set to $true in the success branch of the
        vsix install. Without the flag, the launch always falls through
        to `code chat /setup` and the extension's chat-in-editor never
        wins the race for `/setup`.
        """
        assert re.search(
            r"\$script:MakerProfileInstalled\s*=\s*\$true",
            ps1_text,
        ), (
            "vsix install success branch must set "
            "`$script:MakerProfileInstalled = $true` so the launch "
            "section knows to skip `code chat /setup`"
        )

    def test_launch_branches_on_maker_profile_installed(
        self, ps1_launch_section: str
    ) -> None:
        """Launch section must branch on $script:MakerProfileInstalled
        and call `code .` (not `code chat /setup`) in the maker-profile
        branch.
        """
        assert re.search(
            r"if\s*\(\s*\$script:MakerProfileInstalled\s*\)",
            ps1_launch_section,
        ), (
            "launch section must branch on `$script:MakerProfileInstalled` "
            "so it can skip `code chat /setup` when the extension is "
            "installed"
        )
        # `code .` (workspace-only) invocation in the maker-profile branch.
        assert re.search(
            r"Start-Process\s+-FilePath\s+\$code\.Source\s+-ArgumentList\s+@\('\.'\)",
            ps1_launch_section,
        ), (
            "maker-profile launch branch must call "
            "`Start-Process -FilePath $code.Source -ArgumentList @('.')` "
            "(plain workspace open) instead of `code chat /setup` — the "
            "extension injects /setup itself"
        )


class TestBashInstallerLaunchBranchesOnMakerProfile:
    def test_sets_maker_profile_installed_flag_on_success(
        self, bash_text: str
    ) -> None:
        """Bash equivalent: MAKER_PROFILE_INSTALLED=true in the success
        branch of the vsix install."""
        assert re.search(
            r"MAKER_PROFILE_INSTALLED=true",
            bash_text,
        ), (
            "vsix install success branch must set "
            "`MAKER_PROFILE_INSTALLED=true` so the launch section knows "
            "to skip `code chat /setup`"
        )

    def test_launch_branches_on_maker_profile_installed(
        self, bash_text: str
    ) -> None:
        """Bash launch section must branch on MAKER_PROFILE_INSTALLED
        and call `$CODE_CMD .` (workspace-only) in the maker-profile
        branch.
        """
        # Find section 8 (Launch VS Code).
        launch_start = bash_text.find("# 8. Launch VS Code")
        assert launch_start != -1, "section 8 launch header missing"
        launch_section = bash_text[launch_start:]

        assert re.search(
            r'\$\{MAKER_PROFILE_INSTALLED:-false\}.*==\s*"true"',
            launch_section,
        ), (
            "launch section must branch on `${MAKER_PROFILE_INSTALLED:-false}` "
            "so it can skip `code chat /setup` when the extension is installed"
        )
        # The plain workspace-open invocation: `"$CODE_CMD" .`
        assert re.search(
            r'"\$CODE_CMD"\s+\.\s*\)',
            launch_section,
        ), (
            "maker-profile launch branch must call `\"$CODE_CMD\" .` "
            "(plain workspace open) instead of `code chat /setup`"
        )
