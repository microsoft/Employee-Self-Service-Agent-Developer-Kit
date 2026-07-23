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
from modules.transformation.steps.topic_change_log import record_topic_change

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
    """Disable + [DEPRECATED]-prefix topics whose trigger is unsupported in DA.

    ``triggers`` maps each unsupported ``beginDialog.kind`` this rule handles to a
    short customer guidance string, so one step can cover several related triggers
    (e.g. RULE-006) while RULE-003/004 each pass a single-entry mapping.
    """

    def __init__(
        self,
        logger: Logger,
        *,
        name: str,
        description: str,
        rule_id: str,
        rule_name: str,
        triggers: dict[str, str],
    ) -> None:
        super().__init__(
            name=name,
            description=description,
            supported_modes=("READONLY", "WRITEBACK"),
        )
        self._logger = logger
        self._rule_id = rule_id
        self._rule_name = rule_name
        self._triggers = triggers

    def execute(self, context: MigrationContext) -> MigrationContext:
        deprecated = 0
        for component in context.customizations.values():
            kind = topic_trigger_kind(component.data)
            if kind is None or kind not in self._triggers:
                continue
            if deprecate_topic(
                context,
                self._logger,
                component,
                rule_id=self._rule_id,
                rule_name=self._rule_name,
                reason=f"unsupported '{kind}' trigger",
                guidance=self._triggers[kind],
                pipeline_step=self.name(),
            ):
                deprecated += 1

        self._logger.LogInfo(
            f"{self._rule_id} deprecated {deprecated} unsupported-trigger topic(s).",
            pipeline_stage="Transformation",
            pipeline_step=self.name(),
        )
        return context


def deprecate_topic(
    context: MigrationContext,
    logger: Logger,
    component: CustomizationComponent,
    *,
    rule_id: str,
    rule_name: str,
    reason: str,
    guidance: str,
    pipeline_step: str,
) -> bool:
    """Disable + [DEPRECATED]-prefix a topic (idempotent), warn, and record the change.

    Shared by every "unsupported construct" rule (unsupported trigger *or*
    unsupported node) — the mitigation is uniform: disable the topic
    (``statecode``/``statuscode`` → Inactive), prefix its ``name`` with
    ``[DEPRECATED]`` once, preserve all logic, emit a manual-review warning, and
    record a per-topic change for the report. Stages record-field edits on the
    ``WritebackPlan`` (coalesced across rules). Returns ``True`` when the topic was
    newly deprecated, ``False`` when it was already migrated (MIG-005).
    """
    if _already_migrated(component):
        return False

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

    message = (
        f"Disabled the topic and prefixed its title [DEPRECATED] (all logic "
        f"preserved) — {reason}. {guidance}"
    )
    logger.LogWarning(
        f"{rule_id}: {message} Topic '{component.name}' ({component.schemaname}).",
        pipeline_stage="Transformation",
        pipeline_step=pipeline_step,
    )
    record_topic_change(logger, component, rule_id=rule_id, rule_name=rule_name, message=message)
    return True


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
