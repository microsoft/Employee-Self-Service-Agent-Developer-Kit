# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Contract checks for the local landing-page MCP server."""

from __future__ import annotations

import ast
import json
from pathlib import Path


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
        "open_accent_color": ["titleId"],
        "open_quick_links": ["titleId"],
        "open_starter_prompts": ["titleId"],
    }


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
