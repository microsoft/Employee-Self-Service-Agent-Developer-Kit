"""RULE-003 — Handle OnActivity Topic (disable + deprecate)."""

from __future__ import annotations

from core.logging import Logger
from modules.transformation.steps.deprecate_trigger_topic_step import DeprecateTriggerTopicStep


class HandleOnActivityTopicStep(DeprecateTriggerTopicStep):
    """Disable and [DEPRECATED]-prefix every OnActivity topic (RULE-003)."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            logger,
            name="HandleOnActivityTopic",
            description="Disable + deprecate OnActivity topics (RULE-003).",
            trigger_kind="OnActivity",
            rule_id="RULE-003",
        )
