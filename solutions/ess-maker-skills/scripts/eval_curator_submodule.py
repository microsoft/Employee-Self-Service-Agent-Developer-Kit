# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Validate and report the local eval-curator submodule contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SUPPORTED_SCHEMA_VERSION = 1

_CONTRACT_FIELDS: dict[str, type] = {
    "schemaVersion": int,
    "skillPath": str,
    "structuralValidatorPath": str,
    "defaultOutputRoot": str,
    "supportsHostOutputOverride": bool,
    "supportsHostLifecycleHandoff": bool,
}


class CuratorSubmoduleError(RuntimeError):
    """An expected curator submodule setup or contract error."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def resolve_submodule(repo_root: Path) -> Path:
    """Return the expected eval-curator submodule path."""
    return (
        repo_root
        / "solutions"
        / "ess-maker-skills"
        / "vendor"
        / "evals-curator"
    )


def _invalid_contract(message: str) -> CuratorSubmoduleError:
    return CuratorSubmoduleError("invalid_contract", message)


def _resolve_contract_path(
    submodule_root: Path,
    field_name: str,
    relative_path: str,
) -> Path:
    contract_path = Path(relative_path)
    if contract_path.is_absolute():
        raise CuratorSubmoduleError(
            "invalid_contract_path",
            f"{field_name} must be relative to the submodule root.",
        )
    resolved = (submodule_root / contract_path).resolve()
    if not resolved.is_relative_to(submodule_root) or not resolved.is_file():
        raise CuratorSubmoduleError(
            "invalid_contract_path",
            f"{field_name} must reference an existing file inside the submodule.",
        )
    return resolved


def load_contract(submodule_root: Path) -> dict[str, Any]:
    """Load and validate the curator host contract."""
    submodule_root = submodule_root.resolve()
    contract_path = submodule_root / "integration" / "host-contract.json"
    if not submodule_root.is_dir() or not contract_path.is_file():
        raise CuratorSubmoduleError(
            "submodule_not_initialized",
            "Initialize dependencies with: git submodule update --init --recursive",
        )

    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _invalid_contract(
            "The curator host contract is not valid JSON."
        ) from exc

    if not isinstance(contract, dict):
        raise _invalid_contract("The curator host contract must be a JSON object.")

    for field_name, expected_type in _CONTRACT_FIELDS.items():
        if field_name not in contract:
            raise _invalid_contract(
                f"The curator host contract is missing required field {field_name}."
            )
        value = contract[field_name]
        if type(value) is not expected_type:
            raise _invalid_contract(
                f"The curator host contract field {field_name} has an invalid type."
            )
        if expected_type is str and not value:
            raise _invalid_contract(
                f"The curator host contract field {field_name} must not be empty."
            )

    if contract["schemaVersion"] != SUPPORTED_SCHEMA_VERSION:
        raise CuratorSubmoduleError(
            "unsupported_contract_version",
            "The curator host contract schema version is not supported.",
        )

    contract["skillPath"] = _resolve_contract_path(
        submodule_root,
        "skillPath",
        contract["skillPath"],
    )
    contract["structuralValidatorPath"] = _resolve_contract_path(
        submodule_root,
        "structuralValidatorPath",
        contract["structuralValidatorPath"],
    )
    return contract


def build_status(repo_root: Path) -> dict[str, Any]:
    """Build the validated curator availability payload."""
    submodule_root = resolve_submodule(repo_root).resolve()
    contract = load_contract(submodule_root)
    return {
        "available": True,
        "schemaVersion": contract["schemaVersion"],
        "submoduleRoot": str(submodule_root),
        "skillPath": str(contract["skillPath"]),
        "structuralValidatorPath": str(contract["structuralValidatorPath"]),
        "defaultOutputRoot": contract["defaultOutputRoot"],
        "supportsHostOutputOverride": contract["supportsHostOutputOverride"],
        "supportsHostLifecycleHandoff": contract[
            "supportsHostLifecycleHandoff"
        ],
    }


def main(argv: list[str] | None = None) -> int:
    """Run the curator submodule preflight CLI."""
    parser = argparse.ArgumentParser(
        description="Validate the local eval-curator submodule contract."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--repo-root", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        payload = build_status(args.repo_root)
        exit_code = 0
    except CuratorSubmoduleError as exc:
        payload = {
            "available": False,
            "errorCode": exc.error_code,
            "message": str(exc),
        }
        exit_code = 2

    print(json.dumps(payload))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
