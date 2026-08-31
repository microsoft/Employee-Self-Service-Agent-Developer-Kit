# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Protocol-level tests for AgentConfiguration MCP Apps."""

from __future__ import annotations

import asyncio
import base64
import sys
import warnings
from pathlib import Path
from typing import Any

import pytest
from pydantic_settings.exceptions import IncompleteFieldDefinitionWarning


REPO_ROOT = Path(__file__).parents[3]
AGENTCONFIG_DIR = (
    REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "mcp"
    / "agentconfig_landing_page"
)
sys.path.insert(0, str(AGENTCONFIG_DIR))

with warnings.catch_warnings():
    warnings.simplefilter("ignore", IncompleteFieldDefinitionWarning)
    import server as agentconfig_server  # noqa: E402


WIDGET_ORIGIN = agentconfig_server.WIDGET_ORIGIN
WIDGETS = {
    "open_accent_color": (
        "ui://widget/accent-color/AccentColor.html",
        "accent-color",
    ),
    "open_quick_links": (
        "ui://widget/quick-links/QuickLinks.html",
        "quick-links",
    ),
    "open_starter_prompts": (
        "ui://widget/starter-prompts/StarterPrompts.html",
        "starter-prompts",
    ),
}


def test_widget_origin_uses_production_fallback() -> None:
    assert (
        agentconfig_server.DEFAULT_WIDGET_ORIGIN
        == "https://workforceinsights.m365.cloud.microsoft"
    )


