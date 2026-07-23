"""Golden test for RULE-002 — deterministic EndConversation -> CancelAllDialogs.

Input topic (a realistic AdaptiveDialog) -> ReplaceEndConversationStep -> the
output must exactly match the golden result: only the EndConversation node kind
changes; every other line (ids, indentation, logic) is byte-for-byte preserved.
"""

from __future__ import annotations

from typing import cast

from core.logging import Logger
from modules.transformation.models import CustomizationComponent, MigrationContext
from modules.transformation.steps.replace_end_conversation_step import ReplaceEndConversationStep

_INPUT_TOPIC = """\
kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    triggerQueries:
      - Where can I eat?
  actions:
    - kind: SendActivity
      id: greet
      activity: Here are the dining stations near you.

    - kind: EndConversation
      id: pYEcde

inputType: {}
outputType: {}
"""

_GOLDEN_TOPIC = """\
kind: AdaptiveDialog
beginDialog:
  kind: OnRecognizedIntent
  id: main
  intent:
    triggerQueries:
      - Where can I eat?
  actions:
    - kind: SendActivity
      id: greet
      activity: Here are the dining stations near you.

    - kind: CancelAllDialogs
      id: pYEcde

inputType: {}
outputType: {}
"""


class _FakeLogger:
    def LogInfo(self, *_: object, **__: object) -> None: ...
    def LogWarning(self, *_: object, **__: object) -> None: ...
    def LogDebug(self, *_: object, **__: object) -> None: ...


def test_replace_end_conversation_golden() -> None:
    context = MigrationContext(
        customizations={
            "topic-dining": CustomizationComponent(component_id="topic-dining", data=_INPUT_TOPIC)
        }
    )

    result = ReplaceEndConversationStep(cast(Logger, _FakeLogger())).execute(context)

    writes = result.pending_writes
    assert len(writes) == 1
    assert writes[0]["entity_set"] == "botcomponents"
    assert writes[0]["record_id"] == "topic-dining"
    assert writes[0]["changes"]["data"] == _GOLDEN_TOPIC
