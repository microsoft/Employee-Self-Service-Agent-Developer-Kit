# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Invoke the Microsoft Object Model serializer used by AgentBuilder."""

from __future__ import annotations

import json
import os
import shutil
import sys
import sysconfig
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from agentbuilder_object_model_packages import (
    RUNTIME_CONFIG_PATH,
    assembly_paths,
)


MAX_ERROR_LENGTH = 2000


class ObjectModelConverterError(RuntimeError):
    """Raised when the canonical Object Model converter cannot run safely."""


@dataclass(frozen=True)
class _ObjectModelTypes:
    bot_element: Any
    dialog_base: Any
    element_serializer: Any
    json_serializer: Any
    yaml_serializer: Any


def _python_architecture() -> str:
    platform_name = sysconfig.get_platform().lower()
    if "arm64" in platform_name or "aarch64" in platform_name:
        return "arm64"
    if "amd64" in platform_name or "x86_64" in platform_name:
        return "x64"
    raise ObjectModelConverterError(
        f"Unsupported Python architecture: {platform_name}"
    )


def _dotnet_roots() -> tuple[Path, ...]:
    architecture = _python_architecture()
    candidates: list[Path] = []

    architecture_root = os.environ.get(f"DOTNET_ROOT_{architecture.upper()}")
    if architecture_root:
        candidates.append(Path(architecture_root))
    if os.environ.get("DOTNET_ROOT"):
        candidates.append(Path(os.environ["DOTNET_ROOT"]))

    dotnet = shutil.which("dotnet")
    if dotnet:
        candidates.append(Path(dotnet).resolve().parent)

    if sys.platform == "win32":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        if architecture == "x64":
            candidates.append(program_files / "dotnet" / "x64")
        candidates.append(program_files / "dotnet")
    else:
        candidates.extend(
            (
                Path("/usr/local/share/dotnet"),
                Path("/usr/share/dotnet"),
                Path.home() / ".dotnet",
            )
        )

    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved not in unique:
            unique.append(resolved)
    return tuple(unique)


def _has_dotnet_10_runtime(root: Path) -> bool:
    runtime_directory = root / "shared" / "Microsoft.NETCore.App"
    return (
        (root / "host" / "fxr").is_dir()
        and runtime_directory.is_dir()
        and any(runtime_directory.glob("10.*"))
    )


@lru_cache(maxsize=1)
def _load_object_model() -> _ObjectModelTypes:
    installed_assemblies = assembly_paths()
    missing = [str(path) for path in installed_assemblies if not path.is_file()]
    if missing:
        raise ObjectModelConverterError(
            "Microsoft Object Model dependencies are not installed. "
            "Re-run the ESS ADK installer or run "
            "`python scripts/install_agentbuilder_object_model.py`."
        )

    try:
        from pythonnet import load
    except ImportError as exc:
        raise ObjectModelConverterError(
            "Python.NET is not installed. Re-run the ESS ADK installer."
        ) from exc

    runtime_errors: list[str] = []
    for root in _dotnet_roots():
        if not _has_dotnet_10_runtime(root):
            continue
        try:
            load(
                "coreclr",
                runtime_config=str(RUNTIME_CONFIG_PATH),
                dotnet_root=str(root),
            )
            break
        except RuntimeError as exc:
            runtime_errors.append(f"{root}: {exc}")
    else:
        detail = runtime_errors[-1] if runtime_errors else "No .NET 10 runtime found."
        raise ObjectModelConverterError(
            "A .NET 10 runtime matching the Python process architecture is "
            f"required. Re-run the ESS ADK installer. {detail}"
        )

    library_directories = {str(path.parent) for path in installed_assemblies}
    for directory in library_directories:
        if directory not in sys.path:
            sys.path.insert(0, directory)

    try:
        import clr

        for assembly in installed_assemblies:
            clr.AddReference(str(assembly))

        from Microsoft.Agents.ObjectModel import (
            BotElement,
            DialogBase,
            ElementSerializer,
        )
        from Microsoft.Agents.ObjectModel.Yaml import YamlSerializer
        from System.Text.Json import JsonSerializer
    except Exception as exc:
        raise ObjectModelConverterError(
            "Could not load the Microsoft Object Model assemblies."
        ) from exc

    return _ObjectModelTypes(
        bot_element=BotElement,
        dialog_base=DialogBase,
        element_serializer=ElementSerializer,
        json_serializer=JsonSerializer,
        yaml_serializer=YamlSerializer,
    )


def _error_result(key: str, error: Exception) -> dict[str, Any]:
    get_type = getattr(error, "GetType", None)
    error_type = (
        get_type().Name
        if callable(get_type)
        else type(error).__name__
    )
    message = str(error).strip() or error_type
    return {
        "key": key,
        "success": False,
        "error": {
            "code": "object-model-conversion-failed",
            "type": error_type,
            "message": message[:MAX_ERROR_LENGTH],
        },
    }


def object_models_to_yaml(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert Object Model JSON elements to canonical Copilot Studio YAML."""
    if not items:
        return []

    types = _load_object_model()
    options = types.element_serializer.CreateOptions(False)
    results: list[dict[str, Any]] = []
    for item in items:
        key = item.get("key")
        if not isinstance(key, str) or not key.strip():
            raise ObjectModelConverterError(
                "Each item key must be a non-empty string."
            )
        object_model = item.get("objectModel")
        if not isinstance(object_model, dict):
            raise ObjectModelConverterError("objectModel must be an object.")

        try:
            element = types.json_serializer.Deserialize[types.bot_element](
                json.dumps(object_model, separators=(",", ":"), ensure_ascii=True),
                options,
            )
            if element is None:
                raise ValueError(
                    "The Object Model JSON did not contain a BotElement."
                )
            if not isinstance(element, types.dialog_base):
                raise ValueError(
                    f"Expected a dialog but received {element.GetType().Name}."
                )
            results.append(
                {
                    "key": key,
                    "success": True,
                    "elementType": element.GetType().Name,
                    "yaml": str(types.yaml_serializer.Serialize(element)),
                }
            )
        except Exception as exc:
            results.append(_error_result(key, exc))
    return results
