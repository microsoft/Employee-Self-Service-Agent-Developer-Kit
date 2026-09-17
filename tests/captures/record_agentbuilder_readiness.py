#!/usr/bin/env python
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Record read-only native AgentBuilder FlightCheck API contracts.

Required environment variables:
  ESS_AGENTBUILDER_ENVIRONMENT_ID

Optional environment variables:
  ESS_AGENTBUILDER_HOST         (required with AGENT_ID)
  ESS_AGENTBUILDER_AGENT_ID     (omit for connectivity-only capture)
  ESS_AGENTBUILDER_RING         (default: inferred from host)
  ESS_AGENTBUILDER_TOKEN_CACHE (default: kit .local cache)
  ESS_AGENTBUILDER_CASSETTE    (default: agentbuilder_readiness)
"""

from __future__ import annotations

import os
from pathlib import Path

from _common import (
    REDACT_TABLE,
    announce,
    build_cassette,
    chdir_kit_root,
    confirm_or_exit,
)


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"ERROR: {name} is required.")
    return value


def main() -> None:
    cassette_name = (
        os.environ.get("ESS_AGENTBUILDER_CASSETTE", "").strip()
        or "agentbuilder_readiness"
    )
    announce(cassette_name)
    environment_id = _required("ESS_AGENTBUILDER_ENVIRONMENT_ID")
    host = os.environ.get("ESS_AGENTBUILDER_HOST", "").strip()
    agent_id = os.environ.get("ESS_AGENTBUILDER_AGENT_ID", "").strip()
    if agent_id and not host:
        raise SystemExit("ERROR: ESS_AGENTBUILDER_HOST is required with AGENT_ID.")
    confirm_or_exit()

    chdir_kit_root()
    from agentbuilder import (
        AgentBuilderClient,
        ConnectivityClient,
        authenticate_flightcheck,
        ring_from_environment_host,
    )

    ring = (
        os.environ.get("ESS_AGENTBUILDER_RING", "").strip()
        or (ring_from_environment_host(host) if host else "")
    )
    if not ring:
        raise SystemExit("ERROR: ESS_AGENTBUILDER_RING is required without HOST.")
    if host:
        environment_host_label = host.split("://", 1)[-1].split(".", 1)[0]
        REDACT_TABLE[environment_host_label] = "00000000000000000000000000001111"
    cache_path = Path(
        os.environ.get(
            "ESS_AGENTBUILDER_TOKEN_CACHE",
            ".local/.agentbuilder_token_cache.bin",
        )
    )
    token, tenant_id = authenticate_flightcheck(
        ring,
        cache_path=cache_path,
        include_connectivity=True,
    )
    agentbuilder = (
        AgentBuilderClient(
            host,
            token,
            ring=ring,
            tenant_id=tenant_id,
        )
        if agent_id
        else None
    )
    connectivity = ConnectivityClient(token, ring=ring)

    with build_cassette(cassette_name):
        agent = agentbuilder.get_agent(agent_id) if agentbuilder else None
        configuration = (
            agentbuilder.get_dev_configuration(agent_id) if agentbuilder else None
        )
        components = agentbuilder.fetch_components(agent_id) if agentbuilder else None
        connections = connectivity.list_connections(environment_id)

    if agent is not None and configuration is not None and components is not None:
        component_changes = components.get("botComponentChanges", [])
        connection_refs = components.get("connectionReferenceChanges", [])
        print(f"  Agent: {agent.get('displayName') or agent.get('fullBotName')}")
        print(f"  Dev realm: {configuration.get('realm')}")
        print(f"  Components: {len(component_changes)}")
        print(f"  Logical connection references: {len(connection_refs)}")
    print(f"  Environment connections: {len(connections)}")
    print("Cassette written. Inspect it for tenant-specific content before commit.")


if __name__ == "__main__":
    main()
