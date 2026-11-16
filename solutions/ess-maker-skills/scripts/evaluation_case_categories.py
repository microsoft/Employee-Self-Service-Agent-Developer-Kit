# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Store maker-confirmed case categories locally beside an evaluation set.

Categories are keyed by a fingerprint of each case's prompt and expected
response, so removing other rows never shifts them, and editing a case clears
its stale category for reclassification. The sidecar is local-only: deployment
and review read only ``*.mcs.yml`` and ``review.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from evaluation_csv import EvaluationCSVError, read_set_documents


CATEGORIES_FILENAME = "case-categories.json"
CATEGORIES = ("positive", "boundary", "negative", "out_of_scope")


class CaseCategoryError(ValueError):
    """Categories could not be read or saved for the selected set."""


def case_fingerprint(prompt: str, expected_response: str) -> str:
    payload = json.dumps([prompt, expected_response], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _rows(folder: Path) -> list[tuple[str, str]]:
    _, documents = read_set_documents(folder)
    rows = []
    for document, path in documents:
        items = document.get("rows")
        for index, row in enumerate(items if isinstance(items, list) else [], 1):
            if isinstance(row, dict):
                rows.append((
                    f"{path.name}:{index}",
                    case_fingerprint(
                        str(row.get("input") or ""),
                        str(row.get("expectedOutput") or ""),
                    ),
                ))
    return rows


def _load(folder: Path) -> dict[str, str]:
    path = folder / CATEGORIES_FILENAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    cases = data.get("cases") if isinstance(data, dict) else None
    if not isinstance(cases, dict):
        return {}
    return {
        str(key): value for key, value in cases.items()
        if value in CATEGORIES
    }


def load_case_categories(set_folder: str | Path) -> dict[str, str | None]:
    """Return ``{case_id: category-or-None}`` for every current case."""
    folder = Path(set_folder).resolve()
    stored = _load(folder)
    return {case_id: stored.get(fingerprint) for case_id, fingerprint in _rows(folder)}


def save_case_categories(
    set_folder: str | Path,
    assignments: dict[str, str],
) -> dict[str, Any]:
    """Merge confirmed assignments and drop entries for cases that no longer exist."""
    folder = Path(set_folder).resolve()
    invalid = sorted({value for value in assignments.values() if value not in CATEGORIES})
    if invalid:
        raise CaseCategoryError(
            f"Unknown categories: {', '.join(invalid)}. Use one of: {', '.join(CATEGORIES)}."
        )
    rows = dict(_rows(folder))
    unknown = sorted(set(assignments) - set(rows))
    if unknown:
        raise CaseCategoryError(
            f"Unknown case identities: {', '.join(unknown)}. Nothing was saved."
        )
    stored = _load(folder)
    current = set(rows.values())
    merged = {key: value for key, value in stored.items() if key in current}
    for case_id, category in assignments.items():
        merged[rows[case_id]] = category
    path = folder / CATEGORIES_FILENAME
    handle, temp_name = tempfile.mkstemp(dir=folder, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            json.dump({"schemaVersion": 1, "cases": merged}, stream, indent=2)
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return {
        "status": "saved",
        "setFolder": str(folder),
        "categories": load_case_categories(folder),
    }


def _assignment(value: str) -> tuple[str, str]:
    case_id, separator, category = value.rpartition("=")
    if not separator or not case_id:
        raise argparse.ArgumentTypeError("Use --assign '{case_id}={category}'.")
    return case_id, category


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    show = subparsers.add_parser("show")
    show.add_argument("--evaluation-folder", required=True)
    save = subparsers.add_parser("set")
    save.add_argument("--evaluation-folder", required=True)
    save.add_argument("--assign", action="append", required=True, type=_assignment)
    args = parser.parse_args()
    try:
        if args.command == "show":
            result: dict[str, Any] = {
                "categories": load_case_categories(args.evaluation_folder),
            }
        else:
            assignments: dict[str, str] = {}
            for case_id, category in args.assign:
                if case_id in assignments:
                    raise CaseCategoryError(f"Case {case_id} was assigned more than once.")
                assignments[case_id] = category
            result = save_case_categories(args.evaluation_folder, assignments)
    except (CaseCategoryError, EvaluationCSVError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
