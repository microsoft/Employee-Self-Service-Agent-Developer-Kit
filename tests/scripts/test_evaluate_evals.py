from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "solutions"
    / "ess-maker-skills"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

import evaluate_evals  # noqa: E402


def test_resolve_evaluation_folder_accepts_exact_absolute_path(tmp_path):
    set_folder = tmp_path / "workspace" / "evaluations" / "compensation"
    set_folder.mkdir(parents=True)

    resolved = evaluate_evals.resolve_evaluation_folder(
        str(set_folder),
        tmp_path,
    )

    assert resolved == set_folder.resolve()


def test_resolve_evaluation_folder_accepts_solution_relative_path(
    tmp_path,
    monkeypatch,
):
    set_folder = tmp_path / "workspace" / "evaluations" / "compensation"
    set_folder.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    resolved = evaluate_evals.resolve_evaluation_folder(
        "workspace/evaluations/compensation",
        tmp_path,
    )

    assert resolved == set_folder.resolve()


def test_resolve_evaluation_folder_rejects_missing_path(tmp_path):
    try:
        evaluate_evals.resolve_evaluation_folder(
            "workspace/evaluations/missing",
            tmp_path,
        )
    except FileNotFoundError as exc:
        assert str(exc) == "workspace/evaluations/missing"
    else:
        raise AssertionError("Expected missing evaluation folder to fail")


def test_report_disclaimer_keeps_quality_errors_visible(capsys):
    evaluate_evals.render_report([{
        "category": "Selected", "total_cases": 1, "sampled": 1,
        "error": "Quality judge unavailable",
    }], "Agent", 1)
    report = capsys.readouterr().out
    assert "not whether your agent passes the tests in your tenant" in report
    assert "Run the evaluation in Copilot Studio" in report
    assert "ERROR: Quality judge unavailable" in report
