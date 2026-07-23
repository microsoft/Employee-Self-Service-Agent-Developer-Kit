"""RULE-007 — Disable topics that use unsupported conversational nodes.

Some node kinds (e.g. AnswerQuestionWithAI, RecognizeIntent — see
``service.constants.UNSUPPORTED_TOPIC_NODES``) have no Declarative Agent
equivalent today and no automatic in-place mitigation. A topic that uses any of
them will not function in DA, so — like an unsupported trigger — the topic is
disabled + deprecated (all logic preserved) and flagged for manual review, with
the specific unsupported node(s) named in the per-topic report.
"""

from __future__ import annotations

import re
from typing import Any

from core.logging import Logger
from modules.transformation.migration_step import MigrationPipelineStep
from modules.transformation.models import MigrationContext
from modules.transformation.steps.deprecate_trigger_topic_step import deprecate_topic
from service.constants import UNSUPPORTED_TOPIC_NODES

_RULE_ID = "RULE-007"
_RULE_NAME = "Disable Topics With Unsupported Nodes"

# A node is a YAML line ``<indent>[- ]kind: <NodeKind>``. Capture the kind so we
# can test membership against the unsupported-node set.
_NODE_KIND_RE = re.compile(r"(?m)^[ \t]*(?:-[ \t]*)?kind:[ \t]*(?P<kind>[A-Za-z0-9_]+)[ \t]*$")


class DisableUnsupportedNodeTopicsStep(MigrationPipelineStep):
    """Disable + deprecate any topic whose ``data`` uses an unsupported node kind."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            name="DisableUnsupportedNodeTopics",
            description="Disable + deprecate topics that use unsupported nodes (RULE-007).",
            supported_modes=("READONLY", "WRITEBACK"),
        )
        self._logger = logger

    def execute(self, context: MigrationContext) -> MigrationContext:
        disabled = 0
        for component in context.customizations.values():
            found = unsupported_nodes(component.data)
            if not found:
                continue
            if deprecate_topic(
                context,
                self._logger,
                component,
                rule_id=_RULE_ID,
                rule_name=_RULE_NAME,
                reason=f"uses unsupported node(s): {', '.join(found)}",
                guidance="Re-implement these with supported Declarative Agent constructs, "
                "or wait for MCS platform support.",
                pipeline_step=self.name(),
            ):
                disabled += 1

        self._logger.LogInfo(
            f"{_RULE_ID} disabled {disabled} topic(s) using unsupported nodes.",
            pipeline_stage="Transformation",
            pipeline_step=self.name(),
        )
        return context


def unsupported_nodes(data: Any) -> list[str]:
    """Return the sorted unique unsupported node kinds present in a topic's ``data``."""
    if not isinstance(data, str) or not data:
        return []
    found = {
        match.group("kind")
        for match in _NODE_KIND_RE.finditer(data)
        if match.group("kind") in UNSUPPORTED_TOPIC_NODES
    }
    return sorted(found)
