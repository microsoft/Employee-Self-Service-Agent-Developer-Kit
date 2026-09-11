from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools import minimalbot_evaluation_poc as poc  # noqa: E402


def test_wire_kinds_converts_nested_discriminators():
    result = poc._wire_kinds({
        "kind": "EvaluationSet",
        "graders": [{"kind": "GeneralQualityGrader"}],
    })

    assert result == {
        "$kind": "EvaluationSet",
        "graders": [{"$kind": "GeneralQualityGrader"}],
    }


def test_unwire_kinds_converts_nested_discriminators():
    result = poc._unwire_kinds({
        "$kind": "EvaluationSet",
        "graders": [{"$kind": "GeneralQualityGrader"}],
    })

    assert result == {
        "kind": "EvaluationSet",
        "graders": [{"kind": "GeneralQualityGrader"}],
    }


def test_workspace_payload_converts_evaluation_yaml(tmp_path):
    (tmp_path / "compensation.mcs.yml").write_text(
        """
kind: EvaluationSet
displayName: Compensation
graders:
  - kind: GeneralQualityGrader
  - kind: CompareMeaningGrader
    threshold: 0.7
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "base-compensation.mcs.yml").write_text(
        """
kind: EvaluationData
rows:
  - source: Imported
    input: base compensation
    expectedOutput: Returns base compensation
extensionData:
  displayOrder: "100"
""".strip(),
        encoding="utf-8",
    )

    payload, test_set_id = poc._workspace_payload(tmp_path, "change-token")

    assert payload["changeToken"] == "change-token"
    assert payload["connectionReferenceChanges"] == []
    assert len(payload["botComponentChanges"]) == 2

    parent = payload["botComponentChanges"][0]
    child = payload["botComponentChanges"][1]
    assert parent["$kind"] == "BotComponentInsert"
    assert parent["component"]["$kind"] == "TestCaseComponent"
    assert parent["component"]["id"] == test_set_id
    assert parent["component"]["definition"]["$kind"] == "EvaluationSet"
    assert parent["component"]["definition"]["graders"] == [
        {"$kind": "GeneralQualityGrader"},
        {"$kind": "CompareMeaningGrader", "threshold": 0.7},
    ]
    assert child["component"]["parentBotComponentId"] == test_set_id
    assert child["component"]["definition"]["$kind"] == "EvaluationData"
    assert child["component"]["definition"]["rows"][0]["$kind"] == (
        "SimpleEvaluationCase"
    )
    assert child["component"]["definition"]["extensionData"] == {
        "displayOrder": "100"
    }
    assert parent["component"]["extensionData"] == {
        "UseProvidedBotComponentId": True
    }


def test_workspace_payload_requires_one_parent(tmp_path):
    (tmp_path / "case.mcs.yml").write_text(
        "kind: EvaluationData\nrows:\n  - input: hello\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="exactly one EvaluationSet"):
        poc._workspace_payload(tmp_path, "change-token")


def test_pull_writes_workspace_yaml_and_component_map(tmp_path):
    response = {
        "botComponentChanges": [
            {
                "component": {
                    "id": "parent-id",
                    "schemaName": "mspva_compensation",
                    "definition": {
                        "$kind": "EvaluationSet",
                        "displayName": "Compensation",
                        "graders": [{"$kind": "GeneralQualityGrader"}],
                    },
                },
            },
            {
                "component": {
                    "id": "case-id",
                    "parentBotComponentId": "parent-id",
                    "schemaName": "mspva_base_compensation",
                    "definition": {
                        "$kind": "EvaluationData",
                        "displayName": "Base compensation",
                        "rows": [{
                            "$kind": "SimpleEvaluationCase",
                            "input": "base compensation",
                        }],
                    },
                },
            },
        ],
    }

    counts = poc._write_workspace_evaluations(response, tmp_path)

    assert counts == {"sets": 1, "cases": 1}
    parent = (
        tmp_path
        / "evaluations"
        / "compensation"
        / "compensation.mcs.yml"
    ).read_text(encoding="utf-8")
    case = (
        tmp_path
        / "evaluations"
        / "compensation"
        / "base-compensation.mcs.yml"
    ).read_text(encoding="utf-8")
    assert "kind: EvaluationSet" in parent
    assert "kind: GeneralQualityGrader" in parent
    assert "kind: EvaluationData" in case
    assert "kind: SimpleEvaluationCase" in case
    component_map = json.loads(
        (tmp_path / ".component-map.json").read_text(encoding="utf-8")
    )
    child_path = "evaluations/compensation/base-compensation.mcs.yml"
    assert component_map[child_path]["parentbotcomponentid"] == "parent-id"


def test_pull_rejects_response_without_evaluation_sets(tmp_path):
    with pytest.raises(RuntimeError, match="did not expose"):
        poc._write_workspace_evaluations(
            {"botComponentChanges": []},
            tmp_path,
        )


def test_resolve_target_uses_config_defaults(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "environmentId": "environment-id",
            "agent": {"botId": "bot-id"},
        }),
        encoding="utf-8",
    )

    assert poc._resolve_target(None, None, config_path) == (
        "environment-id",
        "bot-id",
    )


def test_resolve_target_cli_values_override_config(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({
            "environmentId": "old-environment-id",
            "agent": {"botId": "old-bot-id"},
        }),
        encoding="utf-8",
    )

    assert poc._resolve_target(
        "new-environment-id",
        "new-bot-id",
        config_path,
    ) == ("new-environment-id", "new-bot-id")
