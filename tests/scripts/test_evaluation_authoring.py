import csv
from pathlib import Path

import pytest
import yaml

import evaluation_authoring
from evaluation_method_policy import EvaluationMethodError


def _set(tmp_path, count=1):
    folder = tmp_path / "evaluations" / "custom-pay"
    folder.mkdir(parents=True)
    parent = {
        "kind": "EvaluationSet", "displayName": "Pay",
        "graders": [{"kind": "CompareMeaningGrader", "threshold": 0.5}],
    }
    (folder / "set.mcs.yml").write_text(yaml.safe_dump(parent), encoding="utf-8")
    (folder / "original.mcs.yml").write_text(yaml.safe_dump({
        "kind": "EvaluationData",
        "rows": [{"input": "Old", "expectedOutput": "Preserve this."}] * count,
        "extensionData": {"displayOrder": "9999999999999"},
    }), encoding="utf-8")
    (folder / "review.json").write_text('{"status":"review_requested"}', encoding="utf-8")
    return folder


def test_append_keeps_old_files_and_uses_unique_filename_and_order(tmp_path):
    folder = _set(tmp_path)
    before = {path: path.read_bytes() for path in folder.iterdir()}
    first = evaluation_authoring.add_evaluation_case(folder, "New | prompt", "First\nanswer")
    second = evaluation_authoring.add_evaluation_case(folder, "New | prompt", "Other answer")
    assert first["caseFile"] != second["caseFile"]
    for path, content in before.items():
        assert path.read_bytes() == content
    first_doc = yaml.safe_load(Path(first["caseFile"]).read_text(encoding="utf-8"))
    second_doc = yaml.safe_load(Path(second["caseFile"]).read_text(encoding="utf-8"))
    assert int(first_doc["extensionData"]["displayOrder"]) > 9999999999999
    assert int(second_doc["extensionData"]["displayOrder"]) > int(
        first_doc["extensionData"]["displayOrder"]
    )
    with Path(second["csv"]).open(newline="", encoding="utf-8") as stream:
        rows = list(csv.reader(stream))
    assert len(rows) == 4
    assert rows[1][0:2] == ["Old", "Preserve this."]
    assert rows[2][0:2] == ["New | prompt", "First\nanswer"]
    assert rows[3][0:2] == ["New | prompt", "Other answer"]
    assert all(row[-2:] == ["CompareMeaning", "50"] for row in rows[1:])
    assert second["rowCount"] == 3


@pytest.mark.parametrize("count,prompt,expected", [
    (100, "New", "Answer"), (1, " ", "Answer"), (1, "New", ""),
])
def test_rejected_append_has_no_side_effects(tmp_path, count, prompt, expected):
    folder = _set(tmp_path, count)
    before = {path: path.read_bytes() for path in folder.iterdir()}
    with pytest.raises(EvaluationMethodError):
        evaluation_authoring.add_evaluation_case(folder, prompt, expected)
    assert {path: path.read_bytes() for path in folder.iterdir()} == before
    assert not (folder.parent / "exports").exists()


def test_csv_failure_reports_saved_case_and_recovery_without_false_success(tmp_path, monkeypatch):
    folder = _set(tmp_path)

    def fail_export(*args):
        raise PermissionError("locked CSV")

    monkeypatch.setattr(evaluation_authoring, "generate_set_csv", fail_export)
    with pytest.raises(evaluation_authoring.EvaluationAuthoringError, match="do not add the case again"):
        evaluation_authoring.add_evaluation_case(folder, "New", "Answer")
    assert (folder / "custom-pay-new.mcs.yml").is_file()


def _multi_row_set(tmp_path):
    folder = _set(tmp_path)
    (folder / "original.mcs.yml").write_text(yaml.safe_dump({
        "kind": "EvaluationData",
        "rows": [
            {"input": "Keep", "expectedOutput": "Kept."},
            {"input": "Drop", "expectedOutput": "Dropped."},
        ],
        "extensionData": {"displayOrder": "1"},
    }), encoding="utf-8")
    (folder / "negative.mcs.yml").write_text(yaml.safe_dump({
        "kind": "EvaluationData",
        "rows": [{"input": "Someone else's pay", "expectedOutput": "The agent should refuse."}],
        "extensionData": {"displayOrder": "2"},
    }), encoding="utf-8")
    return folder


def test_remove_deletes_only_selected_rows_backs_up_and_syncs_csv(tmp_path):
    folder = _multi_row_set(tmp_path)
    review = (folder / "review.json").read_bytes()
    result = evaluation_authoring.remove_evaluation_cases(
        folder, ["original.mcs.yml:2", "negative.mcs.yml:1"], tmp_path / "backups",
    )
    assert not (folder / "negative.mcs.yml").exists()
    remaining = yaml.safe_load((folder / "original.mcs.yml").read_text(encoding="utf-8"))
    assert remaining["rows"] == [{"input": "Keep", "expectedOutput": "Kept."}]
    assert remaining["extensionData"] == {"displayOrder": "1"}
    assert (folder / "review.json").read_bytes() == review
    assert [item["prompt"] for item in result["removed"]] == ["Drop", "Someone else's pay"]
    assert result["rowCount"] == 1
    backup = Path(result["backup"]) / folder.name
    assert sorted(path.name for path in backup.iterdir()) == ["negative.mcs.yml", "original.mcs.yml"]
    with Path(result["csv"]).open(newline="", encoding="utf-8") as stream:
        rows = list(csv.reader(stream))
    assert [row[0] for row in rows[1:]] == ["Keep"]


@pytest.mark.parametrize("case_ids", [
    ["missing.mcs.yml:1"],
    ["original.mcs.yml:1", "original.mcs.yml:2", "negative.mcs.yml:1"],
    ["original.mcs.yml:1", "original.mcs.yml:1"],
    [],
])
def test_rejected_remove_has_no_side_effects(tmp_path, case_ids):
    folder = _multi_row_set(tmp_path)
    before = {path: path.read_bytes() for path in folder.iterdir()}
    with pytest.raises(evaluation_authoring.EvaluationAuthoringError):
        evaluation_authoring.remove_evaluation_cases(folder, case_ids, tmp_path / "backups")
    assert {path: path.read_bytes() for path in folder.iterdir()} == before
    assert not (tmp_path / "backups").exists()
    assert not (folder.parent / "exports").exists()


def test_remove_restores_files_when_a_write_fails(tmp_path, monkeypatch):
    folder = _multi_row_set(tmp_path)
    before = {path: path.read_bytes() for path in folder.iterdir()}

    def fail_write(*args):
        raise PermissionError("locked")

    monkeypatch.setattr(evaluation_authoring, "_write_yaml_atomic", fail_write)
    with pytest.raises(evaluation_authoring.EvaluationAuthoringError, match="restored"):
        evaluation_authoring.remove_evaluation_cases(
            folder, ["negative.mcs.yml:1", "original.mcs.yml:2"], tmp_path / "backups",
        )
    assert {path: path.read_bytes() for path in folder.iterdir()} == before
