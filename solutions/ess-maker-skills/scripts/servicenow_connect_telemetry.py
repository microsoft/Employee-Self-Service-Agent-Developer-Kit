# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Best-effort ADK telemetry projection for ServiceNow lifecycle transitions."""

from __future__ import annotations

import copy
import datetime as dt
import uuid
from typing import Any, Mapping


TELEMETRY_SCHEMA_VERSION = 1
PHASE_MAP = {
    "preflight": "preflight",
    "plugin-prerequisites": "runtime",
    "entra-registration": "entra",
    "servicenow-oidc": "runtime",
    "credential": "connections",
    "topics": "runtime",
    "portal-url": "runtime",
    "agent-connection": "connections",
    "test": "employee-validation",
}
BLOCKER_CATEGORY_MAP = {
    "preflight": "state",
    "plugin-prerequisites": "permissions",
    "entra-registration": "permissions",
    "servicenow-oidc": "permissions",
    "credential": "connection",
    "topics": "state",
    "portal-url": "state",
    "agent-connection": "connection",
    "test": "validation",
}
_FAILURE_STATUSES = frozenset(
    {"Failed", "Error", "Blocked", "NotConfigured"}
)


def _utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def _parse_utc(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.UTC)


def _duration_ms(started_at: object, ended_at: str) -> int:
    started = _parse_utc(started_at)
    ended = _parse_utc(ended_at)
    if started is None or ended is None:
        return 0
    return max(0, int((ended - started).total_seconds() * 1000))


def _phase_statuses(state: Mapping[str, Any]) -> dict[str, str]:
    phases = state.get("phases")
    if not isinstance(phases, Mapping):
        return {}
    return {
        str(phase_id): str(phase.get("status") or "")
        for phase_id, phase in phases.items()
        if isinstance(phase, Mapping)
        and str(phase_id) in PHASE_MAP
        and phase.get("status") in {
            "pending",
            "in-progress",
            "done",
            "blocked",
        }
    }


def _remediation_id(
    state: Mapping[str, Any],
    phase_id: str,
    allowed_remediation_ids: frozenset[str],
) -> str:
    phases = state.get("phases")
    phase = phases.get(phase_id) if isinstance(phases, Mapping) else None
    results = (
        phase.get("checkpointResults")
        if isinstance(phase, Mapping)
        else None
    )
    if not isinstance(results, Mapping):
        return ""
    return next(
        (
            str(checkpoint)
            for checkpoint, status in sorted(results.items())
            if status in _FAILURE_STATUSES
            and str(checkpoint) in allowed_remediation_ids
        ),
        "",
    )


def _event(
    telemetry: Mapping[str, Any],
    name: str,
    *,
    phase_id: str = "",
    outcome: str = "",
    duration_ms: int = 0,
    blocker_category: str = "",
    remediation_id: str = "",
) -> dict[str, Any]:
    return {
        "event": name,
        "phase": PHASE_MAP.get(phase_id, ""),
        "outcome": outcome,
        "durationMs": max(0, int(duration_ms)),
        "retryCount": max(0, int(telemetry.get("retryCount") or 0)),
        "resumeCount": max(0, int(telemetry.get("resumeCount") or 0)),
        "blockerCategory": blocker_category,
        "remediationId": remediation_id,
        "correlationId": str(telemetry.get("correlationId") or ""),
    }


