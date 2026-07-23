"""RULE-002 — Replace EndConversation nodes with CancelAllDialogs (End All Topics).

Declarative Agents do not support the ``EndConversation`` node; ESS has validated
that ``CancelAllDialogs`` (End All Topics) preserves the expected runtime
behavior. This step rewrites every ``EndConversation`` node in each customized
topic's ``data`` YAML, preserving node connectivity, ids, and all other logic.

The rewrite is a node-anchored line substitution (not a YAML round-trip), so
untouched regions are left byte-for-byte identical — a topic with no
EndConversation node produces no write. Edits are staged on the ``WritebackPlan``
(``context.writeback``); the step performs no Dataverse I/O.
"""

from __future__ import annotations

import re
from typing import Any

from core.logging import Logger
from modules.transformation.migration_step import MigrationPipelineStep
from modules.transformation.models import MigrationContext

_BOTCOMPONENTS_ENTITY = "botcomponents"
_DATA_FIELD = "data"
_CANCEL_ALL_DIALOGS_KIND = "CancelAllDialogs"
# A topic node is a YAML line like ``    - kind: EndConversation`` (optionally
# without the list-item dash for a nested kind). Match the whole line and rewrite
# only the kind, preserving the list-item prefix + indentation so the node id and
# every other line are untouched.
_END_CONVERSATION_RE = re.compile(
    r"(?m)^(?P<prefix>[ \t]*(?:-[ \t]*)?)kind:[ \t]*EndConversation[ \t]*$"
)


class ReplaceEndConversationStep(MigrationPipelineStep):
    """Rewrite EndConversation nodes to CancelAllDialogs across customized topics."""

    def __init__(self, logger: Logger) -> None:
        super().__init__(
            name="ReplaceEndConversation",
            description="Replace EndConversation nodes with CancelAllDialogs (RULE-002).",
            supported_modes=("READONLY", "WRITEBACK"),
        )
        self._logger = logger

    def execute(self, context: MigrationContext) -> MigrationContext:
        rewritten = 0
        for component in context.customizations.values():
            # Read the working value if an earlier rule already staged this topic
            # (chaining), else the original topic data.
            existing = context.writeback.target_for(_BOTCOMPONENTS_ENTITY, component.component_id)
            current = existing.get(_DATA_FIELD) if existing is not None else component.data

            replaced = replace_end_conversation(current)
            if replaced == current:
                continue  # no EndConversation node -> nothing to stage

            target = context.writeback.target(
                _BOTCOMPONENTS_ENTITY,
                component.component_id,
                original={_DATA_FIELD: component.data},
            )
            target.set(_DATA_FIELD, replaced)
            rewritten += 1

        self._logger.LogInfo(
            f"RULE-002 replaced EndConversation nodes in {rewritten} topic(s).",
            pipeline_stage="Transformation",
            pipeline_step=self.name(),
        )
        return context


def replace_end_conversation(data: Any) -> Any:
    """Replace every ``EndConversation`` node kind with ``CancelAllDialogs``.

    Node-anchored line rewrite that preserves the list-item prefix, indentation,
    the node id, and all other topic logic. Idempotent, and returns the input
    unchanged when there is no EndConversation node (no reserialization).
    """
    if not isinstance(data, str) or not data:
        return data
    replaced, count = _END_CONVERSATION_RE.subn(
        lambda match: f"{match.group('prefix')}kind: {_CANCEL_ALL_DIALOGS_KIND}", data
    )
    return replaced if count else data
