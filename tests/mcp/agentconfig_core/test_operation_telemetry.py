# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Offline native-MCP boundary and HTTP accounting regressions."""

from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import sys
import threading
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from mcp import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.memory import create_client_server_memory_streams
from mcp.types import CallToolResult

CORE_DIR = (
    Path(__file__).parents[3] / "solutions" / "ess-maker-skills" / "src" / "mcp"
    / "agentconfig_core"
)
sys.path.insert(0, str(CORE_DIR))

import adk_telemetry as adk  # noqa: E402
import base_client  # noqa: E402
from mcp_observability import ObservedFastMCP, register_client_events_bridge  # noqa: E402
import operation_telemetry as ot  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore:Field 'lifespan'.*")
TENANT = "00000000-0000-0000-0000-000000001111"
OTHER_TENANT = "00000000-0000-0000-0000-000000002222"
SENSITIVE = "QuarterlyPayrollReview"


@pytest.fixture
def records(monkeypatch):
    rows = []
    monkeypatch.setattr(adk, "telemetry_enabled", lambda: True)
    monkeypatch.setattr(adk, "emit_api_call", lambda **fields: rows.append(fields))
    monkeypatch.setattr(
        adk, "get_tenant_identity",
        lambda tenant_id, **kwargs: {"tenant_id": tenant_id, "tenant_name": ""},
    )
    return rows


@pytest.mark.parametrize(
    ("scenario", "kind"),
    [
        ("success", "success"), ("returned_error", "tool_error"),
        ("thrown", "exception"), ("invalid_arguments", "invalid_arguments"),
        ("conversion", "exception"), ("unknown", "unknown_tool"),
        ("cancelled", "cancelled"),
    ],
)
def test_native_boundary_emits_once_and_preserves_results(records, scenario, kind):
    server = ObservedFastMCP("test-server")
    original = RuntimeError(SENSITIVE)
    cancelled = asyncio.CancelledError(SENSITIVE)
    error_result = CallToolResult(content=[], isError=True)

    @server.tool()
    async def business(value: int) -> int:
        ot.handler_entered()
        if scenario == "thrown":
            raise original
        if scenario == "cancelled":
            raise cancelled
        if scenario == "conversion":
            return SENSITIVE
        return value

    @server.tool()
    async def returned_error() -> CallToolResult:
        ot.handler_entered()
        return error_result

    async def run():
        name = SENSITIVE if scenario == "unknown" else (
            "returned_error" if scenario == "returned_error" else "business"
        )
        args = {"value": SENSITIVE if scenario == "invalid_arguments" else 7}
        if scenario == "cancelled":
            with pytest.raises(asyncio.CancelledError) as caught:
                await server.call_tool(name, args)
            assert caught.value is cancelled
        elif scenario in {"thrown", "conversion", "unknown", "invalid_arguments"}:
            with pytest.raises(ToolError) as caught:
                await server.call_tool(name, args)
            if scenario == "thrown":
                assert caught.value.__cause__ is original
        else:
            result = await server.call_tool(name, args)
            if scenario == "returned_error":
                assert result is error_result
            else:
                assert result == await FastMCP.call_tool(server, name, args)
        assert ot.current_operation.get() is None

    asyncio.run(run())
    assert len(records) == 1
    row = records[0]
    assert row["result_kind"] == kind
    assert row["api_endpoint"] == (
        "unknown" if scenario == "unknown" else
        "returned_error" if scenario == "returned_error" else "business"
    )
    assert row["outcome"] == ("success" if kind == "success" else "failure")
    assert row["error_message"] == ""
    assert row["mcp_server"] == "test-server"
    assert row["latency_ms"] >= 0
    assert row["tenant_id"] == row["tenant_name"] == ""
    assert str(UUID(row["server_operation_id"])) == row["server_operation_id"]
    assert SENSITIVE not in json.dumps(row)


