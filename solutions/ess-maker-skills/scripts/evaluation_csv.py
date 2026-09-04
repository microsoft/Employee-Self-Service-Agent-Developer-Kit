# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Generate Copilot Studio evaluation CSV exports from local YAML files."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
import re
from typing import Any

import yaml


class EvaluationCSVError(ValueError):
    """Raised when evaluation YAML cannot be converted to a CSV export."""


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise EvaluationCSVError(
            f"Unable to read evaluation YAML {path}: {exc}"
        ) from exc
    if not isinstance(content, dict):
        raise EvaluationCSVError(
            f"Evaluation YAML must contain an object: {path}"
        )
    return content


def _formula_safe(value: Any) -> str:
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


def _passing_score(threshold: Any) -> str:
    try:
        score = float(threshold) * 100
    except (TypeError, ValueError):
        score = 70.0
    return str(int(score)) if score.is_integer() else f"{score:g}"


def _export_stem(parent: dict[str, Any], folder: Path) -> str:
    display_name = str(parent.get("displayName") or folder.name).strip()
    safe_name = re.sub(r"[^A-Za-z0-9]+", "_", display_name).strip("_")
    return safe_name or "Evaluation_Set"


def evaluation_export_stem(set_folder: str | Path) -> str:
    """Return the collision-safe filename stem for an EvaluationSet."""
    folder = Path(set_folder)
    parent, _ = _set_documents(folder)
    return _unique_export_stem(parent, folder)


def _unique_export_stem(parent: dict[str, Any], folder: Path) -> str:
    """Disambiguate sets whose display names sanitize to the same filename."""
    export_stem = _export_stem(parent, folder)
    collisions = []
    for candidate in folder.parent.iterdir():
        if not candidate.is_dir() or candidate.name.casefold() == "exports":
            continue
        try:
            candidate_parent, _ = _set_documents(candidate)
        except (EvaluationCSVError, OSError):
            continue
        if _export_stem(candidate_parent, candidate).casefold() == (
            export_stem.casefold()
        ):
            collisions.append(candidate)
    if len(collisions) <= 1:
        return export_stem
    folder_stem = re.sub(r"[^A-Za-z0-9]+", "_", folder.name).strip("_")
    return f"{export_stem}__{folder_stem or 'set'}"


def _display_order(document: dict[str, Any], path: Path) -> tuple[int, str]:
    extension_data = document.get("extensionData")
    raw = extension_data.get("displayOrder") if isinstance(
        extension_data, dict
    ) else None
    try:
        return int(raw), path.name
    except (TypeError, ValueError):
        return 0, path.name


def _set_documents(set_folder: Path) -> tuple[
    dict[str, Any],
    list[tuple[dict[str, Any], Path]],
]:
    parent = None
    cases: list[tuple[dict[str, Any], Path]] = []
    for path in set_folder.glob("*.mcs.yml"):
        document = _load_yaml(path)
        kind = document.get("kind")
        if kind == "EvaluationSet":
            parent = document
        elif kind == "EvaluationData":
            cases.append((document, path))
    if parent is None:
        raise EvaluationCSVError(
            f"EvaluationSet parent not found in {set_folder}"
        )
    cases.sort(key=lambda item: _display_order(item[0], item[1]))
    return parent, cases


def _grader(parent: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[
    str,
    str | None,
]:
    graders = parent.get("graders")
    graders = graders if isinstance(graders, list) else []
    compare = next(
        (
            item for item in graders
            if isinstance(item, dict)
            and item.get("kind") == "CompareMeaningGrader"
        ),
        None,
    )
    has_general = any(
        isinstance(item, dict)
        and item.get("kind") == "GeneralQualityGrader"
        for item in graders
    )
    has_expected = any(row.get("expectedOutput") not in (None, "") for row in rows)

    if compare is not None and (has_expected or not has_general):
        return "CompareMeaning", _passing_score(compare.get("threshold", 0.7))
    return "GeneralQuality", None


def generate_set_csv(
    set_folder: str | Path,
    exports_folder: str | Path,
    timestamp: str | None = None,
) -> Path:
    """Generate or refresh one evaluation set's CSV export."""
    folder = Path(set_folder)
    exports = Path(exports_folder)
    parent, case_documents = _set_documents(folder)

    rows: list[dict[str, Any]] = []
    for document, _ in case_documents:
        document_rows = document.get("rows")
        if isinstance(document_rows, list):
            rows.extend(row for row in document_rows if isinstance(row, dict))

    method, passing_score = _grader(parent, rows)
    headers = ["Prompt", "Expected response", "Test Method Type"]
    if passing_score is not None:
        headers.append("Passing Score")

    exports.mkdir(parents=True, exist_ok=True)
    suffix = timestamp or datetime.now().strftime("%Y%m%d")
    date = re.sub(r"[^0-9]", "", suffix)[:8]
    if len(date) != 8:
        date = datetime.now().strftime("%Y%m%d")
    export_stem = _unique_export_stem(parent, folder)
    output = exports / f"{date}_{export_stem}.csv"

    legacy_exports = list(exports.glob(f"{folder.name}-eval-testset-*.csv"))
    dated_exports = [
        path for path in exports.glob("*_*.csv")
        if path.name.split("_", 1)[-1] == f"{export_stem}.csv"
    ]
    for stale in {*legacy_exports, *dated_exports} - {output}:
        stale.unlink()

    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
        for row in rows:
            values = [
                _formula_safe(row.get("input")),
                _formula_safe(row.get("expectedOutput")),
                method,
            ]
            if passing_score is not None:
                values.append(passing_score)
            writer.writerow(values)
    return output


def regenerate_evaluation_exports(
    agent_folder: str | Path,
    timestamp: str | None = None,
) -> list[Path]:
    """Generate CSV exports for every EvaluationSet under an agent folder."""
    agent = Path(agent_folder)
    evaluations = agent / "evaluations"
    if not evaluations.is_dir():
        return []
    exports = evaluations / "exports"
    generated = []
    for set_folder in sorted(evaluations.iterdir()):
        if not set_folder.is_dir() or set_folder.name.casefold() == "exports":
            continue
        if not any(
            _load_yaml(path).get("kind") == "EvaluationSet"
            for path in set_folder.glob("*.mcs.yml")
        ):
            continue
        generated.append(generate_set_csv(set_folder, exports, timestamp))
    return generated
