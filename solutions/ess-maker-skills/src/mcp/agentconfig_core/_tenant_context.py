# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Resolve the maker workspace's configured Dataverse tenant."""

from __future__ import annotations

import json
import logging
import sys
import uuid
from pathlib import Path

import requests

from _odata import _validate_https_base_url


_SOLUTION_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_PATH = _SOLUTION_ROOT / ".local" / "config.json"
_LOGGER = logging.getLogger("ess-agentconfig")

sys.path.insert(0, str(_SOLUTION_ROOT / "scripts"))

from auth import discover_tenant  # noqa: E402


def _unrestricted_login(reason: str) -> None:
    _LOGGER.warning(
        "%s; using unrestricted AgentConfiguration sign-in (organizations).",
        reason,
    )


def configured_tenant_id() -> str | None:
    """Discover a concrete tenant, with a visible fallback when unavailable."""
    try:
        with _CONFIG_PATH.open(encoding="utf-8") as handle:
            config = json.load(handle)
    except FileNotFoundError:
        return _unrestricted_login("Maker workspace configuration is missing")
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return _unrestricted_login("Maker workspace configuration could not be read")

    endpoint = config.get("dataverseEndpoint") if isinstance(config, dict) else None
    if not isinstance(endpoint, str) or not endpoint.strip():
        return _unrestricted_login("No Dataverse endpoint is configured")
    try:
        endpoint = _validate_https_base_url(endpoint.strip(), "dataverseEndpoint")
    except ValueError:
        return _unrestricted_login("The configured Dataverse endpoint is invalid")

    try:
        tenant = discover_tenant(endpoint)
    except requests.RequestException:
        return _unrestricted_login("Dataverse tenant discovery failed")

    try:
        return str(uuid.UUID(tenant))
    except ValueError:
        return _unrestricted_login("Dataverse did not identify a concrete tenant")
