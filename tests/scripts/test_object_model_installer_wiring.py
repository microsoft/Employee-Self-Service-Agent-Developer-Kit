# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_windows_full_installer_provisions_object_model_dependencies() -> None:
    installer = (REPO_ROOT / "setup" / "Install-EssAdk.ps1").read_text(
        encoding="utf-8"
    )
    assert "Microsoft.DotNet.Runtime.10" in installer
    assert "Microsoft.NuGet" in installer
    assert "Get-PythonArchitecture" in installer
    assert "'--architecture', $pythonArchitecture" in installer
    assert "install_agentbuilder_object_model.py" in installer
    assert "if (-not $FlightCheckOnly -and -not $SkipClone)" not in installer
    assert (
        installer.index("# 5. Clone repo")
        < installer.index("install_agentbuilder_object_model.py")
    )


def test_macos_full_installer_provisions_object_model_dependencies() -> None:
    installer = (REPO_ROOT / "setup" / "install-ess-adk.sh").read_text(
        encoding="utf-8"
    )
    assert 'install_brew_cask "dotnet-runtime"' in installer
    assert 'install_brew_pkg "nuget"' in installer
    assert "install_agentbuilder_object_model.py" in installer
    assert (
        installer.index("# 4. Clone repository")
        < installer.index("install_agentbuilder_object_model.py")
    )


def test_codespace_uses_runtime_only_dotnet_feature() -> None:
    config = json.loads(
        (REPO_ROOT / ".devcontainer" / "devcontainer.json").read_text(
            encoding="utf-8"
        )
    )
    dotnet = config["features"]["ghcr.io/devcontainers/features/dotnet:2"]
    assert dotnet == {
        "version": "none",
        "dotnetRuntimeVersions": "10.0",
    }
    assert config["postCreateCommand"] == (
        "bash ${containerWorkspaceFolder}/.devcontainer/post-create.sh"
    )
    post_create = (
        REPO_ROOT / ".devcontainer" / "post-create.sh"
    ).read_text(encoding="utf-8")
    assert 'dirname "${BASH_SOURCE[0]}"' in post_create
    assert "/workspaces/Employee-Self-Service-Agent-Developer-Kit" not in post_create


def test_flightcheck_avoids_system_object_model_dependencies() -> None:
    windows = (REPO_ROOT / "setup" / "Install-EssAdk.ps1").read_text(
        encoding="utf-8"
    )
    flightcheck_block = windows[
        windows.index("if ($FlightCheckOnly) {"):
        windows.index("if (-not $wingetAvailable) {")
    ]
    assert "Microsoft.DotNet.Runtime.10" not in flightcheck_block
    assert "Microsoft.NuGet" not in flightcheck_block

    macos = (REPO_ROOT / "setup" / "install-ess-adk.sh").read_text(
        encoding="utf-8"
    )
    assert 'if [[ "$FLIGHTCHECK_ONLY" != "true" ]]; then' in macos


def test_pythonnet_uses_existing_requirements_convention() -> None:
    requirements = (
        REPO_ROOT
        / "solutions"
        / "ess-maker-skills"
        / "scripts"
        / "requirements.txt"
    ).read_text(encoding="utf-8")
    assert "pythonnet" in requirements
