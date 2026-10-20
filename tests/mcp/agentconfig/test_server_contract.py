# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Contract checks for the local landing-page MCP server."""

from __future__ import annotations

import asyncio
import ast
import json
from pathlib import Path
import sys
import warnings

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic_settings.exceptions import IncompleteFieldDefinitionWarning


REPO_ROOT = Path(__file__).parents[3]
SERVER_PATH = (
    REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "mcp"
    / "agentconfig_landing_page"
    / "server.py"
)
MCP_DEFAULTS_PATH = (
    REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / ".vscode"
    / "mcp.defaults.json"
)
sys.path.insert(0, str(SERVER_PATH.parent))

with warnings.catch_warnings():
    warnings.simplefilter("ignore", IncompleteFieldDefinitionWarning)
    import server as agentconfig_server  # noqa: E402


def _tool_functions() -> dict[str, list[str]]:
    module = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
    tools: dict[str, list[str]] = {}
    for node in module.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        is_tool = any(
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "tool"
            for decorator in node.decorator_list
        )
        if is_tool:
            tools[node.name] = [argument.arg for argument in node.args.args]
    return tools


def test_server_exposes_the_skill_tool_contract() -> None:
    expected_tools = {
        "resolve_agent_title_id": ["botId"],
        "create_agent_config": ["titleId"],
        "get_agent_config": ["titleId"],
        "view_agent_icon": ["titleId"],
        "update_agent_config": ["titleId", "config"],
        "delete_agent_config": ["titleId"],
        "open_accent_color": ["titleId"],
        "open_quick_links": ["titleId"],
        "open_starter_prompts": ["titleId"],
        # App-only telemetry shares the connection serving the widget resources
        # and stays hidden from the model-visible tool list.
        "report_client_events": [
            "schemaVersion",
            "batchId",
            "mountId",
            "appName",
            "buildEnvironment",
            "buildNumber",
            "platform",
            "userAgent",
            "events",
            "toolCallId",
        ],
    }
    for tool_name in ("open_accent_color", "open_quick_links", "open_starter_prompts"):
        expected_tools[tool_name].append("draft")
    assert _tool_functions() == expected_tools


def test_title_resolution_is_read_only_and_requires_only_the_configured_bot() -> None:
    tools = {
        tool.name: tool
        for tool in asyncio.run(agentconfig_server.mcp.list_tools())
    }
    resolver = tools["resolve_agent_title_id"]
    assert set(resolver.inputSchema["properties"]) == {"botId"}
    assert resolver.inputSchema["required"] == ["botId"]
    assert resolver.inputSchema["properties"]["botId"]["type"] == "string"
    assert resolver.annotations.readOnlyHint is True
    assert resolver.annotations.destructiveHint is False
    assert resolver.annotations.idempotentHint is True
    assert "list_agent_configs" not in tools
    assert "search_agents" not in tools


def test_stdio_entrypoint_exposes_discovery_and_rejects_invalid_bots_without_sign_in() -> None:
    async def run():
        parameters = StdioServerParameters(
            command=sys.executable,
            args=[str(SERVER_PATH)],
            cwd=str(SERVER_PATH.parent),
        )
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = {tool.name for tool in (await session.list_tools()).tools}
                assert "resolve_agent_title_id" in tools
                assert "list_agent_configs" not in tools
                assert "search_agents" not in tools
                assert {"get_agent_config", "open_accent_color", "open_quick_links",
                        "open_starter_prompts"} <= tools
                result = await session.call_tool(
                    "resolve_agent_title_id", {"botId": "not-a-guid"}
                )
                assert result.isError is True
                assert any(
                    item.type == "text" and "InvalidRequest:" in item.text
                    for item in result.content
                )

    asyncio.run(asyncio.wait_for(run(), timeout=15))


def test_widget_openers_advertise_surface_specific_draft_schemas() -> None:
    tools = {
        tool.name: tool
        for tool in asyncio.run(agentconfig_server.mcp.list_tools())
    }
    expected_definitions = {
        "open_accent_color": {
            "AccentColorDraft": {"branding"},
            "BrandingDraft": {"theming"},
            "AccentThemeDraft": {"name", "accentColor"},
        },
        "open_quick_links": {
            "QuickLinksDraft": {"quickLinksConfig"},
            "QuickLinksConfigDraft": {"quickLinks"},
            "QuickLinkDraft": {"displayText", "address"},
        },
        "open_starter_prompts": {
            "StarterPromptsDraft": {"pivots"},
            "StarterPromptPivotDraft": {
                "displayName",
                "conversationStarterPrompts",
            },
            "StarterPromptDraft": {"title", "displayText"},
        },
    }

    for tool_name, model_fields in expected_definitions.items():
        schema = tools[tool_name].inputSchema
        assert set(schema["properties"]) == {"titleId", "draft"}
        assert schema["required"] == ["titleId"]
        assert schema["properties"]["draft"]["default"] is None
        assert set(schema["$defs"]) == set(model_fields)

        for model_name, fields in model_fields.items():
            definition = schema["$defs"][model_name]
            assert definition["type"] == "object"
            assert definition["additionalProperties"] is False
            assert set(definition["properties"]) == fields
            assert set(definition["required"]) == fields

    accent_schema = tools["open_accent_color"].inputSchema
    accent_theme = accent_schema["$defs"]["AccentThemeDraft"]["properties"]
    assert accent_theme["name"]["enum"] == ["light", "dark"]
    assert accent_theme["accentColor"]["pattern"] == "^#[0-9A-Fa-f]{6}$"
    assert (
        accent_schema["$defs"]["BrandingDraft"]["properties"]["theming"][
            "maxItems"
        ]
        == 2
    )

    quick_links_schema = tools["open_quick_links"].inputSchema
    quick_links = quick_links_schema["$defs"]["QuickLinksConfigDraft"][
        "properties"
    ]["quickLinks"]
    assert quick_links["maxItems"] == 10

    starter_schema = tools["open_starter_prompts"].inputSchema
    pivots = starter_schema["$defs"]["StarterPromptsDraft"]["properties"][
        "pivots"
    ]
    prompts = starter_schema["$defs"]["StarterPromptPivotDraft"][
        "properties"
    ]["conversationStarterPrompts"]
    assert pivots["maxItems"] == 10
    assert prompts["maxItems"] == 12


def test_mcp_defaults_defer_production_endpoints_to_server_fallbacks() -> None:
    config = json.loads(MCP_DEFAULTS_PATH.read_text(encoding="utf-8"))

    assert "ess-landing-page-config" in config["servers"]
    server = config["servers"]["ess-landing-page-config"]
    assert server["command"] == "{pythonExecutable}"
    assert server["args"] == ["server.py"]
    assert "env" not in server
    serialized = json.dumps(config).lower()
    assert "localhost" not in serialized
    assert "tls_insecure" not in serialized
