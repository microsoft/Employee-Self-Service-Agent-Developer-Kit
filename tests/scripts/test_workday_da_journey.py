# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Outcome-based Workday DA journey evaluations across multiple turns."""

from __future__ import annotations

import json

from workday_da_state import WorkdayDAStateStore, _atomic_write_text


def _evidence(note: str) -> dict:
    return {
        "outcome": "CONFIRMED",
        "provenance": "user-acknowledgement",
        "note": note,
        "capturedAt": "2026-09-25T12:00:00Z",
    }


def test_fresh_setup_resume_drift_and_repair_journey(tmp_path) -> None:
    store = WorkdayDAStateStore(tmp_path)

    first_turn = store.initialize()
    assert first_turn["status"] == "in-progress"
    assert first_turn["setupStatus"]["DA1.1"]["state"] == "pending"

    store.update_row("DA1.1", checkpoint_result="Passed")
    config = json.loads(store.config_path.read_text(encoding="utf-8"))
    config["tenant"] = "tenant-one"
    _atomic_write_text(store.config_path, json.dumps(config, indent=2) + "\n")
    store.update_row(
        "DA2.1",
        checkpoint_result="Manual",
        result_source="user-acknowledgement",
        ack=True,
        evidence=_evidence("Workday SSO application confirmed."),
    )

    second_turn = store.revalidation_plan()
    assert any(
        action["stepId"] == "DA1.1"
        and action["mode"] == "checkpoint"
        for action in second_turn["actions"]
    )
    assert second_turn["config"]["setupStatus"]["DA2.1"]["state"] == "done"

    config = json.loads(store.config_path.read_text(encoding="utf-8"))
    config["tenant"] = "tenant-two"
    _atomic_write_text(store.config_path, json.dumps(config, indent=2) + "\n")
    third_turn = store.revalidation_plan()

    assert any(
        action["stepId"] == "DA2.1"
        and action["mode"] == "manual-evidence-stale"
        for action in third_turn["actions"]
    )
    assert third_turn["config"]["setupStatus"]["DA2.1"]["state"] == "in-progress"
    assert third_turn["config"]["status"] == "in-progress"


def test_failed_revalidation_blocks_and_invalidates_downstream_journey(
    tmp_path,
) -> None:
    store = WorkdayDAStateStore(tmp_path)
    store.initialize()
    store.update_row("DA1.1", checkpoint_result="Passed")
    store.revalidation_plan()

    failed = store.update_row("DA1.1", checkpoint_result="Failed")

    assert failed["setupStatus"]["DA1.1"]["state"] == "blocked"
    assert failed["setupStatus"]["DA5.1"]["state"] == "in-progress"
    assert "revalidation" not in failed
    assert failed["status"] == "in-progress"
