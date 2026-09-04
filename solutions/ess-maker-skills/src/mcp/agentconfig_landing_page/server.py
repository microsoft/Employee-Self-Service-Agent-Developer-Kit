# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""ESS landing-page configuration MCP server."""

from __future__ import annotations

import base64
import binascii
import html
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations

from client import AgentConfigApiError, AgentConfigClient


DEFAULT_WIDGET_ORIGIN = "https://workforceinsights.m365.cloud.microsoft"
WIDGET_MIME_TYPE = "text/html;profile=mcp-app"

ACCENT_COLOR_RESOURCE_URI = "ui://widget/accent-color/AccentColor.html"
QUICK_LINKS_RESOURCE_URI = "ui://widget/quick-links/QuickLinks.html"
STARTER_PROMPTS_RESOURCE_URI = "ui://widget/starter-prompts/StarterPrompts.html"
PNG_DATA_URL_PREFIX = "data:image/png;base64,"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

_READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
_UPDATE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
_DELETE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=True,
    openWorldHint=False,
)


def _resolve_widget_origin(value: str | None = None) -> str:
    origin = (
        value
        or os.environ.get("VORPAL_WIDGET_ORIGIN")
        or DEFAULT_WIDGET_ORIGIN
    ).rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "VORPAL_WIDGET_ORIGIN must be an HTTPS origin without credentials, "
            "a path, a query, or a fragment."
        )
    return origin


WIDGET_ORIGIN = _resolve_widget_origin()


def _widget_tool_meta(resource_uri: str) -> dict[str, Any]:
    return {
        "ui": {
            "resourceUri": resource_uri,
            "visibility": ["model"],
        }
    }


def _app_tool_meta() -> dict[str, Any]:
    return {"ui": {"visibility": ["model", "app"]}}


def _widget_resource_meta() -> dict[str, Any]:
    return {
        "ui": {
            "domain": WIDGET_ORIGIN,
            "csp": {
                "resourceDomains": [WIDGET_ORIGIN],
                "connectDomains": [],
            },
        }
    }


def _widget_shell(surface: str) -> str:
    script_url = html.escape(
        f"{WIDGET_ORIGIN}/mcp-widget/{surface}/widget.js",
        quote=True,
    )
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "  <head>\n"
        '    <meta charset="UTF-8" />\n'
        '    <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n'
        "  </head>\n"
        "  <body>\n"
        '    <div id="mcp-root"></div>\n'
        f'    <script type="module" src="{script_url}"></script>\n'
        "  </body>\n"
        "</html>\n"
    )


mcp = FastMCP(
    "ess-landing-page-config",
    instructions=(
        "Configure ESS landing pages through the production AgentConfiguration "
        "EmployeeAgents API. Resolve an agent by titleId, then read, initialize, "
        "update, or open a landing-page configuration surface."
    ),
)

_client: Optional[AgentConfigClient] = None


def get_client() -> AgentConfigClient:
    global _client
    if _client is None:
        _client = AgentConfigClient()
    return _client


def _format(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


def _structured_result(
    payload: dict[str, Any],
    message: str,
) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=message)],
        structuredContent=payload,
    )


def _extract_png_base64(icon: Any) -> str:
    if not isinstance(icon, str) or not icon.startswith(PNG_DATA_URL_PREFIX):
        raise ValueError("agent icon must be a data:image/png;base64 URL")

    data = icon[len(PNG_DATA_URL_PREFIX) :]
    if not data:
        raise ValueError("agent icon payload is empty")

    try:
        decoded = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("agent icon payload is not valid base64") from error

    if not decoded.startswith(PNG_SIGNATURE):
        raise ValueError("agent icon payload is not a PNG")
    return data


def _widget_error_result(
    error: AgentConfigApiError | httpx.RequestError | ValueError,
) -> CallToolResult:
    if isinstance(error, AgentConfigApiError):
        code = "AgentConfigurationError"
        retryable = False
    elif isinstance(error, httpx.RequestError):
        code = "NetworkError"
        retryable = True
    else:
        code = "InvalidRequest"
        retryable = False

    error_payload = {
        "code": code,
        "message": str(error),
        "retryable": retryable,
    }
    if isinstance(error, AgentConfigApiError) and error.http_status is not None:
        error_payload["httpStatus"] = error.http_status

    return CallToolResult(
        content=[TextContent(type="text", text=str(error))],
        structuredContent={"error": error_payload},
        isError=True,
    )


async def _open_widget(
    request: Callable[[], Awaitable[dict[str, Any]]],
    *,
    success_message: str,
) -> CallToolResult:
    try:
        payload = await request()
    except (AgentConfigApiError, httpx.RequestError, ValueError) as error:
        return _widget_error_result(error)

    return _structured_result(payload, success_message)


@mcp.resource(
    ACCENT_COLOR_RESOURCE_URI,
    name="Accent color",
    title="Accent color",
    description="Employee Agent accent-color editor.",
    mime_type=WIDGET_MIME_TYPE,
    meta=_widget_resource_meta(),
)
def accent_color_widget() -> str:
    return _widget_shell("accent-color")


