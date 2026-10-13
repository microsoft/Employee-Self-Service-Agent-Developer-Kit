from copy import deepcopy

import pytest
import yaml

from evaluation_method_policy import (
    EvaluationMethodError,
    load_evaluation_documents,
    validate_evaluation_documents,
    validate_evaluation_folder,
)


def _documents(kind_key="kind", threshold=0.7):
    return (
        {kind_key: "EvaluationSet", "graders": [
            {kind_key: "CompareMeaningGrader", "threshold": threshold},
        ]},
        [{kind_key: "EvaluationData", "rows": [
            {"input": "Question", "expectedOutput": "Ask for clarification."},
            {"input": "Other's pay", "expectedOutput": "Decline disclosure."},
        ]}],
    )


@pytest.mark.parametrize("kind_key", ["kind", "$kind"])
@pytest.mark.parametrize("threshold", [0, 0.5, 0.7, 0.75, 1])
def test_accepts_local_and_native_compare_meaning_without_mutation(kind_key, threshold):
    parent, cases = _documents(kind_key, threshold)
    original = deepcopy((parent, cases))
    validate_evaluation_documents(parent, cases)
    assert (parent, cases) == original


@pytest.mark.parametrize("graders", [
    None, {}, [], [None], ["CompareMeaningGrader"],
    [{"kind": "GeneralQualityGrader"}], [{"kind": "UnknownGrader"}],
    [{"kind": "CompareMeaningGrader"}, {"kind": "GeneralQualityGrader"}],
    [{"kind": "CompareMeaningGrader"}, {"kind": "CompareMeaningGrader"}],
    [{"kind": "CompareMeaningGrader", "$kind": "GeneralQualityGrader"}],
])
def test_rejects_unsupported_or_malformed_graders(graders):
    parent, cases = _documents()
    parent["graders"] = graders
    original = deepcopy((parent, cases))
    with pytest.raises(EvaluationMethodError):
        validate_evaluation_documents(parent, cases, context="Selected")
    assert (parent, cases) == original


@pytest.mark.parametrize("threshold", [None, True, "0.7", -0.1, 1.1, float("nan"), float("inf")])
def test_rejects_invalid_threshold_instead_of_changing_it(threshold):
    parent, cases = _documents(threshold=threshold)
    with pytest.raises(EvaluationMethodError, match="threshold"):
        validate_evaluation_documents(parent, cases)


@pytest.mark.parametrize("field", ["input", "expectedOutput"])
@pytest.mark.parametrize("value", [None, "", " \n ", 7, [], {}])
def test_checks_each_row_after_a_valid_row(field, value):
    parent, cases = _documents()
    cases[0]["rows"][1][field] = value
    with pytest.raises(EvaluationMethodError, match=f"row 2: {field}"):
        validate_evaluation_documents(parent, cases)


@pytest.mark.parametrize("cases", [
    [], [None], [{"kind": "MultiTurnEvaluationCase", "activities": []}],
    [{"kind": "EvaluationData", "rows": []}],
    [{"kind": "EvaluationData", "rows": [None]}],
])
def test_rejects_unready_or_unsupported_cases(cases):
    parent, _ = _documents()
    with pytest.raises(EvaluationMethodError):
        validate_evaluation_documents(parent, cases)


def test_limit_counts_rows_not_files():
    parent, cases = _documents()
    cases[0]["rows"] = [cases[0]["rows"][0]] * 100
    validate_evaluation_documents(parent, cases)
    cases[0]["rows"].append({"input": "More", "expectedOutput": "Answer"})
    with pytest.raises(EvaluationMethodError, match="101 rows exceeds"):
        validate_evaluation_documents(parent, cases)


def test_folder_requires_one_parent_and_keeps_unknown_child_for_validation(tmp_path):
    parent, cases = _documents()
    (tmp_path / "set.mcs.yml").write_text(yaml.safe_dump(parent), encoding="utf-8")
    (tmp_path / "case.mcs.yml").write_text(yaml.safe_dump(cases[0]), encoding="utf-8")
    validate_evaluation_folder(tmp_path)
    (tmp_path / "unknown.mcs.yml").write_text("kind: Unknown\n", encoding="utf-8")
    with pytest.raises(EvaluationMethodError, match="single-response"):
        validate_evaluation_folder(tmp_path)
    (tmp_path / "second.mcs.yml").write_text(yaml.safe_dump(parent), encoding="utf-8")
    with pytest.raises(EvaluationMethodError, match="found 2"):
        load_evaluation_documents(tmp_path)


def test_folder_error_identifies_the_file_and_row(tmp_path):
    parent, cases = _documents()
    cases[0]["rows"][1]["expectedOutput"] = ""
    (tmp_path / "set.mcs.yml").write_text(yaml.safe_dump(parent), encoding="utf-8")
    (tmp_path / "broken-case.mcs.yml").write_text(yaml.safe_dump(cases[0]), encoding="utf-8")
    with pytest.raises(EvaluationMethodError, match="broken-case.mcs.yml, row 2: expectedOutput"):
        validate_evaluation_folder(tmp_path)
