# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared planning and real CLI regressions using approved API fixtures."""

import base64
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import responses

from flightcheck import cli, registry
from flightcheck.da_checks import DAValidation
from flightcheck.da_execution import DAExecutor, plan_da_checks
from flightcheck.runner import CheckResult
from tests.conftest import require_validated_mock
from tests.flightcheck.test_maker_diagnostics import (
    TENANT_ID, _body, _capture, _register_maker_baseline, _register_native,
    setup_workspace as setup_workspace,
)
from tests.mocks import graph as graph_mock
from tests.mocks import azure_arm as arm_mock
from tests.mocks import powerplatform as platform_mock
from tests.mocks import pp_admin as admin_mock
from tests.mocks import dataverse as dataverse_mock


def _run_cli(ws, monkeypatch, http, options, output="report"):
    (ws.root / ".local" / "config.json").write_text(json.dumps(ws.config), encoding="utf-8")
    monkeypatch.setattr("sys.argv", [
        "flightcheck", *options, "--output", output, "--no-open", "--no-telemetry",
    ])
    with pytest.raises(SystemExit) as exit_result:
        cli.main()
    payload = json.loads((ws.root / output / "results.json").read_text(encoding="utf-8"))
    assert (ws.root / output / "report.html").exists()
    assert payload["coverage"]["planned"] == payload["coverage"]["emitted"]
    assert payload["total"] == len(payload["coverage"]["planned"])
    assert sum(
        payload["coverage"][key]
        for key in ("automaticCompleted", "manual", "notApplicable", "limitations")
    ) == payload["total"]
    html = (ws.root / output / "report.html").read_text(encoding="utf-8")
    assert f'{payload["total"]} planned' in html
    assert f'{payload["coverage"]["automaticCompleted"]} automatically completed' in html
    return payload, exit_result.value.code


def _row(payload, key):
    return next(row for row in payload["results"] if row["checkpoint_id"] == key)


@pytest.mark.parametrize("status", ["Passed", "Manual", "Blocked", "Error", "NotConfigured"])
def test_custom_tags_merge_registered_and_producer_labels_without_mutation(status):
    from flightcheck.da_execution import decorate

    source = CheckResult(
        "CUSTOM-001", "Test", "High", status, "Custom check", "Recorded result.",
        custom_tags=["Shared label", "Producer alias"],
    )
    original = deepcopy(source)
    spec = registry.CheckpointSpec(
        key="CUSTOM-001", category_label="Test", category_fn=lambda _: [source],
        custom_tags=("Registered alias", "Shared label"),
        da=DAValidation(
            purpose="Custom check", prerequisites=(),
            manual_steps=("Inspect the selected setting.",), if_incorrect="Repair confirmed defects.",
        ),
    )
    runner = SimpleNamespace(agent_slug="hr", env_id="test-environment")
    executor = DAExecutor(runner, SimpleNamespace(), (spec.key,), (spec,), {})
    row = executor.run(runner)[0]
    assert row.custom_tags == ["Registered alias", "Shared label", "Producer alias"]
    assert decorate(runner, spec, row).custom_tags == ["Registered alias", "Shared label", "Producer alias"]
    assert row.status == status
    assert source == original


@pytest.mark.parametrize("identity", ["matching", "other_account", "missing_account", "other_tenant", "auth_error"])
def test_graph_uses_its_own_authentication_and_rejects_identity_changes(monkeypatch, identity):
    from flightcheck.graph_client import GraphClient

    calls = []
    token_tenant = TENANT_ID if identity != "other_tenant" else "00000000-0000-4000-8000-000000009999"
    claims = base64.urlsafe_b64encode(json.dumps({"tid": token_tenant}).encode()).decode().rstrip("=")

    def authenticate(client, preferred_username=None):
        calls.append((client.tenant_id, preferred_username))
        if identity == "auth_error":
            raise RuntimeError("Graph authentication failed (invalid_request).")
        client.signed_in_username = {
            "other_account": "other@example.test", "missing_account": None,
        }.get(identity, "maker@example.test")
        client._token = f"header.{claims}.signature"
        return client._token

    monkeypatch.setattr(GraphClient, "authenticate", authenticate)
    runner = SimpleNamespace(
        graph=None, tenant_id=TENANT_ID, authenticated_account="maker@example.test",
        connection_dependency_token=lambda _: pytest.fail("Graph must not use the AgentBuilder public client"),
    )
    executor = DAExecutor(runner, SimpleNamespace(), (), (), {})
    for _ in range(2):
        if identity == "matching":
            assert executor.graph() is runner.graph
            assert runner.graph.strict_reads is True
        else:
            with pytest.raises((ValueError, RuntimeError), match="different|unverifiable|invalid_request"):
                executor.graph()
            assert runner.graph is None
    assert calls == [(TENANT_ID, "maker@example.test")]


def test_remaining_da_guidance_has_real_full_checkpoint_profile_and_entrypoint_parity(
    setup_workspace, monkeypatch,
):
    ws = setup_workspace
    keys = (
        "CONFIG-013", "EXT-002", "EXT-002-ACL", "DA-SP-FILTER-001", "DA-HANDOFF-001",
        "QA-001", "QA-002", "QA-012", "PUB-003", "PUB-006", "PUB-011", "DA-RUNTIME-001",
    )
    monkeypatch.setitem(registry.PROFILES, "da:test-remaining", registry.ProfileSpec(
        "da:test-remaining", keys, "Same scoped remaining DA assertions.",
    ))
    findings = []
    for index, options in enumerate((
        ["--scope", "full", "--invocation-source", "adk"],
        ["--scope", "full", "--invocation-source", "cli"],
        ["--profile", "da:test-remaining", "--validation-realm", "dev"],
        ["--checkpoint", "EXT-002"],
    )):
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            _register_native(http, ws)
            if index < 2:
                _register_maker_baseline(http)
            payload, code = _run_cli(ws, monkeypatch, http, options, f"remaining-{index}")
            assert code == 0
            findings.append({key: _row(payload, key) for key in keys if index != 3 or key == "EXT-002"})
            if index >= 2:
                assert all(
                    call.request.url.split("?")[0].endswith(("/components", ws.config["agents"][0]["botId"], "/configuration"))
                    for call in http.calls
                )
            if index == 2:
                assert payload["profile"] == "da:test-remaining"
                assert payload["overall"] == "READY"
    assert findings[0] == findings[1] == findings[2]
    assert findings[0]["EXT-002"] == findings[3]["EXT-002"]
    assert all(row["status"] == "Manual" for row in findings[0].values())
    assert "page URL includes that page" in findings[0]["CONFIG-013"]["remediation"]
    assert "crawl account" in findings[0]["EXT-002"]["remediation"]
    assert "scripted deny conservatively blocks all" in findings[0]["EXT-002-ACL"]["remediation"]
    assert "scripted allow is skipped" in findings[0]["EXT-002-ACL"]["remediation"]
    assert "managed-property mapping" in findings[0]["DA-SP-FILTER-001"]["remediation"]
    assert "no setup is required" in findings[0]["DA-SP-FILTER-001"]["result"]
    assert findings[0]["DA-HANDOFF-001"]["evidence"]["applicability"] == "unknown"
    assert "standalone HR or IT agent requires no Hub" in findings[0]["DA-HANDOFF-001"]["remediation"]
    assert "instruction behavior rather than mandatory CEA topics" in findings[0]["QA-001"]["remediation"]
    assert "deployed-but-unrun" in findings[0]["QA-002"]["remediation"]
    assert "universal percentage threshold" in findings[0]["QA-012"]["remediation"]
    assert "publication is not required" in findings[0]["PUB-003"]["remediation"]
    assert "Agents > All agents > Requests" in findings[0]["PUB-006"]["remediation"]
    assert "Microsoft 365 Admin" in findings[0]["PUB-006"]["roles"]
    assert "Do not use standalone Teams" in findings[0]["PUB-011"]["remediation"]
    assert "non-maker employee" in findings[0]["DA-RUNTIME-001"]["remediation"]


@pytest.mark.parametrize("state,expected", [
    ("Active", "Manual"), ("Inactive", "NotConfigured"),
    ("unknown", "Manual"), ("absent", "NotConfigured"),
])
def test_native_servicenow_guidance_is_optional_and_consistent_in_all_routes(
    setup_workspace, monkeypatch, state, expected,
):
    ws = setup_workspace
    content = _body(_capture("env004_dependencies.yaml")[1])
    topic = deepcopy(next(change for change in content["botComponentChanges"] if "shared_service-now" in json.dumps(change)))
    topic["component"]["status"] = state
    if state != "absent":
        ws.content["botComponentChanges"].append(topic)
        ws.content["connectionReferenceChanges"] = content["connectionReferenceChanges"]
    keys = ("SN-DA-AUTH-001", "SN-DA-TOPIC-001", "SN-DA-PORTAL-001")
    monkeypatch.setitem(registry.PROFILES, "da:test-native-servicenow", registry.ProfileSpec(
        "da:test-native-servicenow", keys, "Native action checks without CEA requirements.",
    ))
    findings = []
    for index, options in enumerate((
        ["--scope", "full"],
        ["--profile", "da:test-native-servicenow", "--validation-realm", "dev"],
        ["--checkpoint", "SN-DA-AUTH-001"],
    )):
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            _register_native(http, ws)
            if index == 0:
                _register_maker_baseline(http)
            payload, _ = _run_cli(ws, monkeypatch, http, options, f"native-servicenow-{index}")
            findings.append({key: _row(payload, key) for key in keys if index != 2 or key == "SN-DA-AUTH-001"})
            assert not any("/flows/" in call.request.url or "/connectionreferences" in call.request.url for call in http.calls)
            if index:
                assert not any("graph.microsoft" in call.request.url for call in http.calls)
    assert findings[0] == findings[1]
    assert findings[0]["SN-DA-AUTH-001"] == findings[2]["SN-DA-AUTH-001"]
    assert all(row["status"] == expected for row in findings[0].values())
    if state == "Active":
        assert "Microsoft Entra ID User Login" in findings[0]["SN-DA-AUTH-001"]["remediation"]
        assert "Instance name is the short instance name" in findings[0]["SN-DA-AUTH-001"]["remediation"]
        assert "HRSD Setup Configurations" in findings[0]["SN-DA-TOPIC-001"]["remediation"]
        assert "ITSM system-topic list" in findings[0]["SN-DA-TOPIC-001"]["remediation"]
        assert "Set ServiceNow Portal BaseURI" in findings[0]["SN-DA-PORTAL-001"]["remediation"]
    elif state in {"Inactive", "absent"}:
        assert all(row["evidence"]["applicability"] == "not_applicable" for row in findings[0].values())
        assert all(not row["remediation"] for row in findings[0].values())
    else:
        assert "could not be established" in findings[0]["SN-DA-AUTH-001"]["result"]
        assert findings[0]["SN-DA-AUTH-001"]["evidence"]["applicability"] == "unknown"


