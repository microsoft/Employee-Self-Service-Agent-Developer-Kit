# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure integration planning and permission boundaries, not external API proof."""

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from flightcheck import cli, registry
from flightcheck.checks import da_integrations as integrations
from flightcheck.checks._connection_dependencies import ConnectionAudit, Reference
from flightcheck.da_contract import DAApplicability, DAFeature, DAFeatureEvidence
from flightcheck.da_execution import build_da_execution_plan
from flightcheck.runner import CheckResult, Status


BOT = "00000000-0000-0000-0000-000000003333"
ENV = "00000000-0000-0000-0000-000000002222"
TENANT = "00000000-0000-0000-0000-000000001111"


def _config():
    agent = {"slug": "hr", "botId": BOT, "schemaName": "gptagent_hr", "releaseLine": "da"}
    return {
        "activeAgent": "hr", "agents": [agent], "agent": agent,
        "environmentId": ENV, "tenantId": TENANT, "realm": "dev",
    }


def _state():
    return {
        "schemaVersion": 12, "activeTargetRealm": "dev", "status": "ready",
        "scope": {
            "agent": {"slug": "hr", "botId": BOT, "schemaName": "gptagent_hr"},
            "environmentId": ENV, "entraTenantId": TENANT,
            "dataverseUrl": "https://org.crm.dynamics.com",
        },
        "identifiers": {}, "endpoints": {}, "phases": {},
    }


def _merge(tmp_path, state, config=None):
    path = tmp_path / "workday.json"
    path.write_text(json.dumps(state), encoding="utf-8")
    return cli._merge_connect_config(config or _config(), str(path))


@pytest.mark.parametrize("mismatch", ["agent", "schema", "slug", "environment", "realm", "tenant"])
def test_foreign_provider_state_cannot_enable_selected_workday(tmp_path, mismatch):
    state = _state()
    if mismatch in {"agent", "schema", "slug"}:
        key = {"agent": "botId", "schema": "schemaName", "slug": "slug"}[mismatch]
        state["scope"]["agent"][key] = "different"
    elif mismatch == "realm":
        state["activeTargetRealm"] = "prod"
    else:
        state["scope"]["environmentId" if mismatch == "environment" else "entraTenantId"] = "different"
    config = _merge(tmp_path, state)
    assert not integrations.workday_target_matches(config)
    assert integrations.configured_da_features(config) == {}


def test_exact_connect_intent_schedules_reviewed_workday_without_graph(tmp_path):
    config = _merge(tmp_path, _state())
    plan = build_da_execution_plan(config)
    assert {"WD-DA-PKG-001", "WD-DA-FLOW-001", "WD-DA-AUTH-001", "WD-CONN-012",
            "WD-DA-TOPIC-001", "WD-DA-WIRING-001", "WD-DA-ATTACH-001",
            "WD-DA-MAKER-001", "WD-ENTRA-SCOPE-001"} <= set(plan.profile.checkpoint_ids)
    assert registry.DATAVERSE in plan.requirements.clients
    assert registry.GRAPH not in plan.requirements.clients
    assert cli.run_workday_checks not in {fn for _, fn in plan.requirements.ordered_fns}
    with pytest.raises(ValueError, match="contradicts"):
        build_da_execution_plan(
            config, features={DAFeature.WORKDAY: DAFeatureEvidence(False, "conflicting manifest")},
        )
    # Saved "ready" is installation intent, never a passing maker/admin/runtime result.
    assert "intent, not completion" in integrations.configured_da_features(config)[DAFeature.WORKDAY].source


def test_state_adapter_selects_exact_realm_target_without_mutating_state(tmp_path):
    state = _state()
    prod_scope = deepcopy(state["scope"])
    prod_scope["agent"]["botId"] = "00000000-0000-0000-0000-000000009999"
    state["targets"] = {"prod": {"scope": prod_scope, "phases": {"maker": {"status": "ready"}}}}
    config = _config()
    config["realm"] = "prod"
    config["agents"][0]["botId"] = prod_scope["agent"]["botId"]
    config["agent"] = config["agents"][0]
    before = deepcopy(state)
    merged = _merge(tmp_path, state, config)
    assert integrations.workday_target_matches(merged)
    assert merged["_connectConfigRealm"] == "prod"
    assert state == before
    assert json.loads((tmp_path / "workday.json").read_text(encoding="utf-8")) == before


@pytest.mark.parametrize("failure", ["none", "warnings", "failures", "blocked"])
def test_discovery_retains_positive_connectors_and_never_infers_partial_absence(monkeypatch, failure):
    audit = ConnectionAudit(discovered_connectors={"shared_workdaysoap"}, flow_count=1)
    if failure == "blocked":
        audit.blocked = "Exact mapping is unavailable."
    elif failure != "none":
        getattr(audit, failure).append("Some dependency evidence is unavailable.")
    monkeypatch.setattr(integrations, "audit_connections", lambda _runner: audit)
    runner = SimpleNamespace(config=_config())
    features = integrations.discover_da_features(runner)
    assert features[DAFeature.WORKDAY].enabled is True
    assert features[DAFeature.DATAVERSE_RUNTIME].enabled is True
    assert features[DAFeature.SERVICENOW].enabled is (False if failure == "none" else None)
    assert runner._da_connection_audit is audit


