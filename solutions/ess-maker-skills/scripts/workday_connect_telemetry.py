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
        current_target = not event_correlation or event_correlation == current_correlation
        phase = str(event.get("phase") or "")
        steps = ("preflight", "entra", "workday-admin", "connections", "runtime", "maker-validation")
        adk_telemetry.emit_connect_lifecycle(
            str(event.get("event") or ""),
            connector="workday",
            phase=str(event.get("phase") or ""),
            outcome=str(event.get("outcome") or ""),
            duration_ms=int(event.get("durationMs") or 0),
            retry_count=int(event.get("retryCount") or 0),
            resume_count=int(event.get("resumeCount") or 0),
            blocker_category=str(event.get("blockerCategory") or ""),
            remediation_id=str(event.get("remediationId") or ""),
            correlation_id=str(
                event_correlation
                or current_correlation
                or ""
            ),
            # Historical events must not inherit the current target's agent.
            agent_id=(
                str(agent.get("botId") or "")
                if current_target
                else ""
            ),
            environment_id=str(scope.get("environmentId") or "") if current_target else "",
            validation_realm=str(scope.get("validationRealm") or "") if current_target else "",
            target_ring=str(scope.get("ring") or "") if current_target else "",
            step_id=phase,
            step_index=steps.index(phase) + 1 if phase in steps else 0,
            step_attempt=int(event.get("stepAttempt") or 0),
            flow_version=1,
            event_sequence=int(event.get("sequence") or 0),
            event_timestamp=str(event.get("timestamp") or ""),
            journey_started_at=str(lifecycle.get("startedAt") or "") if current_target else "",
            tenant_id=str(scope.get("tenantId") or "") if current_target else "",
        )
    except Exception:  # noqa: BLE001 - telemetry cannot break /connect
        return


def flush_lifecycle_telemetry(timeout: float = 5.0) -> None:
    try:
        import adk_telemetry

        adk_telemetry.flush(timeout=timeout)
    except Exception:  # noqa: BLE001 - telemetry cannot break /connect
        return
