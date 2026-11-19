# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for Workday lifecycle projection into the shared ADK SDK."""

from __future__ import annotations


def test_workday_projection_uses_only_safe_bounded_event_fields(monkeypatch):
    import adk_telemetry
    import workday_connect_telemetry

    observed = {}

    def capture(event, **dimensions):
        observed["event"] = event
        observed.update(dimensions)

    monkeypatch.setattr(adk_telemetry, "emit_connect_lifecycle", capture)
    state = {
        "scope": {"agent": {"botId": "bot-id", "name": "Do not emit"}},
        "lifecycle": {
            "correlationId": "6f7c8f9c-1234-4abc-9def-0123456789ab",
        },
    }
    event = {
        "event": "blocked",
        "phase": "runtime",
        "outcome": "blocked",
        "durationMs": 200,
        "retryCount": 1,
        "resumeCount": 2,
        "blockerCategory": "runtime",
        "remediationId": "WD-E2E-003",
        "correlationId": "9c7f8f9c-1234-4abc-9def-0123456789ab",
        "message": "https://customer.example/secret",
    }

    workday_connect_telemetry.emit_lifecycle_event(state, event)

    assert observed == {
        "event": "blocked",
        "connector": "workday",
        "phase": "runtime",
        "outcome": "blocked",
        "duration_ms": 200,
        "retry_count": 1,
        "resume_count": 2,
        "blocker_category": "runtime",
        "remediation_id": "WD-E2E-003",
        "correlation_id": "9c7f8f9c-1234-4abc-9def-0123456789ab",
        "agent_id": "",
    }


def test_workday_projection_forwards_only_canonical_current_agent_id(
    monkeypatch,
):
    import adk_telemetry
    import workday_connect_telemetry

    observed = []
    monkeypatch.setattr(
        adk_telemetry,
        "emit_connect_lifecycle",
        lambda event, **dimensions: observed.append((event, dimensions)),
    )
    correlation_id = "6f7c8f9c-1234-4abc-9def-0123456789ab"
    event = {"event": "invoked", "correlationId": correlation_id}

    workday_connect_telemetry.emit_lifecycle_event(
        {
            "scope": {"agent": {"botId": "owner@customer.example"}},
            "lifecycle": {"correlationId": correlation_id},
        },
        event,
    )
    workday_connect_telemetry.emit_lifecycle_event(
        {
            "scope": {
                "agent": {
                    "botId": "7f7c8f9c-1234-4abc-9def-0123456789ab",
                }
            },
            "lifecycle": {"correlationId": correlation_id},
        },
        event,
    )

    assert observed[0][1]["agent_id"] == "owner@customer.example"
    assert (
        observed[1][1]["agent_id"]
        == "7f7c8f9c-1234-4abc-9def-0123456789ab"
    )


def test_projection_and_flush_are_fail_open(monkeypatch):
    import adk_telemetry
    import workday_connect_telemetry

    monkeypatch.setattr(
        adk_telemetry,
        "emit_connect_lifecycle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("collector unavailable")
        ),
    )
    monkeypatch.setattr(
        adk_telemetry,
        "flush",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("collector unavailable")
        ),
    )

    workday_connect_telemetry.emit_lifecycle_event(
        {"scope": {}, "lifecycle": {}},
        {"event": "invoked"},
    )
    workday_connect_telemetry.flush_lifecycle_telemetry()
