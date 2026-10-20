# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Landing-page adapter contracts for the neutral title resolver."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anyio
import pytest
from mcp.server.fastmcp.exceptions import ToolError


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _mcp_modules import (  # noqa: E402
    MCP_ROOT,
    load_landing_page_modules,
    load_org_announcements_modules,
)

import agent_title_resolution as shared  # noqa: E402


server = load_landing_page_modules()["server"]
BOT_ID = "aaaaaaaa-0000-4000-8000-000000004444"
TENANT_ID = "11111111-2222-3333-4444-555555555555"
OBJECT_ID = "00000000-0000-0000-0000-000000003333"
ENDPOINT = "https://orgmocktenant.crm.dynamics.com"


@pytest.fixture(autouse=True)
def cold_client(monkeypatch):
    monkeypatch.setattr(server, "_client", None)
    monkeypatch.setattr(server, "_client_construction_task", None)
    initialized = []
    monkeypatch.setattr(
        server.adk_telemetry,
        "initialize_tenant_identity",
        lambda tenant_id, **kwargs: initialized.append((tenant_id, kwargs)),
    )
    return initialized


@pytest.fixture
def configured_target(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    agent = {"botId": BOT_ID, "slug": "selected", "dataverseEndpoint": ENDPOINT}
    path.write_text(json.dumps({
        "setup": "complete", "agent": agent, "activeAgent": "selected", "agents": [agent],
    }), encoding="utf-8")
    monkeypatch.setattr(shared, "CONFIG_PATH", path)
    return path


def test_both_features_share_the_lookup_and_coordination_implementation():
    announcements = load_org_announcements_modules()["server"]
    assert server.load_configured_target is shared.load_configured_target
    assert announcements.load_configured_target is shared.load_configured_target
    assert server.resolve_configured_agent_title is shared.resolve_configured_agent_title
    assert announcements.resolve_configured_agent_title is shared.resolve_configured_agent_title
    assert isinstance(server._title_resolution, shared.TitleResolutionCoordinator)
    assert isinstance(announcements._title_resolution, shared.TitleResolutionCoordinator)
    assert server._title_resolution is not announcements._title_resolution
    for directory in ("agentconfig_landing_page", "agentconfig_org_announcements"):
        assert not (MCP_ROOT / directory / "agent_title.py").exists()


def test_landing_lookup_preserves_identity_and_never_initializes_configuration(
    configured_target, monkeypatch
):
    caller_thread = threading.get_ident()
    calls = []
    client = SimpleNamespace(tenant_id=TENANT_ID, object_id=OBJECT_ID)

    def construct():
        assert threading.get_ident() != caller_thread
        return client

    def resolve(target, tenant_id, object_id):
        assert threading.get_ident() != caller_thread
        assert (target.bot_id, target.dataverse_endpoint) == (BOT_ID, ENDPOINT)
        calls.append((tenant_id, object_id))
        return {"botId": BOT_ID, "titleId": "regular-title", "lobTitleId": "lob-title"}

    monkeypatch.setattr(server, "AgentConfigClient", construct)
    monkeypatch.setattr(server, "resolve_configured_agent_title", resolve)
    before = configured_target.read_bytes()
    result = asyncio.run(server.resolve_agent_title_id(BOT_ID))

    assert result == {
        "botId": BOT_ID, "titleId": "regular-title", "lobTitleId": "lob-title",
    }
    assert calls == [(TENANT_ID, OBJECT_ID)]
    assert configured_target.read_bytes() == before


def test_landing_invalid_target_does_not_start_sign_in(tmp_path, monkeypatch):
    monkeypatch.setattr(shared, "CONFIG_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(
        server, "AgentConfigClient", lambda: pytest.fail("Invalid configuration reached sign-in")
    )
    with pytest.raises(ToolError, match="InvalidRequest:"):
        asyncio.run(server.resolve_agent_title_id(BOT_ID))


def test_landing_authoring_failure_does_not_expose_credentials(
    configured_target, monkeypatch, caplog
):
    private = "PRIVATE_LOCAL_CREDENTIAL_DETAIL"

    def fail():
        raise ValueError(private)

    monkeypatch.setattr(server, "AgentConfigClient", fail)
    with pytest.raises(ToolError, match="AuthenticationRequired:") as caught:
        asyncio.run(server.resolve_agent_title_id(BOT_ID))
    assert private not in str(caught.value)
    assert private not in caplog.text


def test_landing_resolver_schema_is_read_only_and_bot_bound():
    tool = next(
        tool for tool in asyncio.run(server.mcp.list_tools())
        if tool.name == "resolve_agent_title_id"
    )
    assert set(tool.inputSchema["properties"]) == {"botId"}
    assert tool.inputSchema["required"] == ["botId"]
    assert tool.annotations.readOnlyHint is True
    assert not (tool.meta or {}).get("ui", {}).get("resourceUri")


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("list_agent_configs", {}),
        ("search_agents", {"searchString": "example"}),
        ("create_agent_config", {"titleId": "regular-title"}),
        ("get_agent_config", {"titleId": "regular-title"}),
        ("view_agent_icon", {"titleId": "regular-title"}),
        ("update_agent_config", {"titleId": "regular-title", "config": {}}),
        ("delete_agent_config", {"titleId": "regular-title"}),
        ("open_accent_color", {"titleId": "regular-title"}),
        ("open_quick_links", {"titleId": "regular-title"}),
        ("open_starter_prompts", {"titleId": "regular-title"}),
    ],
)
def test_resolver_and_feature_share_cold_client(
    configured_target, cold_client, monkeypatch, tool_name, arguments
):
    loop_thread = threading.get_ident()
    started = threading.Event()
    release = threading.Event()
    constructions = []
    resolved_identities = []
    client = SimpleNamespace(tenant_id=TENANT_ID, object_id=OBJECT_ID)
    operation = AsyncMock(return_value={
        "titleId": "regular-title", "name": "Example", "icon": None,
    })
    setattr(client, tool_name, operation)

    def construct():
        constructions.append(threading.get_ident())
        assert threading.get_ident() != loop_thread
        started.set()
        assert release.wait(timeout=5)
        return client

    def resolve(target, tenant_id, object_id):
        resolved_identities.append((tenant_id, object_id))
        return {"botId": target.bot_id, "titleId": "regular-title", "lobTitleId": None}

    monkeypatch.setattr(server, "AgentConfigClient", construct)
    monkeypatch.setattr(server, "resolve_configured_agent_title", resolve)

    async def run():
        resolver = asyncio.create_task(server.resolve_agent_title_id(BOT_ID))
        feature = None
        try:
            assert await asyncio.wait_for(
                asyncio.to_thread(started.wait, 5), timeout=6
            )
            entered = asyncio.Event()

            async def call_feature():
                entered.set()
                return await getattr(server, tool_name)(**arguments)

            feature = asyncio.create_task(call_feature())
            await asyncio.wait_for(entered.wait(), timeout=5)
            assert len(constructions) == 1
            assert not feature.done()
            release.set()
            result, _ = await asyncio.wait_for(
                asyncio.gather(resolver, feature), timeout=5
            )
            assert result == {
                "botId": BOT_ID, "titleId": "regular-title", "lobTitleId": None,
            }
            assert server._client is client
        finally:
            release.set()
            await asyncio.gather(
                *(task for task in (resolver, feature) if task is not None),
                return_exceptions=True,
            )

    asyncio.run(run())
    operation.assert_awaited_once_with(*arguments.values())
    assert resolved_identities == [(TENANT_ID, OBJECT_ID)]
    assert cold_client == [(TENANT_ID, {"local_dir": server.SOLUTION_LOCAL_DIR})]


