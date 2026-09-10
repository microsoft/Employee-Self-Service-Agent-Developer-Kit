# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.filterwarnings("ignore:Field 'lifespan'.*")

_MCP_ROOT = (
    Path(__file__).resolve().parents[1]
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "mcp"
)


def _load_server(folder: str, alias: str):
    """Import one of the kit's MCP servers by folder name.

    Each server does a sibling-relative ``sys.path.insert`` for ``client`` /
    ``auth``, so its own directory has to be importable while it executes.
    """
    server_path = _MCP_ROOT / folder / "server.py"
    sys.path.insert(0, str(_MCP_ROOT / folder))
    try:
        spec = importlib.util.spec_from_file_location(alias, server_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def _load_adk_server():
    """Load the landing-page server that hosts widgets and their telemetry bridge."""
    return _load_server("agentconfig_landing_page", "landing_page_mcp_server_under_test")


def test_bridge_is_colocated_with_the_widget_resources():
    """The bridge must live on whichever server serves the widgets.

    MCP Apps routes a widget's tool calls through its originating connection.
    Resource and tool registration must therefore agree on the server.
    """
    agentconfig = _load_server("agentconfig_landing_page", "landing_page_colocation_check")
    adk = _load_server("adk", "adk_colocation_check")

    def has_widgets(mod) -> bool:
        return any(
            str(getattr(t, "uri", "")).startswith("ui://widget/")
            for t in mod.mcp._resource_manager._resources.values()
        )

    def has_bridge(mod) -> bool:
        return "report_client_events" in mod.mcp._tool_manager._tools

    # The server with widgets has the bridge; the one without must not.
    assert has_widgets(agentconfig) and has_bridge(agentconfig)
    assert not has_widgets(adk) and not has_bridge(adk)


def test_report_client_events_tool_is_app_only():
    server = _load_adk_server()

    tool = server.mcp._tool_manager._tools["report_client_events"]

    # App-only visibility keeps the bridge out of model-visible tool discovery.
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
        ({"schemaVersion": "2"}, "unsupported_schema_version"),
        ({"buildNumber": None}, "invalid_event_shape"),
        ({"events": None}, "empty_batch"),
    ],
)
def test_malformed_envelopes_return_a_structured_rejection(mutation, expected_reason):
    """Malformed envelopes receive an explicit structured rejection.

    Exercise FastMCP argument validation through ``call_tool``. Vorpal requires
    a ``status`` in the result to classify permanent validation failures and
    avoid retrying them.
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


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        ("error", "error"),
        ("", ""),
        ("error synthetic@example.test", "error <email>"),
        ("x" * 201, "x" * 200),
        (None, None),
        ({"owner": "synthetic@example.test"}, None),
        (["synthetic@example.test"], None),
        ({}, None),
        ([], None),
        (0, None),
        (1.5, None),
        (True, None),
        (False, None),
    ],
)
def test_client_level_is_string_only_without_losing_events(monkeypatch, level, expected):
    server = _load_adk_server()
    emitted = []
    monkeypatch.setattr(server.adk_telemetry, "get_session", lambda surface: ("test", False))
    monkeypatch.setattr(
        server.adk_telemetry, "common_dimensions", lambda *args, **kwargs: {}
    )
    monkeypatch.setattr(
        server.adk_telemetry,
        "_emit_many",
        lambda event_name, rows, **kwargs: emitted.extend(rows),
    )
    args = {
        **_valid_tool_args(),
        "events": [
            {"eventName": "WithLevel", "timeSinceAppStart": 1, "level": level},
            {"eventName": "WithoutLevel", "timeSinceAppStart": 2},
        ],
    }

    result = asyncio.run(server.mcp.call_tool("report_client_events", args))

    assert result.structuredContent == {"status": "accepted", "acceptedEventCount": 2}
    assert result.isError is False
    assert [row["client_event_name"] for row in emitted] == ["WithLevel", "WithoutLevel"]
    if expected is None:
        assert "client_level" not in emitted[0]
    else:
        assert emitted[0]["client_level"] == expected
    assert "client_level" not in emitted[1]


def test_unknown_event_field_survives_the_real_call_tool_path():
    """Optional event fields survive FastMCP argument validation.

    ``events`` is typed ``Any``, so nested keys reach the bridge unchanged.
    The real ``call_tool`` path must accept additive event fields to keep
    producer releases independent of ADK.
    """
    server = _load_adk_server()
    args = {
        **_valid_tool_args(),
        "events": [{"eventName": "WidgetReady", "timeSinceAppStart": 1, "someFutureField": "x"}],
    }

    result = asyncio.run(server.mcp.call_tool("report_client_events", args))

    assert result.structuredContent == {"status": "accepted", "acceptedEventCount": 1}
    assert result.isError is False


def test_bridge_is_total_so_the_wrapper_needs_no_guard(monkeypatch):
    """An internal SDK fault still produces a complete tool verdict.

    Fault the dimension builder to exercise the SDK's exception handling
    through the wrapper. The accepted verdict must account for the full batch.
    """
    server = _load_adk_server()

    def _boom(*_args, **_kwargs):
        raise OSError("state dir gone")

    monkeypatch.setattr(server.adk_telemetry, "common_dimensions", _boom)

    args = {
        **_valid_tool_args(),
        "events": [{"eventName": "E", "timeSinceAppStart": 1} for _ in range(20)],
    }
    result = asyncio.run(server.report_client_events(**args))

    assert result.structuredContent == {"status": "accepted", "acceptedEventCount": 20}
    assert result.isError is False
