# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Opt-in request-local measurements; importing the HTTP core needs no MCP SDK."""

from __future__ import annotations

import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Unpack

if TYPE_CHECKING:
    from adk_telemetry import ApiCallUsage, HttpRequestOutcome, McpResultKind


CORRELATION_ID = "com.microsoft.ess/correlation-id"
CLIENT_REQUEST_ID = "com.microsoft.ess/client-request-id"
SERVER_OPERATION_ID = "com.microsoft.ess/server-operation-id"


def valid_correlation_id(value: object) -> str | None:
    """Keep only canonical hyphenated UUIDs, never arbitrary request metadata."""
    if not isinstance(value, str) or len(value) != 36:
        return None
    try:
        return value if str(uuid.UUID(value)) == value.lower() else None
    except ValueError:
        return None


@dataclass
class Operation:
    mcp_server: str
    api_endpoint: str = "unknown"
    server_operation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = ""
    client_request_id: str | None = None
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

    def __post_init__(self) -> None:
        self.correlation_id = self.correlation_id or self.server_operation_id

    def complete_http_request(
        self,
        *,
        http_request_id: str,
        http_attempt_number: int,
        http_method: str,
        outcome: HttpRequestOutcome,
        latency_ms: int,
        http_status: int | None,
    ) -> None:
        try:
            import adk_telemetry

            if not adk_telemetry.telemetry_enabled():
                return
            adk_telemetry.emit_http_request(
                mcp_server=self.mcp_server,
                api_endpoint=self.api_endpoint,
                correlation_id=self.correlation_id,
                client_request_id=self.client_request_id,
                server_operation_id=self.server_operation_id,
                http_request_id=http_request_id,
                http_attempt_number=http_attempt_number,
                http_method=http_method,
                outcome=outcome,
                latency_ms=latency_ms,
                http_status=http_status,
                tenant_id=self.tenant_id,
                tenant_name=self.tenant_name,
            )
        except Exception:
            # Collector failures must not mask a response or the original exception.
            pass

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
                correlation_id=self.correlation_id,
                client_request_id=self.client_request_id,
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


def result_metadata(meta: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Merge correlation into widget results without changing unobserved results."""
    operation = current_operation.get()
    if operation is None:
        return meta
    merged = dict(meta or {})
    merged[CORRELATION_ID] = operation.correlation_id
    merged[SERVER_OPERATION_ID] = operation.server_operation_id
    if operation.client_request_id is not None:
        merged[CLIENT_REQUEST_ID] = operation.client_request_id
    return merged


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
