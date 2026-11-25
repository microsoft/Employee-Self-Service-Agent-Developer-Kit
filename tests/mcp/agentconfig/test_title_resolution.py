# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Independent provider adapters and cancellation-safe landing-page construction."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path
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
announcements = load_org_announcements_modules()["server"]
BOT_ID = "aaaaaaaa-0000-4000-8000-000000004444"
ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
TENANT_ID = "11111111-2222-3333-4444-555555555555"
OBJECT_ID = "00000000-0000-0000-0000-000000003333"
HOST = (
    "https://0000000000004000800000000000111."
    "1.environment.api.test.powerplatform.com"
)
TITLES = {"botId": BOT_ID, "titleId": "regular-title", "lobTitleId": "lob-title"}


class _Client:
    tenant_id = TENANT_ID
    object_id = OBJECT_ID


@pytest.fixture(autouse=True)
def cold_clients(monkeypatch):
    for provider in (server, announcements):
        monkeypatch.setattr(provider, "_client", None)
        monkeypatch.setattr(provider, "_client_construction_task", None)
        monkeypatch.setattr(provider, "_title_resolution", shared.TitleResolutionCoordinator())
    monkeypatch.setattr(announcements, "_client_lock", asyncio.Lock())
    monkeypatch.setattr(announcements, "_client_users", {})
    monkeypatch.setattr(announcements, "_retired_clients", set())
    monkeypatch.setattr(announcements, "record_operation", lambda *args, **kwargs: None)
    initialized = []
    monkeypatch.setattr(
        server.adk_telemetry, "initialize_tenant_identity",
        lambda tenant_id, **kwargs: initialized.append((tenant_id, kwargs)),
    )
    return initialized


@pytest.fixture
def configured_target(monkeypatch):
    target = shared.ConfiguredAgentTarget(
        BOT_ID, ENVIRONMENT_ID, HOST, "test", TENANT_ID
    )
    for provider in (server, announcements):
        monkeypatch.setattr(provider, "load_configured_target", lambda bot: target)
    return target


def test_both_features_share_resolution_but_not_provider_lifecycle():
    for provider in (server, announcements):
        assert provider.load_configured_target is shared.load_configured_target
        assert provider.resolve_configured_agent_title is shared.resolve_configured_agent_title
        assert isinstance(provider._title_resolution, shared.TitleResolutionCoordinator)
    assert server._title_resolution is not announcements._title_resolution
    for directory in ("agentconfig_landing_page", "agentconfig_org_announcements"):
        assert not (MCP_ROOT / directory / "agent_title.py").exists()


@pytest.mark.parametrize("provider", [server, announcements])
def test_provider_protocol_preserves_exact_target_and_identity_without_feature_calls(
    configured_target, monkeypatch, provider
):
    loop_thread = threading.get_ident()
    calls = []

    def construct():
        assert threading.get_ident() != loop_thread
        return _Client()

    def resolve(target, tenant_id, object_id):
        assert threading.get_ident() != loop_thread
        assert target is configured_target
        calls.append((tenant_id, object_id))
        return TITLES

    constructor = "AgentConfigClient" if provider is server else "OrgAnnouncementsClient"
    monkeypatch.setattr(provider, constructor, construct)
    monkeypatch.setattr(provider, "resolve_configured_agent_title", resolve)
    result = asyncio.run(provider.mcp.call_tool("resolve_agent_title_id", {"botId": BOT_ID}))
    payload = result[1] if isinstance(result, tuple) else result.structuredContent
    assert payload == TITLES
    assert calls == [(TENANT_ID, OBJECT_ID)]
    tool = next(
        tool for tool in asyncio.run(provider.mcp.list_tools())
        if tool.name == "resolve_agent_title_id"
    )
    assert set(tool.inputSchema["properties"]) == {"botId"}
    assert tool.inputSchema["required"] == ["botId"]
    assert tool.annotations.readOnlyHint is True
    assert not (tool.meta or {}).get("ui", {}).get("resourceUri")


@pytest.mark.parametrize("provider", [server, announcements])
def test_invalid_target_does_not_start_authoring_sign_in(tmp_path, monkeypatch, provider):
    monkeypatch.setattr(shared, "CONFIG_PATH", tmp_path / "missing.json")
    constructor = "AgentConfigClient" if provider is server else "OrgAnnouncementsClient"
    monkeypatch.setattr(
        provider, constructor, lambda: pytest.fail("invalid target reached sign-in")
    )
    with pytest.raises(ToolError, match="InvalidRequest:"):
        asyncio.run(provider.resolve_agent_title_id(BOT_ID))


