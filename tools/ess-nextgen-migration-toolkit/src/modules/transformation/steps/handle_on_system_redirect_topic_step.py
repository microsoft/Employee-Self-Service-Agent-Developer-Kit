"""RULE-006 — Handle OnSystemRedirect Topic (disable + deprecate)."""

from __future__ import annotations

from core.logging import Logger
from modules.transformation.steps.unsupported_construct_base import UnsupportedTopicTriggerStep


class HandleOnSystemRedirectTopicStep(UnsupportedTopicTriggerStep):
    """Disable + deprecate every OnSystemRedirect topic (RULE-006)."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            logger,
            name="HandleOnSystemRedirectTopic",
            trigger_kind="OnSystemRedirect",
            rule_id="RULE-006",
            rule_name="Handle OnSystemRedirect Topic",
            mitigation=(
                "OnSystemRedirect (legacy Reset / End Conversation) is cut in DA. Remove "
                "it, or redesign the reset/end flow using supported topics (e.g. End All "
                "Topics)."
            ),
        )
