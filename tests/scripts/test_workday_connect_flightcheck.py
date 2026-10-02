# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for Workday Connect's independent FlightCheck adapter."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest


PROFILE = "workday-da:setup-readiness"


def _state():
    from workday_connect_model import default_state

    state = default_state()
    state["scope"].update(
        {
            "environmentId": "environment-id",
            "dataverseUrl": "https://example.crm.dynamics.com",
            "entraTenantId": "tenant-id",
            "ring": "preprod",
            "agent": {
                "slug": "ess-hr",
                "schemaName": "contoso_agent",
                "botId": "bot-id",
            },
        }
    )
    state["operators"]["powerPlatformMaker"] = {
        "username": "maker@example.com"
    }
    return state


def _contract(*, status: str = "Passed", profile: str = PROFILE):
    from workday_connect_flightcheck import PROFILE_POLICIES

    policy = PROFILE_POLICIES[profile]
    context = {
        "realm": "dev",
        "environmentId": "environment-id",
        "environmentUrl": "https://example.crm.dynamics.com",
        "tenantId": "tenant-id",
        "agentSlug": "ess-hr",
        "agentSchemaName": "contoso_agent",
        "agentId": "bot-id",
    }
    return {
        "schemaVersion": "flightcheck.result.v2",
        "profile": profile,
        "profileCheckpoints": list(policy.checkpoints),
        "profileFamilies": {
            family: {"minimum": minimum}
            for family, minimum in policy.families.items()
        },
        "emittedCheckpoints": [
            checkpoint
            for checkpoint in policy.checkpoints
            if checkpoint not in policy.families
        ],
        "requestedValidationContext": dict(context),
        "validationContext": dict(context),
        "clientAvailability": {
            client: {
                "required": True,
                "available": True,
                "authenticatedAccountVerified": True,
            }
            for client in policy.clients
        },
        "executionErrors": [],
        "overall": "READY" if status == "Passed" else "NOT_READY",
        "counts": {
            "total": len(policy.checkpoints),
            "passed": len(policy.checkpoints) if status == "Passed" else 0,
            "failed": 0,
            "blocked": 0,
            "warnings": 0,
            "notConfigured": 0,
            "manual": 0,
            "skipped": 0,
            "errors": 0,
        },
        "results": [
            {
                "checkpointId": checkpoint,
                "status": status,
                "severity": "Info",
                "automationType": "Automated",
                "remediationId": "",
                "evidence": {},
            }
            for checkpoint in policy.checkpoints
        ],
    }


def test_evaluate_contract_accepts_complete_automated_profile():
    from workday_connect_flightcheck import evaluate_contract

    summary = evaluate_contract(_contract(), _state(), PROFILE)

    assert summary["accepted"] is True
    assert summary["overall"] == "READY"
    assert summary["checkpointStatuses"]["DA-AGENT-001"] == "Passed"
    assert summary["target"]["agentId"] == "bot-id"


def test_requested_context_can_omit_agent_id_when_resolved_context_matches():
    from workday_connect_flightcheck import evaluate_contract

    contract = _contract()
    contract["requestedValidationContext"]["agentId"] = ""

    summary = evaluate_contract(contract, _state(), PROFILE)

    assert summary["target"]["agentId"] == "bot-id"


@pytest.mark.parametrize(
    ("schema", "error_type"),
    [
        ("flightcheck.result.v1", "stale-flightcheck-contract"),
        ("flightcheck.result.v3", "unsupported-flightcheck-contract"),
        (None, "malformed-flightcheck-contract"),
    ],
)
def test_evaluate_contract_rejects_unsupported_schema(schema, error_type):
    from workday_connect_flightcheck import (
        WorkdayConnectFlightCheckError,
        evaluate_contract,
    )

    contract = _contract()
    contract["schemaVersion"] = schema

    with pytest.raises(WorkdayConnectFlightCheckError) as raised:
        evaluate_contract(contract, _state(), PROFILE)

    assert raised.value.error_type == error_type


