"""RULE-007 — Handle topics using the TransferConversationV2 node (disable + deprecate)."""

from __future__ import annotations

from core.logging import Logger
from modules.transformation.steps.unsupported_construct_base import UnsupportedNodeStep


class HandleTransferConversationV2NodeStep(UnsupportedNodeStep):
    """Disable + deprecate topics using the TransferConversationV2 node (RULE-007)."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            logger,
            name="HandleTransferConversationV2Node",
            node_kind="TransferConversationV2",
            rule_id="RULE-007",
            rule_name="Handle TransferConversationV2 Node",
            mitigation=(
                "TransferConversationV2 is not supported yet. Implement hand-off with a "
                "supported action, or wait for DA support in a later wave."
            ),
        )
