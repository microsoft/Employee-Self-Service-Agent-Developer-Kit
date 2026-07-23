"""RULE-006 — Handle OnEscalate Topic (disable + deprecate)."""

from __future__ import annotations

from core.logging import Logger
from modules.transformation.steps.unsupported_construct_base import UnsupportedTopicTriggerStep


class HandleOnEscalateTopicStep(UnsupportedTopicTriggerStep):
    """Disable + deprecate every OnEscalate topic (RULE-006)."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            logger,
            name="HandleOnEscalateTopic",
            trigger_kind="OnEscalate",
            rule_id="RULE-006",
            rule_name="Handle OnEscalate Topic",
            mitigation=(
                "OnEscalate (live-agent hand-off) is not available yet. Implement "
                "escalation via a supported hand-off action, or wait for DA support in a "
                "later wave."
            ),
        )
