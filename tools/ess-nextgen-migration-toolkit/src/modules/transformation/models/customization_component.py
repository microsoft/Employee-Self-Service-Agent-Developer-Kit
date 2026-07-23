"""Hydrated view of one customized ESS component (a topic today).

The input module discovers customized components as raw ``msdyn_componentlayers``
rows whose useful fields (schemaname, componenttype, name, the topic ``data``
YAML) are buried inside the ``msdyn_componentjson`` string on each layer. This
model hoists those fields to the top level so the transformation/output modules
consume them directly, while keeping the raw ``layers`` for full fidelity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CustomizationComponent:
    """A single customized component, hydrated from its component layers."""

    component_id: str
    schemaname: str | None = None
    name: str | None = None
    # botcomponent.componenttype (int) and its display label (e.g. "Topic (V2)").
    component_type: int | None = None
    component_type_label: str | None = None
    # The component's ``data`` payload (the topic YAML) that migration rewrites and
    # writeback applies.
    data: str | None = None
    # Dataverse record state (botcomponent statecode/statuscode). Migration rules
    # that disable a topic set these to the Inactive pair; hydrated so a rule can
    # baseline + idempotency-check the current state.
    statecode: int | None = None
    statuscode: int | None = None
    # Raw msdyn_componentlayers rows for this component, preserved as-is.
    layers: list[dict[str, Any]] = field(default_factory=list)
