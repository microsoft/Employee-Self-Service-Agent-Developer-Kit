# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Contracts for the simplified Workday DA orchestration."""

import argparse
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKDAY_DA = (
    _REPO_ROOT
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "skills"
    / "setup"
    / "workday-da"
)


def test_orchestrator_resumes_from_controller_status() -> None:
    text = (_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "python scripts/workday_connect.py status" in text
    assert "nextPhaseId" in text
    assert "Do not create, copy, update, or infer status from a Markdown" in (
        normalized
    )
    assert "resume the same blocker" in text
    assert "controller status is `ready`" in text


def test_preflight_is_one_identity_aware_operation() -> None:
    text = (_WORKDAY_DA / "install-extension.md").read_text(encoding="utf-8")

    assert "workday_connect.py preflight" in text
    assert "pins and verifies the resulting PAC account" in text
    assert "verifies the exact Dataverse URL directly" in text
    assert "detects or installs the package" in text
    assert "manual-install instruction" in text


def test_connections_are_proven_before_runtime_apply() -> None:
    text = (_WORKDAY_DA / "configure-power-platform.md").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(text.split())

    assert text.index("## Connections") < text.index(
        "## Runtime approval and apply"
    )
    assert "runtime-plan" in text
    assert "record-connections" in text
    assert "runtime-apply" in text
    assert "one shared Dataverse session" in normalized
    assert "delegated" in text
    assert "User Context V2" in text


def test_readiness_requires_real_employee_runtime_evidence() -> None:
    text = (_WORKDAY_DA / "verify-connection.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "real signed-in employee scenario" in text
    assert "returns real" in text
    assert "without an unexpected repeated sign-in" in text
    assert "Never record employee data or credentials" in normalized
    assert "Do not reset completed phases" in normalized


def test_capability_claims_match_controller_surface() -> None:
    skill = (_WORKDAY_DA / "SKILL.md").read_text(encoding="utf-8")
    entra = (_WORKDAY_DA / "provision-entra-app.md").read_text(
        encoding="utf-8"
    )
    tenant = (_WORKDAY_DA / "configure-tenant.md").read_text(
        encoding="utf-8"
    )
    power_platform = (
        _WORKDAY_DA / "configure-power-platform.md"
    ).read_text(encoding="utf-8")
    employee = (_WORKDAY_DA / "verify-connection.md").read_text(
        encoding="utf-8"
    )

    normalized = {
        "skill": " ".join(skill.split()),
        "entra": " ".join(entra.split()),
        "tenant": " ".join(tenant.split()),
        "power_platform": " ".join(power_platform.split()),
        "employee": " ".join(employee.split()),
    }

    assert "## Capability contract" in skill
    assert "Claim an automated change only after" in normalized["skill"]
    assert "does not create or modify the Entra application" in (
        normalized["entra"]
    )
    assert "record-entra" in normalized["entra"]
    assert "This phase never modifies Workday" in normalized["tenant"]
    assert "does not create physical connector connections" in (
        normalized["power_platform"]
    )
    assert "do not describe it as automatically verified" in (
        normalized["power_platform"]
    )
    assert "These are real automated changes" in (
        normalized["power_platform"]
    )
    assert "The skill cannot publish the agent" in normalized["employee"]


def test_runtime_apply_persists_verified_stages_before_later_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import workday_connect as controller

    store = controller.WorkdayConnectStore(tmp_path)
    store.initialize()

    def fail_after_two_stages(_state, **kwargs):
        recorder = kwargs["stage_recorder"]
        recorder(
            "connection-references-bound",
            {"outcome": "verified", "provenance": "Dataverse reread"},
        )
        recorder(
            "runtime-flows-active",
            {"outcome": "verified", "provenance": "Dataverse reread"},
        )
        raise controller.WorkdayConnectRuntimeError("authorization failed")

    monkeypatch.setattr(
        controller,
        "run_runtime_operation",
        fail_after_two_stages,
    )
    args = argparse.Namespace(
        plan_hash="approved",
        workday_connection_id=None,
        dataverse_connection_id=None,
    )

    with pytest.raises(
        controller.WorkdayConnectRuntimeError,
        match="authorization failed",
    ):
        controller._runtime_apply(args, store)

    phase = store.load()["phases"]["runtime"]
    assert phase["status"] == "active"
    assert phase["completedActions"] == [
        "connection-references-bound",
        "runtime-flows-active",
    ]
    assert {
        record["action"] for record in phase["evidence"]
    } == set(phase["completedActions"])
