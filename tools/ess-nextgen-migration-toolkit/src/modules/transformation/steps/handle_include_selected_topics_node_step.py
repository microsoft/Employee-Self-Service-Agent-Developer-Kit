"""RULE-007 — Handle topics using the IncludeSelectedTopics node (disable + deprecate)."""

from __future__ import annotations

from core.logging import Logger
from modules.transformation.steps.unsupported_construct_base import UnsupportedNodeStep


class HandleIncludeSelectedTopicsNodeStep(UnsupportedNodeStep):
    """Disable + deprecate topics using the IncludeSelectedTopics node (RULE-007)."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            logger,
            name="HandleIncludeSelectedTopicsNode",
            node_kind="IncludeSelectedTopics",
            rule_id="RULE-007",
            rule_name="Handle IncludeSelectedTopics Node",
            mitigation=(
                "IncludeSelectedTopics is not supported. Restructure so the needed logic "
                "lives in standalone topics the agent can select directly."
            ),
        )
