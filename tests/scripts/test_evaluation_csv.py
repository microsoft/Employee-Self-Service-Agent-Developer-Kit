from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest
import yaml


SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "solutions"
    / "ess-maker-skills"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

import evaluation_csv  # noqa: E402


def test_passing_score_defaults_for_invalid_threshold():
    assert evaluation_csv._passing_score(None) == "70"


def test_regenerate_exports_creates_multi_turn_conversation_csv(tmp_path):
    set_folder = tmp_path / "evaluations" / "onboarding-multi-turn"
    set_folder.mkdir(parents=True)
    (set_folder / "onboarding.mcs.yml").write_text(
        "kind: EvaluationSet\n"
        "displayName: Onboarding Multi-Turn\n"
        "graders:\n"
        "  - kind: GeneralQualityGrader\n",
        encoding="utf-8",
    )
    (set_folder / "conversation.mcs.yml").write_text(
        "kind: MultiTurnEvaluationCase\n"
        "activities:\n"
        "  - activity:\n"
        "      value:\n"
        "        from:\n"
        "          role: user\n"
        "    text:\n"
        '      - "How do I enroll in benefits?"\n'
        "  - activity:\n"
        "      value:\n"
        "        from:\n"
        "          role: agent\n"
        "    text:\n"
        '      - "Open the Benefits portal and choose Enroll."\n'
        "  - activity:\n"
        "      value:\n"
        "        from:\n"
        "          role: user\n"
        "    text:\n"
        '      - "What is the deadline?"\n',
        encoding="utf-8",
    )

    paths = evaluation_csv.regenerate_evaluation_exports(
        tmp_path,
        timestamp="20260821-1200",
        strict=False,
    )

    assert len(paths) == 1
    assert paths[0].name == "20260821_Onboarding_Multi_Turn.csv"
    with paths[0].open(newline="", encoding="utf-8") as stream:
        rows = list(csv.reader(stream))
    assert rows == [
        ["conversationNumber", "question", "response"],
        ["1", "How do I enroll in benefits?",
         "Open the Benefits portal and choose Enroll."],
        ["1", "What is the deadline?", ""],
    ]


def test_regenerate_exports_creates_general_quality_csv(tmp_path):
    set_folder = tmp_path / "evaluations" / "general"
    set_folder.mkdir(parents=True)
    (set_folder / "general.mcs.yml").write_text(
        "kind: EvaluationSet\n"
        "displayName: General Quality\n"
        "graders:\n"
        "  - kind: GeneralQualityGrader\n",
        encoding="utf-8",
    )
    (set_folder / "case.mcs.yml").write_text(
        "kind: EvaluationData\n"
        "rows:\n"
        '  - input: "=unsafe prompt"\n',
        encoding="utf-8",
    )

    paths = evaluation_csv.regenerate_evaluation_exports(
        tmp_path,
        timestamp="20260821-1200",
        strict=False,
    )

    assert len(paths) == 1
    assert paths[0].name == "20260821_General_Quality.csv"
    with paths[0].open(newline="", encoding="utf-8") as stream:
        rows = list(csv.reader(stream))
    assert rows == [
        ["Prompt", "Expected response", "Test Method Type"],
        ["'=unsafe prompt", "", "GeneralQuality"],
    ]


def test_generate_set_csv_migrates_legacy_export_to_display_name_format(tmp_path):
    set_folder = tmp_path / "evaluations" / "compensation"
    exports = tmp_path / "evaluations" / "exports"
    set_folder.mkdir(parents=True)
    exports.mkdir()
    (set_folder / "compensation.mcs.yml").write_text(
        "kind: EvaluationSet\n"
        "displayName: Workday ProfileUpdates\n"
        "graders:\n"
        "  - kind: CompareMeaningGrader\n"
        "    threshold: 0.75\n",
        encoding="utf-8",
    )
    (set_folder / "case.mcs.yml").write_text(
        "kind: EvaluationData\n"
        "rows:\n"
        '  - input: "base compensation"\n'
        '    expectedOutput: "Returns compensation"\n',
        encoding="utf-8",
    )
    existing = exports / "compensation-eval-testset-20260820-0900.csv"
    existing.write_text("old\n", encoding="utf-8")

    output = evaluation_csv.generate_set_csv(
        set_folder,
        exports,
        timestamp="20260821-1200",
    )

    assert output == exports / "20260821_Workday_ProfileUpdates.csv"
    assert output.exists()
    assert not existing.exists()


