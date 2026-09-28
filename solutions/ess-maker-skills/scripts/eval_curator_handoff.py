# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Validate a hosted eval-curator handoff before Maker Kit consumes it."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any


class CuratorHandoffError(RuntimeError):
    """An expected malformed or unsafe curator handoff error."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction and isjunction(path):
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_attribute)


def _contains_parent_reference(value: str) -> bool:
    return ".." in Path(value).parts


def _logical_supplied_path(solution_root: Path, value: str) -> Path:
    supplied = Path(value)
    try:
        return Path(
            os.path.abspath(
                supplied if supplied.is_absolute() else solution_root / supplied
            )
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise CuratorHandoffError(
            "invalid_path",
            "The curator handoff contains an invalid filesystem path.",
        ) from exc


def _normalized_path(path: Path) -> str:
    return os.path.normcase(str(Path(os.path.abspath(path))))


def _is_contained(root: Path, path: Path) -> bool:
    normalized_root = _normalized_path(root)
    normalized_path = _normalized_path(path)
    try:
        return os.path.commonpath(
            (normalized_root, normalized_path)
        ) == normalized_root
    except ValueError:
        return False


def _require_safe_path(
    root: Path,
    path: Path,
    *,
    error_code: str,
    label: str,
) -> Path:
    absolute_root = Path(os.path.abspath(root))
    absolute_path = Path(os.path.abspath(path))
    if not _is_contained(absolute_root, absolute_path):
        raise CuratorHandoffError(
            error_code,
            f"{label} escapes workspace/evaluations.",
        )

    relative = Path(os.path.relpath(absolute_path, absolute_root))
    current = absolute_root
    for part in relative.parts:
        current /= part
        if os.path.lexists(current) and _is_reparse_point(current):
            raise CuratorHandoffError(
                error_code,
                f"{label} traverses a symlink or junction.",
            )

    try:
        resolved_root = absolute_root.resolve()
        resolved_path = absolute_path.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise CuratorHandoffError(
            error_code,
            f"{label} contains an invalid filesystem path.",
        ) from exc
    if not _is_contained(resolved_root, resolved_path):
        raise CuratorHandoffError(
            error_code,
            f"{label} resolves outside workspace/evaluations.",
        )
    return resolved_path


def _require_string(
    value: object,
    *,
    error_code: str,
    field_name: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CuratorHandoffError(
            error_code,
            f"{field_name} must be a non-empty string.",
        )
    return value


def _validate_set_folder(
    solution_root: Path,
    output_root: Path,
    value: object,
) -> tuple[Path, int]:
    supplied = _require_string(
        value,
        error_code="invalid_set_folder",
        field_name="Set folder",
    )
    if _contains_parent_reference(supplied):
        raise CuratorHandoffError(
            "invalid_set_folder",
            "Set folder must not contain path traversal.",
        )
    logical_folder = _logical_supplied_path(solution_root, supplied)
    folder = _require_safe_path(
        output_root,
        logical_folder,
        error_code="invalid_set_folder",
        label="Set folder",
    )
    if (
        logical_folder.parent != output_root
        or folder.name.casefold() == "exports"
        or not folder.is_dir()
    ):
        raise CuratorHandoffError(
            "invalid_set_folder",
            "Set folder must be an existing direct child of "
            "workspace/evaluations and must not be exports.",
        )
    try:
        yaml_documents = []
        for path in folder.glob("*.mcs.yml"):
            artifact = _require_safe_path(
                folder,
                path,
                error_code="invalid_set_folder",
                label="Set folder artifact",
            )
            if artifact.is_file():
                yaml_documents.append(artifact.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise CuratorHandoffError(
            "invalid_set_folder",
            "Set folder artifacts could not be read.",
        ) from exc
    parent_count = sum("kind: EvaluationSet" in text for text in yaml_documents)
    case_count = sum("kind: EvaluationData" in text for text in yaml_documents)
    if parent_count != 1 or case_count < 1:
        raise CuratorHandoffError(
            "invalid_set_folder",
            "Set folder must contain exactly one EvaluationSet parent and "
            "one or more EvaluationData .mcs.yml artifacts.",
        )
    return folder, case_count


def _validate_set_csv(
    solution_root: Path,
    output_root: Path,
    value: object,
) -> tuple[Path, int]:
    supplied = _require_string(
        value,
        error_code="invalid_set_csv",
        field_name="Set CSV",
    )
    if _contains_parent_reference(supplied):
        raise CuratorHandoffError(
            "invalid_set_csv",
            "Set CSV must not contain path traversal.",
        )
    logical_csv_path = _logical_supplied_path(solution_root, supplied)
    csv_path = _require_safe_path(
        output_root,
        logical_csv_path,
        error_code="invalid_set_csv",
        label="Set CSV",
    )
    if (
        logical_csv_path.parent != output_root / "exports"
        or csv_path.suffix.casefold() != ".csv"
        or not csv_path.is_file()
    ):
        raise CuratorHandoffError(
            "invalid_set_csv",
            "Set CSV must be an existing .csv file directly inside "
            "workspace/evaluations/exports.",
        )
    try:
        with csv_path.open(encoding="utf-8", newline="") as csv_file:
            reader = csv.reader(csv_file)
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise CuratorHandoffError(
            "invalid_set_csv",
            "Set CSV could not be read as CSV.",
        ) from exc
    expected_header = [
        "Prompt",
        "Expected response",
        "Test Method Type",
        "Passing Score",
    ]
    if not rows or rows[0] != expected_header or len(rows) < 2:
        raise CuratorHandoffError(
            "invalid_set_csv",
            "Set CSV must use the curator export header and contain data rows.",
        )
    return csv_path, len(rows) - 1


def validate_handoff(
    repo_root: Path,
    document: object,
) -> dict[str, Any]:
    """Validate and normalize one hosted curator handoff."""
    solution_root = (
        repo_root.resolve() / "solutions" / "ess-maker-skills"
    ).resolve()
    logical_output_root = solution_root / "workspace" / "evaluations"
    output_root = _require_safe_path(
        solution_root,
        logical_output_root,
        error_code="invalid_output_root",
        label="outputRoot",
    )

    if not isinstance(document, dict) or set(document) != {"Curator handoff"}:
        raise CuratorHandoffError(
            "invalid_handoff",
            "Expected exactly one Curator handoff object.",
        )
    handoff = document["Curator handoff"]
    if not isinstance(handoff, dict):
        raise CuratorHandoffError(
            "invalid_handoff",
            "Curator handoff must be an object.",
        )
    if set(handoff) != {
        "outputRoot",
        "sets",
        "structuralValidation",
        "qualityValidation",
    }:
        raise CuratorHandoffError(
            "invalid_handoff",
            "Curator handoff fields do not match the hosted contract.",
        )
    if handoff.get("structuralValidation") != "passed":
        raise CuratorHandoffError(
            "invalid_handoff",
            "Curator structuralValidation must be passed.",
        )
    if handoff.get("qualityValidation") != "passed":
        raise CuratorHandoffError(
            "invalid_handoff",
            "Curator qualityValidation must be passed.",
        )

    supplied_root = _require_string(
        handoff.get("outputRoot"),
        error_code="invalid_output_root",
        field_name="outputRoot",
    )
    if _contains_parent_reference(supplied_root):
        raise CuratorHandoffError(
            "invalid_output_root",
            "outputRoot must not contain path traversal.",
        )
    logical_supplied_root = _logical_supplied_path(
        solution_root,
        supplied_root,
    )
    resolved_supplied_root = _require_safe_path(
        solution_root,
        logical_supplied_root,
        error_code="invalid_output_root",
        label="outputRoot",
    )
    if (
        logical_supplied_root != logical_output_root
        or resolved_supplied_root != output_root
    ):
        raise CuratorHandoffError(
            "invalid_output_root",
            "outputRoot must resolve exactly to workspace/evaluations.",
        )

    sets = handoff.get("sets")
    if not isinstance(sets, list) or not sets:
        raise CuratorHandoffError(
            "invalid_handoff",
            "Curator handoff must contain one or more sets.",
        )

    normalized_sets: list[dict[str, Any]] = []
    seen_folders: set[str] = set()
    seen_csvs: set[str] = set()
    for index, entry in enumerate(sets):
        if not isinstance(entry, dict):
            raise CuratorHandoffError(
                "invalid_handoff",
                f"Set entry {index} must be an object.",
            )
        if set(entry) != {
            "name",
            "folder",
            "csv",
            "caseCount",
            "qualityScore",
        }:
            raise CuratorHandoffError(
                "invalid_handoff",
                f"Set entry {index} fields do not match the hosted contract.",
            )
        name = _require_string(
            entry.get("name"),
            error_code="invalid_handoff",
            field_name=f"Set entry {index} name",
        )
        folder, yaml_case_count = _validate_set_folder(
            solution_root,
            logical_output_root,
            entry.get("folder"),
        )
        csv_path, csv_case_count = _validate_set_csv(
            solution_root,
            logical_output_root,
            entry.get("csv"),
        )
        case_count = entry.get("caseCount")
        quality_score = entry.get("qualityScore")
        if (
            type(case_count) is not int
            or case_count < 1
            or case_count != yaml_case_count
            or case_count != csv_case_count
        ):
            raise CuratorHandoffError(
                "invalid_handoff",
                f"Set entry {index} caseCount does not match its artifacts.",
            )
        if (
            not isinstance(quality_score, (int, float))
            or isinstance(quality_score, bool)
            or not 1 <= quality_score <= 5
        ):
            raise CuratorHandoffError(
                "invalid_handoff",
                f"Set entry {index} qualityScore must be between 1 and 5.",
            )
        folder_key = _normalized_path(folder)
        csv_key = _normalized_path(csv_path)
        if folder_key in seen_folders or csv_key in seen_csvs:
            raise CuratorHandoffError(
                "invalid_handoff",
                "Curator handoff contains duplicate set paths.",
            )
        seen_folders.add(folder_key)
        seen_csvs.add(csv_key)
        normalized_sets.append(
            {
                "name": name,
                "folder": str(folder),
                "csv": str(csv_path),
                "caseCount": case_count,
                "qualityScore": quality_score,
            }
        )

    return {
        "valid": True,
        "outputRoot": str(output_root),
        "setCount": len(normalized_sets),
        "sets": normalized_sets,
    }


def main(argv: list[str] | None = None) -> int:
    """Run the hosted handoff validation CLI."""
    parser = argparse.ArgumentParser(
        description="Validate a hosted eval-curator handoff."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--repo-root", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        document = json.load(sys.stdin)
        payload = validate_handoff(args.repo_root, document)
        exit_code = 0
    except (json.JSONDecodeError, UnicodeError) as exc:
        payload = {
            "valid": False,
            "errorCode": "invalid_json",
            "message": f"Curator handoff is not valid JSON: {exc}",
        }
        exit_code = 2
    except CuratorHandoffError as exc:
        payload = {
            "valid": False,
            "errorCode": exc.error_code,
            "message": str(exc),
        }
        exit_code = 2
    except (OSError, RuntimeError, ValueError) as exc:
        payload = {
            "valid": False,
            "errorCode": "invalid_handoff",
            "message": f"Curator handoff validation failed safely: {exc}",
        }
        exit_code = 2

    print(json.dumps(payload))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
