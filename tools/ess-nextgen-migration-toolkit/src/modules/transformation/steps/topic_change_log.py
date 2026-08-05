"""Per-topic transformation reporting shared by migration rules.

Every rule that acts on a topic records a structured change here (via the
Logger's ``LogChange`` -> ``context.Changes``) so the Reporter can tabulate, per
topic, which rules acted and the mitigation applied — surfaced in the migration
report, including READONLY previews.
"""

from __future__ import annotations

from core.logging import Logger
from modules.transformation.models import CustomizationComponent


def topic_label(component: CustomizationComponent) -> str:
    """A stable, human-readable label for a topic (name + schemaname)."""
    if component.name and component.schemaname:
        return f"{component.name} [{component.schemaname}]"
    return component.name or component.schemaname or component.component_id


def component_type_label(component: CustomizationComponent) -> str:
    """A human-readable component-type label for the report (e.g. ``botcomponent / Topic (V2)``)."""
    label = component.component_type_label or (
        f"componenttype {component.component_type}"
        if component.component_type is not None
        else None
    )
    return f"botcomponent / {label}" if label else "botcomponent"


def record_topic_change(
    logger: Logger,
    component: CustomizationComponent,
    *,
    rule_id: str,
    rule_name: str,
    message: str,
) -> None:
    """Record one per-topic migration action for the report's per-topic summary."""
    logger.LogChange(
        message=message,
        rule_id=rule_id,
        title=rule_name,
        component=topic_label(component),
        component_type=component_type_label(component),
    )
