"""Base classes for handling CA constructs that are unsupported in DA.

Two scenarios, one mitigation (disable-but-preserve): a topic is disabled +
``[DEPRECATED]``-prefixed either because (a) its **trigger** type is unsupported,
or (b) it uses an unsupported **node**. Each concrete rule is a thin subclass that
supplies the specific construct kind and a tailored, user-facing mitigation
message (why it's unsupported + what to do instead) — the business identity lives
in the subclass; the mechanics live here.

The topic ``data`` is never rewritten. Record-field edits (``name`` /
``statecode`` / ``statuscode``) are staged on the ``WritebackPlan`` (coalesced
across rules), a manual-review warning is emitted, and a per-topic change is
recorded for the report.

.. note::
   Inactive ``statecode=1`` / ``statuscode=2`` are writable botcomponent columns
   (Dataverse botcomponent reference), set via a normal ``PATCH /botcomponents(id)``.
   Whether one PATCH may combine the state change with content is confirmed live
   under TASK-009.
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
_INACTIVE_STATECODE = 1
_INACTIVE_STATUSCODE = 2
_DEPRECATED_MARKER = "[DEPRECATED]"
_DEPRECATED_PREFIX = "[DEPRECATED] "

# The topic trigger is ``beginDialog.kind`` — the first indented ``kind:`` line
# after the top-level ``beginDialog:`` key.
_BEGIN_DIALOG_RE = re.compile(r"(?m)^beginDialog:[ \t]*$")
_KIND_RE = re.compile(r"(?m)^[ \t]+kind:[ \t]*(?P<kind>[A-Za-z0-9_]+)")


class UnsupportedTopicTriggerStep(MigrationPipelineStep):
    """Base: disable + deprecate a topic whose trigger is a specific unsupported kind."""

    def __init__(
        self,
        logger: Logger,
        *,
        name: str,
        trigger_kind: str,
        rule_id: str,
        rule_name: str,
        mitigation: str,
    ) -> None:
        super().__init__(
            name=name,
            description=f"Disable + deprecate unsupported '{trigger_kind}' topics ({rule_id}).",
            supported_modes=("READONLY", "WRITEBACK"),
        )
        self._logger = logger
        self._trigger_kind = trigger_kind
        self._rule_id = rule_id
        self._rule_name = rule_name
        self._mitigation = mitigation

    def execute(self, context: MigrationContext) -> MigrationContext:
        disabled = 0
        for component in context.customizations.values():
            if topic_trigger_kind(component.data) != self._trigger_kind:
                continue
            if deprecate_topic(
                context,
                self._logger,
                component,
                rule_id=self._rule_id,
                rule_name=self._rule_name,
                reason=f"unsupported '{self._trigger_kind}' trigger",
                guidance=self._mitigation,
                pipeline_step=self.name(),
            ):
                disabled += 1
        self._logger.LogInfo(
            f"{self._rule_id} disabled {disabled} '{self._trigger_kind}' topic(s).",
            pipeline_stage="Transformation",
            pipeline_step=self.name(),
        )
        return context


class UnsupportedNodeStep(MigrationPipelineStep):
    """Base: disable + deprecate a topic that uses a specific unsupported node kind."""

    def __init__(
        self,
        logger: Logger,
        *,
        name: str,
        node_kind: str,
        rule_id: str,
        rule_name: str,
        mitigation: str,
    ) -> None:
        super().__init__(
            name=name,
            description=f"Disable + deprecate topics using the '{node_kind}' node ({rule_id}).",
            supported_modes=("READONLY", "WRITEBACK"),
        )
        self._logger = logger
        self._node_kind = node_kind
        self._rule_id = rule_id
        self._rule_name = rule_name
        self._mitigation = mitigation
        self._node_re = re.compile(
            rf"(?m)^[ \t]*(?:-[ \t]*)?kind:[ \t]*{re.escape(node_kind)}[ \t]*$"
        )

    def execute(self, context: MigrationContext) -> MigrationContext:
        disabled = 0
        for component in context.customizations.values():
            if not self._uses_node(component.data):
                continue
            if deprecate_topic(
                context,
                self._logger,
                component,
                rule_id=self._rule_id,
                rule_name=self._rule_name,
                reason=f"uses unsupported '{self._node_kind}' node",
                guidance=self._mitigation,
                pipeline_step=self.name(),
            ):
                disabled += 1
        self._logger.LogInfo(
            f"{self._rule_id} disabled {disabled} topic(s) using the '{self._node_kind}' node.",
            pipeline_stage="Transformation",
            pipeline_step=self.name(),
        )
        return context

    def _uses_node(self, data: Any) -> bool:
        return isinstance(data, str) and bool(data) and self._node_re.search(data) is not None


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

    Uniform mitigation for any unsupported construct (trigger or node): disable the
    topic (``statecode``/``statuscode`` → Inactive), prefix ``name`` with
    ``[DEPRECATED]`` once, preserve all logic, warn, and record a per-topic change.
    Stages record-field edits on the ``WritebackPlan`` (coalesced across rules).
    Returns ``True`` when newly deprecated, ``False`` when already migrated (MIG-005).
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
