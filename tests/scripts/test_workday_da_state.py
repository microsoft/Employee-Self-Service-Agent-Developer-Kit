# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for deterministic Workday DA persisted-state operations."""

from __future__ import annotations

import json
import os
from pathlib import Path

import portalocker
import pytest

import workday_da_state as state_module
from workday_da_state import (
    WorkdayDAStateConflictError,
    WorkdayDAStateError,
    WorkdayDAStateLockError,
    WorkdayDAStateStore,
)


TASK_TEMPLATE = (
    Path(__file__).parents[2]
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "skills"
    / "setup"
    / "workday-da"
    / "tasks.md"
)


def _config(root: Path) -> dict:
    return json.loads(
        (root / ".local/connect/workday-da/config.json").read_text(
            encoding="utf-8"
        )
    )


def _evidence(note: str = "Operator confirmed the current step.") -> dict:
    return {
        "outcome": "CONFIRMED",
        "provenance": "user-acknowledgement",
        "note": note,
        "capturedAt": "2026-09-25T12:00:00Z",
    }


def _mark_done(store: WorkdayDAStateStore, *step_ids: str) -> None:
    config = _config(store.workspace_root)
    for step_id in step_ids:
        row = config["setupStatus"][step_id]
        row["state"] = "done"
        row["verifiedBy"] = (
            "programmatic" if row["gate"] == "prog" else "attested"
        )
        row["evidence"] = _evidence(f"Fixture completed {step_id}.")
    state_module._atomic_write_text(
        store.config_path, json.dumps(config, indent=2) + "\n"
    )


def test_initialize_creates_complete_versioned_state_and_checklist(tmp_path) -> None:
    config = WorkdayDAStateStore(tmp_path).initialize()

    assert config["definitionVersion"] == 1
    assert config["stateSchemaVersion"] == 1
    assert config["status"] == "in-progress"
    assert len(config["setupStatus"]) == 21
    assert all(
        row["state"] == "pending" for row in config["setupStatus"].values()
    )
    checklist = (
        tmp_path / ".local/connect/workday-da/tasks.md"
    ).read_text(encoding="utf-8")
    assert checklist.count("status: pending") == 21
    assert ".local/setup/workday-da/tasks.md" not in str(
        WorkdayDAStateStore(tmp_path).checklist_path
    )


