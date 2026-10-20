# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Native MCP 1.x call boundary and opt-in MCP Apps telemetry bridge."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import CallToolResult, ContentBlock, TextContent, ToolAnnotations
from pydantic import ValidationError

from base_client import AgentConfigApiError
from operation_telemetry import Operation, current_operation

if TYPE_CHECKING:
    from adk_telemetry import McpResultKind


def record_error(error: BaseException) -> None:
    """Classify by exception type, never by customer-controlled message text."""
    operation = current_operation.get()
    if operation is None:
        return
    cause = error
    seen: set[int] = set()
    while cause.__cause__ is not None and id(cause) not in seen:
        seen.add(id(cause))
        cause = cause.__cause__
    if isinstance(cause, httpx.TimeoutException):
        code, category = "timeout", "network"
    elif isinstance(cause, httpx.RequestError):
        code, category = "network_error", "network"
    elif isinstance(cause, (AgentConfigApiError, httpx.HTTPStatusError)):
        code, category = "http_error", "api"
    elif isinstance(cause, (ValidationError, ValueError)):
        code, category = "invalid_request", "validation"
    elif isinstance(cause, ToolError):
        code, category = "tool_error", "tool"
    else:
        code, category = "exception", "internal"
    operation.error_code = code
    operation.error_category = category


def _argument_validation_failed(error: Exception) -> bool:
    seen: set[int] = set()
    cause: BaseException | None = error
    while cause is not None and id(cause) not in seen:
        if isinstance(cause, ValidationError):
            return True
        seen.add(id(cause))
        cause = cause.__cause__
    return False


class ObservedFastMCP(FastMCP):
    """Observe completed business calls without changing native tool execution."""

    def __init__(self, name: str, **kwargs: Any) -> None:
        super().__init__(name, **kwargs)
        self._telemetry_server_name = name
        self._telemetry_exempt_tools: set[str] = set()

    async def call_tool(
        self, name: str, arguments: dict[str, Any],
    ) -> Sequence[ContentBlock] | dict[str, Any]:
        if name in self._telemetry_exempt_tools:
            return await super().call_tool(name, arguments)

        operation = Operation(self._telemetry_server_name)
        token = current_operation.set(operation)
        result_kind: McpResultKind = "exception"
        registry_resolved = False
        known = False
        try:
            try:
                tools = await self.list_tools()
                canonical = next((tool.name for tool in tools if tool.name == name), None)
                registry_resolved = True
                known = canonical is not None
                operation.api_endpoint = canonical if canonical is not None else "unknown"
            except Exception:
                # A discovery failure must not prevent the native tool invocation.
                pass
            result = await super().call_tool(name, arguments)
            result_kind = (
                "tool_error" if isinstance(result, CallToolResult) and result.isError
                else "success"
            )
            return result
        except asyncio.CancelledError:
            result_kind = "cancelled"
            raise
        except Exception as error:
            record_error(error)
            if registry_resolved and not known:
                result_kind = "unknown_tool"
            elif not operation.handler_entered and _argument_validation_failed(error):
                result_kind = "invalid_arguments"
            raise
        finally:
            try:
                operation.complete(result_kind)
            finally:
                current_operation.reset(token)


def register_client_events_bridge(
    mcp: ObservedFastMCP,
) -> Callable[..., Awaitable[CallToolResult]]:
    """Register schema-v2 telemetry only on the server hosting the widget resources."""

    @mcp.tool(
        meta={"ui": {"visibility": ["app"]}},
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    async def report_client_events(
        schemaVersion: Any = None,
        batchId: Any = None,
        mountId: Any = None,
        appName: Any = None,
        buildEnvironment: Any = None,
        buildNumber: Any = None,
        platform: Any = None,
        userAgent: Any = None,
        events: Any = None,
        toolCallId: Any = None,
    ) -> CallToolResult:
        """Accept Vorpal telemetry with an explicit accepted/rejected verdict."""
        import adk_telemetry

        envelope: dict[str, Any] = {
            "schemaVersion": schemaVersion,
            "batchId": batchId,
            "mountId": mountId,
            "appName": appName,
            "buildEnvironment": buildEnvironment,
            "buildNumber": buildNumber,
            "platform": platform,
            "userAgent": userAgent,
            "events": events,
        }
        if toolCallId is not None:
            envelope["toolCallId"] = toolCallId
        result = adk_telemetry.report_client_events(envelope)
        message = (
            f"Accepted {result['acceptedEventCount']} client telemetry event(s)."
            if result.get("status") == "accepted"
            else "Rejected the client telemetry batch."
        )
        return CallToolResult(
            content=[TextContent(type="text", text=message)],
            structuredContent=result,
            isError=result.get("status") == "rejected",
        )

    mcp._telemetry_exempt_tools.add("report_client_events")
    return report_client_events
