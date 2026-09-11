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
    assert "'--architecture', $tool.Architecture" in installer
    assert "install_agentbuilder_object_model.py" in installer
    assert "Serialization support dependencies were not installed" in installer
    assert "Microsoft Object Model dependency installation failed" not in installer
    assert "if (-not $FlightCheckOnly -and -not $SkipClone)" not in installer
    assert (
        installer.index("# 5. Clone repo")
        < installer.rindex("install_agentbuilder_object_model.py")
    )


def test_macos_full_installer_provisions_object_model_dependencies() -> None:
    installer = (REPO_ROOT / "setup" / "install-ess-adk.sh").read_text(
        encoding="utf-8"
    )
    assert 'install_optional_brew_cask "dotnet-runtime"' in installer
    assert "install_optional_brew_pkg" in installer
    assert '"nuget"' in installer
    assert "install_agentbuilder_object_model.py" in installer
    assert "Serialization support dependencies were not installed" in installer
    assert 'elif "$VENV_PATH/bin/python" "$OBJECT_MODEL_INSTALLER"; then' in installer
    assert (
        installer.index("# 4. Clone repository")
        < installer.rindex("install_agentbuilder_object_model.py")
    )


def test_codespace_installs_optional_runtime_dependencies() -> None:
    config = json.loads(
        (REPO_ROOT / ".devcontainer" / "devcontainer.json").read_text(
            encoding="utf-8"
        )
    )
    assert "ghcr.io/devcontainers/features/dotnet:2" not in config["features"]
    assert config["postCreateCommand"] == (
        "bash ${containerWorkspaceFolder}/.devcontainer/post-create.sh"
    )
    post_create = (
        REPO_ROOT / ".devcontainer" / "post-create.sh"
    ).read_text(encoding="utf-8")
    assert 'dirname "${BASH_SOURCE[0]}"' in post_create
    assert "/workspaces/Employee-Self-Service-Agent-Developer-Kit" not in post_create
    assert "https://dot.net/v1/dotnet-install.sh" in post_create
    assert "--runtime dotnet" in post_create
    assert "Serialization support dependencies were not installed" in post_create
    assert 'if ! python "$SCRIPTS_DIR/install_agentbuilder_object_model.py"' in (
        post_create
    )


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


def test_dsc_manifest_keeps_optional_dependencies_out_of_fatal_path() -> None:
    manifest = (
        REPO_ROOT / "setup" / "ess-adk-setup.winget.yaml"
    ).read_text(encoding="utf-8")
    assert "Microsoft.DotNet.Runtime.10" not in manifest
    assert "Microsoft.NuGet" not in manifest