@pytest.mark.parametrize("status", [200, 403])
def test_teams_sku_absence_is_not_a_da_prerequisite(setup_workspace, monkeypatch, status):
    ws = setup_workspace
    require_validated_mock(graph_mock)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        if status == 200:
            http.add(**graph_mock.list_subscribed_skus(skus=[]))
        else:
            http.add(
                "GET", f"{graph_mock.GRAPH_BASE}/subscribedSkus",
                status=status, json={"error": {"code": "Authorization_RequestDenied"}},
            )
        payload, code = _run_cli(ws, monkeypatch, http, ["--checkpoint", "PRE-003"])
    row = _row(payload, "PRE-003")
    assert code == 0
    assert row["status"] == ("Passed" if status == 200 else "Manual")
    if status == 200:
        assert "0 matching tenant SKU" in row["result"]
        assert "not a universal DA prerequisite" in row["result"]
        assert row["remediation"] == ""
    else:
        assert "not a universal DA prerequisite" in row["remediation"]
        assert "Do not buy or assign a Teams license" in row["remediation"]


def test_register_once_is_discovered_by_full_checkpoint_and_profile(setup_workspace, monkeypatch):
    ws = setup_workspace
    key = "DA-REGISTER-TEST"

    def check(runner):
        count = len(runner._da_native_snapshot["changeset"]["botComponentChanges"])
        return [CheckResult(
            key, "Agent configuration", "High", "Passed", "Selected content observation",
            f"{count} exact selected-agent component(s).", roles=["ESS Maker / Agent Developer"],
        )]

    monkeypatch.setitem(registry.REGISTRY, key, registry.CheckpointSpec(
        key, check, "Agent configuration",
        roles=("ESS Maker / Agent Developer",),
        da=DAValidation(
            purpose="Selected content observation", prerequisites=("DA-CONTENT-001",),
            manual_steps=("Inspect the selected agent in Copilot Studio.",),
            if_incorrect="Repair the selected content and rerun.",
        ),
    ))
    monkeypatch.setitem(registry.PROFILES, "da:test-registration", registry.ProfileSpec(
        "da:test-registration", (key,), "Shared registration regression.",
    ))
    rows = []
    for index, options in enumerate((
        ["--scope", "full"], ["--checkpoint", key],
        ["--profile", "da:test-registration", "--validation-realm", "dev"],
    )):
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            _register_native(http, ws)
            if index == 0:
                _register_maker_baseline(http)
            payload, code = _run_cli(ws, monkeypatch, http, options, f"registration-{index}")
            assert code == 0
            rows.append(_row(payload, key))
            if index:
                assert not any("graph.microsoft.com" in call.request.url for call in http.calls)
    assert rows[0] == rows[1] == rows[2]


def test_full_checkpoint_and_profile_reuse_real_graph_producer(setup_workspace, monkeypatch):
    ws = setup_workspace
    monkeypatch.setitem(registry.PROFILES, "da:test-license", registry.ProfileSpec(
        "da:test-license", ("PRE-001",), "Same supported SKU observation.",
    ))
    rows = []
    for index, options in enumerate((
        ["--scope", "full"], ["--checkpoint", "PRE-001"],
        ["--profile", "da:test-license", "--validation-realm", "dev"],
    )):
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            _register_native(http, ws)
            if index == 0:
                _register_maker_baseline(http)
            else:
                require_validated_mock(graph_mock)
                http.add(**graph_mock.list_subscribed_skus())
            payload, code = _run_cli(ws, monkeypatch, http, options, f"license-{index}")
            assert code == 0
            rows.append(_row(payload, "PRE-001"))
            assert sum("/subscribedSkus" in call.request.url for call in http.calls) == 1
            if index:
                assert not any(
                    value in call.request.url
                    for call in http.calls
                    for value in ("api.bap", "api.flow", "licensing/", "servicePrincipals", "crm.dynamics")
                )
    assert rows[0] == rows[1] == rows[2]
    assert "tenant inventory" in rows[0]["result"]
    assert rows[0]["remediation"] == ""


@pytest.mark.parametrize("status,body,expected", [
    (403, {"error": {"code": "Authorization_RequestDenied"}}, "Manual"),
    (401, {"error": {"code": "InvalidAuthenticationToken"}}, "Error"),
    (503, {"error": {"code": "ServiceUnavailable"}}, "Error"),
    (200, {"unexpected": []}, "Error"),
    (200, {"value": [{}]}, "Error"),
])
def test_permission_fallback_does_not_hide_auth_service_or_shape_errors(
    setup_workspace, monkeypatch, status, body, expected,
):
    ws = setup_workspace
    require_validated_mock(graph_mock)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        http.add("GET", f"{graph_mock.GRAPH_BASE}/subscribedSkus", status=status, json=body)
        payload, code = _run_cli(ws, monkeypatch, http, ["--checkpoint", "PRE-001"])
    row = _row(payload, "PRE-001")
    assert row["status"] == expected
    assert code == (expected == "Error")
    if expected == "Manual":
        assert "denied" in row["result"]
        assert row["evidence"]["httpStatus"] == 403
        assert row["roles"] == ["Microsoft 365 Admin"]
        assert "Microsoft 365 admin center" in row["remediation"]
        assert row["evidence"]["manualVerificationSteps"]
        assert row["evidence"]["ifMissingOrIncorrect"]
        assert payload["coverage"]["automaticCompleted"] == 2
    else:
        assert row["evidence"]["executionError"] is True
        assert "retry" in row["remediation"]


def test_failed_identity_accounts_for_every_planned_check_without_remote_reads(setup_workspace, monkeypatch):
    ws = setup_workspace
    ws.config["tenantId"] = "00000000-0000-4000-8000-000000009999"
    with responses.RequestsMock() as http:
        payload, code = _run_cli(ws, monkeypatch, http, ["--scope", "full"])
        assert not http.calls
    assert code == 1
    assert _row(payload, "DA-AGENT-001")["status"] == "Blocked"
    assert _row(payload, "PRE-001")["status"] == "Blocked"
    assert _row(payload, "QA-001")["status"] == "Blocked"
    assert payload["coverage"]["limitations"] > 0
    assert payload["validation_context"]["targetVerified"] is False


@pytest.mark.parametrize("produced", [0, 2])
def test_missing_or_duplicate_producer_rows_are_explicit_errors(setup_workspace, monkeypatch, produced):
    ws = setup_workspace
    key = "DA-OUTPUT-TEST"
    monkeypatch.setitem(registry.REGISTRY, key, registry.CheckpointSpec(
        key=key, category_label="Agent setup",
        roles=("ESS Maker / Agent Developer",),
        category_fn=lambda _: [
            CheckResult(key, "Agent setup", "High", "Passed", "Test", "Observed.", roles=["ESS Maker / Agent Developer"])
            for _ in range(produced)
        ],
        da=DAValidation(
            purpose="Output reconciliation", prerequisites=(),
            manual_steps=("Inspect the selected agent.",),
            if_incorrect="Repair the selected content and rerun.",
        ),
    ))
    with responses.RequestsMock() as http:
        payload, code = _run_cli(ws, monkeypatch, http, ["--checkpoint", key])
        assert not http.calls
    row = _row(payload, key)
    assert row["status"] == "Error"
    assert f"returned {produced} matching rows" in row["result"]
    assert code == 1


def test_roles_with_zero_members_do_not_prove_assignment(setup_workspace, monkeypatch):
    ws = setup_workspace
    role = graph_mock.directory_role(
        role_id="00000000-0000-4000-8000-000000001a01",
        role_template_id="62e90394-69f5-4237-9190-012177145e10",
    )
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        http.add(**graph_mock.list_directory_roles(roles=[role]))
        http.add(**graph_mock.list_role_members(role_id=role["id"], members=[]))
        payload, code = _run_cli(ws, monkeypatch, http, ["--checkpoint", "PRE-008"])
    row = _row(payload, "PRE-008")
    assert code == 0
    assert row["status"] == "Manual"
    assert "0 active member(s)" in row["result"]
    assert "Do not assign this role to the maker" in row["remediation"]


@pytest.mark.parametrize("state,expected", [("Succeeded", "Passed"), ("Failed", "Failed"), ("Provisioning", "Failed")])
def test_database_type_does_not_override_provisioning_state(state, expected):
    # Pure assertion regression: the legacy precedence bug is independent of HTTP.
    from flightcheck.checks.da_validation import _provisioning

    spec = registry.REGISTRY["ENV-002"]
    runner = SimpleNamespace(
        _maker_environment_snapshot={"properties": {
            "databaseType": "CommonDataService",
            "linkedEnvironmentMetadata": {"resourceProvisioningState": state},
        }},
        maker_workday_extension=True, _da_connection_audit=None,
        da_executor=SimpleNamespace(group=lambda *_: None),
    )
    row = _provisioning(runner, spec)
    assert row.status == expected
    assert f"state: {state}" in row.result
    assert "not used to override" in row.result


def test_full_dispositions_exclude_aliases_guards_and_deferred_alm():
    _, plan, _ = plan_da_checks()
    keys = {spec.key for spec in plan}
    assert "ENV-004" in keys
    assert "ENV-004-WD" not in keys
    assert not keys.intersection({"PUB-001", "PUB-002", "ENV-004-GRS", "WD-WF-001"})
    for spec in registry.REGISTRY.values():
        assert spec.da is not None
        if spec.da.executable:
            assert spec.key in keys
            assert spec.da.manual_steps
        for replacement in spec.da.replacements:
            assert replacement in registry.REGISTRY
    _, alias_plan, aliases = plan_da_checks(checkpoint="ENV-004-WD")
    assert aliases["ENV-004-WD"] == ("ENV-004",)
    assert "ENV-004-WD" not in {spec.key for spec in alias_plan}
    _, provider_plan, provider_aliases = plan_da_checks(checkpoint="DA-INTEGRATIONS-001")
    assert provider_aliases["DA-INTEGRATIONS-001"] == ("WD-INTEGRATION-001", "SN-INTEGRATION-001")
    assert "DA-INTEGRATIONS-001" not in {spec.key for spec in provider_plan}