def test_cancelled_feature_waiter_keeps_construction_for_the_resolver(
    configured_target, cold_client, monkeypatch
):
    started = threading.Event()
    release = threading.Event()
    constructions = []
    client = SimpleNamespace(
        tenant_id=TENANT_ID,
        object_id=OBJECT_ID,
        get_agent_config=AsyncMock(return_value={"titleId": "regular-title"}),
    )

    def construct():
        constructions.append(client)
        started.set()
        assert release.wait(timeout=5)
        return client

    def resolve(target, tenant_id, object_id):
        assert (tenant_id, object_id) == (TENANT_ID, OBJECT_ID)
        return {"botId": target.bot_id, "titleId": "regular-title", "lobTitleId": None}

    monkeypatch.setattr(server, "AgentConfigClient", construct)
    monkeypatch.setattr(server, "resolve_configured_agent_title", resolve)

    async def run():
        scope = anyio.CancelScope()
        first_done = anyio.Event()
        resolver_waiting = anyio.Event()
        arrivals = []
        results = []
        get_client = server.get_client

        async def observed_get_client():
            arrivals.append(1)
            if len(arrivals) == 2:
                resolver_waiting.set()
            return await get_client()

        monkeypatch.setattr(server, "get_client", observed_get_client)

        async def first_waiter():
            try:
                with scope:
                    await server.get_agent_config("regular-title")
            finally:
                first_done.set()

        async def resolver():
            results.append(await server.resolve_agent_title_id(BOT_ID))

        try:
            async with anyio.create_task_group() as group:
                group.start_soon(first_waiter)
                assert await asyncio.wait_for(
                    asyncio.to_thread(started.wait, 5), timeout=6
                )
                construction = server._client_construction_task
                assert construction is not None
                scope.cancel()
                with anyio.fail_after(5):
                    await first_done.wait()
                assert server._client_construction_task is construction
                assert not construction.done()
                group.start_soon(resolver)
                with anyio.fail_after(5):
                    await resolver_waiting.wait()
                assert server._client_construction_task is construction
                assert len(constructions) == 1
                release.set()
        finally:
            release.set()

        assert results == [{
            "botId": BOT_ID, "titleId": "regular-title", "lobTitleId": None,
        }]
        assert server._client is client
        assert server._client_construction_task is None
        assert json.loads(await server.get_agent_config("regular-title")) == {
            "titleId": "regular-title",
        }

    anyio.run(run, backend="asyncio")
    assert constructions == [client]
    client.get_agent_config.assert_awaited_once_with("regular-title")
    assert cold_client == [(TENANT_ID, {"local_dir": server.SOLUTION_LOCAL_DIR})]


