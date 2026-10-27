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
from typing import Any

from agentbuilder import (
    AgentBuilderClient,
    authenticate_flightcheck,
    ring_from_environment_host,
    validate_environment_host,
)
from auth import discover_tenant
from connected_kb_context import load_connected_kb_context
from flightcheck.kb_connection_resolver import resolve_bound_connections
from flightcheck.pva_client import PVAClient


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


def main(argv: list[str] | None = None) -> int:
    """Run the KB connection resolution CLI. Returns the process exit code."""
    try:
        context = load_connected_kb_context(
            discover_tenant_fn=discover_tenant,
        )
    except ValueError as exc:
        print(json.dumps(_error_result(str(exc))))
        return 1

    if context.dataverse_endpoint:
        pva = PVAClient(context.tenant_id, context.dataverse_endpoint)
        try:
            pva.authenticate()
        except Exception as exc:  # noqa: BLE001 — surfaced as JSON, not raised
            print(json.dumps(_error_result(
                f"Copilot Studio (Island Gateway) authentication failed: {exc}"
            )))
            return 1
    else:
        try:
            native_host = context.power_platform_api_endpoint
            ring = ring_from_environment_host(native_host)
            native_host = validate_environment_host(native_host, ring)
            token, authenticated_tenant_id = authenticate_flightcheck(
                ring,
                include_connectivity=False,
            )
            if (
                authenticated_tenant_id.casefold()
                != context.tenant_id.casefold()
            ):
                raise ValueError(
                    "The authenticated account belongs to a different tenant "
                    "than the active agent."
                )
            agentbuilder = AgentBuilderClient(
                native_host,
                token,
                ring=ring,
                tenant_id=authenticated_tenant_id,
                api_version=context.agent_builder_api_version,
            )
        except Exception as exc:  # noqa: BLE001 — surfaced as JSON, not raised
            print(json.dumps(_error_result(
                f"AgentBuilder authentication failed: {exc}"
            )))
            return 1
        pva = _AgentBuilderKnowledgeSourceClient(agentbuilder)

    result = resolve_bound_connections(pva, context.bot_id)
    print(json.dumps(result.to_dict()))
    return 0 if result.status != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
