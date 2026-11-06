# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pinned Microsoft Object Model package and assembly locations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parents[2]
DEFAULT_PACKAGE_ROOT = SCRIPTS_DIR.parent / ".local" / "object-model" / "packages"
RUNTIME_CONFIG_PATH = SCRIPTS_DIR / "agentbuilder_object_model.runtimeconfig.json"


@dataclass(frozen=True)
class ObjectModelPackage:
    """One exact NuGet package and its runtime assembly."""

    package_id: str
    version: str
    assembly_path: Path

    @property
    def directory_name(self) -> str:
        return f"{self.package_id}.{self.version}"


PACKAGES = (
    ObjectModelPackage(
        "Microsoft.Agents.ObjectModel",
        "2026.8.27.235-prerelease",
        Path("lib/netstandard2.0/Microsoft.Agents.ObjectModel.dll"),
    ),
    ObjectModelPackage(
        "Microsoft.Agents.ObjectModel.Json",
        "2026.8.27.235-prerelease",
        Path("lib/netstandard2.0/Microsoft.Agents.ObjectModel.Json.dll"),
    ),
    ObjectModelPackage(
        "Microsoft.Bcl.HashCode",
        "1.1.0",
        Path("lib/netcoreapp2.1/Microsoft.Bcl.HashCode.dll"),
    ),
)


def package_root() -> Path:
    """Return the installed package directory."""
    override = os.environ.get("ESS_ADK_OBJECT_MODEL_PACKAGES")
    return Path(override).expanduser().resolve() if override else DEFAULT_PACKAGE_ROOT


def package_directory(package: ObjectModelPackage, root: Path | None = None) -> Path:
    """Return one installed NuGet package directory."""
    return (root or package_root()) / package.directory_name


def assembly_paths(root: Path | None = None) -> tuple[Path, ...]:
    """Return the three Object Model runtime assembly paths."""
    return tuple(
        package_directory(package, root) / package.assembly_path
        for package in PACKAGES
    )