def prepare_lifecycle_projection(
    previous: Mapping[str, Any] | None,
    current: dict[str, Any],
    *,
    timestamp: str | None = None,
    new_lifecycle: bool = False,
    required_phase_ids: tuple[str, ...] | None = None,
    completion_ready_phase_ids: frozenset[str] | None = None,
    allowed_remediation_ids: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Update projection metadata and return newly persisted transition events."""
    now = timestamp or _utc_now()
    current_statuses = _phase_statuses(current)
    previous_telemetry = (
        previous.get("telemetry")
        if isinstance(previous, Mapping)
        else None
    )
    if not isinstance(previous_telemetry, Mapping):
        required = tuple(required_phase_ids or ())
        telemetry = {
            "schemaVersion": TELEMETRY_SCHEMA_VERSION,
            "correlationId": str(uuid.uuid4()),
            "startedAt": now,
            "retryCount": 0,
            "resumeCount": 0,
            "phaseDurationsMs": {},
            "phaseStartedAt": {},
            "projectedPhaseStatuses": copy.deepcopy(current_statuses),
            "completed": bool(required)
            and all(
                current_statuses.get(phase_id) == "done"
                and (
                    completion_ready_phase_ids is None
                    or phase_id in completion_ready_phase_ids
                )
                for phase_id in required
            ),
            "backfillSuppressed": not new_lifecycle,
            "updatedAt": now,
        }
        current["telemetry"] = telemetry
        return [_event(telemetry, "invoked")] if new_lifecycle else []

    telemetry = copy.deepcopy(dict(previous_telemetry))
    telemetry["schemaVersion"] = TELEMETRY_SCHEMA_VERSION
    projected = telemetry.get("projectedPhaseStatuses")
    if not isinstance(projected, dict):
        projected = {}
    active_starts = telemetry.get("phaseStartedAt")
    if not isinstance(active_starts, dict):
        active_starts = {}
    phase_durations = telemetry.get("phaseDurationsMs")
    if not isinstance(phase_durations, dict):
        phase_durations = {}
    events: list[dict[str, Any]] = []
    projection_changed = False
    for phase_id in PHASE_MAP:
        current_status = current_statuses.get(phase_id)
        previous_status = projected.get(phase_id)
        if current_status is None or current_status == previous_status:
            continue
        projection_changed = True
        if current_status == "in-progress":
            if previous_status in {"blocked", "done"}:
                if previous_status == "done":
                    phase_durations[phase_id] = 0
                telemetry["retryCount"] = int(
                    telemetry.get("retryCount") or 0
                ) + 1
                telemetry["resumeCount"] = int(
                    telemetry.get("resumeCount") or 0
                ) + 1
                active_starts[phase_id] = now
                events.append(
                    _event(telemetry, "phase-resumed", phase_id=phase_id)
                )
            else:
                phase_durations[phase_id] = 0
                active_starts[phase_id] = now
                events.append(
                    _event(telemetry, "phase-started", phase_id=phase_id)
                )
        elif current_status == "blocked":
            if previous_status not in {"in-progress", "blocked"}:
                if previous_status == "done":
                    phase_durations[phase_id] = 0
                active_starts[phase_id] = now
                events.append(
                    _event(telemetry, "phase-started", phase_id=phase_id)
                )
            duration = _duration_ms(active_starts.get(phase_id), now)
            phase_durations[phase_id] = max(
                0,
                int(phase_durations.get(phase_id) or 0),
            ) + duration
            active_starts[phase_id] = None
            events.append(
                _event(
                    telemetry,
                    "phase-paused",
                    phase_id=phase_id,
                    outcome="blocked",
                    duration_ms=duration,
                )
            )
            events.append(
                _event(
                    telemetry,
                    "blocked",
                    phase_id=phase_id,
                    outcome="blocked",
                    blocker_category=BLOCKER_CATEGORY_MAP[phase_id],
                    remediation_id=_remediation_id(
                        current,
                        phase_id,
                        allowed_remediation_ids,
                    ),
                )
            )
        elif current_status == "done":
            if previous_status == "blocked":
                telemetry["retryCount"] = int(
                    telemetry.get("retryCount") or 0
                ) + 1
                telemetry["resumeCount"] = int(
                    telemetry.get("resumeCount") or 0
                ) + 1
                active_starts[phase_id] = now
                events.append(
                    _event(telemetry, "phase-resumed", phase_id=phase_id)
                )
            elif previous_status not in {"in-progress", "done"}:
                phase_durations[phase_id] = 0
                active_starts[phase_id] = now
                events.append(
                    _event(telemetry, "phase-started", phase_id=phase_id)
                )
            duration = max(
                0,
                int(phase_durations.get(phase_id) or 0),
            ) + _duration_ms(active_starts.get(phase_id), now)
            phase_durations[phase_id] = duration
            active_starts[phase_id] = None
            events.append(
                _event(
                    telemetry,
                    "phase-completed",
                    phase_id=phase_id,
                    outcome="success",
                    duration_ms=duration,
                )
            )
        elif current_status == "pending":
            phase_durations[phase_id] = 0
            active_starts[phase_id] = None
        projected[phase_id] = current_status

    required = tuple(required_phase_ids or ())
    all_done = bool(required) and all(
        current_statuses.get(phase_id) == "done"
        and (
            completion_ready_phase_ids is None
            or phase_id in completion_ready_phase_ids
        )
        for phase_id in required
    )
    previous_completed = telemetry.get("completed") is True
    if all_done and not previous_completed:
        telemetry["completed"] = True
        projection_changed = True
        events.append(
            _event(
                telemetry,
                "completed",
                outcome="success",
                duration_ms=_duration_ms(telemetry.get("startedAt"), now),
            )
        )
    elif not all_done and previous_completed:
        telemetry["completed"] = False
        projection_changed = True
    telemetry["phaseStartedAt"] = active_starts
    telemetry["phaseDurationsMs"] = phase_durations
    telemetry["projectedPhaseStatuses"] = projected
    if projection_changed or events:
        telemetry["updatedAt"] = now
    current["telemetry"] = telemetry
    return events


def emit_lifecycle_event(
    state: Mapping[str, Any],
    event: Mapping[str, Any],
) -> None:
    """Project one already-persisted transition; never affect Connect."""
    try:
        import adk_telemetry

        adk_telemetry.emit_connect_lifecycle(
            str(event.get("event") or ""),
            connector="servicenow",
            phase=str(event.get("phase") or ""),
            outcome=str(event.get("outcome") or ""),
            duration_ms=int(event.get("durationMs") or 0),
            retry_count=int(event.get("retryCount") or 0),
            resume_count=int(event.get("resumeCount") or 0),
            blocker_category=str(event.get("blockerCategory") or ""),
            remediation_id=str(event.get("remediationId") or ""),
            correlation_id=str(event.get("correlationId") or ""),
            agent_id=str(state.get("agentId") or ""),
        )
    except Exception:  # noqa: BLE001 - telemetry cannot break /connect
        return
