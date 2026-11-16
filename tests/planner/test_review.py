# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline spreadsheet review round-trip, identity, and escaping regressions."""

import csv
import json

import pytest

from planner import cli, review
from planner.plan_model import Plan, new_task


def _plan():
    plan = Plan.new(objective="HR rollout")
    plan.add_task(new_task("T1", "Set up environment", description="Verify access first."))
    plan.add_task(new_task("T2", "=not-a-formula", description="Line one\nLine two"))
    plan.set_system("hr-profile", "Not sure yet")
    return plan


def _read(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=review.FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_review_is_editable_without_mutating_plan(tmp_path):
    plan = _plan()
    before = json.dumps(plan.data, sort_keys=True)
    path = tmp_path / "review.csv"
    review.export_review(plan, path)
    rows = _read(path)
    assert rows[1]["Title"] == "'=not-a-formula"
    assert "Not sure yet" in rows[0]["Pending decisions"]
    assert review.review_changes(plan, path) == []
    rows[0]["Title"] = "Prepare the shared environment"
    rows[0]["Review notes"] = "Please nominate an admin; I don't know who yet."
    _write(path, rows)
    proposals = review.review_changes(plan, path)
    assert proposals == [{
        "taskId": "T1", "etag": "", "title": "Prepare the shared environment",
        "reviewNote": "Please nominate an admin; I don't know who yet.",
    }]
    assert json.dumps(plan.data, sort_keys=True) == before


@pytest.mark.parametrize("change", ["task", "context", "etag", "owner"])
def test_stale_review_is_rejected(tmp_path, change):
    plan = _plan()
    path = tmp_path / "review.csv"
    review.export_review(plan, path)
    if change == "task":
        plan.update_task("T1", title="New shared title")
    elif change == "context":
        plan.set_system("hr-profile", "Workday")
    elif change == "etag":
        plan.task("T1")["etag"] = "new-etag"
    else:
        plan.assign_task("T1", role_id="PowerPlatformEnvironmentMaker")
    with pytest.raises(ValueError, match="stale"):
        review.review_changes(plan, path)


def test_refreshed_provenance_does_not_make_review_stale(tmp_path):
    plan = _plan()
    path = tmp_path / "review.csv"
    review.export_review(plan, path)
    for entry in plan.context:
        entry["provenance"] = {"createdAt": "new-read-time", "source": "Agent"}
    plan.data["syncedAt"] = "new-read-time"
    assert review.review_changes(plan, path) == []


@pytest.mark.parametrize("malformation", ["duplicate", "unknown", "missing", "read-only"])
def test_review_cannot_silently_reassign_or_drop_tasks(tmp_path, malformation):
    plan = _plan()
    path = tmp_path / "review.csv"
    review.export_review(plan, path)
    rows = _read(path)
    if malformation == "duplicate":
        rows.append(rows[0])
    elif malformation == "unknown":
        rows[0]["Task ID"] = "unknown"
    elif malformation == "missing":
        rows.pop()
    else:
        rows[0]["Status"] = "Complete"
    _write(path, rows)
    with pytest.raises(ValueError):
        review.review_changes(plan, path)


def test_export_never_overwrites_colleague_review(tmp_path):
    path = tmp_path / "review.csv"
    path.write_text("Existing review", encoding="utf-8")
    with pytest.raises(FileExistsError):
        review.export_review(_plan(), path)
    assert path.read_text(encoding="utf-8") == "Existing review"


def test_review_cli_outputs_proposals_only(tmp_path, capsys):
    plan_path, review_path = tmp_path / "plan.json", tmp_path / "review.csv"
    _plan().save_all(plan_path)
    before = plan_path.read_bytes()
    assert cli.main(["--plan", str(plan_path), "export-review", "--output", str(review_path)]) == 0
    capsys.readouterr()
    assert cli.main(["--plan", str(plan_path), "review-changes", "--input", str(review_path)]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert plan_path.read_bytes() == before
