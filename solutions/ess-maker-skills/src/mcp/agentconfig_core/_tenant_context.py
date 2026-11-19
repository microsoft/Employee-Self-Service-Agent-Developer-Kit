# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Resolve the maker workspace's configured DA or Dataverse tenant."""

from __future__ import annotations

import json
import logging
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from _odata import _validate_https_base_url


_SOLUTION_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_PATH = _SOLUTION_ROOT / ".local" / "config.json"
_LOGGER = logging.getLogger("ess-agentconfig")

sys.path.insert(0, str(_SOLUTION_ROOT / "scripts"))

from auth import discover_tenant  # noqa: E402
from agentbuilder import (  # noqa: E402
    environment_id_from_host,
    validate_environment_host,
)


@dataclass(frozen=True)
class ConfiguredDAEnvironment:
    environment_id: str
    host: str
    ring: str
    tenant_id: str
    agent_ids: frozenset[str]


def _guid(value: Any) -> str:
    if not isinstance(value, str) or not uuid.UUID(value).int:
        raise ValueError
    return str(uuid.UUID(value))


def configured_da_environment(
    config: dict[str, Any], *, config_path: Path | None = None,
) -> ConfiguredDAEnvironment:
    """Validate the DA workspace mirror against its locked canonical setup."""
    try:
        canonical = json.loads(
            ((config_path or _CONFIG_PATH).parent / "setup" / "config.json").read_text(
                encoding="utf-8"
            )
        )
        environment = canonical["environment"]
        environment_id = _guid(environment["id"])
        tenant_id = _guid(environment["tenant_id"])
        ring = environment["ring"]
        host = validate_environment_host(
            environment["power_platform_api_endpoint"], ring
        )
        if (
            environment_id_from_host(host, ring) != environment_id
            or _guid(config["environmentId"]) != environment_id
            or config["ring"] != ring
            or validate_environment_host(
                config["powerPlatformApiEndpoint"], ring
            ) != host
        ):
            raise ValueError
        agents = canonical["agents"]
        if not isinstance(agents, dict):
            raise ValueError
        agent_ids = frozenset(_guid(key) for key in agents)
        if len(agent_ids) != len(agents) or any(
            _guid(entry["agent"]["id"]) != _guid(key)
            for key, entry in agents.items()
        ):
            raise ValueError
    except (
        OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError,
    ) as error:
        raise ValueError(
            "The DA setup environment is missing, invalid, or conflicts with "
            "the workspace configuration. Complete /setup for this environment."
        ) from error
    return ConfiguredDAEnvironment(
        environment_id, host, ring, tenant_id, agent_ids
    )


def _unrestricted_login(reason: str) -> None:
    _LOGGER.warning(
        "%s; using unrestricted AgentConfiguration sign-in (organizations).",
        reason,
    )


def configured_tenant_id() -> str | None:
    """Resolve canonical DA identity or discover the legacy Dataverse tenant."""
    try:
        with _CONFIG_PATH.open(encoding="utf-8") as handle:
            config = json.load(handle)
    except FileNotFoundError:
        return _unrestricted_login("Maker workspace configuration is missing")
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return _unrestricted_login("Maker workspace configuration could not be read")

    if isinstance(config, dict) and config.get("releaseLine") == "da":
        return configured_da_environment(config).tenant_id

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
