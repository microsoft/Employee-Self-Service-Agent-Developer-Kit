"""RULE-006 — Handle OnUnknownIntent Topic (disable + deprecate)."""

from __future__ import annotations

from core.logging import Logger
from modules.transformation.steps.unsupported_construct_base import UnsupportedTopicTriggerStep


class HandleOnUnknownIntentTopicStep(UnsupportedTopicTriggerStep):
    """Disable + deprecate every OnUnknownIntent topic (RULE-006)."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            logger,
            name="HandleOnUnknownIntentTopic",
            trigger_kind="OnUnknownIntent",
            rule_id="RULE-006",
            rule_name="Handle OnUnknownIntent Topic",
            mitigation=(
                "OnUnknownIntent (fallback) is not supported in DA. Add agent instructions "
                "to steer graceful fallback replies, or route unmatched input to a "
                "supported topic."
            ),
        )
