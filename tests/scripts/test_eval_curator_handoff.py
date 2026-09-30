from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

import eval_curator_handoff
import evaluation_csv


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
        "kind: EvaluationSet\n"
        "displayName: Benefits\n"
        "graders:\n"
        "  - kind: CompareMeaningGrader\n"
        "    threshold: 0.7\n",
        encoding="utf-8",
    )
    (set_folder / "case.mcs.yml").write_text(
        "kind: EvaluationData\n"
        "rows:\n"
        "  - input: How?\n"
        "    expectedOutput: Like this\n",
        encoding="utf-8",
    )
    csv_path = evaluation_csv.generate_set_csv(
        set_folder,
        exports,
        timestamp="20260927",
    )
    return {
        "Curator handoff": {
            "outputRoot": "workspace/evaluations",
            "sets": [
                {
                    "name": "Benefits",
                    "folder": "workspace/evaluations/benefits",
                    "csv": (
                        "workspace/evaluations/exports/"
                        f"{csv_path.name}"
                    ),
                    "caseCount": 1,
                    "qualityScore": 5,
                }
            ],
            "structuralValidation": "passed",
            "qualityValidation": "passed",
        }
    }


def test_validate_handoff_accepts_expected_workspace_structure(tmp_path):
    handoff = _valid_handoff(tmp_path)
    result = eval_curator_handoff.validate_handoff(
        tmp_path,
        handoff,
    )

    assert result["valid"] is True
    assert result["setCount"] == 1
    workspace = _workspace(tmp_path).resolve()
    assert Path(result["outputRoot"]) == workspace
    assert Path(result["sets"][0]["folder"]) == workspace / "benefits"
    assert Path(result["sets"][0]["csv"]) == (
        workspace / "exports" / "20260927_Benefits.csv"
    )


def test_validate_handoff_rejects_csv_from_different_same_size_set(tmp_path):
    handoff = _valid_handoff(tmp_path)
    workspace = _workspace(tmp_path)
    beta_folder = workspace / "beta"
    beta_folder.mkdir()
    (beta_folder / "beta.mcs.yml").write_text(
        "kind: EvaluationSet\n"
        "displayName: Beta\n"
        "graders:\n"
        "  - kind: CompareMeaningGrader\n"
        "    threshold: 0.7\n",
        encoding="utf-8",
    )
    (beta_folder / "case.mcs.yml").write_text(
        "kind: EvaluationData\n"
        "rows:\n"
        "  - input: Beta question\n"
        "    expectedOutput: Beta answer\n",
        encoding="utf-8",
    )
    beta_csv = evaluation_csv.generate_set_csv(
        beta_folder,
        workspace / "exports",
        timestamp="20260927",
    )
    handoff["Curator handoff"]["sets"][0]["csv"] = (
        f"workspace/evaluations/exports/{beta_csv.name}"
    )

    with pytest.raises(eval_curator_handoff.CuratorHandoffError) as exc:
        eval_curator_handoff.validate_handoff(tmp_path, handoff)

    assert exc.value.error_code == "mismatched_set_csv"


@pytest.mark.parametrize("replacement", ["duplicate", "changed"])
def test_validate_handoff_rejects_duplicate_or_changed_csv_row(
    tmp_path,
    replacement,
):
    handoff = _valid_handoff(tmp_path)
    workspace = _workspace(tmp_path)
    case_path = workspace / "benefits" / "case.mcs.yml"
    case_path.write_text(
        "kind: EvaluationData\n"
        "rows:\n"
        "  - input: First question\n"
        "    expectedOutput: First answer\n"
        "extensionData:\n"
        "  displayOrder: 1\n",
        encoding="utf-8",
    )
    (workspace / "benefits" / "case-2.mcs.yml").write_text(
        "kind: EvaluationData\n"
        "rows:\n"
        "  - input: Second question\n"
        "    expectedOutput: Second answer\n"
        "extensionData:\n"
        "  displayOrder: 2\n",
        encoding="utf-8",
    )
    csv_path = evaluation_csv.generate_set_csv(
        workspace / "benefits",
        workspace / "exports",
        timestamp="20260927",
    )
    handoff["Curator handoff"]["sets"][0]["caseCount"] = 2
    with csv_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.reader(stream))
    if replacement == "duplicate":
        rows[2] = rows[1]
    else:
        rows[2][1] = "Changed answer"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows(rows)

    with pytest.raises(eval_curator_handoff.CuratorHandoffError) as exc:
        eval_curator_handoff.validate_handoff(tmp_path, handoff)

    assert exc.value.error_code == "mismatched_set_csv"


