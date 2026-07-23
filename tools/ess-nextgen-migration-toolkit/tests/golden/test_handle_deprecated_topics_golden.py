"""Golden test for RULE-003 / RULE-004 — deterministic topic deprecation.

An unsupported-trigger topic -> the handler step -> the exact record-field write:
title prefixed once with [DEPRECATED], state set to the Inactive pair. The topic
``data`` (logic) is preserved and never written.
"""

from __future__ import annotations

from typing import cast

from core.logging import Logger
from modules.transformation.models import CustomizationComponent, MigrationContext
from modules.transformation.steps.handle_generated_response_topic_step import (
    HandleGeneratedResponseTopicStep,
)
from modules.transformation.steps.handle_on_activity_topic_step import HandleOnActivityTopicStep

_ON_ACTIVITY_TOPIC = """\
kind: AdaptiveDialog
beginDialog:
  kind: OnActivity
  id: main
  actions:
    - kind: SendActivity
      id: greet
      activity: Welcome!
"""

_ON_GENERATED_RESPONSE_TOPIC = """\
kind: AdaptiveDialog
beginDialog:
  kind: OnGeneratedResponse
  id: main
  actions:
    - kind: SendActivity
      id: note
      activity: Post-processing the generated response.
"""


class _FakeLogger:
    def LogInfo(self, *_: object, **__: object) -> None: ...
    def LogWarning(self, *_: object, **__: object) -> None: ...
    def LogDebug(self, *_: object, **__: object) -> None: ...


def test_handle_on_activity_topic_golden() -> None:
    context = MigrationContext(
        customizations={
            "topic-onactivity": CustomizationComponent(
                component_id="topic-onactivity",
                name="Custom Activity Handler",
                data=_ON_ACTIVITY_TOPIC,
                statecode=0,
                statuscode=1,
            )
        }
    )

    result = HandleOnActivityTopicStep(cast(Logger, _FakeLogger())).execute(context)

    assert result.pending_writes == [
        {
            "entity_set": "botcomponents",
            "record_id": "topic-onactivity",
            "changes": {
                "name": "[DEPRECATED] Custom Activity Handler",
                "statecode": 1,
                "statuscode": 2,
            },
        }
    ]


def test_handle_generated_response_topic_golden() -> None:
    context = MigrationContext(
        customizations={
            "topic-ongenresp": CustomizationComponent(
                component_id="topic-ongenresp",
                name="Response Post-Processor",
                data=_ON_GENERATED_RESPONSE_TOPIC,
                statecode=0,
                statuscode=1,
            )
        }
    )

    result = HandleGeneratedResponseTopicStep(cast(Logger, _FakeLogger())).execute(context)

    assert result.pending_writes == [
        {
            "entity_set": "botcomponents",
            "record_id": "topic-ongenresp",
            "changes": {
                "name": "[DEPRECATED] Response Post-Processor",
                "statecode": 1,
                "statuscode": 2,
            },
        }
    ]
