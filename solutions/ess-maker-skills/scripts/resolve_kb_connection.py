# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""CLI shim: resolve which knowledge source(s) are bound to the local agent.

Prints a JSON ``ResolutionResult`` (see ``flightcheck.kb_connection_resolver``)
to stdout and exits 0 on success (``"ok"``/``"none_bound"``) or 1 on
``"error"``. Never calls ``auth.load_config()`` (which ``sys.exit``s on a
missing/mismatched config) so every failure mode is surfaced as JSON instead
of an uncaught process exit.
"""

from __future__ import annotations

import json
import os
from typing import Any

from agentbuilder import (
    AgentBuilderClient,
    authenticate_flightcheck,
    ring_from_environment_host,
    validate_environment_host,
)
from auth import discover_tenant
from flightcheck.kb_connection_resolver import resolve_bound_connections
from flightcheck.pva_client import PVAClient

LOCAL_STATE_DIR = ".local"
SETUP_STATE_PATH = os.path.join(LOCAL_STATE_DIR, "setup", "config.json")


def _error_result(message: str) -> dict[str, Any]:
    return {"status": "error", "connections": [], "error": message}


class _AgentBuilderKnowledgeSourceClient:
    """Expose native component fetches through the resolver's read contract."""

    is_configured = True

    def __init__(self, client: AgentBuilderClient) -> None:
        self.client = client

    def get_knowledge_sources(self, bot_id: str) -> list[dict[str, Any]]:
        changeset = self.client.fetch_components(bot_id)
        changes = changeset.get("botComponentChanges")
        if not isinstance(changes, list):
            raise ValueError(
                "AgentBuilder component fetch did not return botComponentChanges."
            )
        sources: list[dict[str, Any]] = []
        for change in changes:
            component = change.get("component") if isinstance(change, dict) else None
            if (
                isinstance(component, dict)
                and component.get("$kind") == "KnowledgeSourceComponent"
            ):
                sources.append(component)
        return sources


def _load_native_setup_state() -> dict[str, Any]:
    """Load and validate the canonical setup state.

    Reads ``.local/setup/config.json``, raising ``ValueError`` if it is
    missing, unreadable, or not schema version 4.
    """
    try:
        with open(SETUP_STATE_PATH, "r", encoding="utf-8") as f:
            setup = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"Could not read {SETUP_STATE_PATH}: {exc}"
        ) from exc
    if not isinstance(setup, dict) or setup.get("schema_version") != 4:
        raise ValueError(
            f"{SETUP_STATE_PATH} is not valid schema version 4 setup state."
        )
    return setup


def _native_identity(
    config: dict[str, Any],
    bot_id: str | None,
) -> str:
    """Return the canonical tenant id for a native DA agent."""
    agent = config.get("agent")
    if not isinstance(agent, dict):
        agent = {}
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


def main(argv: list[str] | None = None) -> int:
    """Run the KB connection resolution CLI. Returns the process exit code."""
    config_path = os.path.join(LOCAL_STATE_DIR, "config.json")
    if not os.path.exists(config_path):
        print(json.dumps(_error_result(
            f"{config_path} not found. Run /setup first."
        )))
        return 1

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps(_error_result(
            f"Could not read {config_path}: {exc}"
        )))
        return 1

    if not isinstance(config, dict):
        print(json.dumps(_error_result(
            f"{config_path} does not contain a JSON object."
        )))
        return 1

    env_url = str(config.get("dataverseEndpoint") or "").strip()
    agent = config.get("agent")
    bot_id = agent.get("botId") if isinstance(agent, dict) else None

    if env_url:
        try:
            tenant_id = discover_tenant(env_url)
        except Exception as exc:  # noqa: BLE001 — surfaced as JSON, not raised
            print(json.dumps(_error_result(
                f"Could not discover tenant for {env_url!r}: {exc}"
            )))
            return 1
        pva = PVAClient(tenant_id, env_url)
        try:
            pva.authenticate()
        except Exception as exc:  # noqa: BLE001 — surfaced as JSON, not raised
            print(json.dumps(_error_result(
                f"Copilot Studio (Island Gateway) authentication failed: {exc}"
            )))
            return 1
    else:
        try:
            tenant_id = _native_identity(config, bot_id)
        except ValueError as exc:
            print(json.dumps(_error_result(str(exc))))
            return 1
        native_host = str(config.get("powerPlatformApiEndpoint") or "").strip()
        if not native_host:
            print(json.dumps(_error_result(
                "No powerPlatformApiEndpoint found in .local/config.json. "
                "Run /setup first."
            )))
            return 1
        try:
            ring = ring_from_environment_host(native_host)
            native_host = validate_environment_host(native_host, ring)
            token, authenticated_tenant_id = authenticate_flightcheck(
                ring,
                include_connectivity=False,
            )
            if authenticated_tenant_id.casefold() != tenant_id.casefold():
                raise ValueError(
                    "The authenticated account belongs to a different tenant "
                    "than the active agent."
                )
            agentbuilder = AgentBuilderClient(
                native_host,
                token,
                ring=ring,
                tenant_id=authenticated_tenant_id,
                api_version=str(
                    config.get("agentBuilderApiVersion") or "2024-10-01"
                ),
            )
        except Exception as exc:  # noqa: BLE001 — surfaced as JSON, not raised
            print(json.dumps(_error_result(
                f"AgentBuilder authentication failed: {exc}"
            )))
            return 1
        pva = _AgentBuilderKnowledgeSourceClient(agentbuilder)

    result = resolve_bound_connections(pva, bot_id)
    print(json.dumps(result.to_dict()))
    return 0 if result.status != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