@pytest.mark.parametrize("value,expected", [
    (None, "Manual"),
    ("", "Manual"),
    ("https://wd.example.test/ccx/api", "Manual"),
    ("https://wd.example.test/ccx/api/", "Manual"),
    ("http://wd.example.test/ccx/api", "Failed"),
    ("https://wd.example.test/wrong/api", "Failed"),
    ("https://wd.example.test/ccx/api/staffing/v1", "Failed"),
    ("https://wd.example.test/ccx/api//", "Failed"),
    ("https:///ccx/api", "Failed"),
    ("https://secret-user:secret-password@wd.example.test/ccx/api", "Failed"),
    ("https://wd.example.test/ccx/api?token=secret-token", "Failed"),
    ("https://wd.example.test/ccx/api#secret-token", "Failed"),
    ("https://wd.example.test:bad/ccx/api", "Failed"),
    ("https://wd.\nexample.test/ccx/api", "Failed"),
    ("https://wd.example.test\\other/ccx/api", "Failed"),
    (" https://wd.example.test/ccx/api", "Failed"),
    ({"url": "https://wd.example.test/ccx/api"}, "Error"),
])
def test_da_rest_checks_saved_structure_without_certifying_deployment(
    setup_workspace, monkeypatch, value, expected,
):
    ws = setup_workspace
    ws.config["restBaseUrl"] = value
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        payload, code = _run_cli(ws, monkeypatch, http, ["--checkpoint", "WD-REST-001"])
        assert all("workday" not in call.request.url for call in http.calls)
    row = _row(payload, "WD-REST-001")
    assert row["status"] == expected
    assert code == (expected in {"Failed", "Error"})
    assert row["doc_link"].endswith("declarative-agent-workday#phase-4-create-connections")
    rendered = json.dumps(row)
    assert "secret-password" not in rendered
    assert "secret-user" not in rendered
    assert "secret-token" not in rendered
    if expected == "Failed":
        assert "/ccx/api" in row["result"]
        assert "Deployed settings were not read" in row["result"]
        assert "/connect workday" in row["remediation"]
    elif expected == "Manual":
        assert "deployed" in row["result"]
        assert "actual deployed connection" in row["remediation"]
        assert row["evidence"]["manualVerificationSteps"]
    else:
        assert "must be a string" in row["result"]
        assert "retry" in row["remediation"]


def test_reference_data_alias_uses_current_topic_guidance_without_legacy_reads(
    setup_workspace, monkeypatch,
):
    ws = setup_workspace
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        payload, code = _run_cli(ws, monkeypatch, http, ["--checkpoint", "LOCAL-TC-001"])
        assert not any(
            value in call.request.url
            for call in http.calls for value in ("template", "workday", "crm.dynamics")
        )
    assert code == 0
    assert payload["coverage"]["aliases"]["LOCAL-TC-001"] == ["WD-REF-001"]
    assert "LOCAL-TC-001" not in payload["coverage"]["emitted"]
    row = _row(payload, "WD-REF-001")
    assert row["status"] == "Manual"
    assert "Set Runtime Template Configurations" in row["remediation"]
    assert "Maintain Reference IDs" in row["remediation"]
    assert "k (ReferenceId)" in row["remediation"]
    assert "doubled quotation marks" in row["remediation"]
    assert "unused types" in row["remediation"]
    assert row["doc_link"].endswith("#customize-workday-reference-data")


def test_reconciled_workday_guidance_reuses_full_checkpoint_and_profile_producers(
    setup_workspace, monkeypatch,
):
    from flightcheck.checks import _connection_dependencies
    from tests.flightcheck.checks.test_workday_da_readiness import _component_payload

    ws = setup_workspace
    ws.content["botComponentChanges"] = _component_payload()["botComponentChanges"]
    ws.config["restBaseUrl"] = "https://wd.example.test/ccx/api"
    monkeypatch.setattr(_connection_dependencies, "discover_tenant", lambda _: TENANT_ID)
    keys = (
        "WD-DA-ATTACH-001", "WD-REF-001", "WD-CONN-AUTH-001", "WD-API-CLIENT-001",
        "WD-TENANT-001", "WD-SEC-003", "WD-DA-MAKER-001", "WD-REST-001", "WD-NET-001",
        "WD-CONN-010", "WD-CONN-102",
        "WD-DA-TOPIC-001", "WD-DA-WIRING-001",
    )
    monkeypatch.setitem(registry.PROFILES, "da:test-workday-guidance", registry.ProfileSpec(
        "da:test-workday-guidance", keys, "Same Workday configuration assertions.",
    ))
    selections = (
        ["--scope", "full"],
        ["--profile", "da:test-workday-guidance", "--validation-realm", "dev"],
        ["--checkpoint", "WD-REF-001"],
    )
    findings = []
    for index, options in enumerate(selections):
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            _register_native(http, ws)
            if index == 0:
                _register_maker_baseline(http)
            payload, _ = _run_cli(ws, monkeypatch, http, options, f"workday-guidance-{index}")
            selected = keys if index < 2 else ("WD-REF-001",)
            findings.append({key: _row(payload, key) for key in selected})
            assert not any("wd.example.test" in call.request.url for call in http.calls)
            if index:
                assert not any(
                    value in call.request.url
                    for call in http.calls for value in ("api.flow", "api.powerapps", "graph.microsoft", "crm.dynamics")
                )
    assert findings[0] == findings[1]
    assert findings[0]["WD-REF-001"] == findings[2]["WD-REF-001"]
    assert all(
        row["status"] == ("Passed" if key in {"WD-DA-TOPIC-001", "WD-DA-WIRING-001"} else "Manual")
        for key, row in findings[0].items()
    )
    assert "not a confirmed configuration defect" in findings[0]["WD-DA-ATTACH-001"]["result"]
    assert "Manage" in findings[0]["WD-DA-ATTACH-001"]["remediation"]
    assert "SAML SP ID http://www.workday.com/<tenant>, not api://" in findings[0]["WD-CONN-AUTH-001"]["remediation"]
    assert "no ISU is required" in findings[0]["WD-CONN-AUTH-001"]["remediation"]
    assert "Workday API client ID, not the Entra" in findings[0]["WD-API-CLIENT-001"]["remediation"]
    for area in ("Core Payroll", "Organizations and Roles", "Staffing", "Time Off and Leave"):
        assert area in findings[0]["WD-API-CLIENT-001"]["remediation"]
    assert "Get under Integration Permissions" in findings[0]["WD-SEC-003"]["remediation"]
    assert "Activate All Pending Authentication Policy Changes" in findings[0]["WD-TENANT-001"]["remediation"]
    assert "Publication is not required" in findings[0]["WD-DA-MAKER-001"]["remediation"]
    assert "not evidence of Power Platform runtime egress" in findings[0]["WD-NET-001"]["remediation"]
    for key in ("WD-CONN-010", "WD-CONN-102"):
        steps = findings[0][key]["evidence"]["manualVerificationSteps"]
        assert len(steps) == 3
        assert "ask the Entra and Workday administrators to inspect the same target" in steps[-1]


@pytest.mark.parametrize("state", ["missing", "Inactive"])
@pytest.mark.parametrize("selection", ["full", "checkpoint", "profile"])
def test_required_workday_topic_defects_use_native_snapshot_without_dataverse_dependency(
    setup_workspace, monkeypatch, state, selection,
):
    from flightcheck.checks import _connection_dependencies
    from tests.flightcheck.checks.test_workday_da_readiness import SCHEMA, _component_payload

    ws = setup_workspace
    schema = f"{SCHEMA}.topic.WorkdayManagerCheck"
    content = _component_payload(
        missing=schema if state == "missing" else "",
        inactive=schema if state == "Inactive" else "",
    )
    ws.content["botComponentChanges"] = content["botComponentChanges"]
    monkeypatch.setattr(_connection_dependencies, "discover_tenant", lambda _: TENANT_ID)
    monkeypatch.setitem(registry.PROFILES, "da:test-workday-topics", registry.ProfileSpec(
        "da:test-workday-topics", ("WD-DA-TOPIC-001",), "Required Workday dependencies.",
    ))
    options = {
        "full": ["--scope", "full"],
        "checkpoint": ["--checkpoint", "WD-DA-TOPIC-001"],
        "profile": ["--profile", "da:test-workday-topics", "--validation-realm", "dev"],
    }[selection]
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        if selection == "full":
            _register_maker_baseline(http)
        payload, code = _run_cli(ws, monkeypatch, http, options)
        if selection != "full":
            assert not any(
                value in call.request.url
                for call in http.calls for value in ("crm.dynamics", "api.bap", "api.flow", "graph.microsoft")
            )
    row = _row(payload, "WD-DA-TOPIC-001")
    assert code == 1
    assert row["status"] == "Failed", row["result"]
    assert schema in row["result"]
    assert ("missing required" if state == "missing" else "inactive required") in row["result"]
    assert "/connect workday" in row["remediation"]
    assert row["doc_link"].endswith("declarative-agent-workday-reference#system-topics")


@pytest.mark.parametrize("key", ["SAP-001", "DA-SAP-RUNTIME-001"])
def test_excluded_assertions_explain_missing_coverage_without_running_old_probes(
    setup_workspace, monkeypatch, key,
):
    with responses.RequestsMock() as http:
        payload, code = _run_cli(setup_workspace, monkeypatch, http, ["--checkpoint", key])
        assert not http.calls
    row = _row(payload, key)
    assert code == 0
    assert row["status"] == "NotConfigured"
    assert "implementation/scope exclusion" in row["result"]
    assert row["evidence"]["disposition"] == "excluded"


@pytest.mark.parametrize("continuation", [
    "https://other.example.test/v1.0/subscribedSkus",
    "https://graph.microsoft.com/v1.0/users",
    "https://graph.microsoft.com/v1.0/subscribedSkus",
])
def test_strict_graph_pagination_rejects_foreign_wrong_resource_and_cycles(continuation):
    from flightcheck.graph_client import GraphClient

    client = GraphClient(TENANT_ID, strict_reads=True)
    client._token = "read-token"
    with responses.RequestsMock() as http:
        http.get(
            f"{graph_mock.GRAPH_BASE}/subscribedSkus",
            json={"value": [], "@odata.nextLink": continuation},
        )
        with pytest.raises(ValueError, match="continuation"):
            client.get_subscribed_skus()
        assert len(http.calls) == 1


