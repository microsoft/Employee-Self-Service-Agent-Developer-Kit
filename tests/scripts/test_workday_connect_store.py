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

    assert state["schemaVersion"] == 3
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
    assert path.with_name("config.pre-v3.json").exists()


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
    assert connect_tasks.read_text(encoding="utf-8") == (
        "legacy connect checklist"
    )


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

    assert state["phases"]["preflight"]["completedActions"] == [
        "verify-target"
    ]
    assert len(state["phases"]["preflight"]["evidence"]) == 1


def test_approved_plan_rejects_changed_target(tmp_path: Path) -> None:
    import workday_connect_store as store_module

    store = store_module.WorkdayConnectStore(tmp_path)
    store.initialize()
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


def test_status_returns_one_progress_line_and_next_phase(tmp_path: Path) -> None:
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
    assert status["progressText"].startswith("Progress: Preflight ✓ · Entra")
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

    assert upgraded["schemaVersion"] == 3
    assert upgraded["phases"]["preflight"]["status"] == "active"
    assert upgraded["migration"]["source"] == "workday-connect-state-v2"