def test_concurrent_calls_isolate_identity_usage_and_counters(records):
    server = ObservedFastMCP("test-server")
    ready = asyncio.Event()
    arrivals = 0

    @server.tool()
    async def business(tenant: str, count: int) -> str:
        nonlocal arrivals
        ot.handler_entered()
        ot.capture_tenant(tenant, local_dir=str(CORE_DIR))
        ot.annotate_usage(discovery_result_count=count)
        for _ in range(count):
            ot.http_attempt(retry=False)
        arrivals += 1
        if arrivals == 2:
            ready.set()
        await ready.wait()
        return "ok"

    async def run():
        await asyncio.gather(
            server.call_tool("business", {"tenant": TENANT, "count": 1}),
            server.call_tool("business", {"tenant": OTHER_TENANT, "count": 2}),
        )
        assert ot.current_operation.get() is None

    asyncio.run(run())
    by_tenant = {row["tenant_id"]: row for row in records}
    assert set(by_tenant) == {TENANT, OTHER_TENANT}
    for tenant, count in [(TENANT, 1), (OTHER_TENANT, 2)]:
        assert by_tenant[tenant]["http_attempt_count"] == count
        assert by_tenant[tenant]["usage"] == {"discovery_result_count": count}
    assert len({row["server_operation_id"] for row in records}) == 2


def test_telemetry_failure_never_masks_tool_result_or_cancellation(monkeypatch, records):
    def unavailable(**kwargs):
        raise OSError(SENSITIVE)

    monkeypatch.setattr(adk, "emit_api_call", unavailable)
    server = ObservedFastMCP("test-server")

    @server.tool()
    async def business(cancel: bool) -> str:
        ot.handler_entered()
        if cancel:
            raise asyncio.CancelledError()
        return "ok"

    async def run():
        await server.call_tool("business", {"cancel": False})
        with pytest.raises(asyncio.CancelledError):
            await server.call_tool("business", {"cancel": True})
        assert ot.current_operation.get() is None

    asyncio.run(run())


def test_opt_out_skips_event_construction(monkeypatch, records):
    monkeypatch.setattr(adk, "telemetry_enabled", lambda: False)
    ot.Operation("test-server").complete("success")
    assert records == []


def test_bridge_registration_is_opt_in_exempt_and_contract_shaped(records, monkeypatch):
    observed = ObservedFastMCP("widget-server")
    other = ObservedFastMCP("other-server")
    register_client_events_bridge(observed)
    calls = []

    def report(envelope):
        calls.append(envelope)
        return {"status": "rejected", "acceptedEventCount": 0, "rejectedReason": "invalid_schema"}

    monkeypatch.setattr(adk, "report_client_events", report)

    async def run():
        tools = {tool.name: tool for tool in await observed.list_tools()}
        bridge = tools["report_client_events"]
        assert bridge.meta == {"ui": {"visibility": ["app"]}}
        assert bridge.annotations.model_dump(exclude_none=True) == {
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": False, "openWorldHint": False,
        }
        assert set(bridge.inputSchema["properties"]) == {
            "schemaVersion", "batchId", "mountId", "appName", "buildEnvironment",
            "buildNumber", "platform", "userAgent", "events", "toolCallId",
        }
        result = await observed.call_tool("report_client_events", {"schemaVersion": []})
        assert result.isError
        assert result.structuredContent["status"] == "rejected"
        assert await other.list_tools() == []

    asyncio.run(run())
    assert calls[0]["schemaVersion"] == []
    assert records == []


