# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for Workday connect state, migration, and approval safety."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _config_path(root: Path) -> Path:
    return root / ".local" / "connect" / "workday-da" / "config.json"


def test_initialize_creates_only_json_state(tmp_path: Path) -> None:
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    state = store.initialize()

    assert state["schemaVersion"] == 9
    assert state["lifecycle"]["retryCount"] == 0
    assert state["lifecycle"]["resumeCount"] == 0
    assert state["lifecycle"]["journal"] == []
    assert _config_path(tmp_path).exists()
    assert not (tmp_path / ".local/connect/workday-da/tasks.md").exists()
    assert not (tmp_path / ".local/setup/workday-da/tasks.md").exists()


def test_migrates_legacy_rows_without_using_app_uri_as_saml_id(
    tmp_path: Path,
) -> None:
    import workday_connect_store as store_module

    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "tenant": "contoso_prod",
                "tenantId": "entra-tenant",
                "entraAdminAccount": "admin@example.com",
                "appIdUri": "api://application-id",
                "setupStatus": {
                    "DA1.1": {"state": "done", "verifiedBy": "programmatic"},
                    "DA2.1": {"state": "in-progress"},
                },
            }
        ),
        encoding="utf-8",
    )

    state = store_module.WorkdayConnectStore(tmp_path).initialize()

    assert state["phases"]["preflight"]["status"] == "complete"
    assert state["phases"]["entra"]["status"] == "active"
    assert state["identifiers"]["entraAppIdUri"] == "api://application-id"
    assert (
        state["identifiers"]["workdaySamlEntityId"]
        == "http://www.workday.com/contoso_prod"
    )
    assert state["migration"]["source"] == "legacy-workday-da-config"
    assert state["operators"]["entraAdmin"]["username"] == "admin@example.com"
    assert path.with_name("config.pre-v9.json").exists()


def test_migration_preserves_existing_tasks_as_snapshot(tmp_path: Path) -> None:
    import workday_connect_store as store_module

    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    tasks = tmp_path / ".local/setup/workday-da/tasks.md"
    connect_tasks = tmp_path / ".local/connect/workday-da/tasks.md"
    tasks.parent.mkdir(parents=True)
    tasks.write_text("legacy setup checklist", encoding="utf-8")
    connect_tasks.write_text("legacy connect checklist", encoding="utf-8")

    store_module.WorkdayConnectStore(tmp_path).initialize()

    assert tasks.read_text(encoding="utf-8") == "legacy setup checklist"
    assert connect_tasks.read_text(encoding="utf-8") == ("legacy connect checklist")


def test_future_schema_is_rejected_without_rewriting_state(
    tmp_path: Path,
) -> None:
    import workday_connect_store as store_module

    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True)
    original = {
        "schemaVersion": 999,
        "futureField": {"mustRemain": True},
    }
    path.write_text(json.dumps(original), encoding="utf-8")

    with pytest.raises(
        store_module.WorkdayConnectStoreError,
        match="Unsupported Workday connect state schema version",
    ):
        store_module.WorkdayConnectStore(tmp_path).initialize()

    assert json.loads(path.read_text(encoding="utf-8")) == original


@pytest.mark.parametrize("schema_version", [[], {}])
def test_malformed_schema_is_rejected_without_rewriting_state(
    tmp_path: Path,
    schema_version: object,
) -> None:
    import workday_connect_store as store_module

    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True)
    original = {
        "schemaVersion": schema_version,
        "existingField": {"mustRemain": True},
    }
    path.write_text(json.dumps(original), encoding="utf-8")

    with pytest.raises(
        store_module.WorkdayConnectStoreError,
        match="Unsupported Workday connect state schema version",
    ):
        store_module.WorkdayConnectStore(tmp_path).initialize()

    assert json.loads(path.read_text(encoding="utf-8")) == original


def test_v5_state_migrates_to_privacy_safe_lifecycle_journal(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_store as store_module

    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True)
    state = model.default_state()
    state["schemaVersion"] = 5
    state.pop("lifecycle")
    path.write_text(json.dumps(state), encoding="utf-8")

    upgraded = store_module.WorkdayConnectStore(tmp_path).initialize()

    assert upgraded["schemaVersion"] == 9
    assert upgraded["lifecycle"]["correlationId"]
    assert upgraded["lifecycle"]["journal"] == []
    assert upgraded["migration"]["source"] == "workday-connect-state-v5"
    assert path.with_name("config.pre-v9.json").exists()


def test_v6_state_migrates_with_administrator_progress(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_store as store_module

    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True)
    state = model.default_state()
    state["schemaVersion"] = 6
    state["phases"]["entra"].pop("administrator")
    state["phases"]["workday-admin"].pop("administrator")
    state["tenantFoundation"] = {
        "legacySchemaV6Snapshot": True,
    }
    path.write_text(json.dumps(state), encoding="utf-8")

    upgraded = store_module.WorkdayConnectStore(tmp_path).initialize()

    assert upgraded["schemaVersion"] == 9
    assert upgraded["phases"]["entra"]["administrator"]["substage"] == (
        "not-started"
    )
    assert upgraded["migration"]["source"] == "workday-connect-state-v6"
    assert path.with_name("config.pre-v9.json").exists()


@pytest.mark.parametrize("source_version", [2, 3, 4, 5, 6])
def test_completed_pre_v7_state_reopens_expanded_evidence_without_losing_safe_values(
    tmp_path: Path,
    source_version: int,
) -> None:
    import workday_connect_model as model
    import workday_connect_store as store_module

    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True)
    state = model.default_state()
    state["schemaVersion"] = source_version
    state["phases"]["entra"].pop("administrator")
    state["phases"]["workday-admin"].pop("administrator")
    state["identifiers"].update(
        {
            "entraAppId": "app-id",
            "workdaySamlEntityId": "http://www.workday.com/contoso",
            "oauthClientId": "oauth-client-id",
            "signingCertificate": {
                "thumbprint": "AA11",
                "validFrom": "2026-01-01",
                "validTo": "2027-01-01",
            },
        }
    )
    state["endpoints"].update(
        {
            "oauthTokenUrl": (
                "https://example.workday.com/ccx/oauth2/contoso/token"
            ),
            "restBaseUrl": "https://example.workday.com/ccx/api",
            "soapBaseUrl": "https://example.workday.com/ccx/service",
        }
    )
    for phase_id in ("preflight", "entra", "workday-admin"):
        actions = sorted(model.PHASE_REQUIRED_ACTIONS[phase_id])
        phase = state["phases"][phase_id]
        phase["status"] = "complete"
        phase["completedActions"] = actions
        phase["evidence"] = [
            {"action": action, "outcome": "verified"}
            for action in actions
        ]
    path.write_text(json.dumps(state), encoding="utf-8")

    upgraded = store_module.WorkdayConnectStore(tmp_path).initialize()

    assert upgraded["phases"]["entra"]["status"] == "active"
    assert upgraded["phases"]["workday-admin"]["status"] == "pending"
    assert upgraded["phases"]["entra"]["administrator"][
        "partialEvidence"
    ]["applicationId"] == "app-id"
    assert upgraded["phases"]["workday-admin"]["administrator"][
        "partialEvidence"
    ]["oauthClientId"] == "oauth-client-id"
    assert upgraded["migration"]["source"] == (
        f"workday-connect-state-v{source_version}"
    )


def test_legacy_migration_never_fabricates_new_runtime_proof(
    tmp_path: Path,
) -> None:
    import workday_connect_store as store_module

    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True)
    setup_status = {
        row: {"state": "done", "verifiedBy": "programmatic"}
        for rows in store_module.LEGACY_PHASE_ROWS.values()
        for row in rows
    }
    path.write_text(
        json.dumps(
            {
                "tenant": "contoso",
                "tenantId": "tenant-id",
                "setupStatus": setup_status,
            }
        ),
        encoding="utf-8",
    )

    upgraded = store_module.WorkdayConnectStore(tmp_path).initialize()

    runtime = upgraded["phases"]["runtime"]
    assert runtime["status"] == "active"
    assert "runtime-template-configured" not in runtime["completedActions"]
    assert "workday-topics-activated" not in runtime["completedActions"]


