"""RULE-006 — Handle OnPlanComplete Topic (disable + deprecate)."""

from __future__ import annotations

from core.logging import Logger
from modules.transformation.steps.unsupported_construct_base import UnsupportedTopicTriggerStep


class HandleOnPlanCompleteTopicStep(UnsupportedTopicTriggerStep):
    """Disable + deprecate every OnPlanComplete topic (RULE-006)."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            logger,
            name="HandleOnPlanCompleteTopic",
            trigger_kind="OnPlanComplete",
            rule_id="RULE-006",
            rule_name="Handle OnPlanComplete Topic",
            mitigation=(
                "OnPlanComplete has no DA equivalent. Move any needed post-response "
                "behavior into agent instructions or a supported topic."
            ),
        )
