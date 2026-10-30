# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import servicenow_connect_telemetry as telemetry


def _state(*, profile: str = "hrsd") -> dict:
    prefix = "SN-DA-HRSD" if profile == "hrsd" else "SN-DA-ITSM"
    return {
        "agentId": "00000000-0000-4000-8000-000000002222",
        "phases": {
            "preflight": {
                "status": "pending",
                "checkpointResults": {},
            },
            "entra-registration": {
                "status": "pending",
                "checkpointResults": {},
            },
            "credential": {
                "status": "pending",
                "checkpointResults": {},
            },
            "topics": {
                "status": "pending",
                "checkpointResults": {},
            },
            "agent-connection": {
                "status": "pending",
                "checkpointResults": {},
            },
            "test": {
                "status": "pending",
                "checkpointResults": {
                    f"{prefix}-TEST-001": "NotConfigured"
                },
            },
        },
    }


def _required(state: dict) -> tuple[str, ...]:
    return tuple(state["phases"])


def _contract_state(profile: str) -> dict:
    provider = f"servicenow-da-{profile}"
    contract_path = (
        Path(__file__).resolve().parents[2]
        / "solutions"
        / "ess-maker-skills"
        / "src"
        / "skills"
        / "connect"
        / provider
        / "contract.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    return {
        "agentId": "00000000-0000-4000-8000-000000002222",
        "phases": {
            phase["id"]: {
                "status": "pending",
                "checkpointResults": {},
            }
            for phase in contract["phases"]
        },
    }


def test_new_lifecycle_records_one_invoked_event() -> None:
    state = _state()

    events = telemetry.prepare_lifecycle_projection(
        None,
        state,
        timestamp="2026-10-23T20:00:00Z",
        new_lifecycle=True,
        required_phase_ids=_required(state),
    )

    assert [event["event"] for event in events] == ["invoked"]
    assert state["telemetry"]["backfillSuppressed"] is False
    assert state["telemetry"]["projectedPhaseStatuses"]["preflight"] == (
        "pending"
    )


def test_existing_state_baselines_without_backfill() -> None:
    existing = _state()
    existing["phases"]["preflight"]["status"] = "done"
    current = copy.deepcopy(existing)

    events = telemetry.prepare_lifecycle_projection(
        existing,
        current,
        timestamp="2026-10-23T20:00:00Z",
        required_phase_ids=_required(current),
    )

    assert events == []
    assert current["telemetry"]["backfillSuppressed"] is True
    assert current["telemetry"]["projectedPhaseStatuses"]["preflight"] == (
        "done"
    )


def test_block_resume_complete_events_are_deduplicated_and_bounded() -> None:
    state = _state()
    telemetry.prepare_lifecycle_projection(
        None,
        state,
        timestamp="2026-10-23T20:00:00Z",
        new_lifecycle=True,
        required_phase_ids=_required(state),
    )
    previous = copy.deepcopy(state)
    state["phases"]["credential"]["status"] = "in-progress"
    started = telemetry.prepare_lifecycle_projection(
        previous,
        state,
        timestamp="2026-10-23T20:01:00Z",
        required_phase_ids=_required(state),
    )
    assert [(event["event"], event["phase"]) for event in started] == [
        ("phase-started", "connections")
    ]

    previous = copy.deepcopy(state)
    state["phases"]["credential"]["status"] = "blocked"
    state["phases"]["credential"]["checkpointResults"] = {
        "SN-DA-HRSD-CREDENTIAL-001": "Failed"
    }
    blocked = telemetry.prepare_lifecycle_projection(
        previous,
        state,
        timestamp="2026-10-23T20:02:00Z",
        required_phase_ids=_required(state),
        allowed_remediation_ids=frozenset(
            {"SN-DA-HRSD-CREDENTIAL-001"}
        ),
    )
    assert [event["event"] for event in blocked] == [
        "phase-paused",
        "blocked",
    ]
    assert blocked[0]["durationMs"] == 60_000
    assert blocked[1]["blockerCategory"] == "connection"
    assert blocked[1]["remediationId"] == "SN-DA-HRSD-CREDENTIAL-001"

    previous = copy.deepcopy(state)
    state["phases"]["credential"]["status"] = "in-progress"
    resumed = telemetry.prepare_lifecycle_projection(
        previous,
        state,
        timestamp="2026-10-23T20:03:00Z",
        required_phase_ids=_required(state),
    )
    assert [event["event"] for event in resumed] == ["phase-resumed"]
    assert resumed[0]["retryCount"] == 1
    assert resumed[0]["resumeCount"] == 1

    previous = copy.deepcopy(state)
    state["phases"]["credential"]["status"] = "done"
    completed = telemetry.prepare_lifecycle_projection(
        previous,
        state,
        timestamp="2026-10-23T20:04:00Z",
        required_phase_ids=_required(state),
    )
    assert [event["event"] for event in completed] == ["phase-completed"]
    assert completed[0]["durationMs"] == 120_000

    previous = copy.deepcopy(state)
    assert telemetry.prepare_lifecycle_projection(
        previous,
        state,
        required_phase_ids=_required(state),
    ) == []


