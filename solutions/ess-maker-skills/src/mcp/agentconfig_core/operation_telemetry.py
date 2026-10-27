# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Opt-in request-local measurements; importing the HTTP core needs no MCP SDK."""

from __future__ import annotations

import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Unpack

if TYPE_CHECKING:
    from adk_telemetry import ApiCallUsage, McpResultKind


@dataclass
class Operation:
    mcp_server: str
    api_endpoint: str = "unknown"
    server_operation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: float = field(default_factory=time.monotonic)
    handler_entered: bool = False
    tenant_id: str = ""
    tenant_name: str = ""
    http_attempt_count: int = 0
    retry_count: int = 0
    auth_refresh_count: int = 0
    retry_exhausted: bool = False
    http_status: int | None = None
    failure_http_status: int | None = None
    write_state: Literal["confirmed"] | None = None
    error_code: str = ""
    error_category: str = ""
    usage: ApiCallUsage = field(default_factory=dict)

    def complete(self, result_kind: McpResultKind) -> None:
        try:
            import adk_telemetry

            if not adk_telemetry.telemetry_enabled():
                return
            adk_telemetry.emit_api_call(
                api_endpoint=self.api_endpoint,
                outcome="success" if result_kind == "success" else "failure",
                latency_ms=int((time.monotonic() - self.started_at) * 1000),
                error_code=self.error_code,
                error_category=self.error_category,
                error_message="",
                tenant_id=self.tenant_id,
                tenant_name=self.tenant_name,
                mcp_server=self.mcp_server,
                server_operation_id=self.server_operation_id,
                result_kind=result_kind,
                http_attempt_count=self.http_attempt_count,
                retry_count=self.retry_count,
                auth_refresh_count=self.auth_refresh_count,
                retry_exhausted=self.retry_exhausted,
                http_status=self.http_status,
                failure_http_status=self.failure_http_status,
                write_state=self.write_state,
                usage=self.usage or None,
            )
        except Exception:
            # Telemetry availability must not change the tool's result or exception.
            pass


current_operation: ContextVar[Operation | None] = ContextVar("adk_operation", default=None)


def handler_entered() -> None:
    if operation := current_operation.get():
        operation.handler_entered = True


def capture_tenant(tenant_id: str, *, local_dir: str) -> None:
    if operation := current_operation.get():
        operation.tenant_id = ""
        operation.tenant_name = ""
        try:
            import adk_telemetry

            identity = adk_telemetry.get_tenant_identity(tenant_id, local_dir=local_dir)
            operation.tenant_id = identity["tenant_id"]
            operation.tenant_name = identity["tenant_name"]
        except Exception:
            pass


def annotate_usage(**fields: Unpack[ApiCallUsage]) -> None:
    if operation := current_operation.get():
        operation.usage.update(fields)


def confirm_write() -> None:
    if operation := current_operation.get():
        operation.write_state = "confirmed"


def http_attempt(*, retry: bool) -> None:
    if operation := current_operation.get():
        operation.http_attempt_count += 1
        operation.retry_count += int(retry)
        operation.http_status = None


def http_response(status: int) -> None:
    if operation := current_operation.get():
        operation.http_status = status
        if status >= 400:
            operation.failure_http_status = status


def auth_refresh() -> None:
    if operation := current_operation.get():
        operation.auth_refresh_count += 1


def retries_exhausted() -> None:
    if operation := current_operation.get():
        operation.retry_exhausted = True
