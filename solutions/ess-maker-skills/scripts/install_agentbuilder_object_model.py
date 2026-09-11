# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Install the pinned Microsoft Object Model packages with NuGet."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from agentbuilder_object_model_packages import (
    PACKAGES,
    REPO_ROOT,
    assembly_paths,
    package_directory,
    package_root,
)


MAX_PROCESS_DETAIL = 4000
NUGET_TIMEOUT_SECONDS = 300
URL_CREDENTIALS = re.compile(
    r"(?i)(https?://)(?:[^/\s:@]+):(?:[^@\s/]+)@"
)
URL_QUERY = re.compile(r"(?i)(https?://[^\s?#]+)\?[^\s]+")


class ObjectModelInstallError(RuntimeError):
    """Raised when Object Model dependencies cannot be installed safely."""


def _process_detail(completed: subprocess.CompletedProcess[str]) -> str:
    detail = (completed.stderr or completed.stdout or "").strip()
    detail = URL_CREDENTIALS.sub(r"\1[REDACTED]@", detail)
    detail = URL_QUERY.sub(r"\1?[REDACTED]", detail)
    return detail[-MAX_PROCESS_DETAIL:] or "No process output was returned."


def _nuget_command() -> str:
    command = shutil.which("nuget")
    if not command:
        raise ObjectModelInstallError(
            "NuGet is not installed. Re-run the ESS ADK installer."
        )
    return command


def _run_nuget(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            [_nuget_command(), *arguments],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=NUGET_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ObjectModelInstallError(
            "NuGet did not complete while installing Object Model dependencies."
        ) from exc
    if completed.returncode != 0:
        raise ObjectModelInstallError(
            f"NuGet failed: {_process_detail(completed)}"
        )
    return completed


def install_packages(
    output_directory: Path,
    *,
    config_file: Path | None = None,
    source: str | None = None,
) -> tuple[Path, ...]:
    """Install and verify the exact Object Model packages."""
    if config_file and source:
        raise ObjectModelInstallError(
            "Use either a NuGet config file or a package source, not both."
        )
    if config_file and not config_file.is_file():
        raise ObjectModelInstallError(
            f"NuGet config file does not exist: {config_file}"
        )

    output_directory.mkdir(parents=True, exist_ok=True)
    source_arguments: list[str] = []
    if config_file:
        source_arguments = ["-ConfigFile", str(config_file.resolve())]
    elif source:
        source_arguments = ["-Source", source]

    for package in PACKAGES:
        _run_nuget(
            [
                "install",
                package.package_id,
                "-Version",
                package.version,
                "-DependencyVersion",
                "Ignore",
                "-OutputDirectory",
                str(output_directory),
                "-PackageSaveMode",
                "nupkg",
                "-NonInteractive",
                "-Prerelease",
                "-Verbosity",
                "quiet",
                *source_arguments,
            ]
        )

        nupkg = package_directory(package, output_directory) / (
            f"{package.directory_name}.nupkg"
        )
        if not nupkg.is_file():
            raise ObjectModelInstallError(
                f"NuGet did not retain the expected package archive: {nupkg}"
            )
        _run_nuget(
            [
                "verify",
                "-All",
                str(nupkg),
                "-NonInteractive",
                "-Verbosity",
                "quiet",
            ]
        )

    installed_assemblies = assembly_paths(output_directory)
    missing = [str(path) for path in installed_assemblies if not path.is_file()]
    if missing:
        raise ObjectModelInstallError(
            "NuGet packages are missing expected runtime assemblies: "
            + ", ".join(missing)
        )
    return installed_assemblies


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install Microsoft Object Model runtime dependencies."
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=package_root(),
    )
    parser.add_argument(
        "--config-file",
        type=Path,
        default=(
            Path(os.environ["ESS_ADK_NUGET_CONFIG"])
            if os.environ.get("ESS_ADK_NUGET_CONFIG")
            else None
        ),
    )
    parser.add_argument(
        "--source",
        default=os.environ.get("ESS_ADK_NUGET_SOURCE"),
        help="NuGet source URL or offline package directory.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        assemblies = install_packages(
            args.output_directory.resolve(),
            config_file=args.config_file,
            source=args.source,
        )
    except ObjectModelInstallError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        "Microsoft Object Model dependencies installed "
        f"({len(assemblies)} assemblies)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