def test_multiple_pause_resume_segments_accumulate_active_duration() -> None:
    state = _state()
    required = _required(state)
    telemetry.prepare_lifecycle_projection(
        None,
        state,
        timestamp="2026-10-23T20:00:00Z",
        new_lifecycle=True,
        required_phase_ids=required,
    )
    timeline = [
        ("in-progress", "2026-10-23T20:01:00Z"),
        ("blocked", "2026-10-23T20:02:00Z"),
        ("in-progress", "2026-10-23T20:03:00Z"),
        ("blocked", "2026-10-23T20:05:00Z"),
        ("in-progress", "2026-10-23T20:06:00Z"),
        ("done", "2026-10-23T20:09:00Z"),
    ]
    events: list[dict] = []
    for status, timestamp in timeline:
        previous = copy.deepcopy(state)
        state["phases"]["credential"]["status"] = status
        events.extend(
            telemetry.prepare_lifecycle_projection(
                previous,
                state,
                timestamp=timestamp,
                required_phase_ids=required,
            )
        )

    completed = next(
        event
        for event in reversed(events)
        if event["event"] == "phase-completed"
    )
    assert completed["durationMs"] == 360_000
    assert completed["retryCount"] == 2
    assert completed["resumeCount"] == 2


def test_direct_blocked_to_done_excludes_paused_wait() -> None:
    state = _state()
    required = _required(state)
    telemetry.prepare_lifecycle_projection(
        None,
        state,
        timestamp="2026-10-23T20:00:00Z",
        new_lifecycle=True,
        required_phase_ids=required,
    )
    previous = copy.deepcopy(state)
    state["phases"]["credential"]["status"] = "in-progress"
    telemetry.prepare_lifecycle_projection(
        previous,
        state,
        timestamp="2026-10-23T20:01:00Z",
        required_phase_ids=required,
    )
    previous = copy.deepcopy(state)
    state["phases"]["credential"]["status"] = "blocked"
    telemetry.prepare_lifecycle_projection(
        previous,
        state,
        timestamp="2026-10-23T20:02:00Z",
        required_phase_ids=required,
    )
    previous = copy.deepcopy(state)
    state["phases"]["credential"]["status"] = "done"
    events = telemetry.prepare_lifecycle_projection(
        previous,
        state,
        timestamp="2026-10-23T20:12:00Z",
        required_phase_ids=required,
    )

    assert [event["event"] for event in events] == [
        "phase-resumed",
        "phase-completed",
    ]
    assert events[-1]["durationMs"] == 60_000