@pytest.mark.parametrize("provider", [server, announcements])
@pytest.mark.parametrize("failure", [PermissionError, ValueError, RuntimeError])
def test_authoring_credential_failure_is_sanitized(
    configured_target, monkeypatch, provider, failure
):
    def fail():
        raise failure("PRIVATE_LOCAL_CREDENTIAL")

    constructor = "AgentConfigClient" if provider is server else "OrgAnnouncementsClient"
    monkeypatch.setattr(provider, constructor, fail)
    with pytest.raises(ToolError, match="AuthenticationRequired:") as caught:
        asyncio.run(provider.resolve_agent_title_id(BOT_ID))
    assert "PRIVATE_LOCAL_CREDENTIAL" not in str(caught.value)


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
def test_resolver_and_every_feature_share_one_off_loop_construction(
    configured_target, cold_clients, monkeypatch, tool_name, arguments
):
    loop_thread = threading.get_ident()
    started, release = threading.Event(), threading.Event()
    constructions = []
    client = _Client()
    operation = AsyncMock(return_value={
        "titleId": "regular-title", "name": "Example", "icon": None,
    })
    setattr(client, tool_name, operation)

    def construct():
        assert threading.get_ident() != loop_thread
        constructions.append(client)
        started.set()
        assert release.wait(timeout=5)
        return client

    monkeypatch.setattr(server, "AgentConfigClient", construct)
    monkeypatch.setattr(server, "resolve_configured_agent_title", lambda *args: TITLES)

    async def run():
        resolver = asyncio.create_task(server.resolve_agent_title_id(BOT_ID))
        feature = None
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 5), timeout=6)
            entered = asyncio.Event()

            async def call_feature():
                entered.set()
                return await getattr(server, tool_name)(**arguments)

            feature = asyncio.create_task(call_feature())
            await asyncio.wait_for(entered.wait(), timeout=5)
            assert constructions == [client]
            assert not feature.done()
            release.set()
            result, _ = await asyncio.wait_for(
                asyncio.gather(resolver, feature), timeout=5
            )
            assert result == TITLES
            assert server._client is client
        finally:
            release.set()
            await asyncio.gather(
                *(task for task in (resolver, feature) if task is not None),
                return_exceptions=True,
            )

    asyncio.run(run())
    operation.assert_awaited_once_with(*arguments.values())
    assert cold_clients == [(TENANT_ID, {"local_dir": server.SOLUTION_LOCAL_DIR})]


def test_anyio_cancelled_feature_waiter_retains_construction_for_resolver(
    configured_target, cold_clients, monkeypatch
):
    started, release = threading.Event(), threading.Event()
    constructions = []
    client = _Client()
    client.get_agent_config = AsyncMock(return_value={"titleId": "regular-title"})

    def construct():
        constructions.append(client)
        started.set()
        assert release.wait(timeout=5)
        return client

    monkeypatch.setattr(server, "AgentConfigClient", construct)
    monkeypatch.setattr(server, "resolve_configured_agent_title", lambda *args: TITLES)

    async def run():
        scope, first_done = anyio.CancelScope(), anyio.Event()
        resolver_waiting = anyio.Event()
        arrivals, results = [], []
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
                assert await asyncio.wait_for(asyncio.to_thread(started.wait, 5), timeout=6)
                construction = server._client_construction_task
                scope.cancel()
                with anyio.fail_after(5):
                    await first_done.wait()
                assert server._client_construction_task is construction
                assert not construction.done()
                group.start_soon(resolver)
                with anyio.fail_after(5):
                    await resolver_waiting.wait()
                assert constructions == [client]
                release.set()
        finally:
            release.set()
        assert results == [TITLES]
        assert server._client is client
        assert server._client_construction_task is None

    anyio.run(run, backend="asyncio")
    assert cold_clients == [(TENANT_ID, {"local_dir": server.SOLUTION_LOCAL_DIR})]


def test_failed_construction_can_retry_through_feature_then_resolver(
    configured_target, monkeypatch
):
    constructions = []
    client = _Client()
    client.get_agent_config = AsyncMock(return_value={"titleId": "regular-title"})

    def construct():
        constructions.append(1)
        if len(constructions) == 1:
            raise ValueError("PRIVATE_CONSTRUCTION_FAILURE")
        return client

    monkeypatch.setattr(server, "AgentConfigClient", construct)
    monkeypatch.setattr(server, "resolve_configured_agent_title", lambda *args: TITLES)

    async def run():
        with pytest.raises(ToolError, match="AuthenticationRequired:") as caught:
            await server.resolve_agent_title_id(BOT_ID)
        assert "PRIVATE_CONSTRUCTION_FAILURE" not in str(caught.value)
        assert server._client is None and server._client_construction_task is None
        assert json.loads(await server.get_agent_config("regular-title")) == {
            "titleId": "regular-title",
        }
        assert await server.resolve_agent_title_id(BOT_ID) == TITLES

    asyncio.run(run())
    assert constructions == [1, 1]


@pytest.mark.parametrize("provider", [server, announcements])
def test_cancelled_threaded_lookup_rejects_retries_until_failure_then_recovers(
    configured_target, monkeypatch, provider
):
    started, release = threading.Event(), threading.Event()
    calls = []
    monkeypatch.setattr(provider, "get_client", AsyncMock(return_value=_Client()))

    def resolve(*args):
        calls.append(1)
        if len(calls) == 1:
            started.set()
            assert release.wait(timeout=5)
            raise shared.AgentTitleResolutionError(
                "The bounded sign-in timed out.", code="AuthenticationRequired"
            )
        return TITLES

    monkeypatch.setattr(provider, "resolve_configured_agent_title", resolve)

    async def run():
        caller = asyncio.create_task(provider.resolve_agent_title_id(BOT_ID))
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 5), timeout=6)
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            pending = provider._title_resolution._task
            assert pending is not None and not pending.done()
            for _ in range(3):
                with pytest.raises(ToolError, match="already in progress"):
                    await provider.resolve_agent_title_id("different-target")
            assert calls == [1]
            release.set()
            with pytest.raises(ToolError, match="AuthenticationRequired:"):
                await asyncio.wait_for(asyncio.shield(pending), timeout=5)
            await asyncio.sleep(0)
            assert provider._title_resolution._task is None
            assert await asyncio.wait_for(asyncio.to_thread(lambda: True), timeout=2)
            assert await provider.resolve_agent_title_id(BOT_ID) == TITLES
        finally:
            release.set()
            await asyncio.gather(caller, return_exceptions=True)

    asyncio.run(run())
