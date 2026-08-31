# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest


pytestmark = pytest.mark.filterwarnings("ignore:Field 'lifespan'.*")


def _load_adk_server():
    server_path = (
        Path(__file__).resolve().parents[1]
        / "solutions"
        / "ess-maker-skills"
        / "src"
        / "mcp"
        / "adk"
        / "server.py"
    )
    spec = importlib.util.spec_from_file_location("adk_mcp_server_under_test", server_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_report_client_events_tool_is_app_only():
    server = _load_adk_server()

    tool = server.mcp._tool_manager._tools["report_client_events"]

    assert tool.meta == {"ui": {"visibility": ["app"]}}
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.idempotentHint is False
    assert tool.annotations.openWorldHint is False


def test_report_client_events_tool_returns_structured_bridge_result(monkeypatch):
    server = _load_adk_server()
    captured = {}

    def _fake_report_client_events(envelope):
        captured["envelope"] = envelope
        return {"status": "accepted", "acceptedEventCount": len(envelope["events"])}

    monkeypatch.setattr(server.adk_telemetry, "report_client_events", _fake_report_client_events)

    result = asyncio.run(
        server.report_client_events(
            schemaVersion=1,
            correlationId="corr-test",
            mountId="mount-test",
            appName="AgentIcon",
            buildEnvironment="dev",
            buildNumber="0",
            toolCallId="tool-test",
            events=[{"eventName": "WidgetReady", "timeSinceAppStart": 1}],
        )
    )

    assert captured["envelope"] == {
        "schemaVersion": 1,
        "correlationId": "corr-test",
        "mountId": "mount-test",
        "appName": "AgentIcon",
        "buildEnvironment": "dev",
        "buildNumber": "0",
        "toolCallId": "tool-test",
        "events": [{"eventName": "WidgetReady", "timeSinceAppStart": 1}],
    }
    assert result.structuredContent == {"status": "accepted", "acceptedEventCount": 1}
    assert result.isError is False


def test_report_client_events_tool_marks_rejection_as_error(monkeypatch):
    server = _load_adk_server()

    monkeypatch.setattr(
        server.adk_telemetry,
        "report_client_events",
        lambda envelope: {
            "status": "rejected",
            "acceptedEventCount": 0,
            "rejectedReason": "invalid_event_shape",
        },
    )

    result = asyncio.run(
        server.report_client_events(
            schemaVersion=1,
            correlationId="corr-test",
            mountId="mount-test",
            appName="AgentIcon",
            buildEnvironment="dev",
            buildNumber="0",
            events=[],
        )
    )

    assert result.structuredContent == {
        "status": "rejected",
        "acceptedEventCount": 0,
        "rejectedReason": "invalid_event_shape",
    }
    assert result.isError is True


def _valid_tool_args():
    return {
        "schemaVersion": 1,
        "correlationId": "corr-test",
        "mountId": "mount-test",
        "appName": "AgentIcon",
        "buildEnvironment": "dev",
        "buildNumber": "0",
        "events": [{"eventName": "WidgetReady", "timeSinceAppStart": 1}],
    }


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        ({"events": [1, 2]}, "invalid_event_shape"),
        ({"correlationId": 123}, "invalid_correlation_id"),
        ({"mountId": 123}, "invalid_mount_id"),
        ({"toolCallId": 123}, "invalid_tool_call_id"),
        ({"schemaVersion": "2"}, "unsupported_schema_version"),
        ({"buildNumber": None}, "invalid_event_shape"),
        ({"events": None}, "empty_batch"),
    ],
)
def test_malformed_envelopes_return_a_structured_rejection(mutation, expected_reason):
    """A malformed envelope must never surface as a bare tool error.

    FastMCP validates the tool signature with Pydantic BEFORE the body runs, so
    a narrowly-typed signature turns an out-of-contract envelope into a
    ToolError with no ``structuredContent``. Vorpal reads a result without a
    ``status`` as a transient ``invalid_result`` and MAY RETRY it — and since
    the envelope is permanently malformed, it would retry forever. Going
    through the real ``call_tool`` path is the point of this test: calling the
    function directly would bypass the Pydantic layer that caused the bug.
    """
    server = _load_adk_server()
    args = {**_valid_tool_args(), **mutation}

    result = asyncio.run(server.mcp.call_tool("report_client_events", args))

    assert result.structuredContent == {
        "status": "rejected",
        "acceptedEventCount": 0,
        "rejectedReason": expected_reason,
    }


def test_valid_envelope_is_accepted_through_the_real_call_tool_path():
    server = _load_adk_server()

    result = asyncio.run(server.mcp.call_tool("report_client_events", _valid_tool_args()))

    # The autouse conftest guard opts telemetry out, so nothing is transmitted —
    # but the batch is still acknowledged in full, because a count that doesn't
    # account for every sent event makes Vorpal retry the batch.
    assert result.structuredContent == {"status": "accepted", "acceptedEventCount": 1}
    assert result.isError is False


def test_tool_fails_open_when_the_telemetry_bridge_raises(monkeypatch):
    server = _load_adk_server()

    def _boom(envelope):
        raise OSError("state dir gone")

    monkeypatch.setattr(server.adk_telemetry, "report_client_events", _boom)

    result = asyncio.run(
        server.report_client_events(**_valid_tool_args())
    )

    assert result.structuredContent == {"status": "accepted", "acceptedEventCount": 1}
    assert result.isError is False


def test_tool_fail_open_echo_is_bounded_by_the_batch_cap(monkeypatch):
    """The wrapper's own fail-open echo must be clamped too.

    `_meta.ui.visibility: ["app"]` is advisory, so if a host does not filter
    this tool from the model-visible list, a misbehaving caller could hand over
    an arbitrarily large `events` list. Nothing is emitted on this path, but an
    unclamped count would still report every one of them as accepted.
    """
    server = _load_adk_server()

    def _boom(envelope):
        raise OSError("state dir gone")

    monkeypatch.setattr(server.adk_telemetry, "report_client_events", _boom)

    args = {
        **_valid_tool_args(),
        "events": [{"eventName": "E", "timeSinceAppStart": 1} for _ in range(100_000)],
    }
    result = asyncio.run(server.report_client_events(**args))

    assert result.structuredContent == {
        "status": "accepted",
        "acceptedEventCount": server.adk_telemetry.CLIENT_EVENTS_MAX_BATCH_EVENTS,
    }
    assert result.isError is False
