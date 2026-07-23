"""RULE-004 — Handle OnGeneratedResponse Topic (disable + deprecate)."""

from __future__ import annotations

from core.logging import Logger
from modules.transformation.steps.deprecate_trigger_topic_step import DeprecateTriggerTopicStep


class HandleGeneratedResponseTopicStep(DeprecateTriggerTopicStep):
    """Disable and [DEPRECATED]-prefix every OnGeneratedResponse topic (RULE-004)."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            logger,
            name="HandleGeneratedResponseTopic",
            description="Disable + deprecate OnGeneratedResponse topics (RULE-004).",
            rule_id="RULE-004",
            rule_name="Handle OnGeneratedResponse Topic",
            triggers={
                "OnGeneratedResponse": "Re-implement any needed behavior (e.g. badges "
                "or disclaimers) with supported Declarative Agent constructs.",
            },
        )
