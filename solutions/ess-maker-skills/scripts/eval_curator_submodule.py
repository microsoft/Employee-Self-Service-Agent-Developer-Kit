# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Validate and report the local eval-curator submodule contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
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


def _run_git(cwd: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise CuratorSubmoduleError(
            "git_metadata_unavailable",
            "Unable to execute git for curator submodule verification.",
        ) from exc
    if result.returncode not in (0, 1):
        detail = result.stderr.strip() or result.stdout.strip()
        raise CuratorSubmoduleError(
            "git_metadata_unavailable",
            "Unable to read curator submodule git metadata"
            + (f": {detail}" if detail else "."),
        )
    return result.stdout.strip()


def _parse_gitlink(
    output: str,
    *,
    source: str,
) -> str:
    pattern = (
        r"^160000 ([0-9a-f]{40}) 0\t.+$"
        if source == "index"
        else r"^160000 commit ([0-9a-f]{40})\t.+$"
    )
    match = re.fullmatch(pattern, output)
    if not match:
        raise CuratorSubmoduleError(
            "invalid_parent_gitlink",
            f"The parent repository {source} does not contain a valid "
            "gitlink for the curator vendor path.",
        )
    return match.group(1)


def validate_submodule_integrity(
    repo_root: Path,
    submodule_root: Path,
) -> dict[str, Any]:
    """Verify the configured gitlink, submodule HEAD, and clean worktree."""
    repo_root = repo_root.resolve()
    submodule_root = submodule_root.resolve()
    relative_path = "solutions/ess-maker-skills/vendor/evals-curator"

    if not submodule_root.is_dir():
        raise CuratorSubmoduleError(
            "submodule_not_initialized",
            "Initialize dependencies with: git submodule update --init "
            "--recursive",
        )
    if not (submodule_root / ".git").exists():
        raise CuratorSubmoduleError(
            "not_configured_submodule",
            "The curator vendor path is an ordinary directory, not the "
            "configured git submodule.",
        )

    parent_top = Path(_run_git(repo_root, "rev-parse", "--show-toplevel"))
    if parent_top.resolve() != repo_root:
        raise CuratorSubmoduleError(
            "git_metadata_unavailable",
            "The supplied repository root is not the parent git worktree.",
        )

    gitmodules_path = repo_root / ".gitmodules"
    configured = _run_git(
        repo_root,
        "config",
        "-f",
        str(gitmodules_path),
        "--get-regexp",
        r"^submodule\..*\.path$",
    )
    configured_paths = {
        line.split(None, 1)[1].replace("\\", "/")
        for line in configured.splitlines()
        if len(line.split(None, 1)) == 2
    }
    if relative_path not in configured_paths:
        raise CuratorSubmoduleError(
            "not_configured_submodule",
            "The curator vendor path is not the configured git submodule.",
        )

    index_gitlink = _parse_gitlink(
        _run_git(
            repo_root,
            "ls-files",
            "--stage",
            "--",
            relative_path,
        ),
        source="index",
    )
    head_gitlink = _parse_gitlink(
        _run_git(
            repo_root,
            "ls-tree",
            "HEAD",
            "--",
            relative_path,
        ),
        source="HEAD",
    )
    parent_gitlink_staged = index_gitlink != head_gitlink
    expected_gitlink = index_gitlink
    gitlink_source = "index" if parent_gitlink_staged else "HEAD"

    if _run_git(
        submodule_root,
        "rev-parse",
        "--is-inside-work-tree",
    ) != "true":
        raise CuratorSubmoduleError(
            "not_configured_submodule",
            "The curator vendor path is not a git worktree.",
        )
    superproject = _run_git(
        submodule_root,
        "rev-parse",
        "--show-superproject-working-tree",
    )
    if not superproject or Path(superproject).resolve() != repo_root:
        raise CuratorSubmoduleError(
            "not_configured_submodule",
            "The curator vendor path is not attached to this parent repository "
            "as its configured submodule.",
        )

    submodule_head = _run_git(submodule_root, "rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", submodule_head):
        raise CuratorSubmoduleError(
            "git_metadata_unavailable",
            "The curator submodule HEAD is unavailable.",
        )
    if submodule_head != expected_gitlink:
        raise CuratorSubmoduleError(
            "submodule_commit_mismatch",
            "The curator submodule HEAD does not match the parent repository "
            f"{gitlink_source} gitlink.",
        )

    dirty = _run_git(
        submodule_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    if dirty:
        raise CuratorSubmoduleError(
            "submodule_dirty",
            "The curator submodule worktree has modified or untracked files.",
        )

    return {
        "parentGitlink": expected_gitlink,
        "headGitlink": head_gitlink,
        "gitlinkSource": gitlink_source,
        "parentGitlinkStaged": parent_gitlink_staged,
        "submoduleHead": submodule_head,
        "submoduleClean": True,
    }


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

    try:
        resolved = (submodule_root / contract_path).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise CuratorSubmoduleError(
            "invalid_contract_path",
            f"{field_name} contains an invalid filesystem path; "
            "use a relative path inside the submodule.",
        ) from exc

    try:
        is_valid = resolved.is_relative_to(submodule_root) and resolved.is_file()
    except (OSError, ValueError) as exc:
        raise CuratorSubmoduleError(
            "invalid_contract_path",
            f"{field_name} contains an invalid filesystem path; "
            "use a relative path inside the submodule.",
        ) from exc

    if not is_valid:
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

    if "schemaVersion" not in contract:
        raise _invalid_contract(
            "The curator host contract is missing required field schemaVersion."
        )
    if type(contract["schemaVersion"]) is not int:
        raise _invalid_contract(
            "The curator host contract field schemaVersion has an invalid type."
        )
    if contract["schemaVersion"] != SUPPORTED_SCHEMA_VERSION:
        raise CuratorSubmoduleError(
            "unsupported_contract_version",
            "The curator host contract schema version is not supported.",
        )

    for field_name, expected_type in _CONTRACT_FIELDS.items():
        if field_name == "schemaVersion":
            continue
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
    integrity = validate_submodule_integrity(repo_root, submodule_root)
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
        **integrity,
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