def _client(monkeypatch, handler):
    payload = base64.urlsafe_b64encode(json.dumps({"tid": TENANT}).encode()).decode()
    monkeypatch.setattr(base_client, "_resolve_token", lambda: f"header.{payload}.signature")
    monkeypatch.delenv("AGENTCONFIG_ACCESS_TOKEN_FILE", raising=False)
    return base_client.AgentConfigBaseClient(
        base_url="https://example.test", logger_name="test",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize(
    ("statuses", "idempotent", "attempts", "retries", "exhausted", "exception_status"),
    [
        ([200], True, 1, 0, False, None),
        ([503, 200], True, 2, 1, False, None),
        ([429, 200], False, 2, 1, False, None),
        ([503], False, 1, 0, False, 503),
        ([503, 503, 503], True, 3, 2, True, None),
        ([400], True, 1, 0, False, 400),
    ],
)
def test_actual_http_attempts_and_existing_exception_metadata(
    monkeypatch, records, statuses, idempotent, attempts, retries, exhausted,
    exception_status,
):
    responses = iter(statuses)
    client = _client(
        monkeypatch,
        lambda request: httpx.Response(
            next(responses), json={"Code": SENSITIVE, "Message": SENSITIVE},
        ),
    )

    async def no_sleep(delay):
        return None

    monkeypatch.setattr(base_client.asyncio, "sleep", no_sleep)
    server = ObservedFastMCP("test-server")

    @server.tool()
    async def business() -> str:
        ot.handler_entered()
        await client._request("POST", "/customer-route", idempotent=idempotent)
        return "ok"

    async def run():
        try:
            if statuses[-1] >= 400:
                with pytest.raises(ToolError) as caught:
                    await server.call_tool("business", {})
                assert isinstance(caught.value.__cause__, base_client.AgentConfigApiError)
                assert caught.value.__cause__.http_status == exception_status
            else:
                await server.call_tool("business", {})
        finally:
            await client.aclose()

    asyncio.run(run())
    row, = records
    assert row["http_attempt_count"] == attempts
    assert row["retry_count"] == retries
    assert row["retry_exhausted"] is exhausted
    assert row["http_status"] == statuses[-1]
    assert row["failure_http_status"] == next(
        (status for status in reversed(statuses) if status >= 400), None,
    )
    assert row["auth_refresh_count"] == 0
    assert SENSITIVE not in json.dumps(row)
    assert "customer-route" not in json.dumps(row)


@pytest.mark.parametrize("idempotent", [True, False])
def test_network_retries_keep_nonidempotent_policy(monkeypatch, records, idempotent):
    def fail(request):
        raise httpx.ConnectError(SENSITIVE, request=request)

    client = _client(monkeypatch, fail)

    async def no_sleep(delay):
        pass

    monkeypatch.setattr(base_client.asyncio, "sleep", no_sleep)
    operation = ot.Operation("test-server")

    async def run():
        token = ot.current_operation.set(operation)
        try:
            with pytest.raises(httpx.ConnectError):
                await client._request("POST", "/resource", idempotent=idempotent)
        finally:
            ot.current_operation.reset(token)
            await client.aclose()

    asyncio.run(run())
    assert operation.http_attempt_count == (3 if idempotent else 1)
    assert operation.retry_count == (2 if idempotent else 0)
    assert operation.retry_exhausted is idempotent
    assert operation.http_status is None
    assert records == []


def test_concurrent_401_refresh_counts_actual_singleflight_once(monkeypatch, records):
    ready = asyncio.Event()
    arrivals = 0

    async def handler(request):
        nonlocal arrivals
        if request.headers["Authorization"] != "Bearer replacement":
            arrivals += 1
            if arrivals == 2:
                ready.set()
            await ready.wait()
            return httpx.Response(401)
        return httpx.Response(200, json={})

    client = _client(monkeypatch, handler)
    refresh_calls = []

    def refresh():
        refresh_calls.append(threading.get_ident())
        return "replacement"

    monkeypatch.setattr(client, "_acquire_replacement_token", refresh)
    server = ObservedFastMCP("test-server")

    @server.tool()
    async def business() -> str:
        ot.handler_entered()
        await client._request("POST", "/resource", idempotent=False)
        return "ok"

    async def run():
        try:
            await asyncio.gather(
                server.call_tool("business", {}), server.call_tool("business", {}),
            )
        finally:
            await client.aclose()

    asyncio.run(run())
    assert len(refresh_calls) == 1
    assert sum(row["auth_refresh_count"] for row in records) == 1
    assert len(records) == 2
    for row in records:
        assert row["http_attempt_count"] == 2
        assert row["retry_count"] == 1
        assert row["http_status"] == 200
        assert row["failure_http_status"] == 401


def test_unobserved_http_is_noop_and_core_import_needs_no_mcp(monkeypatch, records):
    client = _client(monkeypatch, lambda request: httpx.Response(200, json={}))

    async def run():
        try:
            await client._request("GET", "/resource")
        finally:
            await client.aclose()

    asyncio.run(run())
    assert ot.current_operation.get() is None
    assert records == []
    result = subprocess.run(
        [
            sys.executable, "-c",
            "import sys; sys.modules['mcp'] = None; sys.modules['adk_telemetry'] = None; "
            f"sys.path.insert(0, {str(CORE_DIR)!r}); import base_client; "
            "assert 'mcp.server.fastmcp' not in sys.modules",
        ],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_native_protocol_dispatch_uses_observed_public_boundary(records):
    server = ObservedFastMCP("test-server")

    @server.tool()
    async def business(value: int) -> int:
        ot.handler_entered()
        return value

    async def run():
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            task = asyncio.create_task(server._mcp_server.run(
                *server_streams, server._mcp_server.create_initialization_options(),
            ))
            try:
                async with ClientSession(*client_streams) as client:
                    await client.initialize()
                    result = await client.call_tool("business", {"value": 4})
                    assert not result.isError
                    invalid = await client.call_tool("business", {"value": SENSITIVE})
                    assert invalid.isError
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(run())
    assert [row["result_kind"] for row in records] == ["success", "invalid_arguments"]


def test_duration_uses_monotonic_clock(monkeypatch, records):
    operation = ot.Operation("test-server", started_at=10)
    monkeypatch.setattr(ot.time, "monotonic", lambda: 10.125)
    operation.complete("success")
    assert records[0]["latency_ms"] == 125


def test_registry_observation_failure_does_not_break_native_invocation(monkeypatch, records):
    server = ObservedFastMCP("test-server")

    @server.tool()
    async def business() -> str:
        ot.handler_entered()
        return "ok"

    async def unavailable():
        raise RuntimeError(SENSITIVE)

    monkeypatch.setattr(server, "list_tools", unavailable)
    asyncio.run(server.call_tool("business", {}))
    assert records[0]["api_endpoint"] == "unknown"
    assert records[0]["result_kind"] == "success"
    assert SENSITIVE not in json.dumps(records)


def test_failed_identity_snapshot_clears_previous_attribution(monkeypatch, records):
    operation = ot.Operation("test-server", tenant_id=TENANT, tenant_name="Contoso")

    def unavailable(*args, **kwargs):
        raise OSError(SENSITIVE)

    monkeypatch.setattr(adk, "get_tenant_identity", unavailable)
    token = ot.current_operation.set(operation)
    try:
        ot.capture_tenant(OTHER_TENANT, local_dir=str(CORE_DIR))
    finally:
        ot.current_operation.reset(token)
    assert operation.tenant_id == operation.tenant_name == ""


def test_failed_refresh_counts_once_without_replay(monkeypatch, records):
    client = _client(monkeypatch, lambda request: httpx.Response(401))

    def unavailable():
        raise base_client.AgentConfigApiError(SENSITIVE, http_status=401)

    monkeypatch.setattr(client, "_acquire_replacement_token", unavailable)
    operation = ot.Operation("test-server")

    async def run():
        token = ot.current_operation.set(operation)
        try:
            with pytest.raises(base_client.AgentConfigApiError) as caught:
                await client._request("POST", "/resource", idempotent=False)
            assert caught.value.http_status == 401
        finally:
            ot.current_operation.reset(token)
            await client.aclose()

    asyncio.run(run())
    assert operation.http_attempt_count == operation.auth_refresh_count == 1
    assert operation.retry_count == 0
    assert not operation.retry_exhausted
    assert operation.http_status == operation.failure_http_status == 401


def test_final_network_failure_does_not_reuse_prior_http_status(monkeypatch, records):
    attempts = 0

    def handler(request):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503)
        raise httpx.ReadTimeout(SENSITIVE, request=request)

    client = _client(monkeypatch, handler)

    async def no_sleep(delay):
        pass

    monkeypatch.setattr(base_client.asyncio, "sleep", no_sleep)
    operation = ot.Operation("test-server")

    async def run():
        token = ot.current_operation.set(operation)
        try:
            with pytest.raises(httpx.ReadTimeout):
                await client._request("GET", "/resource")
        finally:
            ot.current_operation.reset(token)
            await client.aclose()

    asyncio.run(run())
    assert operation.http_attempt_count == 3
    assert operation.retry_count == 2
    assert operation.retry_exhausted
    assert operation.http_status is None
    assert operation.failure_http_status == 503
