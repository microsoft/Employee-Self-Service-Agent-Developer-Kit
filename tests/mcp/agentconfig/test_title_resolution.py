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

    def get_client():
        assert threading.get_ident() != caller_thread
        return client

    def resolve(target, tenant_id, object_id):
        assert threading.get_ident() != caller_thread
        assert (target.bot_id, target.dataverse_endpoint) == (BOT_ID, ENDPOINT)
        calls.append((tenant_id, object_id))
        return {"botId": BOT_ID, "titleId": "regular-title", "lobTitleId": "lob-title"}

    monkeypatch.setattr(server, "get_client", get_client)
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
        server, "get_client", lambda: pytest.fail("Invalid configuration reached sign-in")
    )
    with pytest.raises(ToolError, match="InvalidRequest:"):
        asyncio.run(server.resolve_agent_title_id(BOT_ID))


def test_landing_authoring_failure_does_not_expose_credentials(
    configured_target, monkeypatch, caplog
):
    private = "PRIVATE_LOCAL_CREDENTIAL_DETAIL"

    def fail():
        raise ValueError(private)

    monkeypatch.setattr(server, "get_client", fail)
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
