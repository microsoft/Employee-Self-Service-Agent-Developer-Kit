"""RULE-007 — Handle topics using the SearchAndSummarizeContent node (disable + deprecate)."""

from __future__ import annotations

from core.logging import Logger
from modules.transformation.steps.unsupported_construct_base import UnsupportedNodeStep


class HandleSearchAndSummarizeContentNodeStep(UnsupportedNodeStep):
    """Disable + deprecate topics using the SearchAndSummarizeContent node (RULE-007)."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            logger,
            name="HandleSearchAndSummarizeContentNode",
            node_kind="SearchAndSummarizeContent",
            rule_id="RULE-007",
            rule_name="Handle SearchAndSummarizeContent Node",
            mitigation=(
                "SearchAndSummarizeContent (generative answers, advanced) is not supported "
                "yet. Use the agent's knowledge sources for grounded answers, or wait for "
                "DA support in a later wave."
            ),
        )