def test_administrator_progress_preserves_valid_fields_and_reopens_invalid(
    tmp_path: Path,
) -> None:
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    store.complete_action(
        "preflight",
        "verify-target",
        evidence={"outcome": "verified"},
    )
    store.complete_action(
        "preflight",
        "verify-package",
        evidence={"outcome": "verified"},
    )
    store.set_phase_status("preflight", "complete")
    for substage in (
        "administrator-engaged",
        "handoff-presented",
        "awaiting-completion",
        "completion-confirmed",
    ):
        store.record_administrator_progress("entra", substage)

    store.record_administrator_progress(
        "entra",
        "collecting-evidence",
        valid_fields={
            "selectedDirectoryId": "tenant-id",
            "replyUrl": "https://example.test/reply",
        },
        invalid_fields=["loginUrl"],
    )
    state = store.record_administrator_progress(
        "entra",
        "collecting-evidence",
        valid_fields={"loginUrl": "https://login.example.test/saml"},
    )

    administrator = state["phases"]["entra"]["administrator"]
    assert administrator["partialEvidence"] == {
        "selectedDirectoryId": "tenant-id",
        "replyUrl": "https://example.test/reply",
        "loginUrl": "https://login.example.test/saml",
    }
    assert administrator["invalidFields"] == []


def test_administrator_progress_rejects_backward_transition(
    tmp_path: Path,
) -> None:
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    store.complete_action(
        "preflight",
        "verify-target",
        evidence={"outcome": "verified"},
    )
    store.complete_action(
        "preflight",
        "verify-package",
        evidence={"outcome": "verified"},
    )
    store.set_phase_status("preflight", "complete")
    store.record_administrator_progress(
        "entra",
        "administrator-engaged",
    )
    store.record_administrator_progress("entra", "handoff-presented")

    with pytest.raises(
        store_module.WorkdayConnectStoreError,
        match="cannot move backward",
    ):
        store.record_administrator_progress(
            "entra",
            "administrator-engaged",
        )


def test_administrator_progress_rejects_forward_jump(
    tmp_path: Path,
) -> None:
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    for action in ("verify-target", "verify-package"):
        store.complete_action(
            "preflight",
            action,
            evidence={"outcome": "verified"},
        )
    store.set_phase_status("preflight", "complete")

    with pytest.raises(
        store_module.WorkdayConnectStoreError,
        match="skip the supported sequence",
    ):
        store.record_administrator_progress(
            "entra",
            "awaiting-completion",
        )


def test_early_v6_events_are_normalized_without_losing_history(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_store as store_module

    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True)
    state = model.default_state()
    state["lifecycle"].pop("phaseDurationsMs")
    state["lifecycle"].pop("activePhaseStartedAt")
    state["lifecycle"].pop("eventMarkers")
    state["lifecycle"]["journal"] = [
        {
            "sequence": 1,
            "event": "blocked",
            "phase": "preflight",
            "outcome": "blocked",
            "blockerCategory": "workdayconnectpreflighterror",
            "durationMs": 0,
            "retryCount": 0,
            "resumeCount": 0,
            "timestamp": "2026-09-28T00:00:00Z",
        }
    ]
    path.write_text(json.dumps(state), encoding="utf-8")

    normalized = store_module.WorkdayConnectStore(tmp_path).initialize()
    event = normalized["lifecycle"]["journal"][0]

    assert event["correlationId"] == normalized["lifecycle"]["correlationId"]
    assert event["blockerCategory"] == "platform"
    assert event["remediationId"] == ""
    assert event["timestamp"] == "2026-09-28T00:00:00Z"
    assert normalized["lifecycle"]["eventMarkers"] == [
        "blocked|preflight"
    ]


def test_invalid_early_v6_normalization_does_not_rewrite_state(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_store as store_module

    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True)
    state = model.default_state()
    state["lifecycle"]["journal"] = [
        {
            "sequence": 1,
            "event": "blocked",
            "phase": "preflight",
            "outcome": "blocked",
            "blockerCategory": "legacy-platform-error",
            "durationMs": -1,
            "retryCount": 0,
            "resumeCount": 0,
            "timestamp": "2026-09-28T00:00:00Z",
        }
    ]
    original = json.dumps(state)
    path.write_text(original, encoding="utf-8")

    with pytest.raises(
        model.WorkdayConnectModelError,
        match="durationMs must be non-negative",
    ):
        store_module.WorkdayConnectStore(tmp_path).initialize()

    assert path.read_text(encoding="utf-8") == original


def test_phase_transitions_append_events_and_publish_after_persistence(
    tmp_path: Path,
) -> None:
    import workday_connect_store as store_module

    published = []

    def sink(state, event):
        persisted = json.loads(_config_path(tmp_path).read_text(encoding="utf-8"))
        persisted_event = next(
            record
            for record in persisted["lifecycle"]["journal"]
            if record["sequence"] == event["sequence"]
        )
        assert persisted_event == event
        published.append((state, event))

    store = store_module.WorkdayConnectStore(tmp_path, event_sink=sink)
    store.initialize()
    store.complete_action(
        "preflight",
        "verify-target",
        evidence={"outcome": "verified"},
    )
    store.set_phase_status(
        "preflight",
        "blocked",
        blocker={
            "operation": "preflight",
            "errorType": "WorkdayConnectPreflightError",
            "message": "Customer-specific URL must not enter the journal.",
        },
    )
    store.complete_action(
        "preflight",
        "verify-package",
        evidence={"outcome": "verified"},
    )
    state = store.set_phase_status("preflight", "complete")

    events = state["lifecycle"]["journal"]
    assert [event["event"] for event in events] == [
        "phase-started",
        "phase-paused",
        "blocked",
        "phase-resumed",
        "phase-completed",
    ]
    assert events[2]["blockerCategory"] == "platform"
    assert "message" not in events[2]
    assert events[-1]["durationMs"] >= events[1]["durationMs"]
    assert {
        event["correlationId"] for event in events
    } == {state["lifecycle"]["correlationId"]}
    assert state["lifecycle"]["retryCount"] == 1
    assert state["lifecycle"]["resumeCount"] == 1
    assert len(published) == 5


def test_target_change_rotates_correlation_and_abandons_old_run(
    tmp_path: Path,
) -> None:
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    original = store.initialize()["lifecycle"]["correlationId"]
    store.record_lifecycle_event("invoked")
    store.merge_section("scope", {"environmentId": "environment-one"})
    store.complete_action(
        "preflight",
        "verify-target",
        evidence={"outcome": "verified"},
    )

    state = store.merge_section(
        "scope",
        {"environmentId": "environment-two"},
    )

    assert state["lifecycle"]["correlationId"] != original
    assert state["lifecycle"]["retryCount"] == 0
    assert state["lifecycle"]["resumeCount"] == 0
    assert state["phases"]["preflight"]["status"] == "pending"
    abandoned = state["lifecycle"]["journal"][-2]
    assert abandoned["event"] == "abandoned"
    assert abandoned["outcome"] == "cancelled"
    assert abandoned["phase"] == "preflight"
    assert abandoned["correlationId"] == original
    invoked = state["lifecycle"]["journal"][-1]
    assert invoked["event"] == "invoked"
    assert invoked["correlationId"] == state["lifecycle"]["correlationId"]


def test_slug_only_target_change_rotates_lifecycle(tmp_path: Path) -> None:
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    store.record_lifecycle_event("invoked", once_per_lifecycle=True)
    store.merge_section(
        "scope",
        {
            "agent": {
                "slug": "agent-a",
                "botId": "7f7c8f9c-1234-4abc-9def-0123456789ab",
                "schemaName": "contoso.agent",
            }
        },
    )
    original = store.load()["lifecycle"]["correlationId"]

    state = store.merge_section(
        "scope",
        {
            "agent": {
                "slug": "agent-b",
                "botId": "7f7c8f9c-1234-4abc-9def-0123456789ab",
                "schemaName": "contoso.agent",
            }
        },
    )

    assert state["lifecycle"]["correlationId"] != original
    assert state["lifecycle"]["journal"][-2]["event"] == "abandoned"
    assert state["lifecycle"]["journal"][-1]["event"] == "invoked"


def test_operator_attestation_is_once_per_lifecycle(tmp_path: Path) -> None:
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    operator = {"username": "maker@example.test"}

    store.merge_section("operators", {"powerPlatformMaker": operator})
    state = store.merge_section(
        "operators",
        {"powerPlatformMaker": operator},
    )

    matching = [
        event
        for event in state["lifecycle"]["journal"]
        if event["event"] == "roles-attested"
    ]
    assert len(matching) == 1
    assert matching[0]["phase"] == "preflight"
    assert matching[0]["outcome"] == "success"


