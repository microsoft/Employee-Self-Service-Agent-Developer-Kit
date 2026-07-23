"""Unit tests for RULE-002 — ReplaceEndConversationStep."""

from __future__ import annotations

from typing import cast

from core.logging import Logger
from modules.transformation.models import CustomizationComponent, MigrationContext
from modules.transformation.steps.replace_end_conversation_step import (
    ReplaceEndConversationStep,
    replace_end_conversation,
)


class FakeLogger:
    def LogInfo(self, *_: object, **__: object) -> None: ...
    def LogWarning(self, *_: object, **__: object) -> None: ...
    def LogDebug(self, *_: object, **__: object) -> None: ...


def _step() -> ReplaceEndConversationStep:
    return ReplaceEndConversationStep(cast(Logger, FakeLogger()))


def _topic(component_id: str, data: str) -> CustomizationComponent:
    return CustomizationComponent(component_id=component_id, data=data)


# --- pure transform ---


def test_replace_end_conversation_rewrites_node_and_preserves_id_and_indent() -> None:
    data = "      actions:\n        - kind: EndConversation\n          id: pYEcde\n"

    replaced = replace_end_conversation(data)

    assert replaced == ("      actions:\n        - kind: CancelAllDialogs\n          id: pYEcde\n")


def test_replace_end_conversation_rewrites_every_node() -> None:
    data = "    - kind: EndConversation\n      id: a\n    - kind: EndConversation\n      id: b\n"

    replaced = replace_end_conversation(data)

    assert "EndConversation" not in replaced
    assert replaced.count("kind: CancelAllDialogs") == 2
    # ids preserved
    assert "id: a" in replaced and "id: b" in replaced


def test_replace_end_conversation_is_idempotent_when_already_cancel_all_dialogs() -> None:
    data = "    - kind: CancelAllDialogs\n      id: pYEcde\n"
    assert replace_end_conversation(data) == data


def test_replace_end_conversation_leaves_topic_without_node_unchanged() -> None:
    data = "beginDialog:\n  kind: OnRecognizedIntent\n  actions:\n    - kind: SendActivity\n"
    assert replace_end_conversation(data) is data or replace_end_conversation(data) == data


def test_replace_end_conversation_does_not_match_substring_in_other_lines() -> None:
    # A variable that merely mentions the word must not be rewritten.
    data = '    value: ="EndConversation was requested"\n'
    assert replace_end_conversation(data) == data


# --- step wiring ---


def test_step_stages_data_write_only_for_topics_with_end_conversation() -> None:
    context = MigrationContext(
        customizations={
            "topic-1": _topic("topic-1", "actions:\n  - kind: EndConversation\n    id: x\n"),
            "topic-2": _topic("topic-2", "actions:\n  - kind: SendActivity\n    id: y\n"),
        }
    )

    result = _step().execute(context)

    writes = {w["record_id"]: w for w in result.pending_writes}
    # Only topic-1 (had EndConversation) produces a write; topic-2 is untouched.
    assert set(writes) == {"topic-1"}
    assert writes["topic-1"]["entity_set"] == "botcomponents"
    assert "kind: CancelAllDialogs" in writes["topic-1"]["changes"]["data"]
    assert "EndConversation" not in writes["topic-1"]["changes"]["data"]


def test_step_no_writes_when_no_topic_has_end_conversation() -> None:
    context = MigrationContext(
        customizations={"topic-2": _topic("topic-2", "actions:\n  - kind: SendActivity\n")}
    )

    result = _step().execute(context)

    assert result.pending_writes == []


def test_step_chains_on_working_value_from_an_earlier_edit() -> None:
    context = MigrationContext(
        customizations={"topic-1": _topic("topic-1", "  - kind: EndConversation\n    id: x\n")}
    )
    # Simulate an earlier rule having already edited this topic's data.
    context.writeback.target(
        "botcomponents", "topic-1", original={"data": "  - kind: EndConversation\n    id: x\n"}
    ).set("data", "  - kind: EndConversation\n    id: x\n# edited-by-earlier-rule\n")

    result = _step().execute(context)

    writes = {w["record_id"]: w for w in result.pending_writes}
    data = writes["topic-1"]["changes"]["data"]
    # RULE-002 composed on the earlier edit (comment retained) and replaced the node.
    assert "# edited-by-earlier-rule" in data
    assert "kind: CancelAllDialogs" in data
    assert "EndConversation" not in data
