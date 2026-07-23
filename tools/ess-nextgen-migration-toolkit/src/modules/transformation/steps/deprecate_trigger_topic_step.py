"""Shared base for topic-trigger deprecation rules (RULE-003, RULE-004).

Some topic triggers (``OnActivity``, ``OnGeneratedResponse``) have no Declarative
Agent equivalent. Per the migration philosophy the toolkit never deletes customer
logic — it **disables** the topic (Inactive statecode/statuscode) and prefixes its
title with ``[DEPRECATED]`` (once), preserving all nodes/expressions, and emits a
manual-review warning.

The trigger type is read from the topic's ``data`` YAML (``beginDialog.kind``);
the title and enabled state are **record fields** (botcomponent ``name`` /
``statecode`` / ``statuscode``), not the YAML — so this rule stages record-field
edits on the ``WritebackPlan`` and never rewrites ``data``.

.. note::
   Per the Dataverse ``botcomponent`` table reference, ``statecode`` (0=Active,
   1=Inactive) and ``statuscode`` are **writable** columns, so ``name`` /
   ``statecode`` / ``statuscode`` are set via a normal ``PATCH /botcomponents(id)``.
   The only live-confirmation item (TASK-009) is whether a *single* PATCH may
   combine the State change with content columns (e.g. ``data``) when a topic is
   also rewritten by another rule — if not, the Writeback step emits the state
   fields as a separate PATCH.
   https://learn.microsoft.com/power-apps/developer/data-platform/reference/entities/botcomponent
"""

from __future__ import annotations

import re
from typing import Any

from core.logging import Logger
from modules.transformation.migration_step import MigrationPipelineStep
from modules.transformation.models import CustomizationComponent, MigrationContext

_BOTCOMPONENTS_ENTITY = "botcomponents"
_NAME_FIELD = "name"
_STATECODE_FIELD = "statecode"
_STATUSCODE_FIELD = "statuscode"
# Disable-but-preserve: the Dataverse botcomponent Inactive state — statecode=1
# (Inactive) / statuscode=2 — both writable columns per the botcomponent table
# reference, set via a normal PATCH /botcomponents(id).
_INACTIVE_STATECODE = 1
_INACTIVE_STATUSCODE = 2
_DEPRECATED_MARKER = "[DEPRECATED]"
_DEPRECATED_PREFIX = "[DEPRECATED] "

# The topic trigger is ``beginDialog.kind`` — the first indented ``kind:`` line
# after the top-level ``beginDialog:`` key.
_BEGIN_DIALOG_RE = re.compile(r"(?m)^beginDialog:[ \t]*$")
_KIND_RE = re.compile(r"(?m)^[ \t]+kind:[ \t]*(?P<kind>[A-Za-z0-9_]+)")


class DeprecateTriggerTopicStep(MigrationPipelineStep):
    """Disable + [DEPRECATED]-prefix topics whose trigger is unsupported in DA."""

    def __init__(
        self, logger: Logger, *, name: str, description: str, trigger_kind: str, rule_id: str
    ) -> None:
        super().__init__(
            name=name,
            description=description,
            supported_modes=("READONLY", "WRITEBACK"),
        )
        self._logger = logger
        self._trigger_kind = trigger_kind
        self._rule_id = rule_id

    def execute(self, context: MigrationContext) -> MigrationContext:
        deprecated = 0
        for component in context.customizations.values():
            if topic_trigger_kind(component.data) != self._trigger_kind:
                continue
            if _already_migrated(component):
                continue

            target = context.writeback.target(
                _BOTCOMPONENTS_ENTITY,
                component.component_id,
                original={
                    _NAME_FIELD: component.name,
                    _STATECODE_FIELD: component.statecode,
                    _STATUSCODE_FIELD: component.statuscode,
                },
            )
            target.set(_NAME_FIELD, _deprecated_title(target.get(_NAME_FIELD)))
            target.set(_STATECODE_FIELD, _INACTIVE_STATECODE)
            target.set(_STATUSCODE_FIELD, _INACTIVE_STATUSCODE)

            self._logger.LogWarning(
                f"{self._rule_id}: disabled unsupported {self._trigger_kind} topic "
                f"'{component.name}' ({component.schemaname}); review and re-implement "
                "its logic with supported Declarative Agent capabilities.",
                pipeline_stage="Transformation",
                pipeline_step=self.name(),
            )
            deprecated += 1

        self._logger.LogInfo(
            f"{self._rule_id} deprecated {deprecated} {self._trigger_kind} topic(s).",
            pipeline_stage="Transformation",
            pipeline_step=self.name(),
        )
        return context


def topic_trigger_kind(data: Any) -> str | None:
    """Return a topic's trigger kind (``beginDialog.kind``) from its ``data`` YAML."""
    if not isinstance(data, str) or not data:
        return None
    begin = _BEGIN_DIALOG_RE.search(data)
    if begin is None:
        return None
    kind = _KIND_RE.search(data, begin.end())
    return kind.group("kind") if kind else None


def _already_migrated(component: CustomizationComponent) -> bool:
    """A topic already disabled AND [DEPRECATED]-prefixed is skipped (MIG-005)."""
    name = component.name or ""
    return component.statecode == _INACTIVE_STATECODE and name.startswith(_DEPRECATED_MARKER)


def _deprecated_title(name: Any) -> Any:
    """Prefix a title with ``[DEPRECATED] `` exactly once (idempotent)."""
    if not isinstance(name, str):
        return name
    if name.startswith(_DEPRECATED_MARKER):
        return name
    return f"{_DEPRECATED_PREFIX}{name}"
