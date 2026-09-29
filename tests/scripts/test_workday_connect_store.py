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

    assert state["schemaVersion"] == 6
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
    assert path.with_name("config.pre-v6.json").exists()


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

    assert upgraded["schemaVersion"] == 6
    assert upgraded["lifecycle"]["correlationId"]
    assert upgraded["lifecycle"]["journal"] == []
    assert upgraded["migration"]["source"] == "workday-connect-state-v5"
    assert path.with_name("config.pre-v6.json").exists()


def test_early_v6_events_are_normalized_without_losing_history(
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
    assert event["timestamp"] == "2026-09-28T00:00:00Z"


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
    abandoned = state["lifecycle"]["journal"][-1]
    assert abandoned["event"] == "abandoned"
    assert abandoned["outcome"] == "cancelled"
    assert abandoned["phase"] == "preflight"
    assert abandoned["correlationId"] == original


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
    assert "| 2 | Microsoft Entra | Next |" in status["progressText"]
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


def _set_foundation_data(store, *, workday_tenant: str = "contoso") -> None:
    store.merge_section(
        "identifiers",
        {
            "entraAppId": "app-id",
            "entraAppObjectId": "app-object-id",
            "entraServicePrincipalId": "service-principal-id",
            "entraAppIdUri": "api://app-id",
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

    assert upgraded["schemaVersion"] == 6
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

    assert upgraded["schemaVersion"] == 6
    assert upgraded["status"] == "in-progress"
    assert upgraded["phases"]["runtime"]["status"] == "active"
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

    assert upgraded["schemaVersion"] == 6
    assert upgraded["migration"]["source"] == "workday-connect-state-v4"
    assert upgraded["tenantFoundation"]["scope"] == {
        "entraTenantId": "tenant-id",
        "workdayTenant": "contoso",
    }
    assert path.with_name("config.pre-v6.json").exists()


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
    assert restored["phases"]["workday-admin"]["status"] == "complete"
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
    assert restored["phases"]["workday-admin"]["status"] == "pending"
