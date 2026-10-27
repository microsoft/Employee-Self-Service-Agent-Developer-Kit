# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Resolve the agent's live instructions from its bound component changeset.

Fetch contract
--------------
``client.get_bot_components(bot_id)`` returns the FULL
``botComponentChanges`` changeset: a list of *change* dicts, each wrapping
the component under ``change["component"]``. (For robustness a change may
also be an already-unwrapped component dict carrying ``$kind`` directly;
both shapes are accepted.)

The instruction text lives in the component whose ``$kind`` is
``"GptComponent"``:
``component["metadata"]["instructions"]["segments"]`` is a list of
``{"$kind": "TextSegment", "value": "..."}`` dicts; the full instruction
text is the concatenation (join with "") of each ``value``. Any of
``metadata`` / ``instructions`` / ``segments`` may be missing -> treated as
no instructions found.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ResolutionResult:
    status: str  # "ok" | "not_found" | "error"
    instructions: str | None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "instructions": self.instructions,
            **({"error": self.error} if self.error else {}),
        }


def _unwrap_component(change: Any) -> dict[str, Any] | None:
    if not isinstance(change, dict):
        return None
    component = change.get("component")
    if isinstance(component, dict):
        return component
    # Already-unwrapped component dict.
    if "$kind" in change:
        return change
    return None


def _extract_instructions(component: dict[str, Any]) -> str:
    metadata = component.get("metadata")
    if not isinstance(metadata, dict):
        return ""
    instructions = metadata.get("instructions")
    if not isinstance(instructions, dict):
        return ""
    segments = instructions.get("segments")
    if not isinstance(segments, list):
        return ""
    values = [
        seg.get("value", "")
        for seg in segments
        if isinstance(seg, dict) and isinstance(seg.get("value"), str)
    ]
    return "".join(values)


def resolve_agent_instructions(client, bot_id: str) -> ResolutionResult:
    """Resolve the live system-prompt instructions bound to ``bot_id``.

    ``client`` is an authenticated component-fetching client (or a
    compatible test double) exposing ``is_configured`` and
    ``get_bot_components(bot_id)``. Resolution only.
    """
    if client is None or not getattr(client, "is_configured", False):
        return ResolutionResult(
            status="error",
            instructions=None,
            error=(
                "Copilot Studio (Island Gateway) is not authenticated/"
                "configured. Run flightcheck or /setup to establish PVA "
                "access, then retry."
            ),
        )
    if not bot_id:
        return ResolutionResult(
            status="error",
            instructions=None,
            error="No agent botId found in .local/config.json. Run /setup first.",
        )

    try:
        changeset = client.get_bot_components(bot_id)
    except Exception as exc:  # surfaced, not swallowed
        return ResolutionResult(status="error", instructions=None, error=str(exc))

    for change in changeset or []:
        component = _unwrap_component(change)
        if component is None or component.get("$kind") != "GptComponent":
            continue
        text = _extract_instructions(component)
        if text.strip():
            return ResolutionResult(status="ok", instructions=text)

    return ResolutionResult(
        status="not_found",
        instructions=None,
        error=(
            "No GptComponent with non-empty instruction segments found in the "
            "botComponentChanges changeset."
        ),
    )
