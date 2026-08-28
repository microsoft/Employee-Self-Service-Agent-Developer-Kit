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

import evaluation_promotion  # noqa: E402


def _write_set(folder: Path) -> None:
    folder.mkdir(parents=True)
    (folder / "compensation.mcs.yml").write_text(
        "kind: EvaluationSet\n"
        "graders:\n"
        "  - kind: CompareMeaningGrader\n"
        "    threshold: 0.7\n",
        encoding="utf-8",
    )
    (folder / "case.mcs.yml").write_text(
        "kind: EvaluationData\n"
        "rows:\n"
        "  - input: What is my compensation?\n"
        "    expectedOutput: Show the employee's compensation.\n",
        encoding="utf-8",
    )


def test_promote_copies_set_and_keeps_workspace_source(tmp_path):
    workspace = tmp_path / "workspace" / "evaluations"
    agent = tmp_path / "agent"
    source = workspace / "compensation"
    _write_set(source)

    result = evaluation_promotion.promote_workspace_set(
        workspace,
        agent,
        "compensation",
    )

    destination = agent / "evaluations" / "compensation"
    assert source.is_dir()
    assert destination.is_dir()
    assert Path(result["csv"]).is_file()
    assert result["resumed"] is False


def test_promote_resumes_identical_staging_without_baseline(tmp_path):
    workspace = tmp_path / "workspace" / "evaluations"
    agent = tmp_path / "agent"
    source = workspace / "compensation"
    destination = agent / "evaluations" / "compensation"
    _write_set(source)
    _write_set(destination)
    (source / "review.json").write_text(
        '{"status":"review_requested"}',
        encoding="utf-8",
    )
    (destination / "review.json").write_text(
        '{"status":"review_requested"}',
        encoding="utf-8",
    )

    result = evaluation_promotion.promote_workspace_set(
        workspace,
        agent,
        "compensation",
    )

    assert result["resumed"] is True
    assert result["replaced"] is False
    assert source.is_dir()
    assert destination.is_dir()


def test_promote_does_not_resume_when_staged_copy_differs(tmp_path):
    workspace = tmp_path / "workspace" / "evaluations"
    agent = tmp_path / "agent"
    source = workspace / "compensation"
    destination = agent / "evaluations" / "compensation"
    _write_set(source)
    _write_set(destination)
    (destination / "case.mcs.yml").write_text(
        "kind: EvaluationData\nrows:\n  - input: different\n",
        encoding="utf-8",
    )

    try:
        evaluation_promotion.promote_workspace_set(
            workspace,
            agent,
            "compensation",
        )
    except evaluation_promotion.EvaluationPromotionError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("Expected differing staged copy to require approval")


def test_cleanup_removes_only_workspace_staging(tmp_path):
    workspace = tmp_path / "workspace" / "evaluations"
    agent = tmp_path / "agent"
    source = workspace / "compensation"
    destination = agent / "evaluations" / "compensation"
    _write_set(source)
    _write_set(destination)
    exports = workspace / "exports"
    exports.mkdir()
    csv_path = exports / "compensation-eval-testset-20260824-1100.csv"
    csv_path.write_text("Prompt\n", encoding="utf-8")

    result = evaluation_promotion.cleanup_workspace_set(
        workspace,
        agent,
        "compensation",
    )

    assert result["sourceRemoved"] is True
    assert not source.exists()
    assert not csv_path.exists()
    assert destination.is_dir()
    assert (destination / "compensation.mcs.yml").is_file()


def test_cleanup_refuses_when_agent_copy_is_missing(tmp_path):
    workspace = tmp_path / "workspace" / "evaluations"
    source = workspace / "compensation"
    _write_set(source)

    try:
        evaluation_promotion.cleanup_workspace_set(
            workspace,
            tmp_path / "agent",
            "compensation",
        )
    except evaluation_promotion.EvaluationPromotionError as exc:
        assert "Refusing workspace cleanup" in str(exc)
    else:
        raise AssertionError("Expected cleanup without agent copy to fail")


def test_cleanup_refuses_when_workspace_changed_after_promotion(tmp_path):
    workspace = tmp_path / "workspace" / "evaluations"
    agent = tmp_path / "agent"
    source = workspace / "compensation"
    destination = agent / "evaluations" / "compensation"
    _write_set(source)
    _write_set(destination)
    (source / "case.mcs.yml").write_text(
        "kind: EvaluationData\nrows:\n  - input: changed after promotion\n",
        encoding="utf-8",
    )

    try:
        evaluation_promotion.cleanup_workspace_set(
            workspace,
            agent,
            "compensation",
        )
    except evaluation_promotion.EvaluationPromotionError as exc:
        assert "staging set changed" in str(exc)
    else:
        raise AssertionError("Expected changed workspace staging to be kept")
