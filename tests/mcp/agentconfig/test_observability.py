# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""LPC instrumentation tests: real native tool boundary, no backend or collector."""

from __future__ import annotations

import asyncio
import json
import sys
import warnings
from pathlib import Path

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from pydantic_settings.exceptions import IncompleteFieldDefinitionWarning

LPC_DIR = (
    Path(__file__).parents[3] / "solutions" / "ess-maker-skills" / "src" / "mcp"
    / "agentconfig_landing_page"
)
sys.path.insert(0, str(LPC_DIR))
with warnings.catch_warnings():
    warnings.simplefilter("ignore", IncompleteFieldDefinitionWarning)
    import server  # noqa: E402

from lpc_telemetry import record_configuration  # noqa: E402
import operation_telemetry as ot  # noqa: E402

TENANT = "00000000-0000-0000-0000-000000001111"
SENSITIVE = "QuarterlyPayrollReview"
CONFIG = {
    "branding": {"theming": [{"name": "light", "accentColor": "#008800"}]},
    "quickLinksConfig": {
        "quickLinks": [{"displayText": SENSITIVE, "address": "https://example.test/private"}],
    },
    "pivots": [
        {
            "displayName": SENSITIVE,
            "conversationStarterPrompts": [
                {"title": SENSITIVE, "displayText": SENSITIVE},
                {"title": SENSITIVE, "displayText": SENSITIVE},
            ],
        },
    ],
    SENSITIVE: SENSITIVE,
}


class FakeClient:
    tenant_id = TENANT
    _object_id = SENSITIVE

    async def list_agent_configs(self):
        return [{"name": SENSITIVE}, {"name": SENSITIVE}]

    async def search_agents(self, search):
        return [{"name": SENSITIVE}]

    async def create_agent_config(self, title_id):
        return CONFIG

    async def get_agent_config(self, title_id):
        return CONFIG

    async def view_agent_icon(self, title_id):
        return {"icon": None, "name": SENSITIVE}

    async def update_agent_config(self, title_id, config):
        return CONFIG

    async def delete_agent_config(self, title_id):
        return {"success": True}

    async def open_accent_color(self, title_id):
        return {"branding": CONFIG["branding"]}

    async def open_quick_links(self, title_id):
        return {"quickLinksConfig": CONFIG["quickLinksConfig"]}

    async def open_starter_prompts(self, title_id):
        return {"pivots": CONFIG["pivots"]}


@pytest.fixture
def records(monkeypatch):
    rows = []
    monkeypatch.setattr(server, "_client", FakeClient())
    monkeypatch.setattr(server.adk_telemetry, "telemetry_enabled", lambda: True)
    monkeypatch.setattr(
        server.adk_telemetry, "emit_api_call", lambda **fields: rows.append(fields),
    )
    monkeypatch.setattr(
        server.adk_telemetry, "get_tenant_identity",
        lambda tenant_id, **kwargs: {"tenant_id": tenant_id, "tenant_name": "Contoso"},
    )
    return rows


@pytest.mark.parametrize(
    "tool",
    [
        "list_agent_configs", "search_agents", "create_agent_config", "get_agent_config",
        "view_agent_icon", "update_agent_config", "delete_agent_config",
        "open_accent_color", "open_quick_links", "open_starter_prompts",
    ],
)
def test_all_business_tools_emit_one_content_free_record(records, tool):
    args = {"titleId": SENSITIVE}
    if tool == "list_agent_configs":
        args = {}
    elif tool == "search_agents":
        args = {"searchString": SENSITIVE}
    elif tool == "update_agent_config":
        args["config"] = CONFIG
    asyncio.run(server.mcp.call_tool(tool, args))
    row, = records
    assert row["api_endpoint"] == tool
    assert row["mcp_server"] == "ess-landing-page-config"
    assert row["result_kind"] == "success"
    assert row["tenant_id"] == TENANT
    assert row["tenant_name"] == "Contoso"
    assert row["write_state"] == (
        "confirmed" if tool in {"create_agent_config", "update_agent_config", "delete_agent_config"}
        else None
    )
    if tool == "list_agent_configs":
        assert row["usage"]["discovery_result_count"] == 2
    if tool == "search_agents":
        assert row["usage"]["discovery_result_count"] == 1
    if tool in {"create_agent_config", "get_agent_config", "update_agent_config"}:
        assert row["usage"] == {
            "config_branding_present": True, "config_quick_links_present": True,
            "config_pivots_present": True, "quick_link_count": 1, "pivot_count": 1,
            "category_count": 1, "prompt_count": 2,
        }
    if tool.startswith("open_"):
        assert row["usage"]["widget"] == tool.removeprefix("open_").replace("_", "-")
        assert row["usage"]["draft_present"] is False
    assert SENSITIVE not in json.dumps(row)
    assert "example.test" not in json.dumps(row)


