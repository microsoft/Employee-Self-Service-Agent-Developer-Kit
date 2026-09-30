# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Render complete evaluation previews from authoritative local artifacts."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import html
import json
from pathlib import Path
import re

from evaluation_csv import EvaluationCSVError, generate_set_csv, read_set_documents
from evaluation_method_policy import EvaluationMethodError, validate_evaluation_documents


MAKER_ACTIONS = (
    "Mark this test set ready for review",
    "Run this test set in Copilot Studio",
    "Edit this test set",
    "Run another quality review",
)
SECTIONS = (
    ("in_scope", "Positive cases / In scope",
     "These prompts cover supported requests, including imperfect wording where appropriate."),
    ("out_of_scope", "Out-of-scope cases",
     "These prompts test how the agent handles requests outside this scenario."),
    ("other_negative", "Other negative cases",
     "These prompts test other limitations, such as privacy restrictions within the scenario."),
    ("unclassified", "Additional cases",
     "These cases are shown without assuming whether they are inside or outside the scenario."),
)


class EvaluationPresentationError(ValueError):
    """A preview cannot be rendered truthfully from the provided context."""


@dataclass(frozen=True)
class PreviewRow:
    case_id: str
    prompt: str
    expected_response: str


def _markdown_text(text: str) -> str:
    escaped = html.escape(text, quote=False)
    escaped = escaped.replace("\\", "\\\\").replace("|", "&#124;")
    escaped = re.sub(r"([`*_\[\]])", r"\\\1", escaped)
    return escaped.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def load_preview_rows(set_folder: str | Path) -> tuple[str, list[PreviewRow]]:
    parent, documents = read_set_documents(set_folder)
    validate_evaluation_documents(
        parent, [document for document, _ in documents], context=str(set_folder),
        case_names=[path.name for _, path in documents],
    )
    rows = [
        PreviewRow(f"{path.name}:{index}", row["input"], row["expectedOutput"])
        for document, path in documents
        for index, row in enumerate(document["rows"], 1)
    ]
    return str(parent.get("displayName") or Path(set_folder).name), rows


def render_preview(
    name: str,
    rows: list[PreviewRow],
    csv_path: str | Path,
    groups: dict[str, str],
    *,
    include_actions: bool = False,
) -> str:
    """Group by explicit semantic context, never by filename or refusal text."""
    known_ids = {row.case_id for row in rows}
    if len(known_ids) != len(rows):
        raise EvaluationPresentationError("Preview case identities must be unique.")
    unknown = set(groups) - known_ids
    if unknown:
        raise EvaluationPresentationError(f"Unknown case identities: {', '.join(sorted(unknown))}")
    allowed = {key for key, _, _ in SECTIONS}
    if set(groups.values()) - allowed:
        raise EvaluationPresentationError("Unknown preview section.")
    path = Path(csv_path).resolve()
    if not path.is_file():
        raise EvaluationPresentationError(f"Evaluation CSV does not exist: {path}")
    lines = [
        f"### Eval generated - {_markdown_text(name)}", "",
        "Here's the evaluation set for your scenario. You can edit, remove, or add "
        "prompts before deciding what to do next.", "",
    ]
    for key, heading, explanation in SECTIONS:
        selected = [row for row in rows if groups.get(row.case_id, "unclassified") == key]
        if not selected and key in ("other_negative", "unclassified"):
            continue
        lines.extend([f"#### {heading}", "", explanation, ""])
        if not selected:
            lines.extend(["No cases in this section.", ""])
            continue
        lines.extend(["| Prompt | Expected Response |", "|---|---|"])
        lines.extend(
            f"| {_markdown_text(row.prompt)} | {_markdown_text(row.expected_response)} |"
            for row in selected
        )
        lines.append("")
    lines.extend([f"[Download the evaluation CSV]({path.as_uri()})", ""])
    if include_actions:
        lines.extend(["What would you like to do next?", ""])
        lines.extend(f"- **{action}**" for action in MAKER_ACTIONS)
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-folder", required=True)
    parser.add_argument("--in-scope", action="append", default=[])
    parser.add_argument("--out-of-scope", action="append", default=[])
    parser.add_argument("--other-negative", action="append", default=[])
    parser.add_argument("--include-actions", action="store_true")
    parser.add_argument("--list-rows", action="store_true")
    args = parser.parse_args()
    try:
        name, rows = load_preview_rows(args.evaluation_folder)
        if args.list_rows:
            print(json.dumps({"name": name, "rows": [asdict(row) for row in rows]}, indent=2))
            return 0
        groups: dict[str, str] = {}
        for key in ("in_scope", "out_of_scope", "other_negative"):
            for case_id in getattr(args, key):
                if case_id in groups:
                    raise EvaluationPresentationError(
                        f"Case {case_id} was assigned more than one section."
                    )
                groups[case_id] = key
        folder = Path(args.evaluation_folder)
        csv_path = generate_set_csv(folder, folder.parent / "exports")
        print(render_preview(name, rows, csv_path, groups, include_actions=args.include_actions))
    except (EvaluationPresentationError, EvaluationCSVError, EvaluationMethodError, OSError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
