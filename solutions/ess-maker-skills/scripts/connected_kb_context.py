# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Load the active agent identity used by connected knowledge-base tools."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Callable

from auth import discover_tenant

LOCAL_STATE_DIR = ".local"
CONFIG_PATH = os.path.join(LOCAL_STATE_DIR, "config.json")
SETUP_STATE_PATH = os.path.join(LOCAL_STATE_DIR, "setup", "config.json")


@dataclass(frozen=True)
class ConnectedKBContext:
    """Immutable active agent, environment, and tenant identity."""

    bot_id: str | None
    tenant_id: str
    dataverse_endpoint: str = ""
    environment_id: str = ""
    power_platform_api_endpoint: str = ""
    agent_builder_api_version: str = "2024-10-01"

    @property
    def is_native(self) -> bool:
        return not self.dataverse_endpoint


def load_connected_kb_context(
    *,
    discover_tenant_fn: Callable[[str], str] | None = None,
) -> ConnectedKBContext:
    """Load and validate the active connected-KB identity from local state."""
    config = _load_json_object(
        CONFIG_PATH,
        missing_message=f"{CONFIG_PATH} not found. Run /setup first.",
        invalid_object_message=f"{CONFIG_PATH} does not contain a JSON object.",
    )
    agent = config.get("agent")
    if not isinstance(agent, dict):
        agent = {}
    bot_id_value = agent.get("botId")
    bot_id = str(bot_id_value).strip() if bot_id_value is not None else None
    if bot_id == "":
        bot_id = None

    dataverse_endpoint = str(config.get("dataverseEndpoint") or "").strip()
    if dataverse_endpoint:
        tenant_discovery = discover_tenant_fn or discover_tenant
        try:
            tenant_id = tenant_discovery(dataverse_endpoint)
        except Exception as exc:
            raise ValueError(
                f"Could not discover tenant for {dataverse_endpoint!r}: {exc}"
            ) from exc
        return ConnectedKBContext(
            bot_id=bot_id,
            tenant_id=tenant_id,
            dataverse_endpoint=dataverse_endpoint,
        )

    environment_id = str(
        agent.get("environmentId") or config.get("environmentId") or ""
    ).strip()
    if not environment_id:
        raise ValueError(
            "No environmentId found in .local/config.json. Run /setup first."
        )
    if not bot_id:
        raise ValueError(
            "No agent botId found in .local/config.json. Run /setup first."
        )

    setup = _load_native_setup_state()
    tenant_id = _validate_native_identity(
        config=config,
        agent=agent,
        setup=setup,
        bot_id=bot_id,
        environment_id=environment_id,
    )
    native_host = str(config.get("powerPlatformApiEndpoint") or "").strip()
    if not native_host:
        raise ValueError(
            "No powerPlatformApiEndpoint found in .local/config.json. "
            "Run /setup first."
        )

    return ConnectedKBContext(
        bot_id=bot_id,
        tenant_id=tenant_id,
        environment_id=environment_id,
        power_platform_api_endpoint=native_host,
        agent_builder_api_version=str(
            config.get("agentBuilderApiVersion") or "2024-10-01"
        ),
    )


def _load_native_setup_state() -> dict:
    setup = _load_json_object(
        SETUP_STATE_PATH,
        missing_message=None,
        invalid_object_message=(
            f"{SETUP_STATE_PATH} is not valid schema version 4 setup state."
        ),
    )
    if setup.get("schema_version") != 4:
        raise ValueError(
            f"{SETUP_STATE_PATH} is not valid schema version 4 setup state."
        )
    return setup


def _load_json_object(
    path: str,
    *,
    missing_message: str | None,
    invalid_object_message: str,
) -> dict:
    if missing_message is not None and not os.path.exists(path):
        raise ValueError(missing_message)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(invalid_object_message)
    return value


def _validate_native_identity(
    *,
    config: dict,
    agent: dict,
    setup: dict,
    bot_id: str,
    environment_id: str,
) -> str:
    environment = setup.get("environment")
    if not isinstance(environment, dict):
        raise ValueError(f"{SETUP_STATE_PATH} has no environment identity.")
    canonical_environment_id = str(environment.get("id") or "").strip()
    if canonical_environment_id.casefold() != environment_id.casefold():
        raise ValueError(
            "The active agent environment does not match canonical setup state."
        )

    agents = setup.get("agents")
    canonical_agent = agents.get(bot_id) if isinstance(agents, dict) else None
    if not isinstance(canonical_agent, dict):
        raise ValueError(
            "The active agent is not present in canonical setup state."
        )
    canonical_identity = canonical_agent.get("agent")
    if not isinstance(canonical_identity, dict):
        raise ValueError(
            "The active agent has no canonical identity in setup state."
        )

    configured_slug = str(config.get("activeAgent") or agent.get("slug") or "")
    if not configured_slug:
        raise ValueError(
            "No active agent slug configured in .local/config.json. "
            "Run /setup first."
        )
    canonical_slug = str(canonical_identity.get("workspace_slug") or "")
    if canonical_slug.casefold() != configured_slug.casefold():
        raise ValueError(
            "The active agent does not match canonical setup state."
        )

    tenant_id = str(environment.get("tenant_id") or "").strip()
    if not tenant_id:
        raise ValueError(
            f"{SETUP_STATE_PATH} has no tenant identity for the active environment."
        )
    return tenant_id
