# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import agentbuilder_object_model as converter
import agentbuilder_object_model_packages as package_manifest
import install_agentbuilder_object_model as package_installer


def test_package_manifest_pins_complete_runtime_graph() -> None:
    assert [
        (package.package_id, package.version)
        for package in package_manifest.PACKAGES
    ] == [
        ("Microsoft.Agents.ObjectModel", "2026.8.27.235-prerelease"),
        ("Microsoft.Agents.ObjectModel.Json", "2026.8.27.235-prerelease"),
        ("Microsoft.Bcl.HashCode", "1.1.0"),
    ]


def test_install_packages_uses_exact_versions_and_verifies_signatures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def fake_run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(arguments)
        if arguments[0] == "install":
            package = next(
                item
                for item in package_manifest.PACKAGES
                if item.package_id == arguments[1]
            )
            package_dir = package_manifest.package_directory(package, tmp_path)
            (package_dir / package.assembly_path).parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            (package_dir / package.assembly_path).touch()
            (package_dir / f"{package.directory_name}.nupkg").touch()
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(package_installer, "_run_nuget", fake_run)

    installed = package_installer.install_packages(tmp_path)

    assert installed == package_manifest.assembly_paths(tmp_path)
    install_commands = [command for command in commands if command[0] == "install"]
    verify_commands = [command for command in commands if command[0] == "verify"]
    assert len(install_commands) == len(package_manifest.PACKAGES)
    assert len(verify_commands) == len(package_manifest.PACKAGES)
    for command, package in zip(
        install_commands,
        package_manifest.PACKAGES,
        strict=True,
    ):
        assert command[1:4] == [
            package.package_id,
            "-Version",
            package.version,
        ]
        assert command[command.index("-DependencyVersion") + 1] == "Ignore"


def test_install_packages_rejects_conflicting_source_options(
    tmp_path: Path,
) -> None:
    config = tmp_path / "NuGet.Config"
    config.touch()
    with pytest.raises(
        package_installer.ObjectModelInstallError,
        match="either a NuGet config file or a package source",
    ):
        package_installer.install_packages(
            tmp_path / "packages",
            config_file=config,
            source=str(tmp_path / "offline"),
        )


def test_nuget_error_detail_redacts_url_credentials() -> None:
    completed = subprocess.CompletedProcess(
        ["nuget"],
        1,
        "",
        (
            "Unable to load "
            "https://user:password@example.test/feed?token=secret"
        ),
    )

    detail = package_installer._process_detail(completed)

    assert "user" not in detail
    assert "password" not in detail
    assert "secret" not in detail
    assert detail == (
        "Unable to load https://[REDACTED]@example.test/feed?[REDACTED]"
    )


def test_missing_packages_report_installer_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    converter._load_object_model.cache_clear()
    monkeypatch.setattr(
        converter,
        "assembly_paths",
        lambda: (tmp_path / "missing.dll",),
    )
    with pytest.raises(converter.ObjectModelConverterError) as exc_info:
        converter._load_object_model()
    message = str(exc_info.value)
    assert "install_agentbuilder_object_model.py" in message
    assert "setup/README.md" in message
    assert "setup/Install-EssAdk.ps1" in message
    assert "setup/install-ess-adk.sh" in message
    assert ".devcontainer/post-create.sh" in message
    converter._load_object_model.cache_clear()


def test_missing_nuget_reports_platform_setup_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(package_installer.shutil, "which", lambda _: None)

    with pytest.raises(package_installer.ObjectModelInstallError) as exc_info:
        package_installer._nuget_command()

    message = str(exc_info.value)
    assert "setup/README.md" in message
    assert "setup/Install-EssAdk.ps1" in message
    assert "setup/install-ess-adk.sh" in message
    assert ".devcontainer/post-create.sh" in message


def test_x64_python_prefers_x64_dotnet_on_windows_arm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(converter.sysconfig, "get_platform", lambda: "win-amd64")
    monkeypatch.setattr(converter.sys, "platform", "win32")
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    monkeypatch.delenv("DOTNET_ROOT", raising=False)
    monkeypatch.delenv("DOTNET_ROOT_X64", raising=False)
    monkeypatch.setattr(converter.shutil, "which", lambda _: None)

    roots = converter._dotnet_roots()

    assert roots[0] == Path(r"C:\Program Files\dotnet\x64").resolve()


def test_arm64_python_uses_native_dotnet_on_windows_arm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(converter.sysconfig, "get_platform", lambda: "win-arm64")
    monkeypatch.setattr(converter.sys, "platform", "win32")
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    monkeypatch.delenv("DOTNET_ROOT", raising=False)
    monkeypatch.delenv("DOTNET_ROOT_ARM64", raising=False)
    monkeypatch.setattr(converter.shutil, "which", lambda _: None)

    roots = converter._dotnet_roots()

    assert roots[0] == Path(r"C:\Program Files\dotnet").resolve()


class _FakeType:
    Name = "FakeDialog"


class _FakeDialog:
    def GetType(self) -> _FakeType:
        return _FakeType()


class _FakeDeserialize:
    def __getitem__(self, _element_type: object) -> object:
        return lambda _payload, _options: _FakeDialog()


class _FakeJsonSerializer:
    Deserialize = _FakeDeserialize()


class _FakeElementSerializer:
    @staticmethod
    def CreateOptions(_indent: bool) -> object:
        return object()


class _FakeYamlSerializer:
    @staticmethod
    def Serialize(_element: object) -> str:
        return "kind: AdaptiveDialog"


def test_object_models_to_yaml_preserves_result_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    types = converter._ObjectModelTypes(
        bot_element=object,
        dialog_base=_FakeDialog,
        element_serializer=_FakeElementSerializer,
        json_serializer=_FakeJsonSerializer,
        yaml_serializer=_FakeYamlSerializer,
    )
    monkeypatch.setattr(converter, "_load_object_model", lambda: types)

    assert converter.object_models_to_yaml(
        [{"key": "topic", "objectModel": {"$kind": "AdaptiveDialog"}}]
    ) == [
        {
            "key": "topic",
            "success": True,
            "elementType": "FakeDialog",
            "yaml": "kind: AdaptiveDialog",
        }
    ]