def test_valid_draft_counts_are_separate_from_baseline(records):
    asyncio.run(server.mcp.call_tool(
        "open_starter_prompts",
        {
            "titleId": SENSITIVE,
            "draft": {"pivots": [
                {"displayName": SENSITIVE, "conversationStarterPrompts": []},
                {"displayName": SENSITIVE, "conversationStarterPrompts": []},
            ]},
        },
    ))
    usage = records[0]["usage"]
    assert usage["draft_present"] is True
    assert usage["pivot_count"] == usage["category_count"] == 1
    assert usage["prompt_count"] == 2
    assert usage["draft_pivot_count"] == usage["draft_category_count"] == 2
    assert usage["draft_prompt_count"] == 0
    assert SENSITIVE not in json.dumps(records)


@pytest.mark.parametrize(
    "config",
    [
        {}, None,
        {"quickLinksConfig": None, "pivots": None},
        {"quickLinksConfig": {"quickLinks": [SENSITIVE]}, "pivots": [SENSITIVE]},
        {"quickLinksConfig": {"quickLinks": [{}]}, "pivots": [{}]},
    ],
)
def test_missing_or_invalid_shapes_do_not_fabricate_zero_counts(config):
    operation = ot.Operation("test")
    token = ot.current_operation.set(operation)
    try:
        record_configuration(config)
    finally:
        ot.current_operation.reset(token)
    assert not any(key.endswith("_count") for key in operation.usage)


def test_explicit_empty_lists_have_actual_zero_counts():
    operation = ot.Operation("test")
    token = ot.current_operation.set(operation)
    try:
        record_configuration({"pivots": [], "quickLinksConfig": {"quickLinks": []}})
    finally:
        ot.current_operation.reset(token)
    for field in ["quick_link_count", "pivot_count", "prompt_count", "category_count"]:
        assert operation.usage[field] == 0


def test_preauth_failure_never_reuses_previous_tenant(records, monkeypatch):
    asyncio.run(server.mcp.call_tool("get_agent_config", {"titleId": SENSITIVE}))

    def auth_failure():
        raise ValueError(SENSITIVE)

    monkeypatch.setattr(server, "_client", None)
    monkeypatch.setattr(server, "AgentConfigClient", auth_failure)
    with pytest.raises(ToolError):
        asyncio.run(server.mcp.call_tool("get_agent_config", {"titleId": SENSITIVE}))
    assert records[0]["tenant_id"] == TENANT
    assert records[1]["tenant_id"] == records[1]["tenant_name"] == ""
    assert records[1]["result_kind"] == "exception"
    assert SENSITIVE not in json.dumps(records)


def test_returned_api_error_keeps_response_but_excludes_backend_text(records, monkeypatch):
    class RejectingClient(FakeClient):
        async def update_agent_config(self, title_id, config):
            ot.http_attempt(retry=False)
            ot.http_response(403)
            raise server.AgentConfigApiError(SENSITIVE, http_status=403)

    monkeypatch.setattr(server, "_client", RejectingClient())
    result = asyncio.run(server.mcp.call_tool(
        "update_agent_config", {"titleId": SENSITIVE, "config": CONFIG},
    ))
    assert result.isError
    assert result.structuredContent["error"]["message"] == SENSITIVE
    row, = records
    assert row["result_kind"] == "tool_error"
    assert row["http_status"] == row["failure_http_status"] == 403
    assert row["error_code"] == "http_error"
    assert row["write_state"] is None
    assert SENSITIVE not in json.dumps(row)
