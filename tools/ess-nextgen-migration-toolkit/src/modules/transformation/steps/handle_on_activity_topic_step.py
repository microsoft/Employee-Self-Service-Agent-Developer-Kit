"""RULE-003 — Handle OnActivity Topic (disable + deprecate)."""

from __future__ import annotations

from core.logging import Logger
from modules.transformation.steps.unsupported_construct_base import UnsupportedTopicTriggerStep


class HandleOnActivityTopicStep(UnsupportedTopicTriggerStep):
    """Disable + deprecate every OnActivity topic (RULE-003)."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            logger,
            name="HandleOnActivityTopic",
            trigger_kind="OnActivity",
            rule_id="RULE-003",
            rule_name="Handle OnActivity Topic",
            mitigation=(
                "OnActivity has no DA equivalent. Move its user-context / setup logic "
                "under an OnConversationStart topic, or discard it if no longer needed."
            ),
        )
