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
    assert _tool_functions() == {
        "list_agent_configs": [],
        "search_agents": ["searchString"],
        "create_agent_config": ["titleId"],
        "get_agent_config": ["titleId"],
        "view_agent_icon": ["titleId"],
        "update_agent_config": ["titleId", "config"],
        "delete_agent_config": ["titleId"],
        "open_accent_color": ["titleId", "draft"],
        "open_quick_links": ["titleId", "draft"],
        "open_starter_prompts": ["titleId", "draft"],
    }


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
