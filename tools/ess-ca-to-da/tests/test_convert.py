from __future__ import annotations

from typing import Any

from essmig.convert import ConversionClass, convert_dialog


def _parse_value(variable: str, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "ParseValue",
        "id": "parse",
        "variable": variable,
        "valueType": {"kind": "Record", "properties": properties},
        "value": "=Topic.raw",
    }


def _answer(variable: str, user_input: str, **extra: Any) -> dict[str, Any]:
    node = {
        "kind": "AnswerQuestionWithAI",
        "id": "aqwai",
        "displayName": "Send GenAI Based response",
        "variable": variable,
        "userInput": user_input,
        "fileSearchDataSource": {"searchFilesMode": {"kind": "DoNotSearchFiles"}},
        "knowledgeSources": {"kind": "SearchSpecificKnowledgeSources"},
    }
    node.update(extra)
    return node


def _composition_dialog() -> dict[str, Any]:
    return {
        "kind": "AdaptiveDialog",
        "beginDialog": {
            "kind": "OnRedirect",
            "id": "main",
            "actions": [
                _parse_value(
                    "Topic.Rec",
                    {"HireDate": "String", "ServiceAwardDate": "String"},
                ),
                _answer("Topic.var_Response", "=JSON(Topic.Rec)"),
                {
                    "kind": "SendActivity",
                    "id": "send",
                    "activity": "{Topic.var_Response}",
                },
            ],
        },
    }


# --- response composition over a scalar record converts ---------------------


def test_scalar_response_composition_is_converted_to_set_variable() -> None:
    dialog = _composition_dialog()
    conversions = convert_dialog(dialog)

    assert len(conversions) == 1
    conversion = conversions[0]
    assert conversion.cls is ConversionClass.RESPONSE_COMPOSITION
    assert conversion.converted is True

    actions = dialog["beginDialog"]["actions"]
    kinds = [a["kind"] for a in actions]
    assert "AnswerQuestionWithAI" not in kinds
    rendered = next(a for a in actions if a["kind"] == "SetVariable")
    assert rendered["variable"] == "Topic.var_Response"
    assert rendered["id"] == "aqwai"
    assert rendered["value"] == (
        '="Hire Date: " & Text(Topic.Rec.HireDate)'
        ' & Char(10) & "Service Award Date: " & Text(Topic.Rec.ServiceAwardDate)'
    )
    assert "auto-upgraded" in rendered["displayName"]
    # The downstream SendActivity still reads the same variable.
    send = next(a for a in actions if a["kind"] == "SendActivity")
    assert send["activity"] == "{Topic.var_Response}"


def test_tabular_record_is_classified_but_not_converted() -> None:
    dialog = {
        "kind": "AdaptiveDialog",
        "beginDialog": {
            "kind": "OnRedirect",
            "id": "main",
            "actions": [
                _parse_value(
                    "Topic.Rec",
                    {
                        "Directs": {
                            "type": {
                                "kind": "Table",
                                "properties": {"Name": "String"},
                            }
                        }
                    },
                ),
                _answer("Topic.Combined", "=JSON(Topic.Rec)", autoSend=True),
            ],
        },
    }
    conversions = convert_dialog(dialog)

    assert len(conversions) == 1
    assert conversions[0].cls is ConversionClass.RESPONSE_COMPOSITION
    assert conversions[0].converted is False
    kinds = [a["kind"] for a in dialog["beginDialog"]["actions"]]
    assert "AnswerQuestionWithAI" in kinds  # left untouched


def test_intent_classifier_is_not_converted() -> None:
    dialog = {
        "kind": "AdaptiveDialog",
        "beginDialog": {
            "kind": "OnRedirect",
            "id": "main",
            "actions": [
                _answer("Topic.intent", "=System.Activity.Text"),
                {
                    "kind": "ConditionGroup",
                    "id": "cg",
                    "conditions": [
                        {"id": "c1", "condition": '=Topic.intent = "HIRE_DATE"'}
                    ],
                },
            ],
        },
    }
    conversions = convert_dialog(dialog)

    assert conversions[0].cls is ConversionClass.INTENT_CLASSIFICATION
    assert conversions[0].converted is False


def test_knowledge_grounded_node_is_not_converted() -> None:
    dialog = {
        "kind": "AdaptiveDialog",
        "beginDialog": {
            "kind": "OnRedirect",
            "id": "main",
            "actions": [
                {
                    "kind": "AnswerQuestionWithAI",
                    "id": "k",
                    "variable": "Topic.ans",
                    "userInput": "=System.Activity.Text",
                    "knowledgeSources": {"kind": "SearchAllKnowledgeSources"},
                },
                {"kind": "SendActivity", "id": "s", "activity": "{Topic.ans}"},
            ],
        },
    }
    conversions = convert_dialog(dialog)

    assert conversions[0].cls is ConversionClass.KNOWLEDGE_GROUNDED
    assert conversions[0].converted is False


def test_general_knowledge_node_is_not_converted() -> None:
    dialog = {
        "kind": "AdaptiveDialog",
        "beginDialog": {
            "kind": "OnRedirect",
            "id": "main",
            "actions": [
                _answer("Topic.ans", "=System.Activity.Text"),
            ],
        },
    }
    conversions = convert_dialog(dialog)

    assert conversions[0].cls is ConversionClass.GENERAL_KNOWLEDGE
    assert conversions[0].converted is False


def test_non_dict_dialog_returns_no_conversions() -> None:
    assert convert_dialog(None) == []
    assert convert_dialog([]) == []