def test_complete_empty_graph_does_not_override_matching_connect_intent(tmp_path, monkeypatch):
    monkeypatch.setattr(integrations, "audit_connections", lambda _runner: ConnectionAudit())
    runner = SimpleNamespace(config=_merge(tmp_path, _state()))
    features = integrations.discover_da_features(runner)
    assert features[DAFeature.WORKDAY].enabled is True
    assert features[DAFeature.DATAVERSE_RUNTIME].enabled is True
    assert features[DAFeature.SERVICENOW].enabled is False


def test_sap_is_excluded_even_with_stale_positive_feature_state():
    plan = build_da_execution_plan(
        _config(), features={DAFeature.SAP_SUCCESSFACTORS: DAFeatureEvidence(True, "stale config")},
    )
    sap = next(entry for entry in plan.coverage if entry.checkpoint.key == "DA-SAP-RUNTIME-001")
    assert sap.applicability == DAApplicability.EXCLUDED
    assert "SAP" in sap.checkpoint.reason
    assert "DA-SAP-RUNTIME-001" not in dict(plan.pending)
    assert not any("SAP" in key for key in plan.profile.checkpoint_ids)


def test_invoked_flow_licensing_and_admin_aliases_do_not_require_graph():
    plan = build_da_execution_plan(_config(), features={
        DAFeature.WORKDAY: DAFeatureEvidence(True, "selected dependency audit"),
        DAFeature.POWER_AUTOMATE: DAFeatureEvidence(True, "selected dependency audit"),
    })
    assert {"LIC-FLOW-001", "LIC-FLOW-002", "WD-ASSIGN-001", "WD-ENTRA-NAMEID-001"} <= set(
        plan.profile.checkpoint_ids
    )
    assert registry.GRAPH not in plan.requirements.clients
    assert {"AUTH-005", "AUTH-006"}.isdisjoint(dict(plan.pending))

@pytest.mark.parametrize("condition,expected", [
    ("bound", Status.PASSED.value), ("unbound", Status.FAILED.value),
    ("unrelated_failure", Status.BLOCKED.value), ("candidate_only", Status.BLOCKED.value),
])
def test_exact_service_now_binding_is_not_a_connected_candidate_or_workday_verdict(condition, expected):
    audit = ConnectionAudit(references=[
        Reference(BOT, "required_sn", "shared_service-now", None if condition == "unbound" else "physical-sn"),
    ])
    if condition == "unrelated_failure":
        audit.failures.append("Unrelated Workday reference is unbound.")
    if condition == "candidate_only":
        audit.references = []
        audit.additional_connections = 2
    runner = SimpleNamespace(
        _da_connection_audit=audit, should_execute=lambda key: key == "SN-CONN-001",
    )
    row = integrations.run_da_integration_checks(runner)[0]
    assert row.status == expected
    assert "exact required reference" in row.result
    if condition == "bound":
        assert row.remediation == ""
    else:
        assert "Connected candidates" in row.remediation
    assert row.evidence["evidenceBoundary"] == "exact_bindings_not_employee_execution"


def test_narrow_workday_producers_do_not_execute_legacy_unselected_checks(monkeypatch):
    package = Mock()
    bindings = Mock(return_value=[])
    dv = Mock(return_value=[])
    redirect = Mock(return_value=[])
    monkeypatch.setattr(integrations, "_check_package_flavor", package)
    monkeypatch.setattr(integrations, "_check_package_connection_completeness", bindings)
    monkeypatch.setattr(integrations, "_check_dv_connection", dv)
    monkeypatch.setattr(integrations, "_check_user_context_redirect", redirect)
    runner = SimpleNamespace(should_execute=lambda key: key == "WD-REST-002")
    integrations.run_da_workday_binding_checks(runner)
    integrations.run_da_workday_extension_checks(runner)
    package.assert_called_once_with(runner, wd_flows=[])
    bindings.assert_called_once_with(runner)
    dv.assert_not_called()
    redirect.assert_called_once_with(runner)


def test_failed_exact_agent_preflight_never_discovers_integrations(monkeypatch):
    row = CheckResult("DA-AGENT-001", "Native", "High", "Failed", "Access", "Wrong target")
    monkeypatch.setattr(cli, "run_native_agent_checks", lambda _runner: [row])
    discover = Mock()
    monkeypatch.setattr(integrations, "discover_da_features", discover)
    plan = build_da_execution_plan(_config())
    actual, rows = cli._prepare_da_integration_execution(SimpleNamespace(), None, plan)
    assert actual is plan and rows == [row]
    discover.assert_not_called()