@pytest.mark.parametrize("required,assigned,expected", [
    (True, True, "Passed"), (True, False, "Failed"), (False, False, "Passed"),
])
def test_workday_assignment_reads_only_the_configured_application(
    setup_workspace, monkeypatch, required, assigned, expected,
):
    ws = setup_workspace
    require_validated_mock(graph_mock)
    application = graph_mock.application()
    principal = graph_mock.service_principal(app_role_assignment_required=required)
    ws.config["entraAppId"] = application["appId"]
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        http.add(**graph_mock.list_applications(applications=[application]))
        http.add(**graph_mock.list_service_principals(service_principals=[principal]))
        http.add(**graph_mock.list_app_role_assignments(
            sp_id=principal["id"], assignments=[graph_mock.app_role_assignment()] if assigned else [],
        ))
        payload, code = _run_cli(ws, monkeypatch, http, ["--checkpoint", "WD-ASSIGN-001"])
        assert not any(value in call.request.url for value in ("api.bap", "api.flow", "api.powerapps") for call in http.calls)
        assert not any("applicationTemplates" in call.request.url for call in http.calls)
    row = _row(payload, "WD-ASSIGN-001")
    assert row["status"] == expected
    assert f"assignment required={required}" in row["result"]
    assert ("assign the approved user/group" in row["remediation"]) is (expected == "Failed")
    assert code == (expected == "Failed")


@pytest.mark.parametrize("stored", ["none", "app", "object", "pair"])
@pytest.mark.parametrize("selection", ["scope", "checkpoint"])
def test_explicit_workday_app_overrides_saved_ids_without_persisting_them(
    setup_workspace, monkeypatch, stored, selection,
):
    ws = setup_workspace
    require_validated_mock(graph_mock)
    stale_app = "00000000-0000-4000-8000-000000008891"
    stale_object = "00000000-0000-4000-8000-000000008892"
    if stored in {"app", "pair"}:
        ws.config["entraAppId"] = stale_app
    if stored in {"object", "pair"}:
        ws.config["entraAppObjectId"] = stale_object
    original = deepcopy(ws.config)
    interactions = _capture("env004_dependencies.yaml")
    content = _body(interactions[1])
    topic = deepcopy(next(change for change in content["botComponentChanges"] if "InvokeConnectorAction" in json.dumps(change)))
    topic["component"]["status"] = "Active"
    ws.content["botComponentChanges"].append(topic)
    ws.content["connectionReferenceChanges"] = content["connectionReferenceChanges"]
    reference = ws.content["connectionReferenceChanges"][0]["connectionReference"]
    reference["connectorId"] = reference["connectorId"].replace("shared_service-now", "shared_workdaysoap")
    records = _body(next(item for item in interactions if "/connectionreferences" in item["request"]["uri"]))["value"]
    reference["connectionId"] = next(row["connectionid"] for row in records if row["connectionreferencelogicalname"] == "msdyn_sharedworkdaysoap_workdayruntime")
    app = graph_mock.application()
    principal = graph_mock.service_principal(app_role_assignment_required=False)
    graph_app_id = "00000003-0000-0000-c000-000000000000"
    graph_principal = graph_mock.service_principal(
        sp_id="00000000-0000-4000-8000-000000008893", app_id=graph_app_id,
    )
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        for item in interactions:
            uri = item["request"]["uri"]
            if "/connections?" in uri:
                captured_env = uri.split("/environments/")[1].split("/")[0]
                http.add("GET", uri.replace(captured_env, ws.config["environmentId"]).split("?")[0], json=_body(item))
        http.add(
            **graph_mock.list_applications(applications=[app]),
            match=[responses.matchers.query_param_matcher({"$filter": f"appId eq '{app['appId']}'"}, strict_match=False)],
        )
        for resource in (principal, graph_principal):
            http.add(
                **graph_mock.list_service_principals(service_principals=[resource]),
                match=[responses.matchers.query_param_matcher({"$filter": f"appId eq '{resource['appId']}'"}, strict_match=False)],
            )
        http.add(**graph_mock.list_app_role_assignments(sp_id=principal["id"], assignments=[]))
        http.add(**graph_mock.list_claims_mapping_policies_for_sp(sp_id=principal["id"], policies=[]))
        http.add(**graph_mock.list_oauth2_permission_grants(grants=[]))
        options = ["--scope", "workday"] if selection == "scope" else ["--checkpoint", "WD-ASSIGN-001"]
        payload, _ = _run_cli(ws, monkeypatch, http, [
            *options, "--workday-app-id", " " + app["appId"].upper() + " ",
        ])
        assert not any(stale_app in call.request.url or stale_object in call.request.url for call in http.calls)
        app_calls = [call for call in http.calls if urlsplit(call.request.url).path.endswith("/applications")]
        assert len(app_calls) == 1
    row = _row(payload, "WD-ASSIGN-001")
    assert row["status"] == "Passed", row["result"]
    assert "assignment required=False" in row["result"]
    assert not any(row["status"] == "Error" for row in payload["results"])
    assert ws.config == original
    assert json.loads((ws.root / ".local" / "config.json").read_text(encoding="utf-8")) == original
    if selection == "checkpoint":
        assert "--workday-app-id " + app["appId"].upper() in payload["rerun_command"]


def test_invalid_explicit_workday_app_does_not_inspect_the_saved_application(setup_workspace, monkeypatch):
    ws = setup_workspace
    ws.config["entraAppId"] = graph_mock.MOCK_WORKDAY_APP_ID
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        payload, code = _run_cli(ws, monkeypatch, http, [
            "--checkpoint", "WD-ASSIGN-001", "--workday-app-id", "not-a-guid",
        ])
        assert not any("graph.microsoft.com" in call.request.url for call in http.calls)
    row = _row(payload, "WD-ASSIGN-001")
    assert row["status"] == "Error"
    assert "ValueError" in row["result"]
    assert code == 1


@pytest.mark.parametrize("variant", ["web_to_api", "api_to_web", "unrelated", "path"])
def test_scope_cli_verifies_dataverse_aliases_against_the_selected_environment(
    setup_workspace, monkeypatch, variant,
):
    from flightcheck import maker_diagnostics as maker
    from flightcheck.checks import _connection_dependencies

    ws = setup_workspace
    environment = _body(next(
        item for item in _capture("flightcheck_pp_admin.yaml")
        if "api.bap.microsoft.com" in item["request"]["uri"] and "/environments/" in item["request"]["uri"]
    ))
    metadata = environment["properties"]["linkedEnvironmentMetadata"]
    web = metadata["instanceUrl"].rstrip("/")
    api = web.replace(".crm.", ".api.crm.")
    metadata["instanceApiUrl"] = api
    ws.config["dataverseEndpoint"] = api if variant == "api_to_web" else web
    requested = {
        "web_to_api": api, "api_to_web": web,
        "unrelated": "https://unrelated.crm.dynamics.com", "path": api + "/other",
    }[variant]
    monkeypatch.setattr(_connection_dependencies, "discover_tenant", lambda _: TENANT_ID)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws, environment_body=environment)
        payload, code = _run_cli(ws, monkeypatch, http, [
            "--scope", "workday", "--environment-url", requested,
        ])
        native_reads = [call for call in http.calls if "/minimalBots/" in call.request.url]
        assert bool(native_reads) is (variant not in {"unrelated", "path"})
    row = _row(payload, "DA-AGENT-001")
    scopes = [call.args[0] for call in maker.authenticate_flightcheck_dependency.call_args_list]
    if variant in {"unrelated", "path"}:
        assert row["status"] == "Blocked"
        assert "different Power Platform environment" in row["result"]
        assert not any(scope.endswith("/user_impersonation") for scope in scopes)
        assert code == 1
    else:
        assert row["status"] == "Passed", row["result"]
        assert [scope for scope in scopes if scope.endswith("/user_impersonation")] == [requested + "/user_impersonation"]
        assert code == 0
    assert json.loads((ws.root / ".local" / "config.json").read_text(encoding="utf-8")) == ws.config


@pytest.mark.parametrize("missing", ["none", "scope_authorization", "graph_permission"])
def test_workday_scope_requires_authorization_for_the_actual_exposed_scope(
    setup_workspace, monkeypatch, missing,
):
    ws = setup_workspace
    app = graph_mock.application(graph_permissions=missing != "graph_permission")
    if missing == "scope_authorization":
        app["api"]["preAuthorizedApplications"][0]["delegatedPermissionIds"] = []
    ws.config["entraAppId"] = app["appId"]
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        http.add(**graph_mock.list_applications(applications=[app]))
        http.add(**graph_mock.list_service_principals())
        payload, code = _run_cli(ws, monkeypatch, http, ["--checkpoint", "WD-ENTRA-SCOPE-001"])
    row = _row(payload, "WD-ENTRA-SCOPE-001")
    assert row["status"] == ("Passed" if missing == "none" else "Failed")
    assert "Enabled user_impersonation" in row["result"]
    assert code == (missing != "none")


def test_wrong_workday_application_response_never_becomes_a_sibling_fallback(setup_workspace, monkeypatch):
    ws = setup_workspace
    ws.config["entraAppId"] = graph_mock.MOCK_WORKDAY_APP_ID
    sibling = graph_mock.service_principal(app_id="00000000-0000-4000-8000-00000000abcd")
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        http.add(**graph_mock.list_applications())
        http.add(**graph_mock.list_service_principals(service_principals=[sibling]))
        payload, code = _run_cli(ws, monkeypatch, http, ["--checkpoint", "WD-ASSIGN-001"])
        assert not any("appRoleAssignedTo" in call.request.url for call in http.calls)
    assert code == 1
    assert _row(payload, "WD-ASSIGN-001")["status"] == "Error"
    assert "exact application" in _row(payload, "WD-ASSIGN-001")["result"]


@pytest.mark.parametrize("value", ["Active", "Inactive", "unknown", "absent"])
def test_full_optional_servicenow_accounts_for_every_child_without_legacy_flows(
    setup_workspace, monkeypatch, value,
):
    ws = setup_workspace
    payload = _body(_capture("env004_dependencies.yaml")[1])
    topic = deepcopy(next(item for item in payload["botComponentChanges"] if "shared_service-now" in json.dumps(item)))
    topic["component"]["status"] = value
    if value != "absent":
        ws.content["botComponentChanges"].append(topic)
        ws.content["connectionReferenceChanges"] = payload["connectionReferenceChanges"]
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        _register_maker_baseline(http)
        result, code = _run_cli(ws, monkeypatch, http, ["--scope", "full"])
        assert not any("/flows/" in call.request.url for call in http.calls)
    assert not any(row["checkpoint_id"].startswith("SN-CFG-") for row in result["results"])
    if value == "Active":
        assert _row(result, "SN-CONN-001")["status"] == "Failed"
        assert _row(result, "SN-RUN-001")["evidence"]["applicability"] == "not_applicable"
        assert _row(result, "SN-FLOW-001")["evidence"]["applicability"] == "not_applicable"
        assert code == 1
    elif value in {"Inactive", "absent"}:
        assert _row(result, "SN-CONN-001")["evidence"]["applicability"] == "not_applicable"
        assert code == 0
    else:
        assert _row(result, "SN-CONN-001")["status"] == "Manual"
        assert _row(result, "SN-CONN-001")["evidence"]["applicability"] == "unknown"


