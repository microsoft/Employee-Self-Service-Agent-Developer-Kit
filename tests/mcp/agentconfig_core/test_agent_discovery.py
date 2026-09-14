# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared deployed-agent discovery with separate feature-owned MCP entry points."""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

import httpx
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _mcp_modules import (  # noqa: E402
    load_landing_page_modules,
)

LANDING = load_landing_page_modules()
from agent_discovery import AgentDiscoveryClient  # noqa: E402
from base_client import AgentConfigApiError  # noqa: E402


TENANT = "00000000-0000-0000-0000-000000001111"
CLIENTS = [
    LANDING["client"].AgentConfigClient,
]


@pytest.fixture
def token(monkeypatch):
    encoded = base64.urlsafe_b64encode(json.dumps({"tid": TENANT}).encode()).decode()
    monkeypatch.setenv("AGENTCONFIG_ACCESS_TOKEN", f"header.{encoded}.signature")


def test_both_features_inherit_the_same_discovery_implementation():
    for client_type in CLIENTS:
        assert client_type.list_agent_configs is AgentDiscoveryClient.list_agent_configs
        assert client_type.search_agents is AgentDiscoveryClient.search_agents


@pytest.mark.parametrize("client_type", CLIENTS)
@pytest.mark.parametrize("wrapped", [False, True])
def test_discovery_preserves_routes_transport_and_title_ids(token, client_type, wrapped):
    requests = []
    records = [{"TitleId": "opaque-title-1", "Name": "Benefits", "BotId": "not-a-title"}]

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"value": records} if wrapped else records)

    client = client_type(transport=httpx.MockTransport(handler))

    async def run():
        try:
            listed = await client.list_agent_configs()
            found = await client.search_agents("  Benefits  ")
            assert listed == found == [
                {"titleId": "opaque-title-1", "name": "Benefits", "botId": "not-a-title"}
            ]
        finally:
            await client.aclose()

    asyncio.run(run())
    collection = f"/weveb2/api/v1.1/tenants('{TENANT}')/EmployeeAgents"
    assert [(r.method, r.url.path) for r in requests] == [
        ("GET", collection), ("POST", f"{collection}/SearchAgents")
    ]
    assert json.loads(requests[1].content) == {"SearchString": "Benefits"}
    assert all(r.headers["Authorization"].startswith("Bearer ") for r in requests)


@pytest.mark.parametrize("client_type", CLIENTS)
@pytest.mark.parametrize("query", ["", "  ", "x" * 257, None])
def test_invalid_search_never_sends_a_request(token, client_type, query):
    def unexpected(request):
        pytest.fail("invalid discovery input reached the network")

    client = client_type(transport=httpx.MockTransport(unexpected))
    with pytest.raises(ValueError, match="searchString"):
        asyncio.run(client.search_agents(query))


@pytest.mark.parametrize("client_type", CLIENTS)
@pytest.mark.parametrize("payload", [{}, {"value": None}, None])
def test_malformed_collections_do_not_become_empty_successes(token, client_type, payload):
    client = client_type(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=json.dumps(payload))
        )
    )

    async def run():
        try:
            with pytest.raises(AgentConfigApiError):
                await client.list_agent_configs()
        finally:
            await client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize("modules", [LANDING])
def test_feature_owned_tools_delegate_without_initializing_configuration(monkeypatch, modules):
    calls = []

    class DiscoveryOnly:
        async def list_agent_configs(self):
            calls.append(("list",))
            return [{"titleId": "deployed-title"}]

        async def search_agents(self, query):
            calls.append(("search", query))
            return [{"titleId": "deployed-title"}]

    server = modules["server"]
    monkeypatch.setattr(
        server, "get_client",
        lambda: DiscoveryOnly(),
    )

    async def run():
        assert json.loads(await server.list_agent_configs()) == [{"titleId": "deployed-title"}]
        assert json.loads(await server.search_agents("Benefits")) == [{"titleId": "deployed-title"}]
        tools = {tool.name: tool for tool in await server.mcp.list_tools()}
        for name, properties in [("list_agent_configs", set()), ("search_agents", {"searchString"})]:
            assert set(tools[name].inputSchema["properties"]) == properties
            # Preserve the existing provider's metadata as well as its wire
            # arguments; request-level tests establish read-only behavior.
            assert tools[name].annotations is None
            assert not (tools[name].meta or {}).get("ui", {}).get("resourceUri")

    asyncio.run(run())
    assert calls == [("list",), ("search", "Benefits")]