def test_evaluate_contract_rejects_target_mismatch():
    from workday_connect_flightcheck import (
        WorkdayConnectFlightCheckError,
        evaluate_contract,
    )

    contract = _contract()
    contract["validationContext"]["agentId"] = "other-agent"

    with pytest.raises(WorkdayConnectFlightCheckError) as raised:
        evaluate_contract(contract, _state(), PROFILE)

    assert raised.value.error_type == "flightcheck-target-mismatch"


def test_evaluate_contract_rejects_required_client_failure():
    from workday_connect_flightcheck import (
        WorkdayConnectFlightCheckError,
        evaluate_contract,
    )

    contract = _contract()
    contract["clientAvailability"]["agentbuilder"]["available"] = False
    contract["clientAvailability"]["agentbuilder"][
        "authenticatedAccountVerified"
    ] = False

    with pytest.raises(WorkdayConnectFlightCheckError) as raised:
        evaluate_contract(contract, _state(), PROFILE)

    assert raised.value.error_type == "flightcheck-client-unavailable"


def test_result_blockers_are_reported_before_client_availability():
    from workday_connect_flightcheck import (
        WorkdayConnectFlightCheckError,
        evaluate_contract,
    )

    profile = "workday-da:dataverse-ready"
    contract = _contract(profile=profile)
    contract["overall"] = "NOT_READY"
    contract["clientAvailability"]["dataverse"]["available"] = False
    contract["clientAvailability"]["dataverse"][
        "authenticatedAccountVerified"
    ] = False
    contract["results"][0]["status"] = "Failed"
    contract["results"][1]["status"] = "Skipped"

    with pytest.raises(WorkdayConnectFlightCheckError) as raised:
        evaluate_contract(contract, _state(), profile)

    assert raised.value.error_type == "flightcheck-profile-not-ready"
    assert "WD-DA-PKG-001=Failed" in str(raised.value)
    assert "WD-DA-FLOW-001=Skipped" in str(raised.value)
    assert "WD-DA-PKG-001=Failed" in raised.value.customer_remediation
    assert "WD-DA-FLOW-001=Skipped" in raised.value.customer_remediation


@pytest.mark.parametrize("mutation", ["missing", "optional"])
def test_evaluate_contract_rejects_client_policy_drift(mutation):
    from workday_connect_flightcheck import (
        WorkdayConnectFlightCheckError,
        evaluate_contract,
    )

    contract = _contract()
    if mutation == "missing":
        contract["clientAvailability"].pop("agentbuilder")
        expected = "flightcheck-profile-drift"
    else:
        contract["clientAvailability"]["agentbuilder"]["required"] = False
        expected = "malformed-flightcheck-contract"

    with pytest.raises(WorkdayConnectFlightCheckError) as raised:
        evaluate_contract(contract, _state(), PROFILE)

    assert raised.value.error_type == expected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("required", "true"),
        ("required", 1),
        ("required", None),
        ("available", "true"),
        ("available", 1),
        ("available", None),
        ("authenticatedAccountVerified", "true"),
        ("authenticatedAccountVerified", 1),
        ("authenticatedAccountVerified", None),
    ],
)
def test_evaluate_contract_requires_exact_client_booleans(field, value):
    from workday_connect_flightcheck import (
        WorkdayConnectFlightCheckError,
        evaluate_contract,
    )

    contract = _contract()
    contract["clientAvailability"]["agentbuilder"][field] = value

    with pytest.raises(WorkdayConnectFlightCheckError) as raised:
        evaluate_contract(contract, _state(), PROFILE)

    assert raised.value.error_type == "malformed-flightcheck-contract"


def test_evaluate_contract_rejects_missing_required_checkpoint():
    from workday_connect_flightcheck import (
        WorkdayConnectFlightCheckError,
        evaluate_contract,
    )

    contract = _contract()
    contract["results"] = contract["results"][:-1]

    with pytest.raises(WorkdayConnectFlightCheckError) as raised:
        evaluate_contract(contract, _state(), PROFILE)

    assert raised.value.error_type == "flightcheck-missing-checkpoints"