@pytest.mark.parametrize("allocated,http_status,expected", [
    (100, 200, "Passed"), (0, 200, "Manual"), (100, 403, "Manual"), (100, 503, "Error"),
])
def test_capacity_uses_actual_allocation_without_turning_billing_alternatives_into_defects(
    setup_workspace, monkeypatch, allocated, http_status, expected,
):
    require_validated_mock(platform_mock)
    ws = setup_workspace
    entitlement = platform_mock.environment_entitlement(allocated=allocated)
    entitlement["environmentId"] = ws.config["environmentId"]
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        http.add(**platform_mock.get_environment_entitlements(
            environment_id=ws.config["environmentId"], entitlements=[entitlement], status=http_status,
        ))
        payload, _ = _run_cli(ws, monkeypatch, http, ["--checkpoint", "ENV-CAPACITY-001"])
    row = _row(payload, "ENV-CAPACITY-001")
    assert row["status"] == expected
    if http_status == 200:
        assert f"{allocated}" in row["result"]
        assert "audience or usage sufficiency" in row["result"]
    assert bool(row["remediation"]) is (expected != "Passed")


@pytest.mark.parametrize("state,budget_status,expected", [
    ("Enabled", 200, "Passed"), ("Disabled", 403, "Failed"),
    ("Enabled", 403, "Manual"), ("Enabled", 401, "Error"),
])
def test_billing_scopes_links_and_does_not_hide_unhealthy_subscription_behind_budget_denial(
    setup_workspace, monkeypatch, state, budget_status, expected,
):
    require_validated_mock(platform_mock)
    require_validated_mock(arm_mock)
    ws = setup_workspace
    policy = platform_mock.billing_policy()
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        http.add(**platform_mock.list_billing_policies(policies=[policy]))
        http.add(**platform_mock.list_policy_environments(environments=[
            platform_mock.billing_policy_environment(environment_id=ws.config["environmentId"]),
        ]))
        http.add(**arm_mock.get_subscription(state=state))
        if state != "Disabled":
            http.add(**arm_mock.list_budgets(budgets=[arm_mock.budget()], status=budget_status))
        payload, code = _run_cli(ws, monkeypatch, http, ["--checkpoint", "PRE-005"])
        if state == "Disabled":
            assert not any("/budgets" in call.request.url for call in http.calls)
    row = _row(payload, "PRE-005")
    assert row["status"] == expected
    assert code == (expected in {"Failed", "Error"})
    if expected == "Passed":
        assert "Enabled subscriptions" in row["result"]
        assert row["remediation"] == ""
    elif expected == "Failed":
        assert "unhealthy subscription" in row["result"]
        assert row["remediation"]
    elif expected == "Manual":
        assert row["evidence"]["subscriptions"][0]["state"] == "Enabled"
        assert "denied" in row["result"]
        assert row["evidence"]["manualVerificationSteps"]


@pytest.mark.parametrize("provider", ["workday", "servicenow"])
@pytest.mark.parametrize("sample,expected", [
    ("success", "Passed"), ("failure", "Failed"), ("stale", "Manual"),
    ("child", "Manual"), ("future", "Error"), ("naive", "Error"),
    ("running", "Manual"), ("mixed", "Passed"), ("caught_failure", "Failed"),
    ("denied", "Manual"), ("unauthorized", "Error"), ("service_error", "Error"), ("malformed", "Error"),
])
def test_passive_history_checks_only_exact_provider_flows_and_validated_recent_samples(provider, sample, expected):
    from flightcheck.pp_admin_client import PPAdminClient

    require_validated_mock(admin_mock)
    flow_id = "00000000-0000-4000-8000-000000007101"
    key = "WD-RUN-001" if provider == "workday" else "SN-RUN-001"
    connector = "shared_workdaysoap" if provider == "workday" else "shared_service-now"
    principal_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    if sample == "stale":
        principal_time -= timedelta(hours=2)
    if sample == "future":
        principal_time += timedelta(hours=2)
    timestamp = principal_time.isoformat()
    if sample == "naive":
        timestamp = principal_time.replace(tzinfo=None).isoformat()
    response_name = "Respond_to_Copilot_with_Success" if provider == "workday" else "Respond_to_Copilot"
    if sample == "child":
        response_name = ""
    run = admin_mock.flow_run(
        env_id=admin_mock.MOCK_ENV_ID, flow_id=flow_id, start_time=timestamp,
        status="Failed" if sample == "failure" else "Running" if sample == "running" else "Succeeded",
        response_name=(
            "Respond_to_Copilot_with_failure_errorMessage" if provider == "workday"
            else "Respond_to_Copilot_-_Failure"
        ) if sample == "caught_failure" else response_name,
    )
    if sample == "malformed":
        run["properties"] = None
    client = PPAdminClient(TENANT_ID)
    client.set_read_tokens(flow_token="fixture-read-token")
    runner = SimpleNamespace(
        agent_slug="hr", env_id=admin_mock.MOCK_ENV_ID, tenant_id=TENANT_ID,
        pp_admin=client, scope="checkpoint", da_explicit_selection=True,
        maker_integrations={"ServiceNow": {"applicability": "enabled"}},
        _da_connection_audit=SimpleNamespace(references=[
            SimpleNamespace(connector_id=connector, flow_ids=[flow_id]),
            SimpleNamespace(connector_id="shared_unrelated", flow_ids=["unrelated-flow"]),
        ]),
    )
    executor = DAExecutor(runner, SimpleNamespace(), (key,), (registry.REGISTRY[key],), {})
    executor.groups["connections"] = []  # The exact dependency audit above is the producer's pure input.
    executor.groups["integrations"] = []
    runner.da_executor = executor
    with responses.RequestsMock() as http:
        runs = [run]
        if sample == "mixed":
            failed = deepcopy(run)
            failed["properties"]["status"] = "Failed"
            runs.append(failed)
        http.add(**admin_mock.list_flow_runs(
            flow_id=flow_id, runs=runs,
            status={"denied": 403, "unauthorized": 401, "service_error": 500}.get(sample, 200),
        ))
        row = executor.run(runner)[0]
        assert http.calls
        assert all(flow_id in call.request.url for call in http.calls)
    assert row.status == expected
    assert row.custom_tags == (["Workday Litmus Test"] if provider == "workday" else [])
    if expected in {"Passed", "Failed"}:
        assert "scoreable recent exact-flow" in row.result
        assert "not a current intended-employee smoke test" in row.result
    elif expected == "Manual":
        if provider == "workday":
            steps = "\n".join(row.evidence["manualVerificationSteps"])
            if sample == "denied":
                assert "history was denied" in row.result
                assert "Do not submit additional test prompts" in steps
                assert "What is my employee ID" not in steps
                assert row.evidence["flowId"] == flow_id
            elif sample == "running":
                assert "rerun the Workday Litmus Test" in steps
                assert "still running" in row.result
                assert "do not create duplicate" in steps.lower()
                assert "What is my employee ID" not in steps
            else:
                assert "rerun the Workday Litmus Test" in steps
                assert "No recent completed Workday response" in row.result
                assert "What is my employee ID" in steps and "Click Test in the top-right corner" in steps
        else:
            assert ("denied" if sample == "denied" else "No scoreable") in row.result
        if sample == "denied":
            assert row.evidence["httpStatus"] == 403
        else:
            assert row.evidence["windowMinutes"] == 60
    else:
        assert row.evidence["executionError"] is True
        if sample in {"future", "naive"}:
            assert "timestamp" in row.result
    assert bool(row.remediation) is (expected != "Passed")


@pytest.mark.parametrize("surface", ["powerplatform", "arm"])
@pytest.mark.parametrize("bad", ["shape", "empty", "foreign", "wrong_resource", "conflicting", "cycle"])
def test_strict_billing_collection_never_hides_invalid_or_unsafe_continuation(surface, bad):
    from flightcheck.azure_arm_client import AzureArmClient
    from flightcheck.powerplatform_client import PowerPlatformClient

    if surface == "powerplatform":
        require_validated_mock(platform_mock)
        client = PowerPlatformClient(TENANT_ID, strict_reads=True)
        fixture = platform_mock.list_billing_policies()
        read = client.list_billing_policies
        continuation_key = "@odata.nextLink"
    else:
        require_validated_mock(arm_mock)
        client = AzureArmClient(TENANT_ID, strict_reads=True)
        fixture = arm_mock.list_budgets()
        def read():
            return client.list_budgets(arm_mock.MOCK_SUBSCRIPTION_ID)
        continuation_key = "nextLink"
    client._token = "fixture-read-token"
    body = fixture["json"]
    if bad == "shape":
        body = {"unexpected": []}
    else:
        body[continuation_key] = {
            "empty": "", "foreign": "https://example.invalid/collection",
            "wrong_resource": fixture["url"] + "/other", "conflicting": fixture["url"] + "?page=2",
            "cycle": fixture["url"],
        }[bad]
        if bad == "conflicting":
            body["nextLink" if surface == "powerplatform" else "@odata.nextLink"] = fixture["url"] + "?page=3"
    fixture["json"] = body
    with responses.RequestsMock() as http:
        http.add(**fixture)
        with pytest.raises(ValueError, match="collection|continuation"):
            read()
        assert len(http.calls) <= 2


