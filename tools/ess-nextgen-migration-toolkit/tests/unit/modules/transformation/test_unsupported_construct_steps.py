"""Unit tests for the unsupported-construct steps (RULE-003/004/006/007) + shared base."""

from __future__ import annotations

from typing import cast

from core.logging import Logger
from modules.transformation.models import CustomizationComponent, MigrationContext
from modules.transformation.steps.handle_answer_question_with_ai_node_step import (
    HandleAnswerQuestionWithAINodeStep,
)
from modules.transformation.steps.handle_generated_response_topic_step import (
    HandleGeneratedResponseTopicStep,
)
from modules.transformation.steps.handle_on_activity_topic_step import HandleOnActivityTopicStep
from modules.transformation.steps.handle_on_escalate_topic_step import HandleOnEscalateTopicStep
from modules.transformation.steps.handle_recognize_intent_node_step import (
    HandleRecognizeIntentNodeStep,
)
from modules.transformation.steps.unsupported_construct_base import topic_trigger_kind


class FakeLogger:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.changes: list[dict[str, object]] = []

    def LogInfo(self, *_: object, **__: object) -> None: ...
    def LogDebug(self, *_: object, **__: object) -> None: ...

    def LogWarning(self, message: str, **__: object) -> None:
        self.warnings.append(message)

    def LogChange(self, message: str, *, rule_id: str | None = None, **__: object) -> None:
        self.changes.append({"rule_id": rule_id, "message": message})


def _topic(
    component_id: str,
    data: str,
    name: str = "Topic",
    *,
    statecode: int | None = 0,
    statuscode: int | None = 1,
) -> CustomizationComponent:
    return CustomizationComponent(
        component_id=component_id,
        schemaname=f"msdyn_copilotforemployeeselfservicehr.topic.{component_id}",
        name=name,
        data=data,
        statecode=statecode,
        statuscode=statuscode,
    )


def _trigger_topic(component_id: str, trigger: str, name: str = "Topic") -> CustomizationComponent:
    return _topic(component_id, f"kind: AdaptiveDialog\nbeginDialog:\n  kind: {trigger}\n", name)


# --- trigger detection ---


def test_topic_trigger_kind_reads_begin_dialog_kind() -> None:
    assert topic_trigger_kind("beginDialog:\n  kind: OnEscalate\n") == "OnEscalate"
    assert topic_trigger_kind("kind: AdaptiveDialog\ninputs: []\n") is None
    assert topic_trigger_kind(None) is None


# --- RULE-003 / RULE-004 / RULE-006 (unsupported triggers) ---


def test_on_activity_topic_disabled_and_recorded() -> None:
    logger = FakeLogger()
    context = MigrationContext(
        customizations={
            "t1": _trigger_topic("t1", "OnActivity", "Greeting"),
            "keep": _trigger_topic("keep", "OnRecognizedIntent", "Vacation"),
        }
    )

    result = HandleOnActivityTopicStep(cast(Logger, logger)).execute(context)

    writes = {w["record_id"]: w for w in result.pending_writes}
    assert set(writes) == {"t1"}
    assert writes["t1"]["changes"] == {
        "name": "[DEPRECATED] Greeting",
        "statecode": 1,
        "statuscode": 2,
    }
    assert logger.changes[0]["rule_id"] == "RULE-003"
    assert "OnActivity" in str(logger.changes[0]["message"])


def test_already_migrated_topic_is_skipped() -> None:
    logger = FakeLogger()
    context = MigrationContext(
        customizations={
            "t1": _trigger_topic("t1", "OnActivity", "[DEPRECATED] Greeting"),
        }
    )
    # Already Inactive + prefixed -> skip (MIG-005).
    context.customizations["t1"] = _topic(
        "t1",
        "kind: AdaptiveDialog\nbeginDialog:\n  kind: OnActivity\n",
        "[DEPRECATED] Greeting",
        statecode=1,
        statuscode=2,
    )

    result = HandleOnActivityTopicStep(cast(Logger, logger)).execute(context)

    assert result.pending_writes == []
    assert logger.changes == []


def test_rule_006_individual_trigger_step_disables_its_trigger_only() -> None:
    logger = FakeLogger()
    context = MigrationContext(
        customizations={
            "esc": _trigger_topic("esc", "OnEscalate", "Escalate"),
            "act": _trigger_topic("act", "OnActivity", "Greeting"),  # a different rule's trigger
        }
    )

    result = HandleOnEscalateTopicStep(cast(Logger, logger)).execute(context)

    writes = {w["record_id"]: w for w in result.pending_writes}
    assert set(writes) == {"esc"}  # only OnEscalate; OnActivity untouched by this step
    assert logger.changes[0]["rule_id"] == "RULE-006"
    assert "OnEscalate" in str(logger.changes[0]["message"])


def test_on_generated_response_mitigation_mentions_instructions() -> None:
    logger = FakeLogger()
    context = MigrationContext(
        customizations={"g": _trigger_topic("g", "OnGeneratedResponse", "Disclaimer")}
    )

    HandleGeneratedResponseTopicStep(cast(Logger, logger)).execute(context)

    assert "instructions" in str(logger.changes[0]["message"]).lower()


# --- RULE-007 (unsupported nodes) ---


def test_node_step_disables_topic_using_that_node() -> None:
    logger = FakeLogger()
    context = MigrationContext(
        customizations={
            "uses": _topic(
                "uses",
                "beginDialog:\n  kind: OnRecognizedIntent\n  actions:\n"
                "    - kind: AnswerQuestionWithAI\n",
                "HR Answers",
            ),
            "clean": _topic(
                "clean",
                "beginDialog:\n  kind: OnRecognizedIntent\n  actions:\n    - kind: SendActivity\n",
            ),
        }
    )

    result = HandleAnswerQuestionWithAINodeStep(cast(Logger, logger)).execute(context)

    writes = {w["record_id"]: w for w in result.pending_writes}
    assert set(writes) == {"uses"}
    assert writes["uses"]["changes"]["statecode"] == 1
    assert writes["uses"]["changes"]["name"] == "[DEPRECATED] HR Answers"
    assert logger.changes[0]["rule_id"] == "RULE-007"
    assert "AnswerQuestionWithAI" in str(logger.changes[0]["message"])


def test_node_step_ignores_topics_without_its_node() -> None:
    logger = FakeLogger()
    context = MigrationContext(
        customizations={
            "uses-other": _topic(
                "uses-other",
                "beginDialog:\n  kind: OnRecognizedIntent\n  actions:\n"
                "    - kind: AnswerQuestionWithAI\n",
            ),
        }
    )

    # RecognizeIntent step must not touch a topic that only uses AnswerQuestionWithAI.
    result = HandleRecognizeIntentNodeStep(cast(Logger, logger)).execute(context)

    assert result.pending_writes == []
    assert logger.changes == []
