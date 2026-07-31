"""RULE-007 — Handle topics using the AnswerQuestionWithAI node (disable + deprecate)."""

from __future__ import annotations

from core.logging import Logger
from modules.transformation.steps.unsupported_construct_base import UnsupportedNodeStep


class HandleAnswerQuestionWithAINodeStep(UnsupportedNodeStep):
    """Disable + deprecate topics using the AnswerQuestionWithAI node (RULE-007)."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            logger,
            name="HandleAnswerQuestionWithAINode",
            node_kind="AnswerQuestionWithAI",
            rule_id="RULE-007",
            rule_name="Handle AnswerQuestionWithAI Node",
            mitigation=(
                "AnswerQuestionWithAI (generative answers) is not supported yet. Configure "
                "the agent's knowledge sources and instructions to answer from your "
                "content, or wait for DA support in a later wave."
            ),
        )
