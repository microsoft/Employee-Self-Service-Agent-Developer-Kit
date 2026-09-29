# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Best-effort ADK telemetry projection for Workday lifecycle events."""

from __future__ import annotations

from typing import Any, Mapping


def emit_lifecycle_event(
    state: Mapping[str, Any],
    event: Mapping[str, Any],
) -> None:
    try:
        import adk_telemetry

        scope = state.get("scope") or {}
        agent = scope.get("agent") or {}
        lifecycle = state.get("lifecycle") or {}
        event_correlation = str(event.get("correlationId") or "")
        current_correlation = str(lifecycle.get("correlationId") or "")
        adk_telemetry.emit_connect_lifecycle(
            str(event.get("event") or ""),
            connector="workday",
            phase=str(event.get("phase") or ""),
            outcome=str(event.get("outcome") or ""),
            duration_ms=int(event.get("durationMs") or 0),
            retry_count=int(event.get("retryCount") or 0),
            resume_count=int(event.get("resumeCount") or 0),
            blocker_category=str(event.get("blockerCategory") or ""),
            correlation_id=str(
                event_correlation
                or current_correlation
                or ""
            ),
            agent_id=(
                str(agent.get("botId") or "")
                if not event_correlation
                or event_correlation == current_correlation
                else ""
            ),
        )
    except Exception:  # noqa: BLE001 - telemetry cannot break /connect
        return


def flush_lifecycle_telemetry(timeout: float = 5.0) -> None:
    try:
        import adk_telemetry

        adk_telemetry.flush(timeout=timeout)
    except Exception:  # noqa: BLE001 - telemetry cannot break /connect
        return
