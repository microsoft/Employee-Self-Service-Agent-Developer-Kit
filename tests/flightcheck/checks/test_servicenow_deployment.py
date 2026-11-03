# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the shared ServiceNow target deployment checkpoint."""

from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

import connect_servicenow_da as snow
from flightcheck.checks import servicenow_deployment as deployment
from flightcheck.runner import Status


_TARGET = {
    "agentId": "00000000-0000-4000-8000-000000000101",
    "environmentId": "00000000-0000-4000-8000-000000000102",
    "tenantId": "00000000-0000-4000-8000-000000000103",
    "dataverseUrl": "https://target.crm.dynamics.com",
    "almFamilyId": "family-1",
    "schemaName": "mcs_servicenow_hrsd_test",
    "commitSha": "a" * 40,
}


def _runner(**target_context):
    source_context = {
        "root": "source-root",
        "agent": {"slug": "source-agent"},
    }
    return SimpleNamespace(
        agent_slug="source-agent",
        config={
            "activeAgent": "source-agent",
            "servicenowTargetContext": copy.deepcopy(target_context),
        },
        servicenow_source_context=source_context,
    )


def test_resolved_target_passes_with_exact_profile_realm_and_identity():
    result = deployment.deployment_result_for_resolved_target(
        profile="hrsd",
        realm="test",
        resolved=copy.deepcopy(_TARGET),
        expected=copy.deepcopy(_TARGET),
    )

    assert result.checkpoint_id == "SN-DA-DEPLOYMENT-001"
    assert result.status == Status.PASSED.value
    assert result.evidence == {
        "outcome": "found",
        "profile": "hrsd",
        "realm": "test",
        "target": {
            **_TARGET,
            "realm": "test",
            "profile": "hrsd",
        },
        "mismatches": {},
        "remoteMutationCount": 0,
    }


def test_resolved_target_conflict_fails_closed():
    expected = copy.deepcopy(_TARGET)
    expected["commitSha"] = "b" * 40

    result = deployment.deployment_result_for_resolved_target(
        profile="hrsd",
        realm="test",
        resolved=copy.deepcopy(_TARGET),
        expected=expected,
    )

    assert result.status == Status.FAILED.value
    assert result.evidence["outcome"] == "conflict"
    assert result.evidence["mismatches"] == {
        "commitSha": {
            "expected": "b" * 40,
            "observed": "a" * 40,
        }
    }


@pytest.mark.parametrize(
    ("details", "message", "outcome", "status"),
    [
        (
            {"targetAbsenceProven": True},
            "No promoted sibling exists.",
            "missing",
            Status.NOT_CONFIGURED.value,
        ),
        (
            {
                "recoveryHandoff": {
                    "category": "Realm identity mismatch",
                },
                "expectedSchemaName": "expected",
                "observedSchemaName": "wrong",
            },
            "The sibling schema conflicts.",
            "conflict",
            Status.FAILED.value,
        ),
        (
            {
                "statusCode": 403,
                "recoveryHandoff": {"category": "Read permission"},
            },
            "Target inventory is forbidden.",
            "permission",
            Status.BLOCKED.value,
        ),
        (
            {},
            "Target discovery is unavailable.",
            "unknown",
            Status.ERROR.value,
        ),
    ],
)
def test_discovery_errors_return_typed_non_success(
    monkeypatch,
    details,
    message,
    outcome,
    status,
):
    def fail(*_args, **_kwargs):
        raise snow.ServiceNowConnectError(message, details=details)

    monkeypatch.setattr(snow, "_resolve_target_realm", fail)
    runner = _runner(profile="hrsd", realm="test")
    before = copy.deepcopy(runner.config)

    result = deployment.run_servicenow_deployment_checks(runner)[0]

    assert result.status == status
    assert result.evidence["outcome"] == outcome
    assert result.evidence["remoteMutationCount"] == 0
    assert runner.config == before
    assert not hasattr(runner, "_servicenow_resolved_target")


def test_found_target_is_cached_on_runner_without_mutating_config(
    monkeypatch,
):
    client = object()
    resolved = {**copy.deepcopy(_TARGET), "client": client}
    calls = []

    def resolve(context, *, realm):
        calls.append((context, realm))
        return copy.deepcopy(resolved)

    monkeypatch.setattr(snow, "_resolve_target_realm", resolve)
    runner = _runner(
        profile="hrsd",
        realm="test",
        expected=copy.deepcopy(_TARGET),
        userAttestation="Completed",
    )
    before = copy.deepcopy(runner.config)

    result = deployment.run_servicenow_deployment_checks(runner)[0]

    assert result.status == Status.PASSED.value
    assert result.evidence["outcome"] == "found"
    assert calls == [(runner.servicenow_source_context, "test")]
    assert runner.config == before
    cached = runner._servicenow_resolved_target
    assert {key: cached[key] for key in _TARGET} == _TARGET
    assert cached["client"] is not None


def test_invalid_context_does_not_attempt_discovery(monkeypatch):
    monkeypatch.setattr(
        snow,
        "_resolve_target_realm",
        lambda *_args, **_kwargs: pytest.fail(
            "Discovery must not run for invalid target context."
        ),
    )

    result = deployment.run_servicenow_deployment_checks(
        _runner(profile="hrsd", realm="dev")
    )[0]

    assert result.status == Status.ERROR.value
    assert result.evidence["outcome"] == "unknown"