def test_initialize_moves_legacy_checklist_without_rewriting_it(tmp_path) -> None:
    legacy = tmp_path / ".local/setup/workday-da/tasks.md"
    legacy.parent.mkdir(parents=True)
    content = TASK_TEMPLATE.read_text(encoding="utf-8").replace(
        "status: pending", "status: done", 1
    ).replace("- [ ] **Install", "- [x] **Install", 1)
    legacy.write_text(content, encoding="utf-8")
    config_path = tmp_path / ".local/connect/workday-da/config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "status": "in-progress",
                "setupStatus": {
                    "DA1.1": {
                        "state": "done",
                        "checkpoint": "WD-DA-PKG-001",
                        "gate": "prog",
                        "verifiedBy": "programmatic",
                        "evidence": {
                            "outcome": "PASSED",
                            "provenance": "flightcheck",
                            "note": "Required package detected.",
                            "capturedAt": "2026-09-25T12:00:00Z",
                        },
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    timestamp = 1_700_000_000
    os.utime(legacy, (timestamp, timestamp))

    config = WorkdayDAStateStore(tmp_path).initialize()
    canonical = tmp_path / ".local/connect/workday-da/tasks.md"

    assert not legacy.exists()
    assert canonical.read_text(encoding="utf-8") == content
    assert canonical.stat().st_mtime == pytest.approx(timestamp, abs=1)
    assert config["setupStatus"]["DA1.1"]["state"] == "done"


def test_initialize_refuses_dual_checklist_copies(tmp_path) -> None:
    canonical = tmp_path / ".local/connect/workday-da/tasks.md"
    legacy = tmp_path / ".local/setup/workday-da/tasks.md"
    canonical.parent.mkdir(parents=True)
    legacy.parent.mkdir(parents=True)
    canonical.write_text("canonical", encoding="utf-8")
    legacy.write_text("legacy", encoding="utf-8")

    with pytest.raises(WorkdayDAStateConflictError, match="Both canonical"):
        WorkdayDAStateStore(tmp_path).initialize()

    assert canonical.read_text(encoding="utf-8") == "canonical"
    assert legacy.read_text(encoding="utf-8") == "legacy"


def test_initialize_refuses_corrupt_config_instead_of_resetting_it(tmp_path) -> None:
    path = tmp_path / ".local/connect/workday-da/config.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(WorkdayDAStateError, match="not valid JSON"):
        WorkdayDAStateStore(tmp_path).initialize()

    assert path.read_text(encoding="utf-8") == "{not-json"


def test_validate_rejects_partial_state_that_does_not_match_definition(
    tmp_path,
) -> None:
    store = WorkdayDAStateStore(tmp_path)
    store.initialize()
    config = _config(tmp_path)
    del config["setupStatus"]["DA5.1"]
    state_module._atomic_write_text(
        store.config_path, json.dumps(config, indent=2) + "\n"
    )

    with pytest.raises(WorkdayDAStateError, match="missing DA5.1"):
        store.validate()


def test_programmatic_pass_completes_row_and_updates_view(tmp_path) -> None:
    store = WorkdayDAStateStore(tmp_path)
    store.initialize()

    config = store.update_row(
        "DA1.1",
        checkpoint_result="Passed",
    )

    row = config["setupStatus"]["DA1.1"]
    assert row["state"] == "done"
    assert row["verifiedBy"] == "programmatic"
    assert row["evidence"]["provenance"] == "flightcheck"
    assert len(row["evidence"]["scopeFingerprint"]) == 64
    checklist = store.checklist_path.read_text(encoding="utf-8")
    assert "- [x] **Install the Workday extension package**" in checklist
    assert "id: DA1.1" in checklist
    assert "status: done" in checklist


def test_manual_row_requires_ack_and_structured_evidence(tmp_path) -> None:
    store = WorkdayDAStateStore(tmp_path)
    store.initialize()
    store.update_row("DA1.1", checkpoint_result="Passed")

    without_evidence = store.update_row(
        "DA2.1",
        checkpoint_result="Manual",
        ack=True,
    )
    assert without_evidence["setupStatus"]["DA2.1"]["state"] == "in-progress"

    completed = store.update_row(
        "DA2.1",
        checkpoint_result="Manual",
        result_source="user-acknowledgement",
        ack=True,
        evidence=_evidence(),
    )
    row = completed["setupStatus"]["DA2.1"]
    assert row["state"] == "done"
    assert row["verifiedBy"] == "attested"


def test_external_programmatic_pass_requires_evidence(tmp_path) -> None:
    store = WorkdayDAStateStore(tmp_path)
    store.initialize()
    _mark_done(store, "DA4.1", "DA4.2")

    missing = store.update_row(
        "DA4.3",
        checkpoint_result="Passed",
        result_source="external",
    )
    assert missing["setupStatus"]["DA4.3"]["state"] == "in-progress"

    completed = store.update_row(
        "DA4.3",
        checkpoint_result="Passed",
        result_source="external",
        evidence={
            "outcome": "PASSED",
            "provenance": "external-operation",
            "note": "Both connection references were verified after update.",
            "capturedAt": "2026-09-25T12:00:00Z",
        },
    )
    assert completed["setupStatus"]["DA4.3"]["state"] == "done"


def test_completion_rejects_pending_prerequisites(tmp_path) -> None:
    store = WorkdayDAStateStore(tmp_path)
    store.initialize()

    with pytest.raises(
        WorkdayDAStateError,
        match="Cannot complete DA2.1; prerequisites are not done: DA1.1",
    ):
        store.update_row(
            "DA2.1",
            checkpoint_result="Manual",
            result_source="user-acknowledgement",
            ack=True,
            evidence=_evidence(),
        )


def test_failure_overrides_ack_and_regresses_transitive_dependents(tmp_path) -> None:
    store = WorkdayDAStateStore(tmp_path)
    store.initialize()
    store.update_row("DA1.1", checkpoint_result="Passed")
    store.update_row(
        "DA2.1",
        checkpoint_result="Manual",
        result_source="user-acknowledgement",
        ack=True,
        evidence=_evidence(),
    )
    config = _config(tmp_path)
    config["setupStatus"]["DA5.1"].update(
        {
            "state": "done",
            "verifiedBy": "attested",
            "evidence": _evidence("Final scenario passed."),
        }
    )
    state_module._atomic_write_text(
        store.config_path, json.dumps(config, indent=2) + "\n"
    )

    failed = store.update_row(
        "DA1.1",
        checkpoint_result="Failed",
        ack=True,
    )

    assert failed["setupStatus"]["DA1.1"]["state"] == "blocked"
    assert failed["setupStatus"]["DA1.1"]["verifiedBy"] is None
    assert failed["setupStatus"]["DA2.1"]["state"] == "in-progress"
    assert failed["setupStatus"]["DA5.1"]["state"] == "in-progress"
    assert failed["status"] == "in-progress"


def test_unknown_config_fields_survive_round_trip(tmp_path) -> None:
    store = WorkdayDAStateStore(tmp_path)
    store.initialize()
    config = _config(tmp_path)
    config["futureProviderField"] = {"keep": True}
    state_module._atomic_write_text(
        store.config_path, json.dumps(config, indent=2) + "\n"
    )

    updated = store.update_row("DA1.1", checkpoint_result="Passed")

    assert updated["futureProviderField"] == {"keep": True}


def test_config_commit_survives_checklist_write_failure_and_reconcile_repairs(
    tmp_path, monkeypatch
) -> None:
    store = WorkdayDAStateStore(tmp_path)
    store.initialize()
    real_write = store._write_checklist

    def fail_checklist(_config):
        raise OSError("simulated view failure")

    monkeypatch.setattr(store, "_write_checklist", fail_checklist)
    with pytest.raises(WorkdayDAStateError, match="config was saved"):
        store.update_row("DA1.1", checkpoint_result="Passed")

    assert _config(tmp_path)["setupStatus"]["DA1.1"]["state"] == "done"
    monkeypatch.setattr(store, "_write_checklist", real_write)
    store.reconcile()
    assert "- [x] **Install the Workday extension package**" in (
        store.checklist_path.read_text(encoding="utf-8")
    )


def test_lock_contention_fails_without_mutation(tmp_path) -> None:
    store = WorkdayDAStateStore(tmp_path, lock_timeout=0.05)
    store.initialize()
    before = store.config_path.read_text(encoding="utf-8")

    with portalocker.Lock(
        str(store.lock_path),
        mode="a+",
        timeout=0,
        encoding="utf-8",
    ):
        with pytest.raises(WorkdayDAStateLockError, match="Another /connect"):
            store.update_row("DA1.1", checkpoint_result="Passed")

    assert store.config_path.read_text(encoding="utf-8") == before


def test_regress_row_clears_completion_and_derived_readiness(tmp_path) -> None:
    store = WorkdayDAStateStore(tmp_path)
    store.initialize()
    config = _config(tmp_path)
    for row in config["setupStatus"].values():
        row["state"] = "done"
        row["verifiedBy"] = (
            "programmatic" if row["gate"] == "prog" else "attested"
        )
    config["status"] = "ready"
    state_module._atomic_write_text(
        store.config_path, json.dumps(config, indent=2) + "\n"
    )

    regressed = store.regress_row("DA3.2")

    assert regressed["setupStatus"]["DA3.2"]["state"] == "in-progress"
    assert regressed["setupStatus"]["DA4.1"]["state"] == "in-progress"
    assert regressed["setupStatus"]["DA5.1"]["state"] == "in-progress"
    assert regressed["status"] == "in-progress"


def test_resume_requires_fresh_programmatic_verification(tmp_path) -> None:
    store = WorkdayDAStateStore(tmp_path)
    store.initialize()
    store.update_row("DA1.1", checkpoint_result="Passed")

    plan = store.revalidation_plan()

    assert plan["actions"] == [
        {
            "stepId": "DA1.1",
            "owner": "da-1",
            "mode": "checkpoint",
            "checkpoints": ["WD-DA-PKG-001"],
            "reason": "live-recheck",
        }
    ]
    assert plan["config"]["revalidation"]["requiredStepIds"] == ["DA1.1"]
    assert plan["config"]["status"] == "in-progress"

    refreshed = store.update_row("DA1.1", checkpoint_result="Passed")
    assert "revalidation" not in refreshed


def test_scope_change_regresses_manual_evidence_and_dependents(tmp_path) -> None:
    store = WorkdayDAStateStore(tmp_path)
    store.initialize()
    store.update_row("DA1.1", checkpoint_result="Passed")
    config = _config(tmp_path)
    config["tenant"] = "tenant-one"
    state_module._atomic_write_text(
        store.config_path, json.dumps(config, indent=2) + "\n"
    )
    store.update_row(
        "DA2.1",
        checkpoint_result="Manual",
        result_source="user-acknowledgement",
        ack=True,
        evidence=_evidence(),
    )
    config = _config(tmp_path)
    config["tenant"] = "tenant-two"
    config["setupStatus"]["DA5.1"].update(
        {
            "state": "done",
            "verifiedBy": "attested",
            "evidence": {
                **_evidence("Final scenario passed."),
                "scopeFingerprint": "0" * 64,
            },
        }
    )
    state_module._atomic_write_text(
        store.config_path, json.dumps(config, indent=2) + "\n"
    )

    plan = store.revalidation_plan()

    stale = {
        action["stepId"]
        for action in plan["actions"]
        if action["mode"] == "manual-evidence-stale"
    }
    assert "DA2.1" in stale
    assert plan["config"]["setupStatus"]["DA2.1"]["state"] == "in-progress"
    assert plan["config"]["setupStatus"]["DA5.1"]["state"] == "in-progress"
    assert plan["config"]["status"] == "in-progress"


def test_unchanged_manual_scope_preserves_completion(tmp_path) -> None:
    store = WorkdayDAStateStore(tmp_path)
    store.initialize()
    store.update_row("DA1.1", checkpoint_result="Passed")
    store.update_row(
        "DA2.1",
        checkpoint_result="Manual",
        result_source="user-acknowledgement",
        ack=True,
        evidence=_evidence(),
    )

    plan = store.revalidation_plan()

    assert not any(
        action["stepId"] == "DA2.1"
        and action["mode"] == "manual-evidence-stale"
        for action in plan["actions"]
    )
    assert plan["config"]["setupStatus"]["DA2.1"]["state"] == "done"