class _FakeClient:
    async def view_agent_icon(self, title_id: str) -> dict[str, Any]:
        icon = base64.b64encode(
            agentconfig_server.PNG_SIGNATURE + b"test-image-content"
        ).decode("ascii")
        return {
            "titleId": title_id,
            "name": "ESS HR",
            "icon": f"{agentconfig_server.PNG_DATA_URL_PREFIX}{icon}",
        }

    async def open_accent_color(self, title_id: str) -> dict[str, Any]:
        return {"titleId": title_id, "branding": {"theming": []}}

    async def open_quick_links(self, title_id: str) -> dict[str, Any]:
        return {"titleId": title_id, "quickLinksConfig": {"quickLinks": []}}

    async def open_starter_prompts(self, title_id: str) -> dict[str, Any]:
        return {"titleId": title_id, "pivots": []}

    async def update_agent_config(
        self,
        title_id: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        return {"titleId": title_id, **config}

    async def delete_agent_config(self, title_id: str) -> dict[str, Any]:
        return {"success": True}


class _NoIconClient:
    async def view_agent_icon(self, title_id: str) -> dict[str, Any]:
        return {"titleId": title_id, "name": "ESS HR", "icon": None}


def test_widget_tools_bind_model_visible_resources() -> None:
    tools = {
        tool.name: tool
        for tool in asyncio.run(agentconfig_server.mcp.list_tools())
    }

    for tool_name, (resource_uri, _) in WIDGETS.items():
        tool = tools[tool_name]
        assert tool.meta == {
            "ui": {
                "resourceUri": resource_uri,
                "visibility": ["model"],
            }
        }
        assert tool.annotations.readOnlyHint is True

    assert tools["update_agent_config"].meta == {
        "ui": {"visibility": ["model", "app"]}
    }
    assert tools["view_agent_icon"].annotations.readOnlyHint is True
    assert tools["view_agent_icon"].meta is None
    assert tools["delete_agent_config"].annotations.destructiveHint is True
    assert tools["delete_agent_config"].annotations.readOnlyHint is False


def test_widget_resources_serve_mcp_app_shells() -> None:
    resources = {
        str(resource.uri): resource
        for resource in asyncio.run(agentconfig_server.mcp.list_resources())
    }

    assert set(resources) == {
        resource_uri for resource_uri, _ in WIDGETS.values()
    }
    for resource_uri, surface in WIDGETS.values():
        resource = resources[resource_uri]
        assert resource.mimeType == "text/html;profile=mcp-app"
        assert resource.meta == {
            "ui": {
                "domain": WIDGET_ORIGIN,
                "csp": {
                    "resourceDomains": [WIDGET_ORIGIN],
                    "connectDomains": [],
                },
            }
        }
        contents = asyncio.run(
            agentconfig_server.mcp.read_resource(resource_uri)
        )
        assert len(contents) == 1
        assert '<div id="mcp-root"></div>' in contents[0].content
        assert (
            f'{WIDGET_ORIGIN}/mcp-widget/{surface}/widget.js'
            in contents[0].content
        )


def test_widget_origin_is_configurable_and_https_only() -> None:
    assert agentconfig_server._resolve_widget_origin(
        "https://widgets.example.test/"
    ) == "https://widgets.example.test"

    for invalid_origin in (
        "http://widgets.example.test",
        "https://user@widgets.example.test",
        "https://widgets.example.test/path",
        "https://widgets.example.test?query=value",
        "https://widgets.example.test#fragment",
    ):
        try:
            agentconfig_server._resolve_widget_origin(invalid_origin)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Accepted invalid origin: {invalid_origin}")


def test_openers_and_app_tools_return_structured_content(monkeypatch) -> None:
    monkeypatch.setattr(agentconfig_server, "_client", _FakeClient())

    async def run() -> None:
        icon = await agentconfig_server.mcp.call_tool(
            "view_agent_icon",
            {"titleId": "title-1"},
        )
        assert icon.isError is False
        assert icon.structuredContent == {
            "titleId": "title-1",
            "name": "ESS HR",
            "hasIcon": True,
        }
        assert [item.type for item in icon.content] == ["text", "image"]
        assert icon.content[1].mimeType == "image/png"
        assert base64.b64decode(icon.content[1].data).startswith(
            agentconfig_server.PNG_SIGNATURE
        )

        for tool_name in WIDGETS:
            opened = await agentconfig_server.mcp.call_tool(
                tool_name,
                {"titleId": "title-1"},
            )
            assert opened.isError is False
            assert opened.structuredContent["titleId"] == "title-1"
            assert opened.content

        updated = await agentconfig_server.mcp.call_tool(
            "update_agent_config",
            {
                "titleId": "title-1",
                "config": {"branding": {"theming": []}},
            },
        )
        assert updated.structuredContent == {
            "titleId": "title-1",
            "branding": {"theming": []},
        }

        deleted = await agentconfig_server.mcp.call_tool(
            "delete_agent_config",
            {"titleId": "title-1"},
        )
        assert deleted.isError is False
        assert deleted.structuredContent == {
            "success": True,
            "titleId": "title-1",
        }

    asyncio.run(run())


def test_view_agent_icon_returns_text_when_no_custom_icon_exists(
    monkeypatch,
) -> None:
    monkeypatch.setattr(agentconfig_server, "_client", _NoIconClient())

    result = asyncio.run(
        agentconfig_server.mcp.call_tool(
            "view_agent_icon",
            {"titleId": "title-1"},
        )
    )

    assert result.isError is False
    assert [item.type for item in result.content] == ["text"]
    assert result.structuredContent == {
        "titleId": "title-1",
        "name": "ESS HR",
        "hasIcon": False,
    }


@pytest.mark.parametrize(
    ("icon", "message"),
    [
        ("not-a-data-url", "data:image/png;base64"),
        ("data:image/png;base64,!!!!", "not valid base64"),
        (
            "data:image/png;base64,"
            + base64.b64encode(b"not a png").decode("ascii"),
            "not a PNG",
        ),
    ],
)
def test_extract_png_base64_rejects_invalid_icons(
    icon: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        agentconfig_server._extract_png_base64(icon)


def test_api_error_result_includes_http_status() -> None:
    result = agentconfig_server._widget_error_result(
        agentconfig_server.AgentConfigApiError(
            "BadRequest: The request is invalid.",
            http_status=400,
        )
    )

    assert result.isError is True
    assert result.structuredContent == {
        "error": {
            "code": "AgentConfigurationError",
            "message": "BadRequest: The request is invalid.",
            "retryable": False,
            "httpStatus": 400,
        }
    }