def test_reopen_completed_phase_resets_duration_for_new_attempt() -> None:
    state = _state()
    required = _required(state)
    telemetry.prepare_lifecycle_projection(
        None,
        state,
        timestamp="2026-10-23T20:00:00Z",
        new_lifecycle=True,
        required_phase_ids=required,
    )
    previous = copy.deepcopy(state)
    state["phases"]["credential"]["status"] = "in-progress"
    telemetry.prepare_lifecycle_projection(
        previous,
        state,
        timestamp="2026-10-23T20:01:00Z",
        required_phase_ids=required,
    )
    previous = copy.deepcopy(state)
    state["phases"]["credential"]["status"] = "done"
    telemetry.prepare_lifecycle_projection(
        previous,
        state,
        timestamp="2026-10-23T20:03:00Z",
        required_phase_ids=required,
    )
    previous = copy.deepcopy(state)
    state["phases"]["credential"]["status"] = "in-progress"
    resumed = telemetry.prepare_lifecycle_projection(
        previous,
        state,
        timestamp="2026-10-23T20:10:00Z",
        required_phase_ids=required,
    )
    previous = copy.deepcopy(state)
    state["phases"]["credential"]["status"] = "done"
    completed = telemetry.prepare_lifecycle_projection(
        previous,
        state,
        timestamp="2026-10-23T20:11:00Z",
        required_phase_ids=required,
    )

    assert resumed[0]["event"] == "phase-resumed"
    assert completed[0]["durationMs"] == 60_000


def test_reopen_completed_phase_as_blocked_resets_old_duration() -> None:
    state = _state()
    required = _required(state)
    telemetry.prepare_lifecycle_projection(
        None,
        state,
        timestamp="2026-10-23T20:00:00Z",
        new_lifecycle=True,
        required_phase_ids=required,
    )
    previous = copy.deepcopy(state)
    state["phases"]["credential"]["status"] = "in-progress"
    telemetry.prepare_lifecycle_projection(
        previous,
        state,
        timestamp="2026-10-23T20:01:00Z",
        required_phase_ids=required,
    )
    previous = copy.deepcopy(state)
    state["phases"]["credential"]["status"] = "done"
    telemetry.prepare_lifecycle_projection(
        previous,
        state,
        timestamp="2026-10-23T20:03:00Z",
        required_phase_ids=required,
    )
    previous = copy.deepcopy(state)
    state["phases"]["credential"]["status"] = "blocked"
    telemetry.prepare_lifecycle_projection(
        previous,
        state,
        timestamp="2026-10-23T20:10:00Z",
        required_phase_ids=required,
    )
    previous = copy.deepcopy(state)
    state["phases"]["credential"]["status"] = "in-progress"
    telemetry.prepare_lifecycle_projection(
        previous,
        state,
        timestamp="2026-10-23T20:11:00Z",
        required_phase_ids=required,
    )
    previous = copy.deepcopy(state)
    state["phases"]["credential"]["status"] = "done"
    completed = telemetry.prepare_lifecycle_projection(
        previous,
        state,
        timestamp="2026-10-23T20:12:00Z",
        required_phase_ids=required,
    )

    assert completed[0]["durationMs"] == 60_000


@pytest.mark.parametrize(
    ("profile", "phase_count"),
    (("hrsd", 9), ("itsm", 8)),
)
def test_all_contract_phases_done_emits_completed_once(
    profile: str,
    phase_count: int,
) -> None:
    state = _contract_state(profile)
    assert len(state["phases"]) == phase_count
    telemetry.prepare_lifecycle_projection(
        None,
        state,
        timestamp="2026-10-23T20:00:00Z",
        new_lifecycle=True,
        required_phase_ids=_required(state),
    )
    previous = copy.deepcopy(state)
    for phase in state["phases"].values():
        phase["status"] = "done"

    events = telemetry.prepare_lifecycle_projection(
        previous,
        state,
        timestamp="2026-10-23T20:05:00Z",
        required_phase_ids=_required(state),
    )

    assert events[-1]["event"] == "completed"
    assert events[-1]["outcome"] == "success"
    assert events[-1]["durationMs"] == 300_000
    previous = copy.deepcopy(state)
    assert telemetry.prepare_lifecycle_projection(
        previous,
        state,
        required_phase_ids=_required(state),
    ) == []