def test_lifecycle_journal_is_bounded(tmp_path: Path) -> None:
    import workday_connect_model as model
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    for _ in range(model.LIFECYCLE_JOURNAL_MAX_EVENTS + 5):
        store.record_lifecycle_event("invoked", phase="preflight")

    state = store.load()
    journal = state["lifecycle"]["journal"]
    assert len(journal) == model.LIFECYCLE_JOURNAL_MAX_EVENTS
    assert journal[0]["sequence"] == 6
    assert journal[-1]["sequence"] == model.LIFECYCLE_JOURNAL_MAX_EVENTS + 5


def test_lifecycle_aggregates_survive_journal_eviction(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import workday_connect_model as model
    import workday_connect_store as store_module

    timestamps = iter(
        [
            "2026-09-29T00:00:00Z",
            "2026-09-29T00:00:01Z",
            *[
                f"2026-09-29T00:00:{second:02d}Z"
                for second in range(2, 60)
            ],
        ]
    )
    last = "2026-09-29T00:00:59Z"

    def fake_now():
        nonlocal last
        try:
            last = next(timestamps)
        except StopIteration:
            pass
        return last

    monkeypatch.setattr(store_module, "utc_now", fake_now)
    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    store.set_phase_status("preflight", "active")
    store.set_phase_status(
        "preflight",
        "blocked",
        blocker={
            "operation": "preflight",
            "errorType": "timeout",
            "message": "Timed out",
        },
    )
    for _ in range(model.LIFECYCLE_JOURNAL_MAX_EVENTS + 5):
        store.record_lifecycle_event("plan-generated")
    state = store.merge_section(
        "operators",
        {"powerPlatformMaker": {"username": "maker@example.test"}},
    )
    state = store.merge_section(
        "operators",
        {"powerPlatformMaker": {"username": "maker@example.test"}},
    )

    assert state["lifecycle"]["phaseDurationsMs"]["preflight"] >= 1000
    assert len(
        [
            event
            for event in state["lifecycle"]["journal"]
            if event["event"] == "roles-attested"
        ]
    ) == 1


def test_telemetry_sink_failure_never_breaks_state_transition(
    tmp_path: Path,
) -> None:
    import workday_connect_store as store_module

    def failing_sink(_state, _event):
        raise RuntimeError("collector unavailable")

    store = store_module.WorkdayConnectStore(
        tmp_path,
        event_sink=failing_sink,
    )
    store.initialize()

    state = store.record_lifecycle_event("invoked", phase="preflight")

    assert state["lifecycle"]["journal"][-1]["event"] == "invoked"


def test_naive_lifecycle_timestamp_is_rejected_before_transition(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_store as store_module

    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True)
    state = model.default_state()
    state["lifecycle"]["activePhaseStartedAt"]["preflight"] = (
        "2026-09-29T12:00:00"
    )
    path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(
        model.WorkdayConnectModelError,
        match="must include a timezone",
    ):
        store_module.WorkdayConnectStore(tmp_path).initialize()


def test_first_attempt_failure_records_start_pause_and_block(
    tmp_path: Path,
) -> None:
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()

    state = store.set_phase_status(
        "preflight",
        "blocked",
        blocker={
            "operation": "preflight",
            "errorType": "WorkdayConnectPreflightError",
            "message": "Failed before evidence was recorded.",
        },
    )

    assert [
        event["event"] for event in state["lifecycle"]["journal"]
    ] == ["phase-started", "phase-paused", "blocked"]


def test_employee_validation_blocker_retains_bounded_remediation_id(
    tmp_path: Path,
) -> None:
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()

    state = store.set_phase_status(
        "employee-validation",
        "blocked",
        blocker={
            "operation": "record-validation-failure",
            "errorType": "employee-context",
            "message": "Canonical remediation",
            "remediationId": "WD-E2E-004",
        },
    )

    blocked = state["lifecycle"]["journal"][-1]
    assert blocked["blockerCategory"] == "validation"
    assert blocked["remediationId"] == "WD-E2E-004"


@pytest.mark.parametrize(
    ("error_type", "expected"),
    [
        ("TimeoutError", "timeout"),
        ("UnauthorizedOperation", "permissions"),
        ("SignInLoop", "auth"),
        ("NetworkEndpointError", "connection"),
        ("EmployeeContextValidation", "validation"),
        ("StateSchemaError", "state"),
        ("DataversePreflightError", "platform"),
        ("RuntimeFlowError", "runtime"),
        ("UnclassifiedFailure", "unknown"),
    ],
)
def test_blocker_category_uses_bounded_taxonomy(
    error_type: str,
    expected: str,
) -> None:
    import workday_connect_store as store_module

    assert (
        store_module._blocker_category({"errorType": error_type})
        == expected
    )


def test_legacy_ready_state_reopens_runtime_for_live_topic_proof(
    tmp_path: Path,
) -> None:
    import workday_connect_store as store_module

    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True)
    rows = {
        row: {"state": "done", "verifiedBy": "legacy"}
        for phase_rows in store_module.LEGACY_PHASE_ROWS.values()
        for row in phase_rows
    }
    path.write_text(
        json.dumps({"setupStatus": rows}),
        encoding="utf-8",
    )

    state = store_module.WorkdayConnectStore(tmp_path).initialize()

    assert state["status"] == "in-progress"
    assert state["phases"]["runtime"]["status"] == "active"
    assert (
        "workday-topics-activated" not in state["phases"]["runtime"]["completedActions"]
    )
    assert state["phases"]["employee-validation"]["status"] == "pending"


def test_phase_completion_requires_prerequisite(tmp_path: Path) -> None:
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()

    with pytest.raises(
        store_module.WorkdayConnectStoreError,
        match="Complete 'preflight'",
    ):
        store.set_phase_status("entra", "complete")


def test_complete_action_is_idempotent(tmp_path: Path) -> None:
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    store.complete_action(
        "preflight",
        "verify-target",
        evidence={"outcome": "passed"},
    )
    state = store.complete_action(
        "preflight",
        "verify-target",
        evidence={"outcome": "passed"},
    )

    assert state["phases"]["preflight"]["completedActions"] == ["verify-target"]
    assert len(state["phases"]["preflight"]["evidence"]) == 1


def test_complete_action_does_not_regress_completed_phase(
    tmp_path: Path,
) -> None:
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    _complete_phase(
        store,
        "preflight",
        store_module.PHASE_REQUIRED_ACTIONS["preflight"],
    )

    state = store.complete_action(
        "preflight",
        "verify-target",
        evidence={"outcome": "verified"},
    )

    assert state["phases"]["preflight"]["status"] == "complete"


def test_complete_action_reactivates_a_blocked_phase(tmp_path: Path) -> None:
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    store.set_phase_status(
        "preflight",
        "blocked",
        blocker={
            "operation": "preflight",
            "errorType": "TestBlocker",
            "message": "Resolve the test blocker.",
        },
    )

    state = store.complete_action(
        "preflight",
        "verify-target",
        evidence={"outcome": "verified"},
    )

    phase = state["phases"]["preflight"]
    assert phase["status"] == "active"
    assert phase["blocker"] is None


def test_complete_action_requires_completed_prerequisite(tmp_path: Path) -> None:
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()

    with pytest.raises(
        store_module.WorkdayConnectStoreError,
        match="Complete 'preflight'",
    ):
        store.complete_action(
            "entra",
            "exact-application-discovered",
            evidence={"outcome": "verified"},
        )


def test_approved_plan_rejects_changed_target(tmp_path: Path) -> None:
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    for phase_id in ("preflight", "entra", "workday-admin", "connections"):
        _complete_phase(
            store,
            phase_id,
            store_module.PHASE_REQUIRED_ACTIONS[phase_id],
        )
    plan = {
        "phase": "runtime",
        "scope": {"tenantId": "tenant-a", "applicationId": "app-a"},
        "actions": ["configure-saml"],
    }
    _state, approved_hash = store.approve_plan("runtime", plan)

    assert store.verify_plan("runtime", plan, approved_hash) == approved_hash
    changed = {
        **plan,
        "scope": {"tenantId": "tenant-a", "applicationId": "app-b"},
    }
    with pytest.raises(store_module.WorkdayConnectPlanChangedError):
        store.verify_plan("runtime", changed, approved_hash)