@mcp.resource(
    QUICK_LINKS_RESOURCE_URI,
    name="Quick links",
    title="Quick links",
    description="Employee Agent quick-links editor.",
    mime_type=WIDGET_MIME_TYPE,
    meta=_widget_resource_meta(),
)
def quick_links_widget() -> str:
    return _widget_shell("quick-links")


@mcp.resource(
    STARTER_PROMPTS_RESOURCE_URI,
    name="Starter prompts",
    title="Starter prompts",
    description="Employee Agent starter-prompts editor.",
    mime_type=WIDGET_MIME_TYPE,
    meta=_widget_resource_meta(),
)
def starter_prompts_widget() -> str:
    return _widget_shell("starter-prompts")


@mcp.tool()
async def list_agent_configs() -> str:
    """List agents that already have landing-page configuration."""
    return _format(await get_client().list_agent_configs())


@mcp.tool()
async def search_agents(searchString: str) -> str:
    """Search tenant-visible agents by a distinctive name substring."""
    return _format(await get_client().search_agents(searchString))


@mcp.tool()
async def create_agent_config(titleId: str) -> str:
    """Initialize landing-page configuration for an eligible primary ESS agent."""
    return _format(await get_client().create_agent_config(titleId))


@mcp.tool()
async def get_agent_config(titleId: str) -> str:
    """Get an employee agent's complete landing-page configuration."""
    return _format(await get_client().get_agent_config(titleId))


@mcp.tool(annotations=_READ_ONLY_ANNOTATIONS)
async def view_agent_icon(titleId: str) -> CallToolResult:
    """Display an employee agent's current PNG icon in the conversation."""
    try:
        payload = await get_client().view_agent_icon(titleId)
        icon = payload.get("icon")
        name = payload.get("name")
        resolved_title_id = payload.get("titleId", titleId)

        if icon is None:
            return _structured_result(
                {
                    "titleId": resolved_title_id,
                    "name": name,
                    "hasIcon": False,
                },
                "This agent does not have a custom icon.",
            )

        image_data = _extract_png_base64(icon)
    except (AgentConfigApiError, httpx.RequestError, ValueError) as error:
        return _widget_error_result(error)

    label = f" for {name}" if isinstance(name, str) and name else ""
    return CallToolResult(
        content=[
            TextContent(type="text", text=f"Here is the current agent icon{label}."),
            ImageContent(type="image", data=image_data, mimeType="image/png"),
        ],
        structuredContent={
            "titleId": resolved_title_id,
            "name": name,
            "hasIcon": True,
        },
    )


@mcp.tool(
    meta=_app_tool_meta(),
    annotations=_UPDATE_ANNOTATIONS,
)
async def update_agent_config(
    titleId: str,
    config: dict[str, Any],
) -> CallToolResult:
    """Apply the complete value of each provided configuration section."""
    try:
        result = await get_client().update_agent_config(titleId, config)
    except (AgentConfigApiError, httpx.RequestError, ValueError) as error:
        return _widget_error_result(error)

    return _structured_result(
        result,
        "Updated the landing-page configuration.",
    )


@mcp.tool(annotations=_DELETE_ANNOTATIONS)
async def delete_agent_config(titleId: str) -> CallToolResult:
    """Delete all landing-page configuration after explicit maker confirmation."""
    try:
        result = await get_client().delete_agent_config(titleId)
    except (AgentConfigApiError, httpx.RequestError, ValueError) as error:
        return _widget_error_result(error)

    return _structured_result(
        {**result, "titleId": titleId},
        "Deleted the landing-page configuration and restored the defaults.",
    )


@mcp.tool(
    meta=_widget_tool_meta(ACCENT_COLOR_RESOURCE_URI),
    annotations=_READ_ONLY_ANNOTATIONS,
)
async def open_accent_color(titleId: str) -> CallToolResult:
    """Open the accent-color widget with the current branding section."""
    return await _open_widget(
        lambda: get_client().open_accent_color(titleId),
        success_message="Opened the accent-color editor.",
    )


@mcp.tool(
    meta=_widget_tool_meta(QUICK_LINKS_RESOURCE_URI),
    annotations=_READ_ONLY_ANNOTATIONS,
)
async def open_quick_links(titleId: str) -> CallToolResult:
    """Open the quick-links widget with the current section."""
    return await _open_widget(
        lambda: get_client().open_quick_links(titleId),
        success_message="Opened the quick-links editor.",
    )


@mcp.tool(
    meta=_widget_tool_meta(STARTER_PROMPTS_RESOURCE_URI),
    annotations=_READ_ONLY_ANNOTATIONS,
)
async def open_starter_prompts(titleId: str) -> CallToolResult:
    """Open the starter-prompts widget with the current pivots."""
    return await _open_widget(
        lambda: get_client().open_starter_prompts(titleId),
        success_message="Opened the starter-prompts editor.",
    )


if __name__ == "__main__":
    mcp.run()
