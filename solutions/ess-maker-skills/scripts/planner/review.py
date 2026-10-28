# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Spreadsheet-friendly review copies; imports propose changes, never apply them."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from .plan_model import Plan, _render_assignee

FIELDS = (
    "Plan version", "Plan objective", "Scenarios", "Pending decisions",
    "Task ID", "Workstream", "Role / owner", "Status", "Title", "Description", "Review notes",
)
EDITABLE = ("Title", "Description", "Review notes")


def _version(plan: Plan) -> str:
    snapshot = {key: plan.data.get(key) for key in ("projectId", "planId", "status", "configuringAgentName")}
    for collection, fields, order_key in (
        ("context", ("key", "value", "group", "description"), "key"),
        ("tasks", ("id", "title", "description", "stream", "state", "assignedTo", "produces", "consumes", "etag", "pendingSync", "pendingOutputs"), "id"),
        ("outputs", ("key", "kind", "attributes", "state", "producedByTaskId", "inventoryRef"), "key"),
    ):
        snapshot[collection] = [
            {key: row.get(key) for key in fields}
            for row in sorted(plan.data.get(collection, []), key=lambda row: row[order_key])
        ]
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    # Spreadsheet applications may evaluate formula-like strings even in quoted CSV cells.
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@", "'")) or text.startswith(("\t", "\r", "\n")) else text


def _text(value: str) -> str:
    return value[1:] if value.startswith("'") else value


def _rows(plan: Plan) -> list[dict[str, str]]:
    version = _version(plan)
    objective = plan.output_value_or_context("objective") or ""
    scenarios = "; ".join(plan.in_scope_scenarios().values())
    pending = "; ".join(
        f"{entry['key']}: {entry['value']} ({entry.get('description', '')})"
        for entry in plan.pending_decisions()
    )
    return [
        {key: _cell(value) for key, value in zip(FIELDS, (
            version, objective, scenarios, pending, task["id"], task.get("stream", ""),
            _render_assignee(task.get("assignedTo")),
            plan._task_state_label(task).split(" ", 1)[1],
            task.get("title", ""), task.get("description", ""), "",
        ))}
        for task in plan.ordered_tasks()
    ]


def export_review(plan: Plan, path: str | Path) -> None:
    """Write a new review copy; do not overwrite a colleague's unsaved review."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(_rows(plan))


def review_changes(plan: Plan, path: str | Path) -> list[dict[str, str]]:
    """Return title/description proposals and notes against an unchanged plan."""
    expected = {row["Task ID"]: row for row in _rows(plan)}
    seen: set[str] = set()
    changes: list[dict[str, str]] = []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(FIELDS):
            raise ValueError("Use the exported review columns without renaming or removing them.")
        for row in reader:
            task_id = row["Task ID"]
            if task_id not in expected or task_id in seen:
                raise ValueError("Review contains an unknown or duplicate Task ID; nothing was applied.")
            seen.add(task_id)
            original = expected[task_id]
            if any(row.get(key) != original[key] for key in FIELDS if key not in EDITABLE):
                raise ValueError(
                    "Review is stale or a read-only column changed. Export a fresh copy "
                    "and reconcile the notes; nothing was applied."
                )
            if None in row or any(value is None for value in row.values()):
                raise ValueError("Review contains a malformed row; nothing was applied.")
            task = plan.task(_text(task_id))
            proposal = {"taskId": task["id"], "etag": task.get("etag", "")}
            for column, field in (("Title", "title"), ("Description", "description"), ("Review notes", "reviewNote")):
                if row[column] != original[column]:
                    proposal[field] = _text(row[column])
            if "title" in proposal and not proposal["title"].strip():
                raise ValueError("A task title cannot be empty; nothing was applied.")
            if len(proposal) > 2:
                changes.append(proposal)
    if seen != expected.keys():
        raise ValueError("Keep every task row; request additions or removals in Review notes.")
    return changes
