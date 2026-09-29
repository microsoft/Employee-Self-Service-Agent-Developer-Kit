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
        "blockerCategory": "runtime-verification",
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
        "blocker_category": "runtime-verification",
        "correlation_id": "6f7c8f9c-1234-4abc-9def-0123456789ab",
        "agent_id": "bot-id",
    }


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
