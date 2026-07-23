"""Unit tests for RULE-003 / RULE-004 — topic-trigger deprecation steps."""

from __future__ import annotations

from typing import cast

from core.logging import Logger
from modules.transformation.models import CustomizationComponent, MigrationContext
from modules.transformation.steps.deprecate_trigger_topic_step import topic_trigger_kind
from modules.transformation.steps.handle_generated_response_topic_step import (
    HandleGeneratedResponseTopicStep,
)
from modules.transformation.steps.handle_on_activity_topic_step import HandleOnActivityTopicStep


class FakeLogger:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def LogInfo(self, *_: object, **__: object) -> None: ...
    def LogDebug(self, *_: object, **__: object) -> None: ...

    def LogWarning(self, message: str, **__: object) -> None:
        self.warnings.append(message)


def _topic(
    component_id: str,
    trigger: str,
    name: str,
    *,
    statecode: int | None = 0,
    statuscode: int | None = 1,
) -> CustomizationComponent:
    data = f"kind: AdaptiveDialog\nbeginDialog:\n  kind: {trigger}\n  id: main\n"
    return CustomizationComponent(
        component_id=component_id,
        schemaname=f"msdyn_copilotforemployeeselfservicehr.topic.{component_id}",
        name=name,
        data=data,
        statecode=statecode,
        statuscode=statuscode,
    )


# --- trigger detection ---


def test_topic_trigger_kind_reads_begin_dialog_kind() -> None:
    assert topic_trigger_kind("beginDialog:\n  kind: OnActivity\n  id: m\n") == "OnActivity"
    assert (
        topic_trigger_kind("kind: AdaptiveDialog\nbeginDialog:\n  kind: OnRecognizedIntent\n")
        == "OnRecognizedIntent"
    )
    assert topic_trigger_kind("kind: AdaptiveDialog\ninputs: []\n") is None
    assert topic_trigger_kind(None) is None


# --- RULE-003: OnActivity ---


def test_on_activity_topic_is_disabled_and_deprecated() -> None:
    logger = FakeLogger()
    context = MigrationContext(
        customizations={
            "t1": _topic("t1", "OnActivity", "Greeting"),
            "t2": _topic("t2", "OnRecognizedIntent", "Vacation"),
        }
    )

    result = HandleOnActivityTopicStep(cast(Logger, logger)).execute(context)

    writes = {w["record_id"]: w for w in result.pending_writes}
    assert set(writes) == {"t1"}  # only the OnActivity topic
    assert writes["t1"]["entity_set"] == "botcomponents"
    assert writes["t1"]["changes"] == {
        "name": "[DEPRECATED] Greeting",
        "statecode": 1,
        "statuscode": 2,
    }
    assert len(logger.warnings) == 1 and "OnActivity" in logger.warnings[0]


def test_already_migrated_on_activity_topic_is_skipped() -> None:
    logger = FakeLogger()
    context = MigrationContext(
        customizations={
            "t1": _topic("t1", "OnActivity", "[DEPRECATED] Greeting", statecode=1, statuscode=2),
        }
    )

    result = HandleOnActivityTopicStep(cast(Logger, logger)).execute(context)

    assert result.pending_writes == []
    assert logger.warnings == []


def test_on_activity_step_is_idempotent_on_repeat_execution() -> None:
    logger = FakeLogger()
    context = MigrationContext(customizations={"t1": _topic("t1", "OnActivity", "Greeting")})
    step = HandleOnActivityTopicStep(cast(Logger, logger))

    step.execute(context)
    result = step.execute(context)  # re-run must not double-prefix or add writes

    writes = {w["record_id"]: w for w in result.pending_writes}
    assert writes["t1"]["changes"]["name"] == "[DEPRECATED] Greeting"


# --- RULE-004: OnGeneratedResponse ---


def test_generated_response_topic_is_disabled_and_deprecated() -> None:
    logger = FakeLogger()
    context = MigrationContext(
        customizations={
            "t1": _topic("t1", "OnGeneratedResponse", "Fallback"),
            "t2": _topic("t2", "OnActivity", "Greeting"),  # RULE-004 must ignore this
        }
    )

    result = HandleGeneratedResponseTopicStep(cast(Logger, logger)).execute(context)

    writes = {w["record_id"]: w for w in result.pending_writes}
    assert set(writes) == {"t1"}
    assert writes["t1"]["changes"] == {
        "name": "[DEPRECATED] Fallback",
        "statecode": 1,
        "statuscode": 2,
    }