def test_generate_set_csv_disambiguates_sanitized_name_collisions(tmp_path):
    evaluations = tmp_path / "evaluations"
    first = evaluations / "payroll-benefits-a"
    second = evaluations / "payroll-benefits-b"
    exports = evaluations / "exports"
    for folder, display_name in (
        (first, "Payroll/Benefits"),
        (second, "Payroll Benefits"),
    ):
        folder.mkdir(parents=True)
        (folder / "set.mcs.yml").write_text(
            "kind: EvaluationSet\n"
            f"displayName: {display_name}\n"
            "graders:\n  - kind: CompareMeaningGrader\n    threshold: 0.7\n",
            encoding="utf-8",
        )
        (folder / "case.mcs.yml").write_text(
            "kind: EvaluationData\nrows:\n  - input: test\n    expectedOutput: answer\n",
            encoding="utf-8",
        )

    first_output = evaluation_csv.generate_set_csv(
        first,
        exports,
        timestamp="20260828",
    )
    second_output = evaluation_csv.generate_set_csv(
        second,
        exports,
        timestamp="20260828",
    )

    assert first_output.name == (
        "20260828_Payroll_Benefits__payroll_benefits_a.csv"
    )
    assert second_output.name == (
        "20260828_Payroll_Benefits__payroll_benefits_b.csv"
    )
    assert first_output.is_file()
    assert second_output.is_file()


def _write_strict_set(tmp_path, *, grader="CompareMeaningGrader", expected="Answer"):
    folder = tmp_path / "evaluations" / "selected"
    folder.mkdir(parents=True)
    (folder / "set.mcs.yml").write_text(yaml.safe_dump({
        "kind": "EvaluationSet", "displayName": "Selected",
        "graders": [{"kind": grader, "threshold": 0.5}],
    }), encoding="utf-8")
    (folder / "case.mcs.yml").write_text(yaml.safe_dump({
        "kind": "EvaluationData",
        "rows": [{"input": "Question", "expectedOutput": expected}],
    }), encoding="utf-8")
    return folder


@pytest.mark.parametrize("grader,expected", [
    ("GeneralQualityGrader", "Answer"),
    ("UnknownGrader", "Answer"),
    ("CompareMeaningGrader", ""),
    ("CompareMeaningGrader", None),
    ("CompareMeaningGrader", " \n "),
])
def test_strict_export_rejection_preserves_previous_csv(tmp_path, grader, expected):
    folder = _write_strict_set(tmp_path, grader=grader, expected=expected)
    exports = folder.parent / "exports"
    exports.mkdir()
    previous = exports / "20260820_Selected.csv"
    previous.write_bytes(b"previous CSV\r\n")
    with pytest.raises(evaluation_csv.EvaluationMethodError):
        evaluation_csv.generate_set_csv(folder, exports, timestamp="20260821")
    assert previous.read_bytes() == b"previous CSV\r\n"
    assert list(exports.iterdir()) == [previous]


def test_failed_atomic_replace_preserves_same_day_and_older_csv(tmp_path, monkeypatch):
    folder = _write_strict_set(tmp_path)
    exports = folder.parent / "exports"
    exports.mkdir()
    current = exports / "20260821_Selected.csv"
    previous = exports / "20260820_Selected.csv"
    for path in (current, previous):
        path.write_bytes(b"original")

    def fail_replace(*args):
        raise PermissionError("file is open")

    monkeypatch.setattr(evaluation_csv.os, "replace", fail_replace)
    with pytest.raises(PermissionError, match="file is open"):
        evaluation_csv.generate_set_csv(folder, exports, timestamp="20260821")
    assert current.read_bytes() == previous.read_bytes() == b"original"
    assert set(exports.iterdir()) == {current, previous}


def test_compare_meaning_preserves_threshold_and_formula_safe_multiline_text(tmp_path):
    folder = _write_strict_set(tmp_path, expected='=answer,"quoted"\nnext | line')
    output = evaluation_csv.generate_set_csv(folder, folder.parent / "exports")
    with output.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.reader(stream))
    assert rows == [
        ["Prompt", "Expected response", "Test Method Type", "Passing Score"],
        ["Question", '\'=answer,"quoted"\nnext | line', "CompareMeaning", "50"],
    ]


def test_strict_export_rejects_mixed_child_kinds_before_creating_exports(tmp_path):
    folder = _write_strict_set(tmp_path)
    (folder / "conversation.mcs.yml").write_text(
        "kind: MultiTurnEvaluationCase\nactivities: []\n", encoding="utf-8"
    )
    exports = folder.parent / "exports"
    with pytest.raises(evaluation_csv.EvaluationMethodError, match="single-response"):
        evaluation_csv.generate_set_csv(folder, exports)
    assert not exports.exists()


def test_invalid_unselected_sibling_does_not_block_selected_export(tmp_path):
    folder = _write_strict_set(tmp_path)
    sibling = folder.parent / "unselected"
    sibling.mkdir()
    (sibling / "set.mcs.yml").write_text(
        "kind: EvaluationSet\n$kind: Unknown\n", encoding="utf-8"
    )
    output = evaluation_csv.generate_set_csv(folder, folder.parent / "exports")
    assert output.is_file()
