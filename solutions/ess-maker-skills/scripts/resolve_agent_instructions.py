# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""CLI shim: resolve the live system-prompt instructions bound to the local agent.

Prints a JSON ``ResolutionResult`` (see ``flightcheck.agent_instructions_resolver``)
to stdout and exits 0 on success (``"ok"``/``"not_found"``) or 1 on
``"error"``. Never calls ``auth.load_config()`` (which ``sys.exit``s on a
missing/mismatched config) so every failure mode is surfaced as JSON instead
of an uncaught process exit.

This is a near-clone of ``resolve_kb_connection.py``; the one structural
difference is the component read contract. The resolver calls
``client.get_bot_components(bot_id)`` and expects the FULL raw
``botComponentChanges`` list. Neither ``PVAClient`` nor ``AgentBuilderClient``
expose that method, so each is wrapped by a small adapter below.
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
from flightcheck.agent_instructions_resolver import resolve_agent_instructions
from flightcheck.pva_client import PVAClient

try:
    import requests
except ImportError:  # pragma: no cover - requests is a hard dependency of pva_client
    requests = None  # type: ignore[assignment]


def _error_result(message: str) -> dict[str, Any]:
    return {"status": "error", "instructions": None, "error": message}


class _PVAComponentClient:
    """Expose a ``PVAClient``'s raw changeset through the resolver's contract.

    ``PVAClient`` only exposes filtered getters (``get_knowledge_sources`` /
    ``get_dialog_components``), both of which POST to the same Island Gateway
    ``botcomponents`` endpoint and then drop everything but one ``$kind``.
    The agent-instructions resolver needs the FULL ``botComponentChanges``
    list, so this adapter replicates that single POST using the PVAClient's
    already-authenticated token / gateway / env attributes and returns the
    raw list. ``pva_client.py`` is intentionally left unmodified.
    """

    def __init__(self, pva: PVAClient) -> None:
        self._pva = pva

    @property
    def is_configured(self) -> bool:
        return bool(self._pva.is_configured)

    def get_bot_components(self, bot_id: str) -> list[dict[str, Any]]:
        if not self._pva.is_configured:
            return []

        url = (
            f"{self._pva._gateway_url}/api/botmanagement/v1"
            f"/environments/{self._pva._bap_env_id}"
            f"/bots/{bot_id}/content/botcomponents"
        )
        headers = {
            "Authorization": f"Bearer {self._pva._pva_token}",
            "Content-Type": "application/json",
            "x-ms-client-tenant-id": self._pva.tenant_id,
            "x-cci-tenantid": self._pva.tenant_id,
            "x-cci-bapenvironmentid": self._pva._bap_env_id,
            "x-cci-cdsbotid": bot_id,
        }

        resp = requests.post(url, headers=headers, json={}, timeout=60)
        if not resp.ok:
            raise RuntimeError(
                f"Island Gateway returned {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        changes = data.get("botComponentChanges")
        return changes if isinstance(changes, list) else []


class _AgentBuilderComponentClient:
    """Expose native component fetches through the resolver's read contract."""

    is_configured = True

    def __init__(self, client: AgentBuilderClient) -> None:
        self.client = client

    def get_bot_components(self, bot_id: str) -> list[dict[str, Any]]:
        changeset = self.client.fetch_components(bot_id)
        changes = changeset.get("botComponentChanges")
        if not isinstance(changes, list):
            raise ValueError(
                "AgentBuilder component fetch did not return botComponentChanges."
            )
        return changes


def main(argv: list[str] | None = None) -> int:
    """Run the agent-instructions resolution CLI. Returns the process exit code."""
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
        client = _PVAComponentClient(pva)
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
        client = _AgentBuilderComponentClient(agentbuilder)

    result = resolve_agent_instructions(client, context.bot_id)
    print(json.dumps(result.to_dict()))
    return 0 if result.status != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
