from __future__ import annotations

import csv
import sys
from pathlib import Path


SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "solutions"
    / "ess-maker-skills"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

import evaluation_csv  # noqa: E402


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
            f"displayName: {display_name}\n",
            encoding="utf-8",
        )
        (folder / "case.mcs.yml").write_text(
            "kind: EvaluationData\nrows:\n  - input: test\n",
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
