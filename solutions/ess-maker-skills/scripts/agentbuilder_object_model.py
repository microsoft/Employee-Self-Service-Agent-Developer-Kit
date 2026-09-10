# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Invoke the Microsoft Object Model serializer used by AgentBuilder."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


PROJECT_PATH = (
    Path(__file__).resolve().parent
    / "agentbuilder-object-model"
    / "AgentBuilder.ObjectModel.csproj"
)
HELPER_DLL = (
    PROJECT_PATH.parent
    / "bin"
    / "Release"
    / "net8.0"
    / "AgentBuilder.ObjectModel.dll"
)
BUILD_TIMEOUT_SECONDS = 300
CONVERSION_TIMEOUT_SECONDS = 120
MAX_PROCESS_DETAIL = 4000


class ObjectModelConverterError(RuntimeError):
    """Raised when the canonical Object Model helper cannot run safely."""


def _process_detail(completed: subprocess.CompletedProcess[str]) -> str:
    detail = (completed.stderr or completed.stdout or "").strip()
    return detail[-MAX_PROCESS_DETAIL:] or "No process output was returned."


def _helper_needs_build() -> bool:
    if not HELPER_DLL.is_file():
        return True
    output_time = HELPER_DLL.stat().st_mtime_ns
    return any(
        path.stat().st_mtime_ns > output_time
        for path in PROJECT_PATH.parent.glob("*")
        if path.is_file() and path.suffix in {".cs", ".csproj"}
    )


def _dotnet_environment() -> dict[str, str]:
    return {
        **os.environ,
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        "DOTNET_NOLOGO": "1",
    }


def _ensure_helper() -> tuple[str, Path]:
    dotnet = shutil.which("dotnet")
    if not dotnet:
        raise ObjectModelConverterError(
            "The Microsoft Object Model converter requires the .NET 8 SDK."
        )
    if _helper_needs_build():
        try:
            completed = subprocess.run(
                [
                    dotnet,
                    "build",
                    str(PROJECT_PATH),
                    "--configuration",
                    "Release",
                    "--nologo",
                    "--verbosity",
                    "quiet",
                ],
                cwd=PROJECT_PATH.parent,
                capture_output=True,
                text=True,
                check=False,
                timeout=BUILD_TIMEOUT_SECONDS,
                env=_dotnet_environment(),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ObjectModelConverterError(
                "Could not build the Microsoft Object Model converter."
            ) from exc
        if completed.returncode != 0 or not HELPER_DLL.is_file():
            raise ObjectModelConverterError(
                "Could not build the Microsoft Object Model converter: "
                f"{_process_detail(completed)}"
            )
    return dotnet, HELPER_DLL


def object_models_to_yaml(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert Object Model JSON elements to canonical Copilot Studio YAML."""
    if not items:
        return []
    dotnet, helper_dll = _ensure_helper()
    request = {
        "operation": "object-model-to-yaml",
        "items": items,
    }
    try:
        completed = subprocess.run(
            [dotnet, str(helper_dll)],
            cwd=PROJECT_PATH.parent,
            input=json.dumps(request, ensure_ascii=True),
            capture_output=True,
            text=True,
            check=False,
            timeout=CONVERSION_TIMEOUT_SECONDS,
            env=_dotnet_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ObjectModelConverterError(
            "The Microsoft Object Model converter did not complete."
        ) from exc
    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ObjectModelConverterError(
            "The Microsoft Object Model converter returned unreadable output: "
            f"{_process_detail(completed)}"
        ) from exc
    if completed.returncode != 0 or response.get("success") is not True:
        error = response.get("error")
        message = (
            error.get("message")
            if isinstance(error, dict)
            else _process_detail(completed)
        )
        raise ObjectModelConverterError(
            f"The Microsoft Object Model converter failed: {message}"
        )
    results = response.get("results")
    if not isinstance(results, list) or len(results) != len(items):
        raise ObjectModelConverterError(
            "The Microsoft Object Model converter returned an incomplete result."
        )
    for expected, result in zip(items, results, strict=True):
        if (
            not isinstance(result, dict)
            or result.get("key") != expected.get("key")
            or not isinstance(result.get("success"), bool)
        ):
            raise ObjectModelConverterError(
                "The Microsoft Object Model converter returned a mismatched "
                "result."
            )
    return results