def test_evaluate_contract_requires_fixed_checkpoint_in_emitted_set():
    from workday_connect_flightcheck import (
        WorkdayConnectFlightCheckError,
        evaluate_contract,
    )

    contract = _contract()
    contract["emittedCheckpoints"].remove("DA-AGENT-001")

    with pytest.raises(WorkdayConnectFlightCheckError) as raised:
        evaluate_contract(contract, _state(), PROFILE)

    assert raised.value.error_type == "flightcheck-missing-checkpoints"
    assert raised.value.phase_id == "preflight"


def test_evaluate_contract_rejects_result_not_in_emitted_set():
    from workday_connect_flightcheck import (
        WorkdayConnectFlightCheckError,
        evaluate_contract,
    )

    contract = _contract()
    contract["results"].append(
        {
            "checkpointId": "STALE-001",
            "status": "Passed",
            "severity": "Info",
            "automationType": "Automated",
            "remediationId": "",
            "evidence": {},
        }
    )

    with pytest.raises(WorkdayConnectFlightCheckError) as raised:
        evaluate_contract(contract, _state(), PROFILE)

    assert raised.value.error_type == "malformed-flightcheck-contract"


def test_evaluate_contract_rejects_non_ready_required_row():
    from workday_connect_flightcheck import (
        WorkdayConnectFlightCheckError,
        evaluate_contract,
    )

    contract = _contract()
    contract["results"][0]["status"] = "Warning"
    contract["results"][0]["remediationId"] = "ENV-001-REMEDIATE"

    with pytest.raises(WorkdayConnectFlightCheckError) as raised:
        evaluate_contract(contract, _state(), PROFILE)

    assert raised.value.error_type == "flightcheck-profile-not-ready"
    assert raised.value.remediation_ids == ("ENV-001-REMEDIATE",)


def test_external_profile_reconciles_manual_rows_from_controller_evidence():
    from workday_connect_flightcheck import evaluate_contract

    profile = "workday-da:external-prerequisites"
    state = _state()
    for phase_id, action in (
        ("entra", "administrator-configuration-verified"),
        ("workday-admin", "administrator-response-validated"),
    ):
        state["phases"][phase_id]["completedActions"].append(action)
        state["phases"][phase_id]["evidence"].append({"action": action})
    from workday_connect_flightcheck import PROFILE_POLICIES

    checkpoints = PROFILE_POLICIES[profile].checkpoints
    contract = _contract(profile=profile)
    contract["results"] = [
        {
            "checkpointId": checkpoint,
            "status": (
                "Manual"
                if checkpoint
                in {
                    "WD-ENTRA-SIGNOPT-001",
                    "WD-API-CLIENT-001",
                    "WD-TENANT-001",
                    "WD-SEC-003",
                    "WD-NET-001",
                }
                else "Passed"
            ),
            "severity": "Info",
            "automationType": "Manual",
            "remediationId": "",
            "evidence": {},
        }
        for checkpoint in checkpoints
    ]

    summary = evaluate_contract(contract, state, profile)

    assert len(summary["acceptedSuppressions"]) == 4


def test_lifecycle_profiles_defer_privileged_graph_checks():
    from flightcheck import registry
    from workday_connect_flightcheck import PROFILE_POLICIES

    deferred = {
        "WD-ENTRA-SCOPE-001",
        "WD-ENTRA-CONSENT-001",
        "WD-ASSIGN-001",
        "WD-ENTRA-NAMEID-001",
        "WD-CONN-010",
        "WD-CONN-102",
    }
    for profile_name in (
        "workday-da:external-prerequisites",
        "workday-da:final",
    ):
        lifecycle_policy = PROFILE_POLICIES[profile_name]
        independent_profile = registry.resolve_profile(profile_name)

        assert independent_profile is not None
        assert "graph" not in lifecycle_policy.clients
        assert deferred.isdisjoint(lifecycle_policy.checkpoints)
        assert deferred.isdisjoint(independent_profile.checkpoint_ids)

    for checkpoint_id in deferred:
        assert registry.resolve(checkpoint_id) is not None


