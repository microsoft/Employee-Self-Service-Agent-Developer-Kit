# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Safe resolution helpers for agent-local FlightCheck checks."""

import re
from pathlib import Path

_AGENT_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def validate_agent_slug(agent_slug: str) -> str:
    """Return a safe single-segment agent slug or raise ``ValueError``."""
    if not isinstance(agent_slug, str) or not agent_slug:
        raise ValueError("agent slug must be a non-empty string")
    if not _AGENT_SLUG_RE.fullmatch(agent_slug):
        raise ValueError(
            "agent slug must contain only letters, numbers, hyphens, or "
            "underscores and must start with a letter or number"
        )
    return agent_slug


def resolve_agent_directory(workspace_root: Path, agent_slug: str) -> Path:
    """Resolve an agent slug to a direct physical child of ``workspace_root``."""
    safe_slug = validate_agent_slug(agent_slug)
    resolved_root = workspace_root.resolve()
    resolved_agent = (resolved_root / safe_slug).resolve()
    if resolved_agent.parent != resolved_root:
        raise ValueError(
            f"agent slug {agent_slug!r} does not resolve to a direct child of "
            f"{workspace_root}"
        )
    return resolved_agent
