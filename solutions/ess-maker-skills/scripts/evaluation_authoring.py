# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Append a single-response case to an exact existing evaluation set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import time
from typing import Any

import yaml

from evaluation_csv import EvaluationCSVError, generate_set_csv
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("add",))
    parser.add_argument("--evaluation-folder", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--expected-output", required=True)
    args = parser.parse_args()
    try:
        result = add_evaluation_case(
            args.evaluation_folder, args.input, args.expected_output
        )
    except (EvaluationAuthoringError, EvaluationMethodError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