def test_final_profile_routes_failure_to_checkpoint_owning_phase():
    from workday_connect_flightcheck import (
        PROFILE_POLICIES,
        WorkdayConnectFlightCheckError,
        evaluate_contract,
    )

    profile = "workday-da:final"
    checkpoints = PROFILE_POLICIES[profile].checkpoints
    contract = _contract(profile=profile)
    contract["emittedCheckpoints"] = list(checkpoints)
    contract["results"] = [
        {
            "checkpointId": checkpoint,
            "status": (
                "Failed" if checkpoint == "WD-API-CLIENT-001" else "Passed"
            ),
            "severity": "Blocking",
            "automationType": "Automated",
            "remediationId": "",
            "evidence": {},
        }
        for checkpoint in checkpoints
    ]

    with pytest.raises(WorkdayConnectFlightCheckError) as raised:
        evaluate_contract(contract, _state(), profile)

    assert raised.value.phase_id == "workday-admin"


@pytest.mark.parametrize(
    ("missing_checkpoint", "expected_phase"),
    [
        ("WD-ENTRA-SIGNOPT-001", "entra"),
        ("WD-API-CLIENT-001", "workday-admin"),
        ("WD-DA-FLOW-001", "runtime"),
        ("DV-CONN-001", "runtime"),
        ("WD-REST-002", "runtime"),
    ],
)
def test_final_profile_routes_missing_checkpoint_to_owning_phase(
    missing_checkpoint,
    expected_phase,
):
    from workday_connect_flightcheck import (
        PROFILE_POLICIES,
        WorkdayConnectFlightCheckError,
        evaluate_contract,
    )

    profile = "workday-da:final"
    checkpoints = PROFILE_POLICIES[profile].checkpoints
    contract = _contract(profile=profile)
    contract["emittedCheckpoints"] = [
        checkpoint
        for checkpoint in checkpoints
        if checkpoint != missing_checkpoint
    ]
    contract["results"] = [
        {
            "checkpointId": checkpoint,
            "status": "Passed",
            "severity": "Info",
            "automationType": "Automated",
            "remediationId": "",
            "evidence": {},
        }
        for checkpoint in contract["emittedCheckpoints"]
    ]

    with pytest.raises(WorkdayConnectFlightCheckError) as raised:
        evaluate_contract(contract, _state(), profile)

    assert raised.value.error_type == "flightcheck-missing-checkpoints"
    assert raised.value.phase_id == expected_phase


def test_workday_profiles_do_not_require_generic_connection_families():
    from workday_connect_flightcheck import PROFILE_POLICIES

    assert PROFILE_POLICIES["workday-da:post-agent-wiring"].families == {}
    assert PROFILE_POLICIES["workday-da:final"].families == {}


def test_every_profile_checkpoint_has_explicit_phase_ownership():
    from workday_connect_flightcheck import (
        PROFILE_POLICIES,
        _CHECKPOINT_PHASES,
    )

    assert {
        checkpoint
        for policy in PROFILE_POLICIES.values()
        for checkpoint in policy.checkpoints
    } <= set(_CHECKPOINT_PHASES)


def test_connect_readiness_lookup_views_are_derived_from_policy():
    from workday_connect_readiness_policy import (
        CHECKPOINT_POLICIES,
        MANUAL_EVIDENCE,
        PHASE_ORDER,
        PHASE_REQUIRED_PROFILES,
        PROFILE_POLICIES,
    )

    assert PHASE_REQUIRED_PROFILES == {
        phase_id: tuple(
            profile_name
            for profile_name, policy in PROFILE_POLICIES.items()
            if policy.phase_id == phase_id
        )
        for phase_id in PHASE_ORDER
    }
    assert MANUAL_EVIDENCE == {
        checkpoint_id: policy.manual_evidence
        for checkpoint_id, policy in CHECKPOINT_POLICIES.items()
        if policy.manual_evidence
    }


