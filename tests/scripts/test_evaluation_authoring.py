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
    assert second["caseCount"] == 3


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