@pytest.mark.parametrize("selection", ["checkpoint", "profile"])
@pytest.mark.parametrize("installed", [True, False])
def test_workday_package_inspection_is_available_before_topics_are_activated(
    setup_workspace, monkeypatch, selection, installed,
):
    from flightcheck.checks import _connection_dependencies

    ws = setup_workspace
    require_validated_mock(dataverse_mock)
    monkeypatch.setattr(_connection_dependencies, "discover_tenant", lambda _: TENANT_ID)
    environment = _body(next(
        item for item in _capture("flightcheck_pp_admin.yaml")
        if "api.bap.microsoft.com" in item["request"]["uri"] and "/environments/" in item["request"]["uri"]
    ))
    env_url = environment["properties"]["linkedEnvironmentMetadata"]["instanceUrl"]
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        http.add(**dataverse_mock.query(
            base_url=env_url, entity_set="solutions",
            records=[{
                "solutionid": "00000000-0000-4000-8000-000000008801",
                "uniquename": "msdyn_EssWorkdayRuntime", "friendlyname": "Workday runtime",
                "ismanaged": True, "version": "2.1.0.0",
            }] if installed else [],
        ))
        options = ["--checkpoint", "WD-DA-PKG-001"] if selection == "checkpoint" else [
            "--profile", "workday-da:package-ready", "--validation-realm", "dev",
        ]
        payload, code = _run_cli(ws, monkeypatch, http, options)
        assert not any(value in call.request.url for call in http.calls for value in ("api.flow", "graph.microsoft", "connectivity/"))
    row = _row(payload, "WD-DA-PKG-001")
    assert row["status"] == ("Passed" if installed else "Failed")
    assert ("msdyn_EssWorkdayRuntime" if installed else "not installed") in row["result"]
    assert bool(row["remediation"]) is not installed
    assert code == (not installed)


@pytest.mark.parametrize("provider", ["WD", "SN"])
@pytest.mark.parametrize("selection", ["checkpoint", "scope"])
def test_selective_integration_uses_real_mixed_dependency_capture_without_other_provider_binding_reads(
    setup_workspace, monkeypatch, provider, selection,
):
    from flightcheck.checks import _connection_dependencies
    from urllib.parse import urlsplit

    ws = setup_workspace
    interactions = _capture("env004_dependencies.yaml")
    content = _body(interactions[1])
    service_connection = "00000000-0000-4000-8000-000000008803"
    if provider == "SN":
        for change in content["botComponentChanges"]:
            if "shared_service-now" in json.dumps(change):
                change["component"]["status"] = "Active"
        content["connectionReferenceChanges"][0]["connectionReference"]["connectionId"] = service_connection
    ws.content["botComponentChanges"].extend(content["botComponentChanges"])
    ws.content["connectionReferenceChanges"] = content["connectionReferenceChanges"]
    captured_env = next(
        item["request"]["uri"].split("/environments/")[1].split("?")[0]
        for item in interactions
        if "api.bap.microsoft.com" in item["request"]["uri"]
    )
    monkeypatch.setattr(_connection_dependencies, "discover_tenant", lambda _: TENANT_ID)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        for item in interactions:
            uri = item["request"]["uri"]
            if "minimalBots" in uri or "api.bap.microsoft" in uri:
                continue
            uri = urlsplit(uri.replace(captured_env, ws.config["environmentId"]))._replace(query="").geturl()
            body = _body(item)
            if provider == "SN" and uri.endswith("/connections"):
                original = next(row for row in body["value"] if "shared_workdaysoap" in row["id"])
                reference = deepcopy(original)
                reference["id"] = original["id"].replace("shared_workdaysoap", "shared_service-now").rsplit("/", 1)[0] + "/" + service_connection
                reference["name"] = service_connection
                reference["properties"]["apiId"] = original["properties"]["apiId"].replace("shared_workdaysoap", "shared_service-now")
                body["value"].append(reference)
            http.add(item["request"]["method"], uri, json=body)
        options = ["--checkpoint", f"{provider}-CONN-001"] if selection == "checkpoint" else [
            "--scope", "workday" if provider == "WD" else "servicenow",
        ]
        result, code = _run_cli(ws, monkeypatch, http, options)
        assert not any("graph.microsoft.com" in call.request.url for call in http.calls)
        if provider == "SN":
            assert not any("/connectionreferences" in call.request.url for call in http.calls)
    row = _row(result, f"{provider}-CONN-001")
    assert row["status"] == "Passed", row["result"]
    assert "Exact bindings were verified" in row["result"]
    expected_connector = "shared_workdaysoap" if provider == "WD" else "shared_service-now"
    assert all(ref["connector_id"].endswith(expected_connector) for ref in row["evidence"]["references"])
    assert not row["remediation"]
    if selection == "checkpoint":
        assert code == 0
    assert not any(row["checkpoint_id"].startswith("SN-" if provider == "WD" else "WD-") for row in result["results"])


@pytest.mark.parametrize("http_status", [403, 503])
@pytest.mark.parametrize("key,activation,unbound", [
    ("WD-CONN-001", "Inactive", False),
    ("WD-CONN-001", "Active", False),
    ("WD-CONN-012", "Active", False),
    ("WD-CONN-012", "Active", True),
])
def test_focused_bindings_separate_inactive_inventory_from_required_active_discovery(
    setup_workspace, monkeypatch, http_status, key, activation, unbound,
):
    from flightcheck.checks import _connection_dependencies

    ws = setup_workspace
    interactions = _capture("env004_dependencies.yaml")
    content = _body(interactions[1])
    failing_flow = "00000000-0000-0000-0000-000000000015"
    for change in content["botComponentChanges"]:
        if failing_flow in json.dumps(change):
            change["component"]["status"] = activation
    ws.content["botComponentChanges"].extend(content["botComponentChanges"])
    ws.content["connectionReferenceChanges"] = content["connectionReferenceChanges"]
    environment = next(item for item in interactions if "api.bap.microsoft" in item["request"]["uri"])
    captured_env = _body(environment)["name"]
    monkeypatch.setattr(_connection_dependencies, "discover_tenant", lambda _: TENANT_ID)

    def references(request):
        query = parse_qs(urlsplit(request.url).query).get("$filter", [""])[0]
        records = _body(next(item for item in interactions if "/connectionreferences" in item["request"]["uri"]))["value"]
        if unbound:
            next(row for row in records if row["connectionreferencelogicalname"] == "msdyn_sharedworkdaysoap_workdayruntime")["connectionid"] = None
        return 200, {"Content-Type": "application/json"}, json.dumps({
            "value": [row for row in records if "'" + row["connectionreferencelogicalname"] + "'" in query],
        })

    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        for item in interactions:
            uri = item["request"]["uri"]
            if "minimalBots" in uri or "api.bap.microsoft" in uri:
                continue
            uri = urlsplit(uri.replace(captured_env, ws.config["environmentId"]))._replace(query="").geturl()
            if "/connectionreferences" in uri:
                http.add_callback("GET", uri, callback=references)
            else:
                http.add(
                    item["request"]["method"], uri, json=_body(item),
                    status=http_status if uri.endswith("/flows/" + failing_flow) else 200,
                )
        payload, code = _run_cli(ws, monkeypatch, http, ["--checkpoint", key])
    row = _row(payload, key)
    expected = "Failed" if unbound else "Passed" if activation == "Inactive" else "Manual" if http_status == 403 else "Error"
    assert row["status"] == expected, row["result"]
    assert row["evidence"]["dependencyCoverageComplete"] is (activation == "Inactive")
    assert bool(row["remediation"]) is (expected != "Passed")
    assert code == (expected != "Passed")
    if activation == "Inactive":
        inventory = row["evidence"]["inactiveInventoryReadLimitations"]
        assert inventory[0]["kind"] == ("permission_denied" if http_status == 403 else "error")
        assert "Exact bindings were verified" in row["result"]
    elif key == "WD-CONN-012":
        assert "discovery was incomplete" in row["result"]
        assert row["evidence"]["readLimitations"][0]["kind"] == ("permission_denied" if http_status == 403 else "error")
        assert not any(item["checkpoint_id"] == "ENV-004" for item in payload["results"])
        if unbound:
            assert row["evidence"]["unbound"] == ["msdyn_sharedworkdaysoap_workdayruntime"]


@pytest.mark.parametrize("http_status", [403, 503])
def test_workday_profile_keeps_confirmed_failures_when_late_reference_read_fails(
    setup_workspace, monkeypatch, http_status,
):
    from flightcheck.checks import _connection_dependencies

    require_validated_mock(dataverse_mock)
    ws = setup_workspace
    monkeypatch.setattr(_connection_dependencies, "discover_tenant", lambda _: TENANT_ID)
    environment = _body(next(
        item for item in _capture("flightcheck_pp_admin.yaml")
        if "api.bap.microsoft.com" in item["request"]["uri"] and "/environments/" in item["request"]["uri"]
    ))
    env_url = environment["properties"]["linkedEnvironmentMetadata"]["instanceUrl"]
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        for entity in ("solutions", "workflows", "connectionreferences"):
            http.add(**dataverse_mock.query(
                base_url=env_url, entity_set=entity, records=[],
                status=http_status if entity == "connectionreferences" else 200,
            ))
        payload, code = _run_cli(ws, monkeypatch, http, [
            "--profile", "workday-da:dataverse-ready", "--validation-realm", "dev",
        ])
    package = _row(payload, "WD-DA-PKG-001")
    assert package["status"] == "Failed", package["result"]
    assert "not installed" in package["result"]
    assert "install" in package["remediation"].lower()
    assert _row(payload, "WD-DA-FLOW-001")["status"] == "Failed"
    reference = _row(payload, "DV-CONN-001")
    assert reference["status"] == ("Manual" if http_status == 403 else "Error")
    assert reference["evidence"]["httpStatus"] == (403 if http_status == 403 else None)
    assert "could not be inspected" in reference["result"]
    assert code == 1


@pytest.mark.parametrize("endpoint", [
    "web", "api", "api_upper", "unrelated", "path", "http", "userinfo", "query", "port",
    "other_tenant", "other_subject",
])
def test_selected_dataverse_accepts_only_verified_web_or_api_roots(monkeypatch, endpoint):
    from flightcheck.checks import _connection_dependencies

    environment = _body(next(
        item for item in _capture("flightcheck_pp_admin.yaml")
        if "api.bap.microsoft.com" in item["request"]["uri"] and "/environments/" in item["request"]["uri"]
    ))
    metadata = environment["properties"]["linkedEnvironmentMetadata"]
    web = metadata["instanceUrl"].rstrip("/")
    api = web.replace(".crm.", ".api.crm.")
    malformed = {
        "path": api + "/other", "http": api.replace("https:", "http:"),
        "userinfo": api.replace("https://", "https://user@"),
        "query": api + "?other=1", "port": api + ":444",
    }
    metadata["instanceApiUrl"] = malformed.get(endpoint, api)
    configured = (
        web if endpoint == "web" else api.upper() + "/" if endpoint == "api_upper" else
        "https://unrelated.crm.dynamics.com" if endpoint == "unrelated" else metadata["instanceApiUrl"]
    )
    requests = []
    runner = SimpleNamespace(
        env_id=environment["name"] if endpoint != "other_subject" else "other-environment",
        env_url=configured, tenant_id=TENANT_ID, maker_diagnostics=True,
        _maker_environment_snapshot=environment,
        connection_dependency_token=lambda scope: requests.append(scope) or "read-token",
    )
    monkeypatch.setattr(
        _connection_dependencies, "discover_tenant",
        lambda _: "other-tenant" if endpoint == "other_tenant" else TENANT_ID,
    )
    if endpoint in {"web", "api", "api_upper"}:
        first = _connection_dependencies._Access(runner).dataverse()
        assert first[0].casefold() == (web if endpoint == "web" else api).casefold()
        assert _connection_dependencies._Access(runner).dataverse() == first
        assert requests == [first[0] + "/user_impersonation"]
    else:
        with pytest.raises(ValueError, match="different|verified Dataverse root"):
            _connection_dependencies._Access(runner).dataverse()
        assert not requests


