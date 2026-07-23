"""RULE-004 — Handle OnGeneratedResponse Topic (disable + deprecate)."""

from __future__ import annotations

from core.logging import Logger
from modules.transformation.steps.unsupported_construct_base import UnsupportedTopicTriggerStep


class HandleGeneratedResponseTopicStep(UnsupportedTopicTriggerStep):
    """Disable + deprecate every OnGeneratedResponse topic (RULE-004)."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            logger,
            name="HandleGeneratedResponseTopic",
            trigger_kind="OnGeneratedResponse",
            rule_id="RULE-004",
            rule_name="Handle OnGeneratedResponse Topic",
            mitigation=(
                "OnGeneratedResponse is removed in DA. If you used it to add a disclaimer or "
                "official badge to outgoing messages, add agent instructions that enforce that "
                "disclaimer/badge on every generated response instead."
            ),
        )
