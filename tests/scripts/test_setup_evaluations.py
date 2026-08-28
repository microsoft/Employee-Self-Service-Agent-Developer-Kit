from __future__ import annotations

import csv
import json
import sys
from pathlib import Path


SCRIPTS = (
    Path(__file__).resolve().parents[2]
    / "solutions"
    / "ess-maker-skills"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

import setup as setup_script  # noqa: E402


def test_extract_components_groups_evaluation_cases_by_parent(tmp_path):
    parent_id = "00000000-0000-0000-0000-000000000001"
    child_id = "00000000-0000-0000-0000-000000000002"
    components = [
        {
            "botcomponentid": child_id,
            "name": "Base compensation",
            "schemaname": "mspva_evaldata_base_compensation",
            "componenttype": 19,
            "parentbotcomponentid": parent_id,
            "data": (
                "kind: EvaluationData\n"
                "rows:\n"
                '  - input: "base compensation"\n'
                '    expectedOutput: "Returns base compensation"\n'
            ),
        },
        {
            "botcomponentid": parent_id,
            "name": "Compensation",
            "schemaname": "mspva_evalset_compensation",
            "componenttype": 19,
            "parentbotcomponentid": None,
            "data": (
                "kind: EvaluationSet\n"
                "graders:\n"
                "  - kind: CompareMeaningGrader\n"
                "    threshold: 0.6\n"
            ),
        },
    ]

    stats = setup_script.extract_components(components, str(tmp_path))

    parent_path = "evaluations/compensation/compensation.mcs.yml"
    child_path = "evaluations/compensation/base-compensation.mcs.yml"
    assert (tmp_path / Path(parent_path)).is_file()
    assert (tmp_path / Path(child_path)).is_file()
    assert stats["component_map"][parent_path]["botcomponentid"] == parent_id
    assert stats["component_map"][child_path]["parentbotcomponentid"] == parent_id
    assert not (tmp_path / "evaluations" / "base-compensation.mcs.yml").exists()
    export_path = (
        tmp_path / "evaluations" / "exports"
        / Path(stats["evaluation_exports"][0]).name
    )
    with export_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.reader(stream))
    assert rows == [
        ["Prompt", "Expected response", "Test Method Type", "Passing Score"],
        ["base compensation", "Returns base compensation", "CompareMeaning", "60"],
    ]


def test_extract_components_writes_review_metadata_for_tagged_parent(tmp_path):
    parent_id = "00000000-0000-0000-0000-000000000021"
    components = [{
        "botcomponentid": parent_id,
        "name": "Compensation",
        "schemaname": "mspva_evalset_compensation",
        "componenttype": 19,
        "parentbotcomponentid": None,
        "data": "kind: EvaluationSet\n",
        "description": (
            "Human description\n\n"
            "[ADK-REVIEW status=review_requested]"
        ),
    }]

    stats = setup_script.extract_components(components, str(tmp_path))

    review_path = (
        tmp_path / "evaluations" / "compensation" / "review.json")
    assert json.loads(review_path.read_text(encoding="utf-8")) == {
        "status": "review_requested",
        "baseDescription": "Human description",
    }
    parent_path = "evaluations/compensation/compensation.mcs.yml"
    assert stats["component_map"][parent_path]["description"].startswith(
        "Human description")


def test_summary_lists_test_sets_tagged_for_review(tmp_path, capsys):
    components = [{
        "botcomponentid": "00000000-0000-0000-0000-000000000031",
        "name": "Compensation",
        "schemaname": "mspva_evalset_compensation",
        "componenttype": 19,
        "parentbotcomponentid": None,
        "data": "kind: EvaluationSet\n",
        "description": "[ADK-REVIEW status=review_requested]",
    }]
    stats = setup_script.extract_components(components, str(tmp_path))

    setup_script.print_summary(stats, template_configs=None)

    output = capsys.readouterr().out
    assert "Tagged for review:" in output
    assert "Compensation" in output


def test_extract_components_removes_tracked_flat_evaluation_paths_on_refresh(
    tmp_path,
):
    parent_id = "00000000-0000-0000-0000-000000000011"
    child_id = "00000000-0000-0000-0000-000000000012"
    evaluations = tmp_path / "evaluations"
    evaluations.mkdir()
    old_parent = evaluations / "compensation.mcs.yml"
    old_child = evaluations / "base-compensation.mcs.yml"
    old_parent.write_text("kind: EvaluationSet\n", encoding="utf-8")
    old_child.write_text("kind: EvaluationData\n", encoding="utf-8")
    (tmp_path / ".component-map.json").write_text(
        json.dumps({
            "evaluations/compensation.mcs.yml": {
                "botcomponentid": parent_id,
                "componenttype": 19,
            },
            "evaluations/base-compensation.mcs.yml": {
                "botcomponentid": child_id,
                "componenttype": 19,
                "parentbotcomponentid": parent_id,
            },
        }),
        encoding="utf-8",
    )
    components = [
        {
            "botcomponentid": parent_id,
            "name": "Compensation",
            "schemaname": "mspva_evalset_compensation",
            "componenttype": 19,
            "data": "kind: EvaluationSet\n",
        },
        {
            "botcomponentid": child_id,
            "name": "Base compensation",
            "schemaname": "mspva_evaldata_base_compensation",
            "componenttype": 19,
            "parentbotcomponentid": parent_id,
            "data": "kind: EvaluationData\n",
        },
    ]

    setup_script.extract_components(components, str(tmp_path))

    assert not old_parent.exists()
    assert not old_child.exists()
    assert (
        tmp_path / "evaluations" / "compensation" / "compensation.mcs.yml"
    ).is_file()
    assert (
        tmp_path / "evaluations" / "compensation"
        / "base-compensation.mcs.yml"
    ).is_file()