@pytest.mark.parametrize("scope,prefix", [("workday", "WD"), ("servicenow", "SN")])
def test_da_provider_scopes_share_maker_and_standalone_planning_and_findings(
    setup_workspace, monkeypatch, scope, prefix,
):
    ws = setup_workspace
    findings = []
    for source in ("adk", "cli"):
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            _register_native(http, ws)
            payload, code = _run_cli(ws, monkeypatch, http, [
                "--scope", scope, "--invocation-source", source, "--agent-slug", "hr",
            ], output=source)
            assert not any("graph.microsoft.com" in call.request.url or "/flows" in call.request.url for call in http.calls)
        assert payload["diagnostic_only"] is True
        assert payload["scope"] == scope
        assert _row(payload, prefix + "-INTEGRATION-001")["evidence"]["applicability"] == "not_configured"
        assert not any(row["checkpoint_id"].startswith("SN-" if prefix == "WD" else "WD-") for row in payload["results"])
        assert code == 0
        findings.append((payload["coverage"], payload["results"]))
    assert findings[0] == findings[1]


@pytest.mark.parametrize("grant_target,expected", [
    ("graph", "Passed"), ("other_resource", "Failed"), ("other_client", "Failed"), ("user", "Failed"),
])
def test_workday_consent_is_bound_to_exact_client_graph_resource_and_tenant_wide_grant(
    setup_workspace, monkeypatch, grant_target, expected,
):
    ws = setup_workspace
    ws.config["entraAppId"] = graph_mock.MOCK_WORKDAY_APP_ID
    graph_sp_id = "00000000-0000-4000-8000-000000008802"
    graph_sp = graph_mock.service_principal(
        sp_id=graph_sp_id, app_id="00000003-0000-0000-c000-000000000000",
    )
    grant = graph_mock.oauth2_permission_grant(
        resource_id=graph_sp_id if grant_target != "other_resource" else "other-resource",
        client_id=graph_mock.MOCK_WORKDAY_SP_ID if grant_target != "other_client" else "other-client",
        consent_type="Principal" if grant_target == "user" else "AllPrincipals",
    )
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        http.add(**graph_mock.list_applications())
        http.add(**graph_mock.list_service_principals())
        http.add(**graph_mock.list_service_principals(service_principals=[graph_sp]))
        http.add(**graph_mock.list_oauth2_permission_grants(grants=[grant]))
        payload, _ = _run_cli(ws, monkeypatch, http, ["--checkpoint", "WD-ENTRA-CONSENT-001"])
    row = _row(payload, "WD-ENTRA-CONSENT-001")
    assert row["status"] == expected, row["result"]
    assert "Grants to other resources were not counted" in row["result"]
    assert bool(row["remediation"]) is (expected == "Failed")


@pytest.mark.parametrize("status,kind", [(403, "permission_denied"), (503, "error")])
def test_inactive_flow_discovery_retains_permission_vs_service_error(status, kind):
    from flightcheck.checks._connection_dependencies import ConnectionAudit
    from flightcheck.checks.maker_integrations import run_optional_integration_checks
    from flightcheck.pp_admin_client import PPAdminClient

    content = _body(_capture("env004_dependencies.yaml")[1])
    topic = next(change for change in content["botComponentChanges"] if "InvokeFlowAction" in json.dumps(change))
    topic["component"]["status"] = "Inactive"
    content["botComponentChanges"] = [topic]
    content["bot"] = {"schemaName": "gptagent_copilotforemployeeselfservicehr"}
    client = PPAdminClient(TENANT_ID)
    client.set_read_tokens(flow_token="fixture-read-token")
    runner = SimpleNamespace(
        _da_native_snapshot={"changeset": content}, _da_connection_audit=ConnectionAudit(),
        pp_admin=client, env_id=admin_mock.MOCK_ENV_ID,
    )
    from flightcheck.checks._connection_dependencies import _nodes
    flow_id = next(node["flowId"] for node in _nodes(topic) if node.get("$kind") == "InvokeFlowAction")
    require_validated_mock(admin_mock)
    uri = next(
        item["request"]["uri"] for item in _capture("env004_dependencies.yaml")
        if f"/flows/{flow_id}?" in item["request"]["uri"]
    )
    captured_env = uri.split("/environments/")[1].split("/")[0]
    uri = uri.replace(captured_env, runner.env_id).split("?")[0]
    with responses.RequestsMock() as http:
        http.add("GET", uri, status=status, json={})
        rows = run_optional_integration_checks(runner)
    assert all(row.status == "Blocked" for row in rows)
    assert not runner._da_connection_audit.read_limitations
    limitation = runner.maker_integrations["Workday"]["inventoryReadLimitations"][0]
    assert limitation["kind"] == kind
    assert flow_id in limitation["context"]
    runner.agent_slug = "hr"
    runner.da_explicit_selection = True
    keys = ("WD-INTEGRATION-001", "WD-CONN-001")
    executor = DAExecutor(runner, SimpleNamespace(), keys, tuple(registry.REGISTRY[key] for key in keys), {})
    executor.groups["integrations"] = rows
    runner.da_executor = executor
    results = executor.run(runner)
    assert all(row.status == ("Manual" if status == 403 else "Error") for row in results)
    assert all(row.remediation for row in results)


@pytest.mark.parametrize("mode,expected", [
    ("allow", "Passed"), ("blocked", "Failed"), ("blocked_unknown", "Failed"),
    ("denied", "Manual"), ("malformed", "Error"),
])
def test_dlp_wrapper_evaluates_exact_connectors_without_hiding_policy_read_limitations(mode, expected):
    from flightcheck.checks._connection_dependencies import ConnectionAudit, Reference
    from flightcheck.pp_admin_client import PPAdminClient

    require_validated_mock(admin_mock)
    connector = "/providers/Microsoft.PowerApps/apis/shared_workdaysoap"
    policy = admin_mock.dlp_policy_modern(
        business=[connector] if mode == "allow" else [],
        blocked=[connector] if mode == "blocked" else [],
    )
    if mode == "blocked_unknown":
        policy = admin_mock.dlp_policy(blocked=[connector])
    client = PPAdminClient(TENANT_ID)
    client.set_read_tokens(powerapps_token="fixture-read-token")
    runner = SimpleNamespace(
        agent_slug="hr", env_id=admin_mock.MOCK_ENV_ID, pp_admin=client,
        da_observations={}, _da_connection_audit=ConnectionAudit(references=[
            Reference("agent", "reference", connector, "connection"),
        ]),
    )
    if mode == "blocked_unknown":
        runner._da_connection_audit.references.append(Reference("agent", "other", "shared_service-now", "other"))
    key = "INFRA-006"
    executor = DAExecutor(runner, SimpleNamespace(), (key,), (registry.REGISTRY[key],), {})
    runner.da_executor = executor
    uri = next(
        item["request"]["uri"] for item in _capture("flightcheck_pp_admin.yaml")
        if "/apiPolicies" in item["request"]["uri"]
    )
    with responses.RequestsMock() as http:
        http.add(
            "GET", uri, status=403 if mode == "denied" else 200,
            json={} if mode == "denied" else {"value": [{"properties": None}] if mode == "malformed" else [policy]},
        )
        row = executor.run(runner)[0]
    assert row.status == expected, row.result
    assert bool(row.remediation) is (expected != "Passed")
    if mode in {"allow", "blocked", "blocked_unknown"}:
        assert "Selected connector classification" in row.result
        assert bool(row.evidence["blocked"]) is (mode != "allow")
    if mode == "denied":
        assert "denied" in row.result
        assert "Data policies" in row.remediation


@pytest.mark.parametrize("dependency", ["missing", "cycle"])
def test_da_registry_rejects_invalid_prerequisite_graph_before_execution(monkeypatch, dependency):
    from dataclasses import replace

    original = registry.REGISTRY["PRE-001"]
    bad = "NOT-REGISTERED" if dependency == "missing" else original.key
    monkeypatch.setitem(registry.REGISTRY, original.key, replace(
        original, da=replace(original.da, prerequisites=(bad,)),
    ))
    with pytest.raises(ValueError, match="Missing DA|Cyclic DA"):
        plan_da_checks(checkpoint=original.key)


@pytest.mark.parametrize("blocked,read_error,no_references,no_policies", [
    (False, False, False, False), (True, False, False, False),
    (False, True, False, False), (False, True, True, False),
    (False, False, False, True),
])
def test_dlp_partial_discovery_retains_defects_without_passing(blocked, read_error, no_references, no_policies):
    from flightcheck.checks._connection_dependencies import ConnectionAudit, Reference

    connector = "/providers/Microsoft.PowerApps/apis/shared_workdaysoap"
    policy = admin_mock.dlp_policy_modern(
        blocked=[connector] if blocked else [], business=[] if blocked else [connector],
    )
    audit = ConnectionAudit(
        references=[] if no_references else [Reference("hr", "ref", connector, "connection")],
        failures=["Another binding is missing."],
        warnings=["An active flow could not be inspected."],
        read_limitations=[{"kind": "error" if read_error else "denied", "context": "flow"}],
    )
    runner = SimpleNamespace(
        agent_slug="hr", env_id=admin_mock.MOCK_ENV_ID,
        da_observations={"dlp_policies": [] if no_policies else [policy]}, _da_connection_audit=audit,
    )
    key = "INFRA-006"
    executor = DAExecutor(runner, SimpleNamespace(), (key,), (registry.REGISTRY[key],), {})
    runner.da_executor = executor
    executor.rows["ENV-004"] = CheckResult("ENV-004", "Connections", "High", "Failed", "Bindings", "Missing binding.")
    row = executor.run(runner)[0]
    assert row.status == ("Failed" if blocked else "Error" if read_error else "Manual"), row.result
    assert row.evidence["dependencyCoverageComplete"] is False