def test_validate_handoff_accepts_reordered_columns_and_quoted_newlines(tmp_path):
    handoff = _valid_handoff(tmp_path)
    workspace = _workspace(tmp_path)
    case_path = workspace / "benefits" / "case.mcs.yml"
    case_path.write_text(
        "kind: EvaluationData\n"
        "rows:\n"
        "  - input: |-\n"
        "      First line\n"
        "      Second line\n"
        "    expectedOutput: Answer, with comma\n",
        encoding="utf-8",
    )
    csv_path = evaluation_csv.generate_set_csv(
        workspace / "benefits",
        workspace / "exports",
        timestamp="20260927",
    )
    with csv_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    fieldnames = [
        "Passing Score",
        "Expected response",
        "Prompt",
        "Test Method Type",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    result = eval_curator_handoff.validate_handoff(tmp_path, handoff)

    assert result["valid"] is True


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


def test_validate_handoff_rejects_symlinked_output_root(tmp_path):
    handoff = _valid_handoff(tmp_path)
    logical_output_root = _workspace(tmp_path)
    outside = tmp_path / "outside-evaluations"
    logical_output_root.rename(outside)
    try:
        logical_output_root.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation is not available on this host")

    with pytest.raises(eval_curator_handoff.CuratorHandoffError) as exc:
        eval_curator_handoff.validate_handoff(tmp_path, handoff)

    assert exc.value.error_code == "invalid_output_root"


def test_validate_handoff_rejects_output_root_reparse_point(
    tmp_path,
    monkeypatch,
):
    handoff = _valid_handoff(tmp_path)
    output_root = _workspace(tmp_path)
    original = eval_curator_handoff._is_reparse_point
    monkeypatch.setattr(
        eval_curator_handoff,
        "_is_reparse_point",
        lambda path: path == output_root or original(path),
    )

    with pytest.raises(eval_curator_handoff.CuratorHandoffError) as exc:
        eval_curator_handoff.validate_handoff(tmp_path, handoff)

    assert exc.value.error_code == "invalid_output_root"


def test_reparse_detection_uses_windows_file_attributes(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(Path, "is_symlink", lambda self: False)
    monkeypatch.setattr(Path, "lstat", lambda self: SimpleNamespace(
        st_file_attributes=0x400,
    ))
    if hasattr(eval_curator_handoff.os.path, "isjunction"):
        monkeypatch.setattr(
            eval_curator_handoff.os.path,
            "isjunction",
            lambda path: False,
        )

    assert eval_curator_handoff._is_reparse_point(tmp_path / "artifact")


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


@pytest.mark.parametrize(
    ("artifact_name", "artifact_text"),
    [
        ("benefits.mcs.yml", "kind: EvaluationSet\n"),
        ("case.mcs.yml", "kind: EvaluationData\n"),
    ],
)
def test_validate_handoff_rejects_symlinked_yaml_artifact(
    tmp_path,
    artifact_name,
    artifact_text,
):
    handoff = _valid_handoff(tmp_path)
    artifact = _workspace(tmp_path) / "benefits" / artifact_name
    artifact.unlink()
    outside = tmp_path / f"outside-{artifact_name}"
    outside.write_text(artifact_text, encoding="utf-8")
    try:
        artifact.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation is not available on this host")

    with pytest.raises(eval_curator_handoff.CuratorHandoffError) as exc:
        eval_curator_handoff.validate_handoff(tmp_path, handoff)

    assert exc.value.error_code == "invalid_set_folder"


def test_validate_handoff_rejects_symlinked_csv_artifact(tmp_path):
    handoff = _valid_handoff(tmp_path)
    csv_path = (
        tmp_path
        / "solutions"
        / "ess-maker-skills"
        / handoff["Curator handoff"]["sets"][0]["csv"]
    )
    csv_text = csv_path.read_text(encoding="utf-8")
    csv_path.unlink()
    target = csv_path.parent / "target.csv"
    target.write_text(csv_text, encoding="utf-8")
    try:
        csv_path.symlink_to(target)
    except OSError:
        pytest.skip("Symlink creation is not available on this host")

    with pytest.raises(eval_curator_handoff.CuratorHandoffError) as exc:
        eval_curator_handoff.validate_handoff(tmp_path, handoff)

    assert exc.value.error_code == "invalid_set_csv"


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


def test_validate_handoff_uses_platform_normalization_for_duplicates(
    tmp_path,
    monkeypatch,
):
    handoff = _valid_handoff(tmp_path)
    workspace = _workspace(tmp_path)
    first_folder = workspace / "benefits"
    renamed_first_folder = workspace / "alpha"
    first_folder.rename(renamed_first_folder)
    first_csv = (
        tmp_path
        / "solutions"
        / "ess-maker-skills"
        / handoff["Curator handoff"]["sets"][0]["csv"]
    )
    renamed_first_csv = first_csv.with_name("alpha.csv")
    first_csv.rename(renamed_first_csv)
    handoff["Curator handoff"]["sets"][0]["folder"] = (
        "workspace/evaluations/alpha"
    )
    handoff["Curator handoff"]["sets"][0]["csv"] = (
        "workspace/evaluations/exports/alpha.csv"
    )
    second_folder = workspace / "beta"
    second_folder.mkdir()
    (second_folder / "beta.mcs.yml").write_text(
        "kind: EvaluationSet\n"
        "displayName: Beta\n"
        "graders:\n"
        "  - kind: CompareMeaningGrader\n"
        "    threshold: 0.7\n",
        encoding="utf-8",
    )
    (second_folder / "case.mcs.yml").write_text(
        "kind: EvaluationData\n"
        "rows:\n"
        "  - input: How?\n"
        "    expectedOutput: Like this\n",
        encoding="utf-8",
    )
    second_csv = workspace / "exports" / "beta.csv"
    generated_second_csv = evaluation_csv.generate_set_csv(
        second_folder,
        workspace / "exports",
        timestamp="20260927",
    )
    generated_second_csv.rename(second_csv)
    handoff["Curator handoff"]["sets"].append(
        {
            "name": "Duplicate benefits",
            "folder": "workspace/evaluations/beta",
            "csv": "workspace/evaluations/exports/beta.csv",
            "caseCount": 1,
            "qualityScore": 5,
        }
    )
    monkeypatch.setattr(
        eval_curator_handoff.os.path,
        "normcase",
        lambda value: value.casefold().replace("alpha", "duplicate").replace(
            "beta",
            "duplicate",
        ),
    )

    with pytest.raises(eval_curator_handoff.CuratorHandoffError) as exc:
        eval_curator_handoff.validate_handoff(tmp_path, handoff)

    assert exc.value.error_code == "invalid_handoff"
