import pytest
import yaml

from evaluation_presentation import (
    EvaluationPresentationError,
    PreviewRow,
    load_preview_rows,
    render_preview,
)


def test_renders_all_rows_once_with_full_safe_assertions_and_actual_link(tmp_path):
    csv_path = tmp_path / "pay (current).csv"
    csv_path.write_text("CSV", encoding="utf-8")
    rows = [
        PreviewRow("positive:1", "pay | lookup", "Return <amount>\nKeep *full* assertion."),
        PreviewRow("typo:1", "pay | lookup", "Interpret the typo."),
        PreviewRow("out:1", "Book a trip", "Explain travel is out of scope."),
        PreviewRow("privacy:1", "Another person's pay", "Decline unauthorized disclosure."),
        PreviewRow("unknown:1", "Unclassified prompt", "Do not infer a category."),
    ]
    groups = {
        "positive:1": "in_scope", "typo:1": "in_scope",
        "out:1": "out_of_scope", "privacy:1": "other_negative",
    }
    result = render_preview("Pay [scenario]", rows, csv_path, groups)
    assert "### Eval generated - Pay \\[scenario\\]" in result
    assert "Return &lt;amount&gt;<br>Keep \\*full\\* assertion." in result
    assert result.count("pay &#124; lookup") == 2
    assert result.count("Interpret the typo.") == 1
    assert result.index("Interpret the typo.") < result.index("#### Out-of-scope")
    assert result.index("Another person's pay") > result.index("#### Other negative")
    assert result.count("Unclassified prompt") == 1
    assert "Test Method" not in result and "File |" not in result
    assert csv_path.as_uri() in result
    assert "What would you like to do next?" not in result


def test_unknown_group_does_not_silently_drop_or_classify_a_case(tmp_path):
    path = tmp_path / "set.csv"
    path.touch()
    rows = [PreviewRow("one:1", "Prompt", "Refuse")]
    with pytest.raises(EvaluationPresentationError, match="Unknown case"):
        render_preview("Set", rows, path, {"other:1": "in_scope"})
    result = render_preview("Set", rows, path, {})
    assert "No cases in this section." in result
    assert result.index("| Prompt | Refuse |") > result.index("#### Additional cases")
    assert "What would you like to do next?" not in result


def test_missing_csv_cannot_produce_a_fabricated_download_link(tmp_path):
    with pytest.raises(EvaluationPresentationError, match="does not exist"):
        render_preview("Set", [], tmp_path / "absent.csv", {})


def test_load_rows_uses_display_order_and_preserves_duplicate_prompts(tmp_path):
    parent = {"kind": "EvaluationSet", "displayName": "Actual",
              "graders": [{"kind": "CompareMeaningGrader", "threshold": 0.7}]}
    (tmp_path / "set.mcs.yml").write_text(yaml.safe_dump(parent), encoding="utf-8")
    for filename, order, answer in (("a", 2, "Second"), ("z", 1, "First")):
        (tmp_path / f"{filename}.mcs.yml").write_text(yaml.safe_dump({
            "kind": "EvaluationData",
            "rows": [{"input": "Same", "expectedOutput": answer}],
            "extensionData": {"displayOrder": str(order)},
        }), encoding="utf-8")
    name, rows = load_preview_rows(tmp_path)
    assert name == "Actual"
    assert [row.case_id for row in rows] == ["z.mcs.yml:1", "a.mcs.yml:1"]
    assert [row.expected_response for row in rows] == ["First", "Second"]
