# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_INSTALLER = REPO_ROOT / "setup" / "Install-EssAdk.ps1"
MACOS_INSTALLER = REPO_ROOT / "setup" / "install-ess-adk.sh"


def test_windows_installer_supports_rerunning_a_pinned_tag() -> None:
    installer = WINDOWS_INSTALLER.read_text(encoding="utf-8")

    assert "git fetch --quiet --tags origin" in installer
    assert "[string]::IsNullOrWhiteSpace([string]$currentRef)" in installer
    assert '"detached HEAD at $currentCommit"' in installer
    assert '"refs/remotes/origin/$Branch"' in installer
    assert '"refs/tags/$Branch"' in installer
    assert "Checked out pinned tag $Branch" in installer
    assert (
        "git branch --show-current } | Select-Object -First 1).Trim()"
        not in installer
    )


def test_macos_installer_supports_rerunning_a_pinned_tag() -> None:
    installer = MACOS_INSTALLER.read_text(encoding="utf-8")

    assert "git -C \"$REPO_PATH\" fetch --quiet --tags origin" in installer
    assert '"refs/remotes/origin/$BRANCH"' in installer
    assert '"refs/tags/$BRANCH"' in installer
    assert 'ok "Checked out pinned tag $BRANCH"' in installer
    assert 'git -C "$REPO_PATH" pull --quiet origin "$BRANCH"' not in installer


def test_windows_installer_skips_existing_vscode_and_extensions() -> None:
    installer = WINDOWS_INSTALLER.read_text(encoding="utf-8")

    assert "function Resolve-CodeCommand" in installer
    assert "$env:LOCALAPPDATA\\Programs\\Microsoft VS Code\\bin\\code.cmd" in installer
    assert "$env:ProgramFiles\\Microsoft VS Code\\bin\\code.cmd" in installer
    assert "} elseif ($pkg.Cmd -eq 'code') {" in installer
    assert "$extensionListOutput = Invoke-Native { & $codeBin --list-extensions }" in installer
    assert "$installedExtensions -contains $ext.ToLowerInvariant()" in installer


def test_installers_skip_matching_maker_profile_version() -> None:
    windows = WINDOWS_INSTALLER.read_text(encoding="utf-8")
    macos = MACOS_INSTALLER.read_text(encoding="utf-8")

    assert "& $codeBin --list-extensions --show-versions" in windows
    assert (
        '$installedVersionedExtensions -contains '
        '"microsoft-ess.ess-maker-profile@$makerVersion"'
    ) in windows
    assert "if ($makerProfileCurrent)" in windows

    assert 'INSTALLED_EXTENSIONS_WITH_VERSIONS=$("$CODE_CMD" --list-extensions --show-versions' in macos
    assert (
        'grep -Fqix "microsoft-ess.ess-maker-profile@$MAKER_VERSION"'
        in macos
    )
