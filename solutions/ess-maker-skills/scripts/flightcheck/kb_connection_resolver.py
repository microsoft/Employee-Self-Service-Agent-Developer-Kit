# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Resolve which Graph-connector knowledge source(s) are bound to an agent."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from flightcheck.checks.graph_connector_kb import (
    _connector_reference,
    _filter_graph_connector_sources,
)


@dataclass
class BoundConnection:
    connection_name: str
    state: str | None
    status: str | None


@dataclass
class ResolutionResult:
    status: str  # "ok" | "none_bound" | "error"
    connections: list[BoundConnection]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "connections": [asdict(c) for c in self.connections],
            **({"error": self.error} if self.error else {}),
        }


def resolve_bound_connections(pva, bot_id: str) -> ResolutionResult:
    """Resolve Graph-connector knowledge sources bound to ``bot_id``.

    ``pva`` is an authenticated ``PVAClient`` (or a compatible test double).
    Resolution only — never runs a grounding search itself.
    """
    if pva is None or not getattr(pva, "is_configured", False):
        return ResolutionResult(
            status="error",
            connections=[],
            error=(
                "Copilot Studio (Island Gateway) is not authenticated/"
                "configured. Run flightcheck or /setup to establish PVA "
                "access, then retry."
            ),
        )
    if not bot_id:
        return ResolutionResult(
            status="error",
            connections=[],
            error="No agent botId found in .local/config.json. Run /setup first.",
        )

    try:
        knowledge_sources = pva.get_knowledge_sources(bot_id)
    except Exception as exc:  # surfaced, not swallowed
        return ResolutionResult(status="error", connections=[], error=str(exc))

    gc_sources = _filter_graph_connector_sources(knowledge_sources)
    if not gc_sources:
        return ResolutionResult(status="none_bound", connections=[])

    connections = []
    for src in gc_sources:
        name = _connector_reference(src)
        if not name:
            continue
        connections.append(
            BoundConnection(
                connection_name=name,
                state=src.get("state"),
                status=src.get("status"),
            )
        )

    if not connections:
        return ResolutionResult(status="none_bound", connections=[])

    return ResolutionResult(status="ok", connections=connections)
