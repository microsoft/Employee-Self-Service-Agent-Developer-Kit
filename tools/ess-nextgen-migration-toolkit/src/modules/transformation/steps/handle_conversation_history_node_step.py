"""RULE-007 — Handle topics using the ConversationHistory node (disable + deprecate)."""

from __future__ import annotations

from core.logging import Logger
from modules.transformation.steps.unsupported_construct_base import UnsupportedNodeStep


class HandleConversationHistoryNodeStep(UnsupportedNodeStep):
    """Disable + deprecate topics using the ConversationHistory node (RULE-007)."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            logger,
            name="HandleConversationHistoryNode",
            node_kind="ConversationHistory",
            rule_id="RULE-007",
            rule_name="Handle ConversationHistory Node",
            mitigation=(
                "The ConversationHistory node is not supported. Rely on the agent's "
                "built-in context handling, or restructure the topic to not depend on it."
            ),
        )
