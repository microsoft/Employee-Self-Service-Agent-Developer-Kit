# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Request-boundary validation shared by the announcements client and server."""

from __future__ import annotations

import os
import sys

# The AgentConfiguration MCP family lives at the ``src/mcp`` root as sibling
# folders sharing the neutral ``agentconfig_core`` client core. There is no
# package __init__.py, and each server launches with cwd set to its own folder
# on a flat sys.path, so make the sibling ``agentconfig_core`` folder importable.
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agentconfig_core"),
)

from _odata import _validate_title_id  # noqa: E402


_MAX_BULLETIN_ID_LENGTH = 256


def validate_title_id(title_id: str) -> str:
    """Validate the opaque Employee Agent route key."""
    return _validate_title_id(title_id)


def validate_bulletin_id(bulletin_id: str) -> str:
    """Validate a path-bound backend-assigned bulletin identifier."""
    if not isinstance(bulletin_id, str) or not bulletin_id:
        raise ValueError("bulletinId must be a non-empty string")
    if bulletin_id != bulletin_id.strip():
        raise ValueError("bulletinId must not have surrounding whitespace")
    if bulletin_id in {".", ".."}:
        raise ValueError("bulletinId must not be a URL dot-segment")
    if len(bulletin_id) > _MAX_BULLETIN_ID_LENGTH:
        raise ValueError(
            f"bulletinId must not exceed {_MAX_BULLETIN_ID_LENGTH} characters"
        )
    if any(
        ord(character) < 0x20 or ord(character) == 0x7F for character in bulletin_id
    ):
        raise ValueError("bulletinId must not contain control characters")
    if any(separator in bulletin_id for separator in ("/", "\\", "?", "#", "%")):
        raise ValueError(
            "bulletinId must not contain path, query, fragment, or escape separators"
        )
    return bulletin_id
