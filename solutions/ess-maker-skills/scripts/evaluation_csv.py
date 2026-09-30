# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Generate Copilot Studio evaluation CSV exports from local YAML files."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import io
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

import yaml

from evaluation_method_policy import (
    EvaluationMethodError,
    document_kind,
    validate_evaluation_documents,
)


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
        except (EvaluationCSVError, EvaluationMethodError, OSError):
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
    for path in sorted(set_folder.glob("*.mcs.yml")):
        document = _load_yaml(path)
        kind = document_kind(document, context=str(path))
        if kind == "EvaluationSet":
            if parent is not None:
                raise EvaluationCSVError(f"Multiple EvaluationSet parents in {set_folder}")
            parent = document
        else:
            cases.append((document, path))
    if parent is None:
        raise EvaluationCSVError(
            f"EvaluationSet parent not found in {set_folder}"
        )
    cases.sort(key=lambda item: _display_order(item[0], item[1]))
    return parent, cases


def read_set_documents(set_folder: str | Path) -> tuple[
    dict[str, Any], list[tuple[dict[str, Any], Path]],
]:
    """Read the parent and ordered cases with their source identities."""
    return _set_documents(Path(set_folder))


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
            and document_kind(item, context="CSV grader") == "CompareMeaningGrader"
        ),
        None,
    )
    has_general = any(
        isinstance(item, dict)
        and document_kind(item, context="CSV grader") == "GeneralQualityGrader"
        for item in graders
    )
    has_expected = any(row.get("expectedOutput") not in (None, "") for row in rows)

    if compare is not None and (has_expected or not has_general):
        return "CompareMeaning", _passing_score(compare.get("threshold", 0.7))
    return "GeneralQuality", None


def _activity_role(activity: dict[str, Any]) -> str | None:
    outer = activity.get("activity")
    if not isinstance(outer, dict):
        return None
    value = outer.get("value")
    if not isinstance(value, dict):
        return None
    sender = value.get("from")
    if not isinstance(sender, dict):
        return None
    role = sender.get("role")
    return role if isinstance(role, str) else None


def _activity_text(activity: dict[str, Any]) -> str:
    text_field = activity.get("text")
    if isinstance(text_field, list) and text_field:
        first = text_field[0]
        return "" if first is None else str(first)
    if isinstance(text_field, str):
        return text_field
    return ""


def _multi_turn_pairs(document: dict[str, Any]) -> list[tuple[str, str]]:
    """Flatten a MultiTurnEvaluationCase into (question, response) pairs.

    Mirrors the Copilot Studio conversation import template: each user turn is
    a question row; the immediately following agent turn (if any) supplies the
    optional reference response.
    """
    pairs: list[tuple[str, str]] = []
    activities = document.get("activities")
    if not isinstance(activities, list):
        return pairs
    pending_question: str | None = None
    for activity in activities:
        if not isinstance(activity, dict):
            continue
        role = _activity_role(activity)
        text = _activity_text(activity)
        if role == "user":
            if pending_question is not None:
                pairs.append((pending_question, ""))
            pending_question = text
        elif role == "agent" and pending_question is not None:
            pairs.append((pending_question, text))
            pending_question = None
    if pending_question is not None:
        pairs.append((pending_question, ""))
    return pairs


def _resolve_export_path(
    parent: dict[str, Any],
    folder: Path,
    exports: Path,
    timestamp: str | None,
) -> tuple[Path, set[Path]]:
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
    return output, {*legacy_exports, *dated_exports} - {output}


def _write_export(output: Path, content: str, stale_exports: set[Path]) -> None:
    """Replace the preview atomically before removing superseded exports."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", newline="", encoding="utf-8",
            dir=output.parent, prefix=".evaluation-", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    for stale in stale_exports:
        stale.unlink(missing_ok=True)


def generate_set_csv(
    set_folder: str | Path,
    exports_folder: str | Path,
    timestamp: str | None = None,
    *,
    strict: bool = True,
) -> Path:
    """Generate or refresh one evaluation set's CSV export.

    Feature callers are strict by default. Explicit ``strict=False`` is only
    for read-only export of historical formats during remote refresh.
    """
    folder = Path(set_folder)
    exports = Path(exports_folder)
    parent, case_documents = _set_documents(folder)
    if strict:
        validate_evaluation_documents(
            parent, [document for document, _ in case_documents], context=str(folder),
            case_names=[path.name for _, path in case_documents],
        )

    single_turn_docs = [
        (document, path)
        for document, path in case_documents
        if document_kind(document, context=str(path)) == "EvaluationData"
    ]
    multi_turn_docs = [
        (document, path)
        for document, path in case_documents
        if document_kind(document, context=str(path)) == "MultiTurnEvaluationCase"
    ]
    if multi_turn_docs and single_turn_docs:
        raise EvaluationCSVError(
            f"{folder}: mixed single-turn/multi-turn sets cannot be exported without losing cases."
        )
    content = io.StringIO(newline="")
    writer = csv.writer(content, quoting=csv.QUOTE_MINIMAL)

    if multi_turn_docs and not single_turn_docs:
        writer.writerow(["conversationNumber", "question", "response"])
        for index, (document, _) in enumerate(multi_turn_docs, start=1):
            for question, response in _multi_turn_pairs(document):
                writer.writerow([
                    index,
                    _formula_safe(question),
                    _formula_safe(response),
                ])
        output, stale = _resolve_export_path(parent, folder, exports, timestamp)
        _write_export(output, content.getvalue(), stale)
        return output

    rows: list[dict[str, Any]] = []
    for document, _ in single_turn_docs:
        document_rows = document.get("rows")
        if isinstance(document_rows, list):
            rows.extend(row for row in document_rows if isinstance(row, dict))

    method, passing_score = _grader(parent, rows)
    headers = ["Prompt", "Expected response", "Test Method Type"]
    if passing_score is not None:
        headers.append("Passing Score")

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
    output, stale = _resolve_export_path(parent, folder, exports, timestamp)
    _write_export(output, content.getvalue(), stale)
    return output


def regenerate_evaluation_exports(
    agent_folder: str | Path,
    timestamp: str | None = None,
    *,
    strict: bool = True,
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
        generated.append(generate_set_csv(set_folder, exports, timestamp, strict=strict))
    return generated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-folder", required=True)
    parser.add_argument("--exports-folder", required=True)
    args = parser.parse_args()
    try:
        output = generate_set_csv(args.evaluation_folder, args.exports_folder)
    except (EvaluationCSVError, EvaluationMethodError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1
    print(json.dumps({"status": "exported", "csv": str(output.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