def test_run_profile_rejects_ready_contract_after_nonzero_exit(
    tmp_path,
    monkeypatch,
):
    from workday_connect_flightcheck import run_profile

    observed = {}

    def fake_run(command, **kwargs):
        observed["command"] = command
        output = Path(command[command.index("--output") + 1])
        (output / "results.json").write_text(
            json.dumps({"contract": _contract()}),
            encoding="utf-8",
        )
        observed["output"] = output
        return subprocess.CompletedProcess(command, 1, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    from workday_connect_flightcheck import WorkdayConnectFlightCheckError

    with pytest.raises(WorkdayConnectFlightCheckError) as raised:
        run_profile(tmp_path, _state(), PROFILE)

    assert raised.value.error_type == "flightcheck-transport-error"
    assert "--preferred-username" in observed["command"]
    assert "--validation-realm" in observed["command"]
    assert observed["command"][
        observed["command"].index("--ring") + 1
    ] == "preprod"
    assert "--no-open" in observed["command"]
    assert not observed["output"].exists()


def test_connect_profile_policy_matches_independent_registry():
    from flightcheck.registry import (
        profile_family_contract,
        profile_requirements,
        resolve_profile,
    )
    from workday_connect_flightcheck import PROFILE_POLICIES

    for profile_name, policy in PROFILE_POLICIES.items():
        profile = resolve_profile(profile_name)
        assert profile is not None
        assert profile.checkpoint_ids == policy.checkpoints
        assert profile_family_contract(profile_name) == {
            family: {"minimum": minimum}
            for family, minimum in policy.families.items()
        }
        assert tuple(sorted(profile_requirements(profile_name).clients)) == (
            policy.clients
        )


def test_run_profile_parses_nonzero_not_ready_contract(
    tmp_path,
    monkeypatch,
):
    from workday_connect_flightcheck import (
        WorkdayConnectFlightCheckError,
        run_profile,
    )

    def fake_run(command, **kwargs):
        output = Path(command[command.index("--output") + 1])
        contract = _contract()
        contract["overall"] = "NOT_READY"
        contract["results"][0]["status"] = "Failed"
        (output / "results.json").write_text(
            json.dumps({"contract": contract}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 1, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(WorkdayConnectFlightCheckError) as raised:
        run_profile(tmp_path, _state(), PROFILE)

    assert raised.value.error_type == "flightcheck-profile-not-ready"


def test_run_profile_uses_utf8_replacement_decoding(tmp_path, monkeypatch):
    from workday_connect_flightcheck import run_profile

    observed = {}

    def fake_run(command, **kwargs):
        observed.update(kwargs)
        output = Path(command[command.index("--output") + 1])
        (output / "results.json").write_text(
            json.dumps({"contract": _contract()}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "\u2713", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    summary = run_profile(tmp_path, _state(), PROFILE)

    assert summary["accepted"] is True
    assert observed["encoding"] == "utf-8"
    assert observed["errors"] == "replace"


def test_run_profile_requires_recorded_maker(tmp_path, monkeypatch):
    from workday_connect_flightcheck import (
        WorkdayConnectFlightCheckError,
        run_profile,
    )

    state = _state()
    state["operators"] = {}

    with pytest.raises(WorkdayConnectFlightCheckError) as raised:
        run_profile(tmp_path, state, PROFILE)

    assert raised.value.error_type == "flightcheck-maker-account-required"


def test_run_profile_fails_closed_for_malformed_foundation_config(
    tmp_path,
    monkeypatch,
):
    from workday_connect_flightcheck import (
        WorkdayConnectFlightCheckError,
        run_profile,
    )

    foundation = tmp_path / ".local" / "config.json"
    foundation.parent.mkdir(parents=True)
    foundation.write_text("{not-json", encoding="utf-8")
    called = False

    def fake_run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("subprocess must not run")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(WorkdayConnectFlightCheckError) as raised:
        run_profile(tmp_path, _state(), PROFILE)

    assert called is False
    assert raised.value.error_type == "flightcheck-target-mismatch"
    assert raised.value.phase_id == "preflight"
    assert raised.value.input_fingerprint


def test_run_profile_reports_timeout(tmp_path, monkeypatch):
    from workday_connect_flightcheck import (
        WorkdayConnectFlightCheckError,
        run_profile,
    )

    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(WorkdayConnectFlightCheckError) as raised:
        run_profile(tmp_path, _state(), PROFILE, timeout_seconds=1)

    assert raised.value.error_type == "flightcheck-timeout"


def test_ready_v7_migration_runs_only_final_profile(
    tmp_path,
    monkeypatch,
):
    import workday_connect
    import workday_connect_model as model
    from workday_connect_flightcheck import (
        PHASE_REQUIRED_PROFILES,
        PROFILE_POLICIES,
    )
    from workday_connect_store import WorkdayConnectStore

    document = model.default_state()
    document["schemaVersion"] = 7
    document["scope"].update(
        {
            "environmentId": "environment-id",
            "dataverseUrl": "https://example.crm.dynamics.com",
            "entraTenantId": "tenant-id",
            "agent": {
                "slug": "ess-hr",
                "schemaName": "contoso_agent",
                "botId": "bot-id",
            },
        }
    )
    runtime_plan = {
        "phase": "runtime",
        "scope": {"environmentId": "environment-id"},
        "actions": ["Configure runtime"],
        "flows": [{"name": "REST", "workflowId": "flow-id"}],
    }
    document["phases"]["runtime"]["approvedPlan"] = runtime_plan
    document["phases"]["runtime"]["approvedPlanHash"] = model.plan_hash(
        runtime_plan
    )
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
    store = WorkdayConnectStore(tmp_path)
    store.config_path.parent.mkdir(parents=True)
    store.config_path.write_text(json.dumps(document), encoding="utf-8")
    observed = []
    final_checkpoints = {
        checkpoint
        for policy in PROFILE_POLICIES.values()
        for checkpoint in policy.checkpoints
        if checkpoint not in policy.families
    }

    def fake_run_profile(_root, _state, profile_name, **kwargs):
        from workday_connect_flightcheck import (
            effective_validation_state,
            validation_input_fingerprint,
        )

        observed.append((profile_name, kwargs))
        return {
            "profile": profile_name,
            "sourceProfile": "workday-da:final",
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
            "checkpointStatuses": {
                checkpoint: "Passed"
                for checkpoint in sorted(final_checkpoints)
            },
            "acceptedSuppressions": [],
            "remediationIds": [],
            "accepted": True,
            "migrationBaseline": True,
            "inputFingerprint": validation_input_fingerprint(
                effective_validation_state(tmp_path, _state),
                "workday-da:final",
            ),
        }

    monkeypatch.setattr(workday_connect, "run_profile", fake_run_profile)

    workday_connect._ensure_migration_baseline(store)

    state = store.load()
    public_status = store.status()
    assert observed == [
        (
            "workday-da:final",
            {
                "source_profile": "workday-da:final",
                "migration_baseline": True,
            },
        )
    ]
    assert state["status"] == "ready"
    assert all(
        phase["readiness"]["accepted"]
        for phase in public_status["phases"]
        if PHASE_REQUIRED_PROFILES[phase["id"]]
    )
    assert state["migration"]["flightcheckBaselineRequired"] is False
    assert "workday-da:" not in json.dumps(store.status())
    for profile_name, policy in PROFILE_POLICIES.items():
        summary = state["phases"][policy.phase_id]["validationProfiles"][
            profile_name
        ]
        assert summary["sourceProfile"] == "workday-da:final"
        assert summary["migrationBaseline"] is True


def test_partial_v7_migration_validates_completed_boundaries(
    tmp_path,
    monkeypatch,
):
    import workday_connect
    import workday_connect_model as model
    from workday_connect_flightcheck import (
        PROFILE_POLICIES,
        effective_validation_state,
        validation_input_fingerprint,
    )
    from workday_connect_store import WorkdayConnectStore

    document = model.default_state()
    document["schemaVersion"] = 7
    document["scope"].update(_state()["scope"])
    document["operators"] = _state()["operators"]
    for phase in document["phases"].values():
        phase.pop("validationProfiles")
        phase.pop("employeeTestAttempt", None)
    preflight = document["phases"]["preflight"]
    for action in model.PHASE_REQUIRED_ACTIONS["preflight"]:
        preflight["completedActions"].append(action)
        preflight["evidence"].append(
            {"action": action, "outcome": "verified"}
        )
    preflight["status"] = "complete"
    store = WorkdayConnectStore(tmp_path)
    store.config_path.parent.mkdir(parents=True)
    store.config_path.write_text(json.dumps(document), encoding="utf-8")
    observed = []

    def fake_run_profile(_root, state, profile_name, **_kwargs):
        observed.append(profile_name)
        policy = PROFILE_POLICIES[profile_name]
        return {
            "profile": profile_name,
            "sourceProfile": profile_name,
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
            "checkpointStatuses": {
                checkpoint: "Passed"
                for checkpoint in policy.checkpoints
                if checkpoint not in policy.families
            },
            "acceptedSuppressions": [],
            "remediationIds": [],
            "accepted": True,
            "migrationBaseline": True,
            "inputFingerprint": validation_input_fingerprint(
                effective_validation_state(tmp_path, state),
                profile_name,
            ),
        }

    monkeypatch.setattr(workday_connect, "run_profile", fake_run_profile)

    workday_connect._ensure_migration_baseline(store)

    state = store.load()
    assert observed == ["workday-da:setup-readiness"]
    assert state["migration"]["flightcheckBaselineRequired"] is False
    assert (
        "workday-da:setup-readiness"
        in state["phases"]["preflight"]["validationProfiles"]
    )


def test_failed_migration_baseline_is_not_replayed_before_every_command(
    tmp_path,
    monkeypatch,
):
    import workday_connect
    import workday_connect_model as model
    from workday_connect_flightcheck import (
        WorkdayConnectFlightCheckError,
        effective_validation_state,
        validation_input_fingerprint,
    )
    from workday_connect_store import (
        WorkdayConnectStore,
        WorkdayConnectStoreError,
    )

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
    store.complete_action(
        "employee-validation",
        "signed-in-scenario",
        evidence={
            "outcome": "verified",
            "timestamp": "2026-09-28T12:00:00Z",
        },
    )
    store.set_phase_status("employee-validation", "complete")
    state = store.load()
    state["migration"] = {
        "source": "workday-connect-state-v7",
        "migratedAt": "2026-09-28T12:01:00Z",
        "flightcheckBaselineRequired": True,
        "legacyReady": True,
    }
    store.config_path.write_text(json.dumps(state), encoding="utf-8")
    calls = 0

    def fail_profile(_root, current, _profile, **_kwargs):
        nonlocal calls
        calls += 1
        raise WorkdayConnectFlightCheckError(
            "Runtime readiness needs remediation.",
            error_type="flightcheck-profile-not-ready",
            phase_id="runtime",
            customer_remediation="Review Runtime and retry.",
            input_fingerprint=validation_input_fingerprint(
                effective_validation_state(tmp_path, current),
                "workday-da:final",
            ),
        )

    monkeypatch.setattr(workday_connect, "run_profile", fail_profile)

    with pytest.raises(WorkdayConnectStoreError):
        workday_connect._ensure_migration_baseline(store)
    workday_connect._ensure_migration_baseline(store)

    state = store.load()
    assert calls == 1
    assert state["migration"]["flightcheckBaselineRequired"] is False
    assert (
        state["migration"]["flightcheckBaselineOutcome"]
        == "remediation-required"
    )
    assert state["phases"]["runtime"]["status"] == "blocked"
