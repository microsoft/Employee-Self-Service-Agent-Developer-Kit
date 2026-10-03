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
    save_results,
    versioned_run_result_to_dict,
)


FIXTURE_PATH = (
    Path(__file__).with_name("fixtures") / "workday_da_connections.json"
)

EXPECTED_PROFILES = {
    "workday-da:setup-readiness",
    "workday-da:dataverse-ready",
    "workday-da:external-prerequisites",
    "workday-da:package-ready",
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
        evidence={"summary": "Observed non-secret test evidence."},
        remediation="Fix the profile contract.",
        roles=[Role.ESS_MAKER.value],
    )


def test_validation_context_requires_explicit_realm() -> None:
    with pytest.raises(ValueError, match="realm"):
        ValidationContext(realm="")


def test_validation_context_normalizes_nullable_identifiers() -> None:
    payload = ValidationContext(
        realm="dev",
        environment_id=None,
        agent_slug=None,
        agent_schema_name=None,
        agent_id=None,
        tenant_id=None,
    ).to_dict()

    assert payload == {
        "realm": "dev",
        "environmentId": "",
        "environmentUrl": "",
        "agentSlug": "",
        "agentSchemaName": "",
        "agentId": "",
        "tenantId": "",
    }


def test_post_runtime_profile_uses_dataverse_and_run_history() -> None:
    requirements = registry.profile_requirements(
        "workday-da:post-runtime"
    )

    assert requirements.requires_dataverse_endpoint is True
    assert requirements.clients == frozenset({
        registry.DATAVERSE,
        registry.PP_ADMIN,
    })
    assert requirements.pp_admin_flow_required is True


def test_setup_readiness_requires_only_agentbuilder_audience() -> None:
    requirements = registry.profile_requirements(
        "workday-da:setup-readiness"
    )

    assert requirements.clients == frozenset({registry.AGENTBUILDER})
    assert requirements.pp_admin_flow_required is False


def test_da_profiles_do_not_include_legacy_workday_flow_family() -> None:
    for profile in registry.list_profiles():
        if not profile.name.startswith("workday-da:"):
            continue
        assert "WD-FLOW" not in profile.checkpoint_ids


def test_versioned_json_contract_shape_contains_connect_fields() -> None:
    runner = FlightCheckRunner(scope="profile:workday-da:setup-readiness")
    runner.register("Workday", lambda _runner: [_result()])
    run_result = runner.run()
    run_result.profile = "workday-da:setup-readiness"
    run_result.profile_checkpoints = ["WD-CONTRACT-001"]
    run_result.profile_families = {"WD-FLOW": {"minimum": 1}}
    run_result.requested_validation_context = ValidationContext(
        realm="dev",
        agent_slug="ess-hr",
    ).to_dict()
    run_result.validation_context = ValidationContext(
        realm="dev",
        environment_id="00000000-0000-0000-0000-000000001111",
        agent_slug="ess-hr",
        agent_schema_name="gptagent_mockemployeeselfservice",
        tenant_id="00000000-0000-0000-0000-000000002222",
    ).to_dict()
    run_result.client_availability = {
        "agentbuilder": {
            "required": True,
            "available": True,
            "authenticatedAccountVerified": True,
        }
    }

    payload = versioned_run_result_to_dict(run_result)

    assert payload["schemaVersion"] == FLIGHTCHECK_RESULT_SCHEMA_VERSION
    assert payload["profile"] == "workday-da:setup-readiness"
    assert payload["profileFamilies"]["WD-FLOW"]["minimum"] == 1
    assert payload["emittedCheckpoints"] == ["WD-CONTRACT-001"]
    assert payload["requestedValidationContext"]["agentSlug"] == "ess-hr"
    assert payload["validationContext"]["realm"] == "dev"
    assert payload["validationContext"]["tenantId"].endswith("2222")
    assert payload["clientAvailability"]["agentbuilder"]["available"] is True
    assert payload["executionErrors"] == []
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


def test_scope_results_keep_legacy_json_and_global_v2_contract(
    tmp_path,
    capsys,
) -> None:
    runner = FlightCheckRunner(scope="environment")
    runner.register("Environment", lambda _runner: [_result()])
    run_result = runner.run()

    save_results(run_result, str(tmp_path))

    payload = json.loads(
        (tmp_path / "results.json").read_text(encoding="utf-8")
    )
    assert payload["schema_version"] == FLIGHTCHECK_RESULT_SCHEMA_VERSION
    assert payload["results"][0]["checkpoint_id"] == "WD-CONTRACT-001"
    assert payload["contract"]["schemaVersion"] == (
        FLIGHTCHECK_RESULT_SCHEMA_VERSION
    )
    assert payload["contract"]["profile"] == ""
    assert payload["contract"]["results"][0]["checkpointId"] == (
        "WD-CONTRACT-001"
    )
    assert (tmp_path / "report.html").exists()
    capsys.readouterr()


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


