# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Safe resolution helpers for agent-local FlightCheck checks."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_AGENT_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def active_agent(
    config: dict[str, Any] | None,
    selected_slug: str | None = None,
) -> dict[str, Any]:
    """Return the config's active agent record, or ``{}`` when none resolves.

    Canonical resolver so every check picks the same agent. An explicit
    ``selected_slug`` is fail-closed: it either resolves that exact record or
    returns ``{}``. Without an explicit selection, prefer the ``activeAgent``
    slug (or the ``agent.slug`` back-compat copy), then the single ``agent``
    copy, then the first agent on file.
    """
    config = config or {}
    agents = config.get("agents") or []
    active_slug = selected_slug or config.get("activeAgent") or (
        config.get("agent") or {}
    ).get("slug")
    if active_slug:
        matches = [
            agent
            for agent in agents
            if isinstance(agent, dict) and agent.get("slug") == active_slug
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return {}
        single = config.get("agent")
        if (
            isinstance(single, dict)
            and single.get("slug") == active_slug
        ):
            return single
        return {}
    single = config.get("agent")
    if isinstance(single, dict) and single:
        return single
    return next(
        (agent for agent in agents if isinstance(agent, dict)),
        {},
    )


def active_agent_bot_id(
    config: dict[str, Any] | None,
    selected_slug: str | None = None,
) -> str | None:
    """Return the active agent's ``botId``, or ``None`` when none is recorded.

    Resolves the active agent via :func:`active_agent` and returns only that
    agent's ``botId``. Never substitutes a sibling agent's id: a per-agent
    check must report on the selected agent or refuse, otherwise it would
    silently verify the wrong agent. Callers treat ``None`` as "no usable agent
    identity" and skip or degrade explicitly.
    """
    config = config or {}
    return (
        _clean_bot_id(
            active_agent(config, selected_slug).get("botId")
        )
        or None
    )


def is_declarative_agent(runner: Any) -> bool:
    """Use explicit workspace/selected-agent metadata, never package presence.

    A missing or ambiguous selected agent must not inherit a sibling's type.
    Agent metadata takes precedence over the workspace's compatibility marker.
    An explicitly requested Workday DA profile is also a DA context, unless the
    selected record declares a different release line.
    """
    config = getattr(runner, "config", None)
    if not isinstance(config, dict):
        config = {}
    single = config.get("agent")
    configured_slug = config.get("activeAgent")
    if configured_slug in (None, "") and isinstance(single, dict):
        configured_slug = single.get("slug")
    selected_slug = getattr(runner, "agent_slug", None)
    if selected_slug in (None, ""):
        selected_slug = configured_slug
    if selected_slug == "":
        selected_slug = None

    selected = {}
    if selected_slug is not None:
        if not isinstance(selected_slug, str):
            return False
        selected = active_agent(config, selected_slug)
        if not selected:
            return False
    elif config.get("agents"):
        # Do not use active_agent's legacy "first record" fallback for type.
        return False
    else:
        if isinstance(single, dict):
            selected = single

    release_line = selected.get("releaseLine")
    if release_line is None and configured_slug in (None, "", selected_slug):
        # A command-line override must not inherit another active agent's marker.
        release_line = config.get("releaseLine")
    if release_line is not None:
        return isinstance(release_line, str) and release_line.strip().casefold() == "da"
    return getattr(runner, "workday_da_profile", False) is True


def _clean_bot_id(value: Any) -> str:
    return str(value or "").strip()


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