@pytest.mark.parametrize("profile", [
    "workday-da:setup-readiness", "workday-da:external-prerequisites",
    "workday-da:package-ready", "workday-da:dataverse-ready",
    "workday-da:post-connection", "workday-da:post-agent-wiring",
    "workday-da:post-runtime", "workday-da:final",
])
def test_real_cli_profile_adapter_output_is_consumed_by_connect(setup_workspace, monkeypatch, profile):
    """Domain rows are pure inputs; exercise real native reads, planning and contracts."""
    from dataclasses import replace
    from flightcheck.checks import _connection_dependencies
    from tests.scripts.test_workday_connect_flightcheck import _state, _record_rest_target
    from workday_connect_flightcheck import evaluate_contract
    from workday_connect_readiness_policy import PROFILE_POLICIES

    ws = setup_workspace
    environment = _body(next(
        item for item in _capture("flightcheck_pp_admin.yaml")
        if "api.bap.microsoft.com" in item["request"]["uri"] and "/environments/" in item["request"]["uri"]
    ))
    url = environment["properties"]["linkedEnvironmentMetadata"]["instanceUrl"]
    ws.config.update({"dataverseEndpoint": url, "restBaseUrl": "https://example.test/ccx/api"})
    monkeypatch.setattr(_connection_dependencies, "discover_tenant", lambda _: TENANT_ID)
    # Keep native, endpoint and portal-only producers real. Supply other domain
    # observations without adding an invented external API response.
    for key in PROFILE_POLICIES[profile].checkpoints:
        spec = registry.REGISTRY[key]
        if spec.da.strategy in {"native", "rest_endpoint", "manual", "workday_entra"}:
            continue
        def domain_row(_runner, current=spec):
            return [CheckResult(current.key, current.category_label, current.priority, "Passed", current.da.purpose, "Domain observation fixture.")]
        monkeypatch.setitem(registry.REGISTRY, key, replace(
            spec, category_fn=domain_row, da=replace(spec.da, strategy="custom", feature=""),
        ))
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        payload, code = _run_cli(ws, monkeypatch, http, [
            "--profile", profile, "--validation-realm", "dev",
            "--environment-url", url, "--preferred-username", "maker@example.test",
        ])
    state = _state()
    state["scope"].update({
        "environmentId": ws.config["environmentId"], "dataverseUrl": url,
        "entraTenantId": TENANT_ID, "agent": ws.config["agents"][0],
    })
    state["operators"]["powerPlatformMaker"]["username"] = "maker@example.test"
    _record_rest_target(state, ws.config["restBaseUrl"])
    for phase, action in (
        ("entra", "administrator-configuration-verified"),
        ("workday-admin", "administrator-response-validated"),
        ("runtime", "flow-attachment-confirmed"),
    ):
        state["phases"][phase]["completedActions"].append(action)
        state["phases"][phase]["evidence"].append({"action": action})
    assert code == 0
    assert set(payload["client_availability"]) == set(PROFILE_POLICIES[profile].clients)
    assert evaluate_contract(payload["contract"], state, profile)["accepted"] is True


@pytest.mark.parametrize("variant", ["no_endpoint", "configured_endpoint", "wrong_account", "denied_endpoint"])
def test_real_setup_profile_keeps_optional_endpoint_and_rejects_unverified_target(setup_workspace, monkeypatch, variant):
    from flightcheck.checks import _connection_dependencies
    from tests.scripts.test_workday_connect_flightcheck import _state
    from workday_connect_flightcheck import evaluate_contract, WorkdayConnectFlightCheckError

    ws = setup_workspace
    profile = "workday-da:setup-readiness"
    state = _state()
    url = "https://orgmocktenant.crm.dynamics.com" if variant != "no_endpoint" else ""
    if url:
        ws.config["dataverseEndpoint"] = url
        monkeypatch.setattr(_connection_dependencies, "discover_tenant", lambda _: TENANT_ID)
    if variant == "wrong_account":
        ws.auth.return_value = ("token", TENANT_ID, "other@example.test")
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        if variant == "denied_endpoint":
            def denied(*_args, **_kwargs):
                raise PermissionError("The selected environment read was denied.")
            monkeypatch.setattr(_connection_dependencies._Access, "admin", denied)
        payload, code = _run_cli(ws, monkeypatch, http, [
            "--profile", profile, "--validation-realm", "dev", "--preferred-username", "maker@example.test",
        ])
    state["scope"].update({
        "environmentId": ws.config["environmentId"], "dataverseUrl": url,
        "entraTenantId": TENANT_ID, "agent": ws.config["agents"][0],
    })
    state["operators"]["powerPlatformMaker"]["username"] = "maker@example.test"
    if variant in {"wrong_account", "denied_endpoint"}:
        assert code == (1 if variant == "wrong_account" else 0)
        assert _row(payload, "DA-AGENT-001")["status"] in {"Blocked", "Manual"}
        with pytest.raises(WorkdayConnectFlightCheckError):
            evaluate_contract(payload["contract"], state, profile)
    else:
        assert code == 0
        assert evaluate_contract(payload["contract"], state, profile)["accepted"] is True
        assert payload["validation_context"]["environmentUrl"].rstrip("/") == url


def test_local_inventory_denied_fallback_has_no_minimum(monkeypatch):
    from flightcheck import maker_diagnostics

    def denied(_):
        raise PermissionError("Selected workspace is unreadable.")
    monkeypatch.setattr(maker_diagnostics, "_check_local", denied)
    key = "TOPIC-011"
    runner = SimpleNamespace(agent_slug="hr", env_id="")
    executor = DAExecutor(runner, SimpleNamespace(), (key,), (registry.REGISTRY[key],), {})
    runner.da_executor = executor
    row = executor.run(runner)[0]
    assert row.status == "Manual"
    assert "no required minimum" in row.remediation
    assert "minimum of five" not in row.remediation


@pytest.mark.parametrize("bad_identity", [False, True])
def test_litmus_default_output_is_focused_and_preserves_full_report(setup_workspace, monkeypatch, bad_identity):
    import re

    ws = setup_workspace
    full = ws.root / "workspace" / "flightcheck" / "report.html"
    full.parent.mkdir()
    full.write_text("Existing full report", encoding="utf-8")
    if bad_identity:
        ws.content["bot"]["cdsBotId"] = "00000000-0000-4000-8000-000000009991"
    (ws.root / ".local" / "config.json").write_text(json.dumps(ws.config), encoding="utf-8")
    monkeypatch.setattr("sys.argv", [
        "flightcheck", "--checkpoint", "WD-RUN-001", "--no-open", "--no-telemetry",
        "--preferred-username", "maker@example.test", "--validation-realm", "dev",
    ])
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        _register_native(http, ws)
        with pytest.raises(SystemExit):
            cli.main()
    folder = full.parent / "workday-litmus"
    data = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    html = (folder / "report.html").read_text(encoding="utf-8")
    cards = re.findall(r'<article class="finding"[^>]*>(.*?)</article>', html, re.S)
    assert len(cards) == 1 and ">WD-RUN-001</code>" in cards[0]
    assert data["coverage"]["requested"] == ["WD-RUN-001"]
    assert len(data["results"]) == 3
    assert "3 planned" in html and "2 supporting validation(s)" in html
    assert "--checkpoint WD-RUN-001" in html
    assert "--preferred-username maker@example.test" in data["rerun_command"]
    assert "--validation-realm dev" in data["rerun_command"]
    assert "--no-telemetry" in data["rerun_command"]
    assert "Supporting validation:" in html
    target_index = next(index for index, row in enumerate(data["results"]) if row["checkpoint_id"] == "WD-RUN-001")
    assert f'href="#finding-{target_index}">View requested finding</a>' in html
    assert data["rerun_command"] == data["contract"]["rerunCommand"]
    assert full.read_text(encoding="utf-8") == "Existing full report"
    if bad_identity:
        assert _row(data, "WD-RUN-001")["status"] == "Blocked"
        assert "Dependent reads were not attempted" in cards[0]


@pytest.mark.parametrize("service_error", [False, True])
def test_litmus_discovery_failure_does_not_request_another_prompt(service_error):
    from flightcheck.checks._connection_dependencies import ConnectionAudit

    runner = SimpleNamespace(
        agent_slug="hr", env_id="environment", scope="checkpoint", da_explicit_selection=True,
        _da_connection_audit=ConnectionAudit(
            warnings=["Could not read an invoked flow."],
            read_limitations=[{"kind": "error" if service_error else "permission_denied"}],
        ),
    )
    key = "WD-RUN-001"
    executor = DAExecutor(runner, SimpleNamespace(), (key,), (registry.REGISTRY[key],), {})
    executor.groups["connections"] = []
    runner.da_executor = executor
    row = executor.run(runner)[0]
    assert row.status == ("Error" if service_error else "Manual")
    assert "What is my employee ID" not in row.remediation
    assert row.evidence["dependencyCoverageComplete"] is False


@pytest.mark.parametrize("has_labels", [False, True])
def test_litmus_instructions_name_the_target_and_separate_agent_test_from_chat_rerun(has_labels):
    from flightcheck.checks.da_validation import _litmus_manual

    runner = SimpleNamespace(agent_slug="hr", env_id="target-environment")
    if has_labels:
        runner._da_native_snapshot = {"changeset": {"bot": {"displayName": "HR Test Agent"}}}
        runner._maker_environment_snapshot = {"properties": {"displayName": "Workday Test Environment"}}
    row = _litmus_manual(runner, registry.REGISTRY["WD-RUN-001"], {"recentRuns": []}, running=False)
    steps = row.evidence["manualVerificationSteps"]
    assert len(steps) == 5
    assert steps[0].startswith("Sign in to [Copilot Studio]")
    assert "Microsoft work account shown in this report" in steps[0]
    assert ('"Workday Test Environment"' if has_labels else '"target-environment"') in steps[0]
    assert ('"HR Test Agent"' if has_labels else '"hr"') in steps[0]
    assert "Start a new conversation" in steps[1]
    assert "Click Test in the top-right corner" in steps[1]
    assert '"What is my employee ID"' in steps[2]
    assert "not to VS Code Copilot Chat" in steps[2]
    assert "Wait for the agent to finish" in steps[3]
    assert "separate from signing in to Copilot Studio" in steps[3]
    assert "Keep the employee ID private" in steps[3]
    assert steps[4] == "Once the agent finishes answering, rerun the Workday Litmus Test."
    assert "FlightCheck does not run the test for you" in row.result
    assert "do not enable it" in row.evidence["ifMissingOrIncorrect"]
    assert "Do not keep sending test questions" in row.evidence["ifMissingOrIncorrect"]
    assert "publishing" not in "\n".join(steps).lower()
