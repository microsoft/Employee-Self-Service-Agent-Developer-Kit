"""RULE-006 — Handle OnSelectIntent Topic (disable + deprecate)."""

from __future__ import annotations

from core.logging import Logger
from modules.transformation.steps.unsupported_construct_base import UnsupportedTopicTriggerStep


class HandleOnSelectIntentTopicStep(UnsupportedTopicTriggerStep):
    """Disable + deprecate every OnSelectIntent topic (RULE-006)."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            logger,
            name="HandleOnSelectIntentTopic",
            trigger_kind="OnSelectIntent",
            rule_id="RULE-006",
            rule_name="Handle OnSelectIntent Topic",
            mitigation=(
                "OnSelectIntent (Multiple Topics Matched) is not supported in DA. Rely on "
                "agent instructions to disambiguate, and design topics so one is selected "
                "per turn."
            ),
        )
