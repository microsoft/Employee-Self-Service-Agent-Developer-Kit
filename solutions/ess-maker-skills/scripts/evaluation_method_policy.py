# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Validate the Compare Meaning-only authoring and execution contract."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import yaml


MAX_EVALUATION_ROWS = 100


class EvaluationMethodError(ValueError):
    """An evaluation is not supported by the ADK evaluation feature."""


def document_kind(document: dict[str, Any], *, context: str) -> str | None:
    """Read local/native discriminators without accepting conflicting values."""
    if "kind" in document and "$kind" in document:
        if document["kind"] != document["$kind"]:
            raise EvaluationMethodError(f"{context}: conflicting kind and $kind.")
    return document.get("kind", document.get("$kind"))


def validate_evaluation_documents(
    parent: dict[str, Any],
    cases: list[dict[str, Any]],
    *,
    context: str = "Evaluation set",
    case_names: list[str] | None = None,
) -> None:
    """Validate supplied documents without repairing or mutating them."""
    if not isinstance(parent, dict) or document_kind(
        parent, context=context
    ) != "EvaluationSet":
        raise EvaluationMethodError(f"{context}: an EvaluationSet parent is required.")
    graders = parent.get("graders")
    if not isinstance(graders, list) or len(graders) != 1:
        raise EvaluationMethodError(
            f"{context}: exactly one CompareMeaningGrader is required; "
            "this feature supports Compare Meaning only."
        )
    grader = graders[0]
    if not isinstance(grader, dict) or document_kind(
        grader, context=f"{context} grader"
    ) != "CompareMeaningGrader":
        raise EvaluationMethodError(
            f"{context}: unsupported grader; this feature supports Compare Meaning only."
        )
    threshold = grader.get("threshold", 0.7)
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not 0 <= threshold <= 1
        or not math.isfinite(threshold)
    ):
        raise EvaluationMethodError(
            f"{context}: Compare Meaning threshold must be a number between 0 and 1."
        )
    if not isinstance(cases, list) or not cases:
        raise EvaluationMethodError(f"{context}: at least one EvaluationData case is required.")
    if case_names is not None and len(case_names) != len(cases):
        raise EvaluationMethodError(f"{context}: case identities do not match the supplied cases.")
    row_count = 0
    for index, case in enumerate(cases, 1):
        label = case_names[index - 1] if case_names is not None else f"case {index}"
        case_context = f"{context}, {label}"
        if not isinstance(case, dict) or document_kind(
            case, context=case_context
        ) != "EvaluationData":
            raise EvaluationMethodError(
                f"{case_context}: only single-response EvaluationData is supported; "
                "multi-turn cases cannot use this feature."
            )
        rows = case.get("rows")
        if not isinstance(rows, list) or not rows:
            raise EvaluationMethodError(f"{case_context}: rows must be a nonempty list.")
        for row_index, row in enumerate(rows, 1):
            for field in ("input", "expectedOutput"):
                value = row.get(field) if isinstance(row, dict) else None
                if not isinstance(value, str) or not value.strip():
                    raise EvaluationMethodError(
                        f"{case_context}, row {row_index}: {field} must be nonblank text."
                    )
            row_count += 1
    if row_count > MAX_EVALUATION_ROWS:
        raise EvaluationMethodError(
            f"{context}: {row_count} rows exceeds the {MAX_EVALUATION_ROWS}-case limit. "
            "Choose a separate set before adding more cases."
        )


def _load_named_documents(
    set_folder: str | Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Read one exact set folder, retaining all child kinds for validation."""
    folder = Path(set_folder)
    parents: list[dict[str, Any]] = []
    cases: list[dict[str, Any]] = []
    names: list[str] = []
    for path in sorted(folder.glob("*.mcs.yml")):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise EvaluationMethodError(f"Unable to read evaluation {path}: {exc}") from exc
        if not isinstance(document, dict):
            raise EvaluationMethodError(f"{path}: evaluation YAML must contain an object.")
        if document_kind(document, context=str(path)) == "EvaluationSet":
            parents.append(document)
        else:
            cases.append(document)
            names.append(path.name)
    if len(parents) != 1:
        raise EvaluationMethodError(
            f"{folder}: exactly one EvaluationSet parent is required; found {len(parents)}."
        )
    return parents[0], cases, names


def load_evaluation_documents(
    set_folder: str | Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Read the exact parent and all children, without filtering invalid cases."""
    parent, cases, _ = _load_named_documents(set_folder)
    return parent, cases


def validate_evaluation_folder(set_folder: str | Path) -> None:
    """Validate an exact local set before export, promotion, push, or Run."""
    parent, cases, names = _load_named_documents(set_folder)
    validate_evaluation_documents(parent, cases, context=str(set_folder), case_names=names)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-folder", required=True)
    args = parser.parse_args()
    try:
        validate_evaluation_folder(args.evaluation_folder)
    except EvaluationMethodError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}))
        return 1
    print(json.dumps({"status": "valid", "method": "CompareMeaning"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
