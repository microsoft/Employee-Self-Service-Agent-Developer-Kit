"""Unit tests for RULE-007 — DisableUnsupportedNodeTopicsStep."""

from __future__ import annotations

from typing import cast

from core.logging import Logger
from modules.transformation.models import CustomizationComponent, MigrationContext
from modules.transformation.steps.disable_unsupported_node_topics_step import (
    DisableUnsupportedNodeTopicsStep,
    unsupported_nodes,
)


class FakeLogger:
    def __init__(self) -> None:
        self.changes: list[dict[str, object]] = []

    def LogInfo(self, *_: object, **__: object) -> None: ...
    def LogWarning(self, *_: object, **__: object) -> None: ...
    def LogDebug(self, *_: object, **__: object) -> None: ...

    def LogChange(self, message: str, *, rule_id: str | None = None, **__: object) -> None:
        self.changes.append({"rule_id": rule_id, "message": message})


def _topic(component_id: str, data: str, name: str = "Topic") -> CustomizationComponent:
    return CustomizationComponent(
        component_id=component_id,
        schemaname=f"msdyn_copilotforemployeeselfservicehr.topic.{component_id}",
        name=name,
        data=data,
        statecode=0,
        statuscode=1,
    )


# --- detection ---


def test_unsupported_nodes_detects_and_sorts_unique_kinds() -> None:
    data = (
        "beginDialog:\n"
        "  kind: OnRecognizedIntent\n"
        "  actions:\n"
        "    - kind: SendActivity\n"
        "    - kind: AnswerQuestionWithAI\n"
        "    - kind: RecognizeIntent\n"
        "    - kind: AnswerQuestionWithAI\n"  # duplicate
    )
    assert unsupported_nodes(data) == ["AnswerQuestionWithAI", "RecognizeIntent"]


def test_unsupported_nodes_empty_for_supported_only() -> None:
    data = "beginDialog:\n  kind: OnRecognizedIntent\n  actions:\n    - kind: SendActivity\n"
    assert unsupported_nodes(data) == []
    assert unsupported_nodes(None) == []


# --- step ---


def test_step_disables_topics_using_unsupported_nodes() -> None:
    logger = FakeLogger()
    context = MigrationContext(
        customizations={
            "uses-node": _topic(
                "uses-node",
                "beginDialog:\n  kind: OnRecognizedIntent\n  actions:\n"
                "    - kind: SearchAndSummarizeContent\n",
                name="HR Answers",
            ),
            "clean": _topic(
                "clean",
                "beginDialog:\n  kind: OnRecognizedIntent\n  actions:\n    - kind: SendActivity\n",
            ),
        }
    )

    result = DisableUnsupportedNodeTopicsStep(cast(Logger, logger)).execute(context)

    writes = {w["record_id"]: w for w in result.pending_writes}
    assert set(writes) == {"uses-node"}
    assert writes["uses-node"]["changes"] == {
        "name": "[DEPRECATED] HR Answers",
        "statecode": 1,
        "statuscode": 2,
    }
    assert logger.changes[0]["rule_id"] == "RULE-007"
    assert "SearchAndSummarizeContent" in str(logger.changes[0]["message"])
