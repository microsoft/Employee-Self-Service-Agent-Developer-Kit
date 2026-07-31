"""RULE-007 — Handle topics using the InvokeAIBuilderModelAction node (disable + deprecate)."""

from __future__ import annotations

from core.logging import Logger
from modules.transformation.steps.unsupported_construct_base import UnsupportedNodeStep


class HandleInvokeAIBuilderModelActionNodeStep(UnsupportedNodeStep):
    """Disable + deprecate topics using the InvokeAIBuilderModelAction node (RULE-007)."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            logger,
            name="HandleInvokeAIBuilderModelActionNode",
            node_kind="InvokeAIBuilderModelAction",
            rule_id="RULE-007",
            rule_name="Handle InvokeAIBuilderModelAction Node",
            mitigation=(
                "Invoking AI Builder models from a topic is not supported. Call the model "
                "via a connected Power Automate flow instead, or wait for DA support."
            ),
        )