def test_approving_completed_runtime_invalidates_employee_validation(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    for definition in model.PHASE_DEFINITIONS:
        phase_id = definition.identifier.value
        _complete_phase(
            store,
            phase_id,
            set(model.PHASE_REQUIRED_ACTIONS[phase_id]),
        )

    state, _hash = store.approve_plan(
        "runtime",
        {
            "phase": "runtime",
            "scope": {"botId": "bot-id"},
            "actions": ["Reapply reviewed runtime bindings"],
        },
    )

    assert state["phases"]["runtime"]["status"] == "active"
    assert state["phases"]["employee-validation"]["status"] == "pending"
    assert state["phases"]["employee-validation"]["completedActions"] == []


def test_approving_changed_plan_clears_current_phase_evidence(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    for phase_id in ("preflight", "entra", "workday-admin", "connections"):
        _complete_phase(
            store,
            phase_id,
            set(model.PHASE_REQUIRED_ACTIONS[phase_id]),
        )
    original = {
        "phase": "runtime",
        "scope": {"botId": "bot-a"},
        "actions": ["Apply runtime bindings"],
    }
    store.approve_plan("runtime", original)
    store.complete_action(
        "runtime",
        "runtime-template-configured",
        evidence={"outcome": "verified", "botId": "bot-a"},
    )

    changed = {
        **original,
        "scope": {"botId": "bot-b"},
    }
    state, approved_hash = store.approve_plan("runtime", changed)

    runtime = state["phases"]["runtime"]
    assert runtime["status"] == "active"
    assert runtime["approvedPlan"] == changed
    assert runtime["approvedPlanHash"] == approved_hash
    assert runtime["completedActions"] == []
    assert runtime["evidence"] == []
    assert runtime["validationProfiles"] == {}


def test_status_returns_progress_roadmap_and_next_phase_summary(
    tmp_path: Path,
) -> None:
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    for action in ("verify-target", "verify-package"):
        store.complete_action(
            "preflight",
            action,
            evidence={"outcome": "verified"},
        )
    store.set_phase_status("preflight", "complete")

    status = store.status()

    assert status["nextPhaseId"] == "entra"
    assert "| 1 | Preflight | Complete |" in status["progressText"]
    assert "| 2 | Microsoft Entra | Current |" in status["progressText"]
    assert "| 3 | Workday administrator | Pending |" in status["progressText"]
    assert status["nextPhaseSummary"]["title"] == "Microsoft Entra"
    assert len(status["nextPhaseSummary"]["whatHappens"]) == 3
    assert len(status["phases"]) == 6


def test_phase_cannot_complete_without_required_evidence(
    tmp_path: Path,
) -> None:
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()

    with pytest.raises(
        store_module.WorkdayConnectStoreError,
        match="missing required verified actions",
    ):
        store.set_phase_status("preflight", "complete")


def test_scope_change_invalidates_affected_phases(tmp_path: Path) -> None:
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    store.merge_section("scope", {"agent": {"slug": "agent-a"}})
    for action in ("verify-target", "verify-package"):
        store.complete_action(
            "preflight",
            action,
            evidence={"outcome": "verified"},
        )
    store.set_phase_status("preflight", "complete")

    state = store.merge_section("scope", {"agent": {"slug": "agent-b"}})

    assert state["phases"]["preflight"]["status"] == "pending"
    assert state["phases"]["preflight"]["completedActions"] == []
    assert state["phases"]["entra"]["status"] == "pending"


def test_regressing_completed_phase_invalidates_downstream(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    for definition in model.PHASE_DEFINITIONS:
        phase_id = definition.identifier.value
        _complete_phase(
            store,
            phase_id,
            set(model.PHASE_REQUIRED_ACTIONS[phase_id]),
        )

    state = store.set_phase_status(
        "runtime",
        "blocked",
        blocker={
            "operation": "record-topic-activation",
            "errorType": "RuntimeVerificationFailed",
            "message": "The live topic is not active.",
        },
    )

    assert state["phases"]["runtime"]["status"] == "blocked"
    assert state["phases"]["employee-validation"]["status"] == "pending"
    assert state["phases"]["employee-validation"]["completedActions"] == []


def _complete_phase(store, phase_id: str, actions: set[str]) -> None:
    for action in actions:
        store.complete_action(
            phase_id,
            action,
            evidence={"outcome": "verified"},
        )
    store.set_phase_status(phase_id, "complete")


def _complete_runtime_for_employee(
    store,
    model,
    *,
    attachment_names: list[str],
    flows: list[dict[str, str]] | None = None,
) -> None:
    store.approve_plan(
        "runtime",
        {
            "phase": "runtime",
            "scope": {"environmentId": "environment-id"},
            "actions": ["Configure runtime"],
            "flows": flows
            or [{"name": "REST", "workflowId": "flow-id"}],
        },
    )
    for action in model.PHASE_REQUIRED_ACTIONS["runtime"]:
        evidence = {"outcome": "verified"}
        if action == "flow-attachment-confirmed":
            evidence["flowNames"] = attachment_names
        store.complete_action("runtime", action, evidence=evidence)
    store.set_phase_status("runtime", "complete")


def _set_foundation_data(store, *, workday_tenant: str = "contoso") -> None:
    store.merge_section(
        "identifiers",
        {
            "entraAppId": "app-id",
            "entraAppObjectId": "app-object-id",
            "entraServicePrincipalId": "service-principal-id",
            "entraAppIdUri": "api://app-id",
            "microsoftEntraIdentifier": (
                "https://sts.windows.net/tenant-id/"
            ),
            "entraLoginUrl": (
                "https://login.microsoftonline.com/tenant-id/saml2"
            ),
            "replyUrl": "https://www.workday.com/saml/acs",
            "workdaySamlEntityId": (f"http://www.workday.com/{workday_tenant}"),
            "scopeGuid": "scope-id",
            "signingCertificate": {
                "thumbprint": "thumbprint",
                "validFrom": "2026-01-01",
                "validTo": "2027-01-01",
            },
            "oauthClientId": "oauth-client-id",
        },
    )
    store.merge_section(
        "endpoints",
        {
            "oauthTokenUrl": "https://example.workday.com/oauth/token",
            "restBaseUrl": "https://example.workday.com/ccx/api",
            "soapBaseUrl": (
                f"https://example.workday.com/ccx/service/{workday_tenant}"
            ),
        },
    )


def test_pre_v7_migration_preserves_existing_valid_tenant_foundation(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    store.merge_section(
        "scope",
        {
            "entraTenantId": "tenant-id",
            "workdayTenant": "contoso",
        },
    )
    _set_foundation_data(store)
    for phase_id in ("preflight", "entra", "workday-admin"):
        _complete_phase(
            store,
            phase_id,
            set(model.PHASE_REQUIRED_ACTIONS[phase_id]),
        )
    captured = store.capture_tenant_foundation()["tenantFoundation"]
    state = store.load()
    state["schemaVersion"] = 5
    store_module._reset_phase(state["phases"]["preflight"])
    store_module._reset_phase(state["phases"]["entra"])
    _config_path(tmp_path).write_text(json.dumps(state), encoding="utf-8")

    upgraded = store_module.WorkdayConnectStore(tmp_path).initialize()

    assert upgraded["tenantFoundation"] == captured
    assert upgraded["phases"]["preflight"]["status"] == "pending"


def test_endpoint_change_invalidates_workday_and_downstream_phases(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    for phase_id in (
        "preflight",
        "entra",
        "workday-admin",
        "connections",
        "runtime",
        "employee-validation",
    ):
        _complete_phase(
            store,
            phase_id,
            set(model.PHASE_REQUIRED_ACTIONS[phase_id]),
        )

    state = store.merge_section(
        "endpoints",
        {"restBaseUrl": "https://example.workday.com/ccx/api"},
    )

    assert state["status"] == "in-progress"
    assert state["phases"]["preflight"]["status"] == "complete"
    assert state["phases"]["entra"]["status"] == "complete"
    assert state["phases"]["workday-admin"]["status"] == "pending"
    assert state["phases"]["connections"]["status"] == "pending"
    assert state["phases"]["runtime"]["status"] == "pending"
    assert state["phases"]["employee-validation"]["status"] == "pending"


def test_maker_change_preserves_reusable_tenant_foundation(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    for phase_id in (
        "preflight",
        "entra",
        "workday-admin",
        "connections",
        "runtime",
        "employee-validation",
    ):
        _complete_phase(
            store,
            phase_id,
            set(model.PHASE_REQUIRED_ACTIONS[phase_id]),
        )
    store.merge_section(
        "scope",
        {
            "entraTenantId": "tenant-id",
            "workdayTenant": "contoso",
        },
    )
    _set_foundation_data(store)
    for phase_id in ("preflight", "entra", "workday-admin"):
        _complete_phase(
            store,
            phase_id,
            set(model.PHASE_REQUIRED_ACTIONS[phase_id]),
        )
    store.capture_tenant_foundation()

    state = store.merge_section(
        "operators",
        {"powerPlatformMaker": {"username": "new@example.com"}},
    )

    assert state["status"] == "in-progress"
    assert all(phase["status"] == "pending" for phase in state["phases"].values())
    assert state["tenantFoundation"] is not None


def test_v2_state_is_downgraded_when_completion_has_no_evidence(
    tmp_path: Path,
) -> None:
    import workday_connect_store as store_module

    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True)
    state = store_module.default_state()
    state["schemaVersion"] = 2
    state["phases"]["preflight"]["status"] = "complete"
    state["status"] = "in-progress"
    path.write_text(json.dumps(state), encoding="utf-8")

    upgraded = store_module.WorkdayConnectStore(tmp_path).initialize()

    assert upgraded["schemaVersion"] == 9
    assert upgraded["phases"]["preflight"]["status"] == "active"
    assert upgraded["migration"]["source"] == "workday-connect-state-v2"


def test_v3_runtime_completion_is_reopened_for_live_topic_proof(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_store as store_module

    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True)
    state = model.default_state()
    state["schemaVersion"] = 3
    for phase_id in (
        "preflight",
        "entra",
        "workday-admin",
        "connections",
        "runtime",
        "employee-validation",
    ):
        actions = set(model.PHASE_REQUIRED_ACTIONS[phase_id])
        actions.discard("workday-topics-activated")
        phase = state["phases"][phase_id]
        phase["status"] = "complete"
        phase["completedActions"] = sorted(actions)
        phase["evidence"] = [
            {"action": action, "outcome": "verified"} for action in sorted(actions)
        ]
    state["status"] = "ready"
    path.write_text(json.dumps(state), encoding="utf-8")

    upgraded = store_module.WorkdayConnectStore(tmp_path).initialize()

    assert upgraded["schemaVersion"] == 9
    assert upgraded["status"] == "in-progress"
    assert upgraded["phases"]["entra"]["status"] == "pending"
    assert upgraded["phases"]["runtime"]["status"] == "pending"
    assert upgraded["phases"]["employee-validation"]["status"] == "pending"
    assert upgraded["migration"]["source"] == "workday-connect-state-v3"


def test_v4_migration_captures_complete_tenant_foundation(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_store as store_module

    path = _config_path(tmp_path)
    path.parent.mkdir(parents=True)
    state = model.default_state()
    state["schemaVersion"] = 4
    state.pop("tenantFoundation")
    state["scope"].update(
        {
            "entraTenantId": "tenant-id",
            "workdayTenant": "contoso",
        }
    )
    state["identifiers"].update(
        {
            "entraAppId": "app-id",
            "entraAppObjectId": "app-object-id",
            "entraServicePrincipalId": "service-principal-id",
            "entraAppIdUri": "api://app-id",
            "microsoftEntraIdentifier": (
                "https://sts.windows.net/tenant-id/"
            ),
            "entraLoginUrl": (
                "https://login.microsoftonline.com/tenant-id/saml2"
            ),
            "replyUrl": "https://www.workday.com/saml/acs",
            "workdaySamlEntityId": "http://www.workday.com/contoso",
            "scopeGuid": "scope-id",
            "signingCertificate": {
                "thumbprint": "thumbprint",
                "validFrom": "2026-01-01",
                "validTo": "2027-01-01",
            },
            "oauthClientId": "oauth-client-id",
        }
    )
    state["endpoints"].update(
        {
            "oauthTokenUrl": "https://example.workday.com/oauth/token",
            "restBaseUrl": "https://example.workday.com/ccx/api",
            "soapBaseUrl": "https://example.workday.com/ccx/service/contoso",
        }
    )
    for phase_id in ("preflight", "entra", "workday-admin"):
        actions = sorted(model.PHASE_REQUIRED_ACTIONS[phase_id])
        phase = state["phases"][phase_id]
        phase["status"] = "complete"
        phase["completedActions"] = actions
        phase["evidence"] = [
            {"action": action, "outcome": "verified"} for action in actions
        ]
    path.write_text(json.dumps(state), encoding="utf-8")

    upgraded = store_module.WorkdayConnectStore(tmp_path).initialize()

    assert upgraded["schemaVersion"] == 9
    assert upgraded["migration"]["source"] == "workday-connect-state-v4"
    assert upgraded["tenantFoundation"]["scope"] == {
        "entraTenantId": "tenant-id",
        "workdayTenant": "contoso",
    }
    assert path.with_name("config.pre-v9.json").exists()


def test_v7_ready_state_requests_one_flightcheck_migration_baseline(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    from workday_connect_store import WorkdayConnectStore

    document = model.default_state()
    document["schemaVersion"] = 7
    historical_v7_actions = {
        "preflight": ("verify-target", "verify-package"),
        "entra": (
            "exact-application-discovered",
            "administrator-configuration-verified",
        ),
        "workday-admin": ("administrator-response-validated",),
        "connections": ("physical-connections-verified",),
        "runtime": (
            "connection-references-bound",
            "runtime-flows-active",
            "delegated-authorization-configured",
            "runtime-template-configured",
            "user-context-v2-configured",
            "agent-parameter-sharing-verified",
            "flow-attachment-confirmed",
            "workday-topics-activated",
        ),
        "employee-validation": ("signed-in-scenario",),
    }
    for phase_id, phase in document["phases"].items():
        phase.pop("validationProfiles")
        phase.pop("employeeTestAttempt", None)
        for action in historical_v7_actions[phase_id]:
            phase["completedActions"].append(action)
            phase["evidence"].append(
                {"action": action, "outcome": "verified"}
            )
        phase["status"] = "complete"
    document["status"] = "ready"
    path = tmp_path / ".local" / "connect" / "workday-da" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(document), encoding="utf-8")

    upgraded = WorkdayConnectStore(tmp_path).load()

    assert upgraded["schemaVersion"] == 9
    assert upgraded["status"] == "in-progress"
    assert (
        upgraded["phases"]["employee-validation"]["status"]
        == "active"
    )
    assert upgraded["migration"]["flightcheckBaselineRequired"] is True
    assert upgraded["migration"]["legacyReady"] is True
    assert upgraded["phases"]["runtime"]["status"] == "complete"
    assert upgraded["phases"]["connections"]["completedActions"] == [
        "physical-connections-verified",
        "verify-package",
    ]
    assert all(
        phase["validationProfiles"] == {}
        for phase in upgraded["phases"].values()
    )


def test_v7_ready_migration_cannot_accept_stale_employee_evidence(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    from workday_connect_store import (
        WorkdayConnectStore,
        WorkdayConnectStoreError,
    )

    document = model.default_state()
    document["schemaVersion"] = 7
    for phase_id, phase in document["phases"].items():
        phase.pop("validationProfiles")
        phase.pop("employeeTestAttempt", None)
        for action in model.PHASE_REQUIRED_ACTIONS[phase_id]:
            phase["completedActions"].append(action)
            phase["evidence"].append(
                {"action": action, "outcome": "verified"}
            )
        phase["status"] = "complete"
    document["status"] = "ready"
    path = tmp_path / ".local" / "connect" / "workday-da" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    store = WorkdayConnectStore(tmp_path)
    store.load()

    assert store.prepare_migration_employee_test_attempt() is False
    state = store.load()
    employee = state["phases"]["employee-validation"]
    assert employee["status"] == "active"
    assert employee["completedActions"] == []
    assert employee["evidence"] == []
    assert employee["employeeTestAttempt"] is None
    assert (
        state["migration"]["flightcheckBaselineOutcome"]
        == "employee-validation-required"
    )

    with pytest.raises(
        WorkdayConnectStoreError,
        match="bounded employee test attempt",
    ):
        store.complete_flightcheck_migration()


def test_v7_ready_migration_requires_final_readiness_after_preparing_attempt(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    from workday_connect_store import (
        WorkdayConnectStore,
        WorkdayConnectStoreError,
    )

    document = model.default_state()
    document["schemaVersion"] = 7
    runtime_plan = {
        "phase": "runtime",
        "scope": {"environmentId": "environment-id"},
        "actions": ["Configure runtime"],
        "flows": [{"name": "REST", "workflowId": "flow-id"}],
    }
    runtime = document["phases"]["runtime"]
    runtime["approvedPlan"] = runtime_plan
    runtime["approvedPlanHash"] = model.plan_hash(runtime_plan)
    for phase_id, phase in document["phases"].items():
        phase.pop("validationProfiles")
        phase.pop("employeeTestAttempt", None)
        for action in model.PHASE_REQUIRED_ACTIONS[phase_id]:
            evidence = {"action": action, "outcome": "verified"}
            if (
                phase_id == "runtime"
                and action == "flow-attachment-confirmed"
            ):
                evidence["flowNames"] = ["REST"]
            if (
                phase_id == "employee-validation"
                and action == "signed-in-scenario"
            ):
                evidence["timestamp"] = "2026-09-28T12:00:00Z"
            phase["completedActions"].append(action)
            phase["evidence"].append(evidence)
        phase["status"] = "complete"
    document["status"] = "ready"
    path = tmp_path / ".local" / "connect" / "workday-da" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    store = WorkdayConnectStore(tmp_path)
    store.load()

    assert store.prepare_migration_employee_test_attempt() is True
    with pytest.raises(
        WorkdayConnectStoreError,
        match="final readiness profile",
    ):
        store.complete_flightcheck_migration()

    state = store.load()
    assert (
        state["phases"]["employee-validation"]["employeeTestAttempt"][
            "status"
        ]
        == "validating"
    )
    assert state["status"] == "in-progress"
    assert state["migration"]["flightcheckBaselineRequired"] is True


def test_v7_migration_repairs_malformed_backup(tmp_path: Path) -> None:
    import workday_connect_model as model
    from workday_connect_store import WorkdayConnectStore

    document = model.default_state()
    document["schemaVersion"] = 7
    for phase in document["phases"].values():
        phase.pop("validationProfiles")
        phase.pop("employeeTestAttempt", None)
    path = tmp_path / ".local" / "connect" / "workday-da" / "config.json"
    backup = path.with_name("config.pre-v9.json")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    backup.write_text('{"schemaVersion": 7}', encoding="utf-8")

    WorkdayConnectStore(tmp_path).load()

    assert json.loads(backup.read_text(encoding="utf-8")) == document


def test_v8_package_evidence_moves_from_preflight_to_connections(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    from workday_connect_store import WorkdayConnectStore

    document = model.default_state()
    document["schemaVersion"] = 8
    preflight = document["phases"]["preflight"]
    preflight["status"] = "complete"
    preflight["completedActions"] = ["verify-target", "verify-package"]
    package_evidence = {
        "action": "verify-package",
        "outcome": "passed",
        "packageSchema": "msdyn_EssWorkdayRuntime",
        "packageInstalled": True,
    }
    preflight["evidence"] = [
        {"action": "verify-target", "outcome": "passed"},
        package_evidence,
    ]
    path = tmp_path / ".local" / "connect" / "workday-da" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(document), encoding="utf-8")

    upgraded = WorkdayConnectStore(tmp_path).load()

    assert upgraded["schemaVersion"] == 9
    assert upgraded["phases"]["preflight"]["completedActions"] == [
        "verify-target"
    ]
    assert upgraded["phases"]["preflight"]["evidence"] == [
        {"action": "verify-target", "outcome": "passed"}
    ]
    connections = upgraded["phases"]["connections"]
    assert connections["completedActions"] == ["verify-package"]
    assert connections["evidence"] == [package_evidence]
    assert path.with_name("config.pre-v9.json").exists()


def test_v8_package_action_without_evidence_is_safely_reopened(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    from workday_connect_store import WorkdayConnectStore

    document = model.default_state()
    document["schemaVersion"] = 8
    preflight = document["phases"]["preflight"]
    preflight["status"] = "complete"
    preflight["completedActions"] = ["verify-target", "verify-package"]
    preflight["evidence"] = [{"action": "verify-target", "outcome": "passed"}]
    path = tmp_path / ".local" / "connect" / "workday-da" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(document), encoding="utf-8")

    upgraded = WorkdayConnectStore(tmp_path).load()

    assert upgraded["schemaVersion"] == 9
    assert upgraded["phases"]["preflight"]["status"] == "complete"
    assert upgraded["phases"]["preflight"]["completedActions"] == [
        "verify-target"
    ]
    assert upgraded["phases"]["connections"]["completedActions"] == []


def test_v8_ready_state_requires_flightcheck_migration_baseline(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    from workday_connect_store import WorkdayConnectStore

    document = model.default_state()
    document["schemaVersion"] = 8
    historical_v8_actions = {
        "preflight": ("verify-target", "verify-package"),
        "entra": (
            "exact-application-discovered",
            "administrator-configuration-verified",
        ),
        "workday-admin": ("administrator-response-validated",),
        "connections": ("physical-connections-verified",),
        "runtime": (
            "connection-references-bound",
            "runtime-flows-active",
            "delegated-authorization-configured",
            "runtime-template-configured",
            "user-context-v2-configured",
            "agent-parameter-sharing-verified",
            "flow-attachment-confirmed",
            "workday-topics-activated",
        ),
        "employee-validation": ("signed-in-scenario",),
    }
    for phase_id, phase in document["phases"].items():
        phase.pop("validationProfiles")
        phase.pop("employeeTestAttempt", None)
        for action in historical_v8_actions[phase_id]:
            phase["completedActions"].append(action)
            phase["evidence"].append(
                {"action": action, "outcome": "verified"}
            )
        phase["status"] = "complete"
    document["status"] = "ready"
    path = tmp_path / ".local" / "connect" / "workday-da" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(document), encoding="utf-8")

    upgraded = WorkdayConnectStore(tmp_path).load()

    assert upgraded["schemaVersion"] == 9
    assert upgraded["status"] == "in-progress"
    assert upgraded["migration"]["source"] == "workday-connect-state-v8"
    assert upgraded["migration"]["legacyReady"] is True
    assert upgraded["migration"]["flightcheckBaselineRequired"] is True
    assert upgraded["phases"]["runtime"]["status"] == "complete"
    assert upgraded["phases"]["employee-validation"]["status"] == "active"


def test_operation_guard_rejects_overlapping_mutating_session(
    tmp_path: Path,
) -> None:
    from workday_connect_store import (
        WorkdayConnectStore,
        WorkdayConnectStoreError,
    )

    first = WorkdayConnectStore(tmp_path, lock_timeout=0.05)
    second = WorkdayConnectStore(tmp_path, lock_timeout=0.05)

    with first.operation_guard():
        with pytest.raises(
            WorkdayConnectStoreError,
            match="Another /connect workday session",
        ):
            with second.operation_guard():
                pass


def test_profile_blocking_preserves_lifecycle_evidence_and_plans(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    from workday_connect_flightcheck import (
        effective_validation_state,
        validation_input_fingerprint,
    )
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    for phase_id in ("preflight", "entra", "workday-admin", "connections"):
        for action in model.PHASE_REQUIRED_ACTIONS[phase_id]:
            store.complete_action(
                phase_id,
                action,
                evidence={"outcome": "verified"},
            )
        store.set_phase_status(phase_id, "complete")
    plan = {
        "phase": "runtime",
        "scope": {"environmentId": "environment-id"},
        "actions": ["Configure runtime"],
    }
    store.approve_plan("runtime", plan)
    store.complete_action(
        "runtime",
        "runtime-template-configured",
        evidence={"outcome": "verified"},
    )

    state = store.block_validation_profile(
        "runtime",
        "workday-da:dataverse-ready",
        error_type="flightcheck-profile-not-ready",
        message="Runtime readiness needs remediation.",
        customer_remediation="Review Runtime and retry.",
        input_fingerprint=validation_input_fingerprint(
            effective_validation_state(tmp_path, store.load()),
            "workday-da:dataverse-ready",
        ),
        source_profile="workday-da:dataverse-ready",
    )

    runtime = state["phases"]["runtime"]
    assert runtime["status"] == "blocked"
    assert runtime["completedActions"] == ["runtime-template-configured"]
    assert runtime["evidence"][0]["outcome"] == "verified"
    assert runtime["approvedPlan"] == plan


def test_completed_phase_evidence_refresh_clears_stale_profile(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    from workday_connect_flightcheck import (
        effective_validation_state,
        validation_input_fingerprint,
    )
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    store.merge_section(
        "scope",
        {
            "environmentId": "environment-id",
            "dataverseUrl": "https://example.crm.dynamics.com",
            "entraTenantId": "tenant-id",
            "agent": {
                "slug": "ess-hr",
                "schemaName": "contoso_agent",
                "botId": "bot-id",
            },
        },
    )
    store.merge_section(
        "operators",
        {"powerPlatformMaker": {"username": "maker@example.com"}},
    )
    _complete_phase(
        store,
        "preflight",
        set(model.PHASE_REQUIRED_ACTIONS["preflight"]),
    )
    current = store.load()
    store.record_validation_profile(
        "preflight",
        {
            "profile": "workday-da:setup-readiness",
            "sourceProfile": "workday-da:setup-readiness",
            "schemaVersion": "flightcheck.result.v2",
            "overall": "READY",
            "target": {
                "realm": "dev",
                "environmentId": "environment-id",
                "environmentUrl": "https://example.crm.dynamics.com",
                "tenantId": "tenant-id",
                "agentSlug": "ess-hr",
                "agentSchemaName": "contoso_agent",
                "agentId": "bot-id",
            },
            "checkpointStatuses": {"DA-AGENT-001": "Passed"},
            "acceptedSuppressions": [],
            "remediationIds": [],
            "accepted": True,
            "migrationBaseline": False,
            "inputFingerprint": validation_input_fingerprint(
                effective_validation_state(tmp_path, current),
                "workday-da:setup-readiness",
            ),
            "validatedAt": "2026-09-28T12:00:00Z",
        },
    )

    state = store.complete_action(
        "preflight",
        "verify-target",
        evidence={"outcome": "verified", "environmentId": "changed"},
    )

    assert state["phases"]["preflight"]["status"] == "active"
    assert state["phases"]["preflight"]["validationProfiles"] == {}
    assert state["phases"]["entra"]["status"] == "pending"


def test_successful_retry_persists_current_readiness_fingerprint(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    from workday_connect_flightcheck import (
        effective_validation_state,
        validation_input_fingerprint,
    )
    from workday_connect_store import WorkdayConnectStore

    profile = "workday-da:setup-readiness"
    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    _complete_phase(
        store,
        "preflight",
        set(model.PHASE_REQUIRED_ACTIONS["preflight"]),
    )
    store.block_validation_profile(
        "preflight",
        profile,
        error_type="flightcheck-client-unavailable",
        message="Readiness client unavailable.",
        customer_remediation="Sign in and retry.",
        input_fingerprint=validation_input_fingerprint(
            effective_validation_state(tmp_path, store.load()),
            profile,
        ),
        source_profile=profile,
    )
    blocked = store.load()
    blocked_fingerprint = validation_input_fingerprint(
        effective_validation_state(tmp_path, blocked),
        profile,
    )
    updated = store.record_validation_profile(
        "preflight",
        {
            "profile": profile,
            "sourceProfile": profile,
            "schemaVersion": "flightcheck.result.v2",
            "overall": "READY",
            "target": {
                "realm": "dev",
                "environmentId": "",
                "environmentUrl": "",
                "tenantId": "",
                "agentSlug": "",
                "agentSchemaName": "",
                "agentId": "",
            },
            "checkpointStatuses": {
                "DA-AGENT-001": "Passed",
                "DA-CONTENT-001": "Passed",
            },
            "acceptedSuppressions": [],
            "remediationIds": [],
            "accepted": True,
            "migrationBaseline": False,
            "inputFingerprint": blocked_fingerprint,
        },
    )
    store.set_phase_status("preflight", "complete")

    persisted = updated["phases"]["preflight"]["validationProfiles"][profile]
    assert persisted["inputFingerprint"] != blocked_fingerprint
    assert store.status()["phases"][0]["readiness"]["accepted"] is True


def test_employee_attempt_uses_reviewed_runtime_flow_ids(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    for phase_id in (
        "preflight",
        "entra",
        "workday-admin",
        "connections",
    ):
        for action in model.PHASE_REQUIRED_ACTIONS[phase_id]:
            store.complete_action(
                phase_id,
                action,
                evidence={"outcome": "verified"},
            )
        store.set_phase_status(phase_id, "complete")
    runtime_plan = {
        "phase": "runtime",
        "scope": {"environmentId": "environment-id"},
        "actions": ["Configure runtime"],
        "flows": [
            {"name": "REST", "workflowId": "flow-b"},
            {"name": "SOAP", "workflowId": "flow-a"},
            {"name": "References", "workflowId": "flow-c"},
        ],
    }
    store.approve_plan("runtime", runtime_plan)
    for action in model.PHASE_REQUIRED_ACTIONS["runtime"]:
        evidence = {"outcome": "verified"}
        if action == "flow-attachment-confirmed":
            evidence["flowNames"] = ["REST", "SOAP"]
        store.complete_action(
            "runtime",
            action,
            evidence=evidence,
        )
    store.set_phase_status("runtime", "complete")

    state = store.begin_employee_test_attempt()
    attempt = state["phases"]["employee-validation"][
        "employeeTestAttempt"
    ]

    assert attempt["status"] == "active"
    assert attempt["expectedFlowIds"] == ["flow-a", "flow-b"]
    assert attempt["correlationMode"] == "bounded-window-flow-set"

    store.freeze_employee_test_attempt(
        evidence_timestamp=attempt["startedAt"],
    )
    replay = store.freeze_employee_test_attempt(
        evidence_timestamp=attempt["startedAt"],
    )
    assert (
        replay["phases"]["employee-validation"]["employeeTestAttempt"][
            "status"
        ]
        == "validating"
    )


@pytest.mark.parametrize(
    "attachment_names",
    [
        [],
        ["REST", "Missing"],
        ["REST", "REST"],
    ],
)
def test_employee_attempt_requires_exact_attachment_flow_mapping(
    tmp_path: Path,
    attachment_names: list[str],
) -> None:
    import workday_connect_model as model
    from workday_connect_store import (
        WorkdayConnectStore,
        WorkdayConnectStoreError,
    )

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    for phase_id in (
        "preflight",
        "entra",
        "workday-admin",
        "connections",
    ):
        _complete_phase(
            store,
            phase_id,
            set(model.PHASE_REQUIRED_ACTIONS[phase_id]),
        )
    _complete_runtime_for_employee(
        store,
        model,
        attachment_names=attachment_names,
    )

    with pytest.raises(
        WorkdayConnectStoreError,
        match="does not map",
    ):
        store.begin_employee_test_attempt()


def test_abandoned_employee_attempt_is_journaled_and_retryable(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    for phase_id in (
        "preflight",
        "entra",
        "workday-admin",
        "connections",
    ):
        _complete_phase(
            store,
            phase_id,
            set(model.PHASE_REQUIRED_ACTIONS[phase_id]),
        )
    _complete_runtime_for_employee(
        store,
        model,
        attachment_names=["REST"],
    )
    first = store.begin_employee_test_attempt()["phases"][
        "employee-validation"
    ]["employeeTestAttempt"]

    abandoned = store.abandon_employee_test_attempt()
    attempt = abandoned["phases"]["employee-validation"][
        "employeeTestAttempt"
    ]
    replay = store.abandon_employee_test_attempt()
    second = store.begin_employee_test_attempt()["phases"][
        "employee-validation"
    ]["employeeTestAttempt"]

    assert attempt["status"] == "failed"
    assert attempt["outcome"] == "abandoned"
    assert (
        replay["phases"]["employee-validation"]["employeeTestAttempt"]
        == attempt
    )
    assert second["attemptId"] != first["attemptId"]
    assert any(
        event["event"] == "abandoned"
        and event["phase"] == "employee-validation"
        for event in abandoned["lifecycle"]["journal"]
    )


def test_employee_attempt_rejects_evidence_outside_bounded_window(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    from workday_connect_store import (
        WorkdayConnectStore,
        WorkdayConnectStoreError,
    )

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    for phase_id in (
        "preflight",
        "entra",
        "workday-admin",
        "connections",
    ):
        for action in model.PHASE_REQUIRED_ACTIONS[phase_id]:
            store.complete_action(
                phase_id,
                action,
                evidence={"outcome": "verified"},
            )
        store.set_phase_status(phase_id, "complete")
    runtime_plan = {
        "phase": "runtime",
        "scope": {"environmentId": "environment-id"},
        "actions": ["Configure runtime"],
        "flows": [{"name": "REST", "workflowId": "flow-id"}],
    }
    store.approve_plan("runtime", runtime_plan)
    for action in model.PHASE_REQUIRED_ACTIONS["runtime"]:
        evidence = {"outcome": "verified"}
        if action == "flow-attachment-confirmed":
            evidence["flowNames"] = ["REST"]
        store.complete_action(
            "runtime",
            action,
            evidence=evidence,
        )
    store.set_phase_status("runtime", "complete")
    store.begin_employee_test_attempt()

    with pytest.raises(
        WorkdayConnectStoreError,
        match="outside the bounded",
    ):
        store.freeze_employee_test_attempt(
            evidence_timestamp="2000-01-01T00:00:00Z",
        )


def test_blocked_final_readiness_allows_a_new_employee_attempt(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    from workday_connect_flightcheck import (
        effective_validation_state,
        validation_input_fingerprint,
    )
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    for phase_id in (
        "preflight",
        "entra",
        "workday-admin",
        "connections",
    ):
        for action in model.PHASE_REQUIRED_ACTIONS[phase_id]:
            store.complete_action(
                phase_id,
                action,
                evidence={"outcome": "verified"},
            )
        store.set_phase_status(phase_id, "complete")
    store.approve_plan(
        "runtime",
        {
            "phase": "runtime",
            "scope": {"environmentId": "environment-id"},
            "actions": ["Configure runtime"],
            "flows": [{"name": "REST", "workflowId": "flow-id"}],
        },
    )
    for action in model.PHASE_REQUIRED_ACTIONS["runtime"]:
        evidence = {"outcome": "verified"}
        if action == "flow-attachment-confirmed":
            evidence["flowNames"] = ["REST"]
        store.complete_action(
            "runtime",
            action,
            evidence=evidence,
        )
    store.set_phase_status("runtime", "complete")
    first = store.begin_employee_test_attempt()["phases"][
        "employee-validation"
    ]["employeeTestAttempt"]
    store.freeze_employee_test_attempt(
        evidence_timestamp=first["startedAt"],
    )
    state = store.load()
    store.block_validation_profile(
        "employee-validation",
        "workday-da:final",
        error_type="flightcheck-transport-error",
        message="Readiness service failed.",
        customer_remediation="Retry employee validation.",
        input_fingerprint=validation_input_fingerprint(
            effective_validation_state(tmp_path, state),
            "workday-da:final",
        ),
        source_profile="workday-da:final",
    )

    second = store.begin_employee_test_attempt()["phases"][
        "employee-validation"
    ]["employeeTestAttempt"]

    assert second["attemptId"] != first["attemptId"]
    assert second["status"] == "active"


def test_profile_result_is_rejected_after_target_changes(
    tmp_path: Path,
) -> None:
    from workday_connect_flightcheck import evaluate_contract
    from workday_connect_store import (
        WorkdayConnectStore,
        WorkdayConnectStoreError,
    )

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    store.merge_section(
        "scope",
        {
            "environmentId": "environment-a",
            "dataverseUrl": "https://a.crm.dynamics.com",
            "entraTenantId": "tenant-id",
            "agent": {
                "slug": "ess-hr",
                "schemaName": "contoso_agent",
                "botId": "bot-id",
            },
        },
    )
    store.merge_section(
        "operators",
        {"powerPlatformMaker": {"username": "maker@example.com"}},
    )
    state = store.load()
    checkpoints = [
        "DA-AGENT-001",
        "DA-CONTENT-001",
    ]
    context = {
        "realm": "dev",
        "environmentId": "environment-a",
        "environmentUrl": "https://a.crm.dynamics.com",
        "tenantId": "tenant-id",
        "agentSlug": "ess-hr",
        "agentSchemaName": "contoso_agent",
        "agentId": "bot-id",
    }
    summary = evaluate_contract(
        {
            "schemaVersion": "flightcheck.result.v2",
            "profile": "workday-da:setup-readiness",
            "profileCheckpoints": checkpoints,
            "profileFamilies": {},
            "emittedCheckpoints": checkpoints,
            "requestedValidationContext": context,
            "validationContext": context,
            "clientAvailability": {
                client: {
                    "required": True,
                    "available": True,
                    "authenticatedAccountVerified": True,
                }
                for client in ("agentbuilder",)
            },
            "executionErrors": [],
            "overall": "READY",
            "counts": {},
            "results": [
                {
                    "checkpointId": checkpoint,
                    "status": "Passed",
                    "severity": "Info",
                    "automationType": "Automated",
                    "remediationId": "",
                    "evidence": {},
                }
                for checkpoint in checkpoints
            ],
        },
        state,
        "workday-da:setup-readiness",
    )
    store.merge_section("scope", {"environmentId": "environment-b"})

    with pytest.raises(
        WorkdayConnectStoreError,
        match="state changed",
    ):
        store.record_validation_profile("preflight", summary)


def test_matching_foundation_restores_workday_after_entra_reread(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    store.merge_section(
        "scope",
        {
            "agent": {"slug": "agent-a"},
            "environmentId": "environment-a",
            "entraTenantId": "tenant-id",
            "workdayTenant": "contoso",
        },
    )
    _set_foundation_data(store)
    for phase_id in ("preflight", "entra", "workday-admin"):
        _complete_phase(
            store,
            phase_id,
            set(model.PHASE_REQUIRED_ACTIONS[phase_id]),
        )
    store.capture_tenant_foundation()

    changed = store.merge_section(
        "scope",
        {
            "agent": {"slug": "agent-b"},
            "environmentId": "environment-b",
        },
    )
    assert changed["phases"]["workday-admin"]["status"] == "pending"
    assert changed["tenantFoundation"] is not None

    store.merge_section(
        "identifiers",
        {
            "signingCertificate": {
                "thumbprint": "TH UM BP RI NT",
                "validFrom": "2026-01-01T12:00:00+00:00",
                "validTo": "2027-01-01T12:00:00+00:00",
            }
        },
    )
    _complete_phase(
        store,
        "preflight",
        set(model.PHASE_REQUIRED_ACTIONS["preflight"]),
    )
    _complete_phase(
        store,
        "entra",
        set(model.PHASE_REQUIRED_ACTIONS["entra"]),
    )
    restored, reused = store.restore_workday_foundation()

    assert reused is True
    assert restored["phases"]["workday-admin"]["status"] == "active"
    assert (
        restored["phases"]["workday-admin"]["administrator"]["substage"]
        == "collecting-evidence"
    )
    assert restored["phases"]["connections"]["status"] == "pending"
    assert any(
        evidence["action"] == "tenant-foundation-reused"
        for evidence in restored["phases"]["workday-admin"]["evidence"]
    )


def test_foundation_is_not_reused_for_a_different_workday_tenant(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
    store.merge_section(
        "scope",
        {
            "entraTenantId": "tenant-id",
            "workdayTenant": "contoso",
        },
    )
    _set_foundation_data(store)
    for phase_id in ("preflight", "entra", "workday-admin"):
        _complete_phase(
            store,
            phase_id,
            set(model.PHASE_REQUIRED_ACTIONS[phase_id]),
        )
    store.capture_tenant_foundation()

    store.merge_section("scope", {"workdayTenant": "fabrikam"})
    restored, reused = store.restore_workday_foundation()

    assert reused is False
    assert restored["tenantFoundation"] is None
    assert restored["phases"]["workday-admin"]["status"] == "pending"


def test_workday_endpoint_drift_clears_tenant_foundation(
    tmp_path: Path,
) -> None:
    import workday_connect_model as model
    from workday_connect_store import WorkdayConnectStore

    store = WorkdayConnectStore(tmp_path)
    store.initialize()
    store.merge_section(
        "scope",
        {
            "entraTenantId": "tenant-id",
            "workdayTenant": "contoso",
        },
    )
    _set_foundation_data(store)
    for phase_id in ("preflight", "entra", "workday-admin"):
        _complete_phase(
            store,
            phase_id,
            set(model.PHASE_REQUIRED_ACTIONS[phase_id]),
        )
    store.capture_tenant_foundation()

    state = store.merge_section(
        "endpoints",
        {
            "restBaseUrl": "https://new.example.workday.com/ccx/api",
        },
    )

    assert state["tenantFoundation"] is None