def test_execution_error_ids_are_collision_free_and_explicit() -> None:
    def fail(_runner):
        raise RuntimeError("boom")

    runner = FlightCheckRunner(scope="profile:test")
    runner.register("Workday Runtime", fail)
    runner.register("Workday Readiness", fail)
    run_result = runner.run()
    payload = versioned_run_result_to_dict(run_result)

    ids = [result.checkpoint_id for result in run_result.results]
    assert len(ids) == len(set(ids)) == 2
    assert all(value.startswith("EXEC-") and value.endswith("-ERR") for value in ids)
    assert len(payload["executionErrors"]) == 2
    assert all(
        row["evidence"]["executionError"] is True
        for row in payload["executionErrors"]
    )


def test_profiles_are_registered_with_resolvable_checkpoint_members() -> None:
    profiles = {profile.name: profile for profile in registry.list_profiles()}

    assert set(profiles) == EXPECTED_PROFILES
    for profile in profiles.values():
        assert profile.checkpoint_ids
        for checkpoint_id in profile.checkpoint_ids:
            assert registry.resolve(checkpoint_id) is not None


def test_final_profile_exactly_matches_boundary_profile_union() -> None:
    final = registry.resolve_profile("workday-da:final")
    assert final is not None
    expected = {
        checkpoint_id
        for profile in registry.list_profiles()
        if profile.name.startswith("workday-da:")
        and profile.name != "workday-da:final"
        for checkpoint_id in profile.checkpoint_ids
    }
    assert expected == set(final.checkpoint_ids)


def test_profile_membership_matches_lifecycle_boundaries() -> None:
    setup = registry.resolve_profile("workday-da:setup-readiness")
    package = registry.resolve_profile("workday-da:package-ready")
    external = registry.resolve_profile("workday-da:external-prerequisites")
    post_connection = registry.resolve_profile("workday-da:post-connection")
    post_wiring = registry.resolve_profile("workday-da:post-agent-wiring")

    assert setup is not None
    assert set(setup.checkpoint_ids) == {
        "DA-AGENT-001",
        "DA-CONTENT-001",
    }
    assert external is not None
    assert "WD-SEC-003" not in external.checkpoint_ids
    assert package is not None
    assert set(package.checkpoint_ids) == {
        "WD-DA-PKG-001",
    }
    dataverse = registry.resolve_profile("workday-da:dataverse-ready")
    assert dataverse is not None
    assert set(dataverse.checkpoint_ids) == {
        "WD-DA-PKG-001",
        "WD-DA-FLOW-001",
        "DV-CONN-001",
    }
    assert post_connection is not None
    assert "WD-REST-002" not in post_connection.checkpoint_ids
    assert post_wiring is not None
    assert "WD-REST-002" in post_wiring.checkpoint_ids


def test_da_wiring_profile_uses_oob_contract_not_custom_topic_families() -> None:
    profile = registry.resolve_profile("workday-da:post-agent-wiring")
    assert profile is not None
    assert "WD-DA-TOPIC-001" in profile.checkpoint_ids
    assert "WD-DA-WIRING-001" in profile.checkpoint_ids
    assert "TOPIC-TRIGGER" not in profile.checkpoint_ids
    assert "TOPIC-INTEGRATION" not in profile.checkpoint_ids


def test_final_profile_contains_every_declared_family_contract() -> None:
    families = registry.profile_family_contract("workday-da:final")
    assert families == {}


def test_profile_excludes_generic_agent_connection_sharing() -> None:
    # WD-CONN-013 evaluates every connector exposed by the selected agent.
    # An unrelated persona connector must not block Workday Connect runtime.
    profile = registry.resolve_profile("workday-da:post-connection")

    assert profile is not None
    assert "WD-CONN-013" not in profile.checkpoint_ids
    assert not registry.profile_matches(
        "workday-da:post-connection", "WD-CONN-013"
    )


def test_post_connection_profile_runs_real_workday_category() -> None:
    plan = registry.profile_requirements("workday-da:post-connection")
    labels = [label for label, _fn in plan.ordered_fns]

    assert "Profile Stubs" not in labels
    assert "Workday" in labels


@pytest.mark.parametrize("target", [
    "WD-DA-FLOW-001",
    "WD-DA-AUTH-001",
    "WD-DA-RUN-001",
])
def test_runtime_checkpoint_plan_uses_dataverse_inventory(target: str) -> None:
    plan = registry.transitive_requirements(target)
    labels = [label for label, _fn in plan.ordered_fns]

    assert registry.DATAVERSE in plan.clients
    assert "External Systems" not in labels
    assert "Workday DA" in labels


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
