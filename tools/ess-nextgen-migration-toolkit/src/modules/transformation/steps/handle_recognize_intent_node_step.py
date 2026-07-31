"""RULE-007 — Handle topics using the RecognizeIntent node (disable + deprecate)."""

from __future__ import annotations

from core.logging import Logger
from modules.transformation.steps.unsupported_construct_base import UnsupportedNodeStep


class HandleRecognizeIntentNodeStep(UnsupportedNodeStep):
    """Disable + deprecate topics using the RecognizeIntent node (RULE-007)."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            logger,
            name="HandleRecognizeIntentNode",
            node_kind="RecognizeIntent",
            rule_id="RULE-007",
            rule_name="Handle RecognizeIntent Node",
            mitigation=(
                "The RecognizeIntent node is not supported. Model the intent as a topic's "
                "trigger phrases, or rely on the agent's natural-language routing."
            ),
        )
