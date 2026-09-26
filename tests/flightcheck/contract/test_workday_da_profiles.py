# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Contract tests for Workday DA validation profiles and Connect JSON output.

Pure-logic only: no external API is called. The connection-state fixtures are
non-secret minimalBots ``connectionReferenceChanges`` shapes that mirror the
validated AgentBuilder components contract used by ``tests.mocks``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flightcheck import registry
from flightcheck.runner import (
    BUCKET_ACTION,
    BUCKET_PASSED,
    CheckResult,
    FlightCheckRunner,
    FLIGHTCHECK_RESULT_SCHEMA_VERSION,
    Priority,
    Role,
    Status,
    ValidationContext,
    bucket_results,
    versioned_run_result_to_dict,
)


FIXTURE_PATH = (
    Path(__file__).with_name("fixtures") / "workday_da_connections.json"
)

EXPECTED_PROFILES = {
    "workday-da:setup-readiness",
    "workday-da:dataverse-ready",
    "workday-da:external-prerequisites",
    "workday-da:post-runtime",
    "workday-da:post-connection",
    "workday-da:post-agent-wiring",
    "workday-da:final",
    "workday-legacy:diagnostic",
}

EXPECTED_CONNECTION_STATES = {
    "absent",
    "partial",
    "legacy",
    "healthy",
    "degraded",
    "invoker",
    "embedded",
}


def _result(status: str = Status.PASSED.value) -> CheckResult:
    return CheckResult(
        checkpoint_id="WD-CONTRACT-001",
        category="Workday",
        priority=Priority.HIGH.value,
        status=status,
        description="Contract result",
        result="Observed non-secret test evidence.",
        remediation="Fix the profile contract.",
        roles=[Role.ESS_MAKER.value],
    )


def test_validation_context_requires_explicit_realm() -> None:
    with pytest.raises(ValueError, match="realm"):
        ValidationContext(realm="")


def test_versioned_json_contract_shape_contains_connect_fields() -> None:
    runner = FlightCheckRunner(scope="profile:workday-da:setup-readiness")
    runner.register("Workday", lambda _runner: [_result()])
    run_result = runner.run()
    run_result.profile = "workday-da:setup-readiness"
    run_result.profile_checkpoints = ["WD-CONTRACT-001"]
    run_result.validation_context = ValidationContext(
        realm="dev",
        environment_id="00000000-0000-0000-0000-000000001111",
        agent_schema_name="gptagent_mockemployeeselfservice",
    ).to_dict()

    payload = versioned_run_result_to_dict(run_result)

    assert payload["schemaVersion"] == FLIGHTCHECK_RESULT_SCHEMA_VERSION
    assert payload["profile"] == "workday-da:setup-readiness"
    assert payload["validationContext"]["realm"] == "dev"
    row = payload["results"][0]
    for key in (
        "checkpointId",
        "status",
        "severity",
        "automationType",
        "remediationId",
        "evidence",
    ):
        assert key in row
    assert row["checkpointId"] == "WD-CONTRACT-001"
    assert row["evidence"]["summary"] == "Observed non-secret test evidence."


def test_blocked_is_action_required_and_not_ready() -> None:
    blocked = _result(Status.BLOCKED.value)
    passed = _result(Status.PASSED.value)

    buckets = bucket_results([blocked, passed])

    assert blocked in buckets[BUCKET_ACTION]
    assert blocked not in buckets[BUCKET_PASSED]

    runner = FlightCheckRunner(scope="test")
    runner.register("Workday", lambda _runner: [blocked])
    run_result = runner.run()
    assert run_result.blocked == 1
    assert run_result.overall == "NOT_READY"


def test_profiles_are_registered_with_resolvable_checkpoint_members() -> None:
    profiles = {profile.name: profile for profile in registry.list_profiles()}

    assert set(profiles) == EXPECTED_PROFILES
    for profile in profiles.values():
        assert profile.checkpoint_ids
        for checkpoint_id in profile.checkpoint_ids:
            assert registry.resolve(checkpoint_id) is not None


def test_profile_wd_conn_013_resolves_to_real_workday_check() -> None:
    # WD-CONN-013 (agent connection OBO parameter sharing) is a fully
    # implemented, tested check in checks/workday.py, emitted by
    # run_workday_checks. It must resolve to the real WD-CONN family /
    # Workday category, NOT a placeholder stub.
    profile = registry.resolve_profile("workday-da:post-connection")

    assert profile is not None
    assert "WD-CONN-013" in profile.checkpoint_ids
    spec = registry.resolve("WD-CONN-013")
    assert spec is not None
    assert spec.category_label == "Workday"
    assert registry.profile_matches("workday-da:post-connection", "WD-CONN-013")


def test_profile_plan_runs_wd_conn_013_via_real_workday_category() -> None:
    plan = registry.profile_requirements("workday-da:post-connection")
    labels = [label for label, _fn in plan.ordered_fns]

    # No placeholder "Profile Stubs" category exists; WD-CONN-013 runs inside
    # the real Workday category.
    assert "Profile Stubs" not in labels
    assert "Workday" in labels


def test_profile_requirements_rejects_empty_profile(monkeypatch) -> None:
    # A profile with no checkpoint members must fail loudly instead of
    # indexing checkpoint_ids[0] and raising an opaque IndexError.
    empty = registry.ProfileSpec(
        name="workday-da:empty-guard",
        checkpoint_ids=(),
        description="Intentionally empty profile for the guard test.",
    )
    monkeypatch.setitem(registry.PROFILES, empty.name, empty)

    with pytest.raises(registry.RegistryError, match="no checkpoints"):
        registry.profile_requirements(empty.name)


def test_connection_state_fixtures_cover_required_states() -> None:
    fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert set(fixtures) == EXPECTED_CONNECTION_STATES
    for state, payload in fixtures.items():
        changes = payload.get("connectionReferenceChanges")
        assert isinstance(changes, list), state
        for change in changes:
            ref = change["connectionReference"]
            assert str(ref["connectorId"]).endswith("/apis/shared_workdaysoap")
            assert "password" not in json.dumps(ref).lower()
            assert "secret" not in json.dumps(ref).lower()


@pytest.mark.parametrize("state", sorted(EXPECTED_CONNECTION_STATES))
def test_connection_state_fixture_has_expected_shape(state: str) -> None:
    fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    changes = fixtures[state]["connectionReferenceChanges"]

    if state == "absent":
        assert changes == []
    else:
        assert changes
        assert all("connectionReference" in change for change in changes)
