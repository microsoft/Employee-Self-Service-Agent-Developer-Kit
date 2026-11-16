# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Append or remove single-response cases in an exact existing evaluation set."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from typing import Any

import yaml

from evaluation_csv import EvaluationCSVError, generate_set_csv, read_set_documents
from evaluation_method_policy import (
    EvaluationMethodError,
    load_evaluation_documents,
    validate_evaluation_documents,
)


class EvaluationAuthoringError(RuntimeError):
    """An authored case could not be saved or synchronized."""


def add_evaluation_case(
    set_folder: str | Path,
    prompt: str,
    expected_output: str,
) -> dict[str, Any]:
    """Append without overwriting prior cases, metadata, or parent identity."""
    folder = Path(set_folder).resolve()
    parent, cases = load_evaluation_documents(folder)
    orders = []
    for case in cases:
        extension = case.get("extensionData")
        order = extension.get("displayOrder") if isinstance(extension, dict) else None
        try:
            orders.append(int(order))
        except (TypeError, ValueError):
            continue
    document = {
        "kind": "EvaluationData",
        "rows": [{
            "source": "Imported", "input": prompt, "expectedOutput": expected_output,
        }],
        "extensionData": {
            "displayOrder": str(max([time.time_ns() // 1_000_000, *orders]) + 1),
        },
    }
    validate_evaluation_documents(parent, [*cases, document], context=str(folder))
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.casefold()).strip("-")[:60] or "case"
    stem = f"{folder.name[:60]}-{slug}"
    payload = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    suffix = 1
    while True:
        name = stem if suffix == 1 else f"{stem}-{suffix}"
        case_path = folder / f"{name}.mcs.yml"
        try:
            with case_path.open("x", encoding="utf-8", newline="") as stream:
                stream.write(payload)
            break
        except FileExistsError:
            suffix += 1
    try:
        csv_path = generate_set_csv(folder, folder.parent / "exports")
    except (EvaluationCSVError, EvaluationMethodError, OSError) as exc:
        raise EvaluationAuthoringError(
            f"Case saved at {case_path}, but CSV synchronization failed: {exc}. "
            "Regenerate the CSV after resolving the error; do not add the case again."
        ) from exc
    return {
        "status": "added",
        "setFolder": str(folder),
        "caseFile": str(case_path),
        "csv": str(csv_path),
        "rowCount": sum(len(case["rows"]) for case in cases) + 1,
    }


DEFAULT_BACKUP_ROOT = Path(".local") / "evaluation-delete-backups"


def _write_yaml_atomic(path: Path, document: dict[str, Any]) -> None:
    payload = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    handle, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(payload)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _unique_backup_dir(backup_root: Path, folder: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    suffix = 1
    while True:
        name = f"{stamp}-{folder.name}" if suffix == 1 else f"{stamp}-{folder.name}-{suffix}"
        candidate = backup_root / name
        try:
            candidate.mkdir(parents=True)
            return candidate
        except FileExistsError:
            suffix += 1


def remove_evaluation_cases(
    set_folder: str | Path,
    case_ids: list[str],
    backup_root: str | Path = DEFAULT_BACKUP_ROOT,
) -> dict[str, Any]:
    """Remove exactly the confirmed ``{file}:{row}`` cases, preserving all others.

    Case identities match ``evaluation_presentation.py --list-rows``. Every
    affected file is backed up before mutation and restored on write failure.
    Removing every case is rejected; whole-set deletion is a separate decision.
    """
    folder = Path(set_folder).resolve()
    if not case_ids:
        raise EvaluationAuthoringError("Select at least one case to remove.")
    if len(set(case_ids)) != len(case_ids):
        raise EvaluationAuthoringError("Each case may be selected only once.")
    _, documents = read_set_documents(folder)
    known: dict[str, tuple[Path, int, dict[str, Any]]] = {}
    for document, path in documents:
        rows = document.get("rows")
        for index, row in enumerate(rows if isinstance(rows, list) else [], 1):
            known[f"{path.name}:{index}"] = (path, index, row)
    unknown = [case_id for case_id in case_ids if case_id not in known]
    if unknown:
        raise EvaluationAuthoringError(
            f"Unknown case identities: {', '.join(unknown)}. Nothing was removed."
        )
    if len(case_ids) == len(known):
        raise EvaluationAuthoringError(
            "The selection includes every case in this set. Nothing was removed; "
            "confirm whole-set deletion separately instead."
        )

    selected: dict[Path, set[int]] = {}
    for case_id in case_ids:
        path, index, _ = known[case_id]
        selected.setdefault(path, set()).add(index)

    backup_dir = _unique_backup_dir(Path(backup_root).resolve(), folder)
    for path in selected:
        target = backup_dir / folder.name / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        if target.read_bytes() != path.read_bytes():
            raise EvaluationAuthoringError(
                f"Backup verification failed for {path}. Nothing was removed."
            )

    documents_by_path = {path: document for document, path in documents}
    deleted_files: list[str] = []
    updated_files: list[str] = []
    try:
        for path, indexes in selected.items():
            document = documents_by_path[path]
            remaining = [
                row for index, row in enumerate(document["rows"], 1)
                if index not in indexes
            ]
            if remaining:
                _write_yaml_atomic(path, {**document, "rows": remaining})
                updated_files.append(str(path))
            else:
                path.unlink()
                deleted_files.append(str(path))
    except OSError as exc:
        for path in selected:
            shutil.copy2(backup_dir / folder.name / path.name, path)
        raise EvaluationAuthoringError(
            f"Removal failed and the affected files were restored from {backup_dir}: {exc}"
        ) from exc

    removed = [
        {
            "caseId": case_id,
            "prompt": known[case_id][2].get("input"),
            "expectedResponse": known[case_id][2].get("expectedOutput"),
        }
        for case_id in case_ids
    ]
    result = {
        "status": "removed",
        "setFolder": str(folder),
        "removed": removed,
        "updatedFiles": updated_files,
        "deletedFiles": deleted_files,
        "backup": str(backup_dir),
        "rowCount": len(known) - len(case_ids),
    }
    try:
        result["csv"] = str(generate_set_csv(folder, folder.parent / "exports"))
    except (EvaluationCSVError, EvaluationMethodError, OSError) as exc:
        raise EvaluationAuthoringError(
            f"Cases removed (backup: {backup_dir}), but CSV synchronization failed: "
            f"{exc}. Regenerate the CSV after resolving the error; do not remove "
            "the cases again."
        ) from exc
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("--evaluation-folder", required=True)
    add_parser.add_argument("--input", required=True)
    add_parser.add_argument("--expected-output", required=True)
    remove_parser = subparsers.add_parser("remove")
    remove_parser.add_argument("--evaluation-folder", required=True)
    remove_parser.add_argument("--case-id", action="append", required=True)
    remove_parser.add_argument("--backup-root", default=str(DEFAULT_BACKUP_ROOT))
    args = parser.parse_args()
    try:
        if args.command == "remove":
            result = remove_evaluation_cases(
                args.evaluation_folder, args.case_id, args.backup_root
            )
        else:
            result = add_evaluation_case(
                args.evaluation_folder, args.input, args.expected_output
            )
    except (EvaluationAuthoringError, EvaluationCSVError, EvaluationMethodError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    from adk_telemetry import script_error_boundary

    with script_error_boundary("evaluation_authoring"):
        raise SystemExit(main())