def test_failed_construction_can_retry_through_a_feature_call(
    configured_target, cold_client, monkeypatch
):
    constructions = []
    client = SimpleNamespace(
        tenant_id=TENANT_ID,
        object_id=OBJECT_ID,
        get_agent_config=AsyncMock(return_value={"titleId": "regular-title"}),
    )

    def construct():
        constructions.append(1)
        if len(constructions) == 1:
            raise ValueError("PRIVATE_CONSTRUCTION_FAILURE")
        return client

    def resolve(target, tenant_id, object_id):
        assert (tenant_id, object_id) == (TENANT_ID, OBJECT_ID)
        return {"botId": target.bot_id, "titleId": "regular-title", "lobTitleId": None}

    monkeypatch.setattr(server, "AgentConfigClient", construct)
    monkeypatch.setattr(server, "resolve_configured_agent_title", resolve)

    async def run():
        with pytest.raises(ToolError, match="AuthenticationRequired:") as caught:
            await server.resolve_agent_title_id(BOT_ID)
        assert "PRIVATE_CONSTRUCTION_FAILURE" not in str(caught.value)
        assert server._client is None
        assert server._client_construction_task is None
        assert json.loads(await server.get_agent_config("regular-title")) == {
            "titleId": "regular-title",
        }
        assert await server.resolve_agent_title_id(BOT_ID) == {
            "botId": BOT_ID, "titleId": "regular-title", "lobTitleId": None,
        }
        assert server._client is client

    asyncio.run(run())
    assert constructions == [1, 1]
    client.get_agent_config.assert_awaited_once_with("regular-title")
    assert cold_client == [(TENANT_ID, {"local_dir": server.SOLUTION_LOCAL_DIR})]