def test_projector_drops_unregistered_same_prefix_remediation() -> None:
    state = _state()
    required = _required(state)
    telemetry.prepare_lifecycle_projection(
        None,
        state,
        timestamp="2026-10-23T20:00:00Z",
        new_lifecycle=True,
        required_phase_ids=required,
    )
    previous = copy.deepcopy(state)
    state["phases"]["credential"]["status"] = "blocked"
    state["phases"]["credential"]["checkpointResults"] = {
        "SN-DA-HRSD-EMPLOYEE-ALICE-001": "Failed"
    }

    events = telemetry.prepare_lifecycle_projection(
        previous,
        state,
        timestamp="2026-10-23T20:01:00Z",
        required_phase_ids=required,
        allowed_remediation_ids=frozenset(
            {"SN-DA-HRSD-CREDENTIAL-001"}
        ),
    )

    blocked = next(event for event in events if event["event"] == "blocked")
    assert blocked["remediationId"] == ""


@pytest.mark.parametrize(
    ("profile", "missing_phase"),
    (
        ("hrsd", "test"),
        ("hrsd", "portal-url"),
        ("hrsd", "servicenow-oidc"),
        ("itsm", "test"),
        ("itsm", "portal-url"),
        ("itsm", "servicenow-oidc"),
    ),
)
def test_missing_contract_phase_never_emits_completed(
    profile: str,
    missing_phase: str,
) -> None:
    state = _contract_state(profile)
    required = _required(state)
    state["phases"].pop(missing_phase)
    for phase in state["phases"].values():
        phase["status"] = "done"

    events = telemetry.prepare_lifecycle_projection(
        None,
        state,
        timestamp="2026-10-23T20:00:00Z",
        new_lifecycle=True,
        required_phase_ids=required,
    )

    assert all(event["event"] != "completed" for event in events)
    assert state["telemetry"]["completed"] is False


@pytest.mark.parametrize("profile", ("hrsd", "itsm"))
def test_partial_or_invalid_phase_state_never_emits_completed(
    profile: str,
) -> None:
    state = _contract_state(profile)
    required = _required(state)
    for phase_id, phase in state["phases"].items():
        phase["status"] = "done" if phase_id == "preflight" else "pending"
    state["phases"]["test"]["status"] = "invalid"

    events = telemetry.prepare_lifecycle_projection(
        None,
        state,
        timestamp="2026-10-23T20:00:00Z",
        new_lifecycle=True,
        required_phase_ids=required,
    )

    assert all(event["event"] != "completed" for event in events)
    assert state["telemetry"]["completed"] is False


def test_emitter_projects_only_bounded_existing_fields(
    monkeypatch,
) -> None:
    captured: list[dict] = []
    fake = SimpleNamespace(
        emit_connect_lifecycle=lambda *args, **kwargs: captured.append(
            {"args": args, "kwargs": kwargs}
        )
    )
    monkeypatch.setitem(sys.modules, "adk_telemetry", fake)
    state = {
        "agentId": "00000000-0000-4000-8000-000000002222",
        "secret": "must-not-emit",
    }
    event = {
        "event": "blocked",
        "phase": "runtime",
        "outcome": "blocked",
        "durationMs": 5,
        "retryCount": 2,
        "resumeCount": 1,
        "blockerCategory": "state",
        "remediationId": "SN-DA-ITSM-TOPICS-001",
        "correlationId": "00000000-0000-4000-8000-000000003333",
        "freeText": "customer instance and employee value",
    }

    telemetry.emit_lifecycle_event(state, event)

    assert captured[0]["args"] == ("blocked",)
    assert captured[0]["kwargs"] == {
        "connector": "servicenow",
        "phase": "runtime",
        "outcome": "blocked",
        "duration_ms": 5,
        "retry_count": 2,
        "resume_count": 1,
        "blocker_category": "state",
        "remediation_id": "SN-DA-ITSM-TOPICS-001",
        "correlation_id": "00000000-0000-4000-8000-000000003333",
        "agent_id": "00000000-0000-4000-8000-000000002222",
    }


def test_emitter_is_fail_open(monkeypatch) -> None:
    fake = SimpleNamespace(
        emit_connect_lifecycle=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("collector unavailable")
        )
    )
    monkeypatch.setitem(sys.modules, "adk_telemetry", fake)

    telemetry.emit_lifecycle_event(
        {"agentId": "00000000-0000-4000-8000-000000002222"},
        {
            "event": "phase-started",
            "phase": "preflight",
            "correlationId": "00000000-0000-4000-8000-000000003333",
        },
    )
