from __future__ import annotations

from pathlib import Path

import pytest

import eval_curator_handoff


def _workspace(repo_root: Path) -> Path:
    return (
        repo_root
        / "solutions"
        / "ess-maker-skills"
        / "workspace"
        / "evaluations"
    )


def _valid_handoff(repo_root: Path) -> dict[str, object]:
    workspace = _workspace(repo_root)
    set_folder = workspace / "benefits"
    exports = workspace / "exports"
    set_folder.mkdir(parents=True)
    exports.mkdir()
    (set_folder / "benefits.mcs.yml").write_text(
        "kind: EvaluationSet\n",
        encoding="utf-8",
    )
    (set_folder / "case.mcs.yml").write_text(
        "kind: EvaluationData\n",
        encoding="utf-8",
    )
    csv_path = exports / "benefits.csv"
    csv_path.write_text(
        "Prompt,Expected response,Test Method Type,Passing Score\n"
        "How?,Like this,CompareMeaning,70\n",
        encoding="utf-8",
    )
    return {
        "Curator handoff": {
            "outputRoot": "workspace/evaluations",
            "sets": [
                {
                    "name": "Benefits",
                    "folder": "workspace/evaluations/benefits",
                    "csv": "workspace/evaluations/exports/benefits.csv",
                    "caseCount": 1,
                    "qualityScore": 5,
                }
            ],
            "structuralValidation": "passed",
            "qualityValidation": "passed",
        }
    }


def test_validate_handoff_accepts_expected_workspace_structure(tmp_path):
    result = eval_curator_handoff.validate_handoff(
        tmp_path,
        _valid_handoff(tmp_path),
    )

    assert result["valid"] is True
    assert result["setCount"] == 1
    assert result["sets"][0]["folder"].endswith("evaluations\\benefits")
    assert result["sets"][0]["csv"].endswith("exports\\benefits.csv")


@pytest.mark.parametrize(
    ("field", "hostile_path", "error_code"),
    [
        ("folder", "../outside", "invalid_set_folder"),
        ("folder", "workspace/evaluations/exports", "invalid_set_folder"),
        ("folder", "workspace/evaluations/missing", "invalid_set_folder"),
        ("csv", "../outside.csv", "invalid_set_csv"),
        (
            "csv",
            "workspace/evaluations/benefits/benefits.csv",
            "invalid_set_csv",
        ),
        (
            "csv",
            "workspace/evaluations/exports/missing.csv",
            "invalid_set_csv",
        ),
    ],
)
def test_validate_handoff_rejects_hostile_or_malformed_paths(
    tmp_path,
    field,
    hostile_path,
    error_code,
):
    handoff = _valid_handoff(tmp_path)
    handoff["Curator handoff"]["sets"][0][field] = hostile_path

    with pytest.raises(eval_curator_handoff.CuratorHandoffError) as exc:
        eval_curator_handoff.validate_handoff(tmp_path, handoff)

    assert exc.value.error_code == error_code


def test_validate_handoff_rejects_symlink_escape(tmp_path):
    handoff = _valid_handoff(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evil.mcs.yml").write_text(
        "kind: EvaluationSet\n",
        encoding="utf-8",
    )
    link = _workspace(tmp_path) / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation is not available on this host")
    handoff["Curator handoff"]["sets"][0]["folder"] = (
        "workspace/evaluations/escape"
    )

    with pytest.raises(eval_curator_handoff.CuratorHandoffError) as exc:
        eval_curator_handoff.validate_handoff(tmp_path, handoff)

    assert exc.value.error_code == "invalid_set_folder"


def test_validate_handoff_rejects_reparse_point_before_validation(
    tmp_path,
    monkeypatch,
):
    handoff = _valid_handoff(tmp_path)
    set_folder = _workspace(tmp_path) / "benefits"
    original = eval_curator_handoff._is_reparse_point
    monkeypatch.setattr(
        eval_curator_handoff,
        "_is_reparse_point",
        lambda path: path == set_folder or original(path),
    )

    with pytest.raises(eval_curator_handoff.CuratorHandoffError) as exc:
        eval_curator_handoff.validate_handoff(tmp_path, handoff)

    assert exc.value.error_code == "invalid_set_folder"


def test_validate_handoff_rejects_hostile_output_root(tmp_path):
    handoff = _valid_handoff(tmp_path)
    handoff["Curator handoff"]["outputRoot"] = "../outside"

    with pytest.raises(eval_curator_handoff.CuratorHandoffError) as exc:
        eval_curator_handoff.validate_handoff(tmp_path, handoff)

    assert exc.value.error_code == "invalid_output_root"


def test_validate_handoff_rejects_mismatched_case_counts(tmp_path):
    handoff = _valid_handoff(tmp_path)
    handoff["Curator handoff"]["sets"][0]["caseCount"] = 2

    with pytest.raises(eval_curator_handoff.CuratorHandoffError) as exc:
        eval_curator_handoff.validate_handoff(tmp_path, handoff)

    assert exc.value.error_code == "invalid_handoff"
