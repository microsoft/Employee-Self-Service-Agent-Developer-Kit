# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Selected DA CLI and binding regressions replay validated native/dependency captures.

Authentication is stubbed; HTTP contracts come from agentbuilder_readiness.yaml
and env004_dependencies.yaml. Scalar mutations exercise recorded field types.
Local-file, report and orchestration assertions do not simulate external APIs.
"""

from copy import deepcopy
import base64
import json
from pathlib import Path
import re
from types import SimpleNamespace
from urllib.parse import urlsplit
from unittest.mock import Mock

import pytest
import responses
import yaml

from tests.conftest import require_validated_mock
from tests.mocks import graph as graph_mock, powerplatform as powerplatform_mock

from agentbuilder import AgentBuilderClient, ConnectivityClient, derive_environment_host
from flightcheck import cli, maker_diagnostics as maker
from flightcheck.checks import _connection_dependencies, maker_integrations, workday_da
from flightcheck.runner import (
    CheckResult, FlightCheckRunner, _render_header, maker_diagnostic_outcome, save_results,
    versioned_run_result_to_dict,
)
from flightcheck.graph_client import GraphClient


CASSETTES = Path(__file__).resolve().parents[1] / "fixtures" / "cassettes"
ENV_ID = "00000000-0000-4000-8000-000000001111"
TENANT_ID = "00000000-0000-4000-8000-000000003333"


def _capture(name):
    return yaml.safe_load((CASSETTES / name).read_text(encoding="utf-8"))["interactions"]


def _body(item):
    return json.loads(item["response"]["body"]["string"])


@pytest.fixture
def setup_workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    native = [
        item for item in _capture("agentbuilder_readiness.yaml")
        if "/minimalBots/api/" in item["request"]["uri"]
    ]
    content = _body(next(item for item in native if item["request"]["method"] == "POST"))
    # A DA may have only instructions/variables, with no active task dependencies.
    content["botComponentChanges"] = [
        change for change in content["botComponentChanges"]
        if change["component"]["$kind"] != "DialogComponent"
    ]
    agent = {
        "slug": "hr", "botId": content["bot"]["cdsBotId"],
        "schemaName": content["bot"]["schemaName"], "releaseLine": "da",
    }
    config = {
        "environmentId": ENV_ID, "tenantId": TENANT_ID,
        "activeAgent": "hr", "agents": [agent], "ring": "prod",
    }
    (tmp_path / ".local").mkdir()
    path = tmp_path / "workspace" / "agents" / "hr"
    path.mkdir(parents=True)
    (path / "agent.mcs.yml").write_text(
        "displayName: Employee Self-Service\ninstructions: Help employees find approved HR information.\n"
        "conversationStarters:\n  - text: Find HR policies\n  - text: Find leave information\n"
        "  - text: Find benefits information\n",
        encoding="utf-8",
    )
    auth = Mock(return_value=("read-token", TENANT_ID, "maker@example.test"))
    monkeypatch.setattr(maker, "authenticate_flightcheck", auth)
    monkeypatch.setattr(maker, "authenticate_flightcheck_dependency", Mock(return_value="read-token"))

    def authenticate_graph(client, preferred_username=None):
        claims = base64.urlsafe_b64encode(json.dumps({"tid": TENANT_ID}).encode()).decode().rstrip("=")
        client._token = f"header.{claims}.signature"
        client.signed_in_username = "maker@example.test"
        return client._token

    monkeypatch.setattr(GraphClient, "authenticate", authenticate_graph)
    return SimpleNamespace(config=config, native=native, content=content, auth=auth, root=tmp_path)


def _register_native(http, workspace):
    host = derive_environment_host(ENV_ID, "prod")
    for item in workspace.native:
        parsed = urlsplit(item["request"]["uri"])
        uri = parsed._replace(netloc=urlsplit(host).netloc, query="").geturl()
        body = workspace.content if item["request"]["method"] == "POST" else _body(item)
        http.add(item["request"]["method"], uri, json=body)
    environment = next(
        item for item in _capture("flightcheck_pp_admin.yaml")
        if item["request"]["method"] == "GET"
        and "api.bap.microsoft.com" in item["request"]["uri"]
        and "/environments/" in item["request"]["uri"]
    )
    body = _body(environment)
    body["name"] = ENV_ID
    url = urlsplit(environment["request"]["uri"])
    url = url._replace(path=url.path.rsplit("/", 1)[0] + "/" + ENV_ID, query="").geturl()
    http.add("GET", url, json=body)


def _register_maker_baseline(http):
    require_validated_mock(graph_mock)
    require_validated_mock(powerplatform_mock)
    http.add(**graph_mock.list_subscribed_skus(skus=[
        graph_mock.subscribed_sku(sku_part_number=value)
        for value in ("MICROSOFT_365_COPILOT", "COPILOT_STUDIO", "TEAMS")
    ]))
    http.add(**graph_mock.list_directory_roles(roles=[]))
    http.add(**graph_mock.list_organization(organizations=[graph_mock.organization(tenant_id=TENANT_ID)]))
    http.add(**graph_mock.list_conditional_access_policies(policies=[]))
    users = graph_mock.list_users(users=[])
    users["url"] = users["url"].split("?")[0]
    http.add(**users)
    http.add(**powerplatform_mock.list_billing_policies())
    entitlement = powerplatform_mock.environment_entitlement(allocated=100)
    entitlement["environmentId"] = ENV_ID
    http.add(**powerplatform_mock.get_environment_entitlements(
        environment_id=ENV_ID, entitlements=[entitlement],
    ))
    policies = next(
        item for item in _capture("flightcheck_pp_admin.yaml")
        if "/apiPolicies" in item["request"]["uri"]
    )
    http.add("GET", policies["request"]["uri"], json=_body(policies))


@pytest.mark.parametrize("dataverse", [False, True])
@pytest.mark.parametrize("explicit_active", [False, True])
def test_real_cli_da_full_restores_readonly_coverage_without_legacy_probes(
    setup_workspace, monkeypatch, dataverse, explicit_active,
):
    ws = setup_workspace
    if not explicit_active:
        ws.config.pop("activeAgent")
    if dataverse:
        ws.config["dataverseEndpoint"] = "https://orgmocktenant.crm.dynamics.com"
    (ws.root / ".local" / "config.json").write_text(json.dumps(ws.config), encoding="utf-8")
    for name in ("GraphClient", "AzureArmClient", "PowerPlatformClient", "PVAClient", "PPAdminClient"):
        monkeypatch.setattr(cli, name, Mock(side_effect=AssertionError(f"Unexpected {name}")))
    monkeypatch.setattr("sys.argv", [
        "flightcheck", "--scope", "full", "--output", "report", "--no-open", "--no-telemetry",
    ])
    with responses.RequestsMock() as http:
        _register_native(http, ws)
        _register_maker_baseline(http)
        with pytest.raises(SystemExit) as exit_result:
            cli.main()
        assert exit_result.value.code == 0, [
            (row["checkpoint_id"], row["status"], row["result"])
            for row in json.loads((ws.root / "report" / "results.json").read_text(encoding="utf-8"))["results"]
            if row["status"] in {"Failed", "Blocked", "Error"}
        ]
        assert all(
            request.request.method == "GET" or request.request.url.split("?")[0].endswith("/components")
            for request in http.calls
        )
        assert sum(call.request.method == "POST" for call in http.calls) == 1
    result = json.loads((ws.root / "report" / "results.json").read_text(encoding="utf-8"))
    assert result["diagnostic_only"] is True
    assert result["overall"] == "CHECKED_WITH_NOTES"
    assert result["validation_context"]["accountEmail"] == "maker@example.test"
    assert result["validation_context"]["agentName"] == ws.content["bot"]["displayName"]
    assert {row["evidence"]["applicability"] for row in result["results"] if "-INTEGRATION-" in row["checkpoint_id"]} == {"not_configured"}
    assert not any(row["checkpoint_id"] == "DA-CONN-001" for row in result["results"])
    assert any(row["checkpoint_id"] == "CONFIG-012" for row in result["results"])
    assert result["coverage"]["planned"] == result["coverage"]["emitted"]
    assert result["total"] == len(result["coverage"]["planned"])
    assert ws.auth.call_args.kwargs["allow_write"] is False
    assert (ws.root / "report" / "report.html").exists()


@pytest.mark.parametrize("scope", ["full", "local"])
@pytest.mark.parametrize("dataverse", [False, True])
@pytest.mark.parametrize("variant", ["healthy", "missing_instructions", "unverified_identity"])
def test_maker_and_standalone_have_identical_findings(
    setup_workspace, monkeypatch, scope, dataverse, variant,
):
    ws = setup_workspace
    if dataverse:
        ws.config["dataverseEndpoint"] = "https://orgmocktenant.crm.dynamics.com"
    if variant == "missing_instructions":
        agent_path = ws.root / "workspace" / "agents" / "hr" / "agent.mcs.yml"
        agent_path.write_text("displayName: Employee Self-Service\n", encoding="utf-8")
        for change in ws.content["botComponentChanges"]:
            component = change["component"]
            if component["$kind"] == "GptComponent":
                component["metadata"]["instructions"]["segments"] = []
    elif variant == "unverified_identity":
        ws.config["tenantId"] = "00000000-0000-4000-8000-000000009999"
    for name in ("GraphClient", "AzureArmClient", "PowerPlatformClient", "PVAClient", "PPAdminClient"):
        monkeypatch.setattr(cli, name, Mock(side_effect=AssertionError(f"Unexpected {name}")))

    payloads, requests_made = [], []
    for source in ("adk", "cli"):
        # A maker may diagnose incomplete setup; standalone installation is
        # operational metadata, not a different set of checks.
        ws.config["flightCheckOnly"] = source == "cli"
        (ws.root / ".local" / "config.json").write_text(json.dumps(ws.config), encoding="utf-8")
        setup = ws.root / ".local" / "setup"
        setup.mkdir(exist_ok=True)
        (setup / "config.json").write_text(json.dumps({
            "schema_version": 4, "agents": {"hr": {"connect_ready": False}},
        }), encoding="utf-8")
        output = f"report-{source}"
        options = (
            ["--scope", scope, "--invocation-source", "adk", "--select-targets", "never"]
            if source == "adk" else ["--scope", "local"] if scope == "local" else []
        )
        monkeypatch.setattr("sys.argv", [
            "flightcheck", *options, "--output", output, "--no-open", "--no-telemetry",
        ])
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            if scope == "full":
                _register_native(http, ws)
                _register_maker_baseline(http)
            with pytest.raises(SystemExit) as exit_result:
                cli.main()
            expected_exit = int(
                variant == "missing_instructions"
                or (variant == "unverified_identity" and scope == "full")
            )
            assert exit_result.value.code == expected_exit
            requests_made.append([(call.request.method, call.request.url) for call in http.calls])
        payload = json.loads((ws.root / output / "results.json").read_text(encoding="utf-8"))
        payload.pop("started")
        payload.pop("duration_secs")
        payloads.append(payload)
        assert (ws.root / output / "report.html").exists()
        assert payload["scope"] == scope
        assert payload["diagnostic_only"] is True
        assert payload["validation_context"]["agentId"] == ws.config["agents"][0]["botId"]
        assert payload["validation_context"]["targetVerified"] is (
            scope == "full" and variant != "unverified_identity"
        )
        if variant == "unverified_identity" and scope == "full":
            row = next(row for row in payload["results"] if row["checkpoint_id"] == "DA-AGENT-001")
            assert row["status"] == "Blocked"
            assert "different tenant" in row["result"]
            assert "signed-in account" in row["remediation"]
        if variant == "missing_instructions":
            assert any(row["status"] == "Failed" for row in payload["results"])
    assert payloads[0] == payloads[1]
    assert requests_made[0] == requests_made[1]
    if scope == "local":
        ws.auth.assert_not_called()
        assert requests_made == [[], []]
    else:
        assert ws.auth.call_count == 2
        assert all(call.kwargs["allow_write"] is False for call in ws.auth.call_args_list)


def test_da_local_is_exact_and_does_not_authenticate(setup_workspace, monkeypatch):
    ws = setup_workspace
    sibling = ws.root / "workspace" / "agents" / "other"
    sibling.mkdir()
    (sibling / "agent.mcs.yml").write_text("invalid: [", encoding="utf-8")
    ws.config["agents"].append({"slug": "other", "releaseLine": "da"})
    (ws.root / ".local" / "config.json").write_text(json.dumps(ws.config), encoding="utf-8")
    monkeypatch.setattr("sys.argv", [
        "flightcheck", "--scope", "local", "--output", "report", "--no-open", "--no-telemetry",
    ])
    with pytest.raises(SystemExit) as exit_result:
        cli.main()
    assert exit_result.value.code == 0
    ws.auth.assert_not_called()
    result = json.loads((ws.root / "report" / "results.json").read_text(encoding="utf-8"))
    assert result["diagnostic_only"] is True
    assert all(row["evidence"]["agentSlug"] == "hr" for row in result["results"])
    assert all(row["evidence"]["deploymentFreshnessVerified"] is False for row in result["results"])


@pytest.mark.parametrize("topic,status", [
    ("modelDescription: Find current leave balances.\n", "Passed"),
    ("kind: AdaptiveDialog\n", "Passed"),
    ("modelDescription: '[TODO]'\n", "Failed"),
    ("modelDescription: [\n", "Skipped"),
])
def test_da_local_descriptions_do_not_impose_legacy_word_counts(setup_workspace, topic, status):
    ws = setup_workspace
    topics = ws.root / "workspace" / "agents" / "hr" / "topics"
    topics.mkdir()
    (topics / "leave.mcs.yml").write_text(topic, encoding="utf-8")
    runner = SimpleNamespace(
        config=ws.config, agent_slug="hr", maker_diagnostics=True,
        env_id=ENV_ID, env_url=None, dv_token=None, pva=None,
    )
    rows = maker._check_local(runner)
    descriptions = [row for row in rows if row.checkpoint_id == "CONFIG-014"]
    assert descriptions[0].status == status
    assert not any(row.status == "Warning" for row in descriptions)


def test_absent_local_extraction_is_a_limitation_not_a_cloud_defect(setup_workspace):
    ws = setup_workspace
    (ws.root / "workspace" / "agents" / "hr" / "agent.mcs.yml").unlink()
    rows = maker._check_local(SimpleNamespace(config=ws.config, agent_slug="hr", env_id=ENV_ID))
    assert len(rows) == 1
    assert rows[0].status == "Blocked"
    assert rows[0].evidence["evidenceBoundary"] == "local_authored_content"
    ws.auth.assert_not_called()


@pytest.mark.parametrize("selection", ["missing", None])
@pytest.mark.parametrize("scope", ["full", "workday", "servicenow"])
def test_ambiguous_or_stale_selection_fails_before_any_authentication(setup_workspace, monkeypatch, selection, scope):
    ws = setup_workspace
    ws.config["agents"].append({"slug": "other", "releaseLine": "da"})
    ws.config["activeAgent"] = selection
    (ws.root / ".local" / "config.json").write_text(json.dumps(ws.config), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["flightcheck", "--scope", scope, "--no-open", "--no-telemetry"])
    with pytest.raises(SystemExit) as exit_result:
        cli.main()
    assert exit_result.value.code == 1
    ws.auth.assert_not_called()


def test_legacy_multi_agent_full_retains_its_existing_admission(setup_workspace, monkeypatch, capsys):
    ws = setup_workspace
    config = {"ring": "prod", "agents": [{"slug": slug, "releaseLine": "legacy"} for slug in ("hr", "it")]}
    (ws.root / ".local" / "config.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["flightcheck", "--scope", "full", "--no-open", "--no-telemetry"])
    with pytest.raises(SystemExit):
        cli.main()
    output = capsys.readouterr().out
    assert "No dataverseEndpoint" in output
    assert "Select exactly one" not in output


@pytest.mark.parametrize("invalid", [None, 123, "not-a-guid"])
def test_bad_target_identifiers_are_explicitly_unverified(setup_workspace, invalid):
    ws = setup_workspace
    ws.config["agents"][0]["botId"] = invalid
    args = SimpleNamespace(
        agent_slug="hr", environment_id=None, environment_url=None, validation_realm=None,
        ring=None, preferred_username=None, tenant_id=None,
    )
    result = maker.run_maker_diagnostics(args, ws.config)
    assert result.overall == "SOME_CHECKS_UNVERIFIED"
    assert next(row for row in result.results if row.checkpoint_id == "DA-AGENT-001").status == "Blocked"
    ws.auth.assert_not_called()


@pytest.mark.parametrize("variant", ["captured", "unbound", "unknown_activation", "malformed_inventory"])
def test_selected_dependency_audit_replays_actual_clients(monkeypatch, variant):
    interactions = _capture("env004_dependencies.yaml")
    native_agent = next(item for item in interactions if "/minimalBots/api/" in item["request"]["uri"])
    bot_id = _body(native_agent)["botId"]
    env_id = next(
        item["request"]["uri"].split("/environments/")[1].split("/")[0].split("?")[0]
        for item in interactions if "api.bap.microsoft.com" in item["request"]["uri"]
    )
    host = derive_environment_host(env_id, "prod")
    payload = _body(interactions[1])
    if variant == "unknown_activation":
        for change in payload["botComponentChanges"]:
            change["component"].pop("status", None)
    runner = SimpleNamespace(
        config={"activeAgent": "hr", "agents": [{"slug": "hr", "botId": bot_id}]},
        agent_slug="hr", env_id=env_id, env_url="", dv_token=None, tenant_id=TENANT_ID,
        ring="prod", maker_diagnostics=True, connection_agent_ids=(bot_id,),
        connection_dependency_token=lambda _scope: "read-token",
        agentbuilder=AgentBuilderClient(host, "read-token", ring="prod", tenant_id=TENANT_ID),
        connectivity=ConnectivityClient("read-token", ring="prod"),
        _da_native_snapshot={"agentId": bot_id, "environmentId": env_id, "changeset": payload},
    )
    monkeypatch.setattr(_connection_dependencies, "discover_tenant", lambda _url: TENANT_ID)
    with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
        for item in interactions:
            body = _body(item)
            uri = item["request"]["uri"]
            if "/minimalBots/api/" in uri:
                uri = urlsplit(uri)._replace(netloc=urlsplit(host).netloc, query="").geturl()
            if variant == "unbound" and "/connectionreferences?" in uri:
                for reference in body["value"]:
                    if "workdaysoap" in reference["connectorid"]:
                        reference["connectionid"] = None
            if variant == "malformed_inventory" and "/connectionreferences?" in uri:
                body["value"] = {}
            http.add(item["request"]["method"], urlsplit(uri)._replace(query="").geturl(), json=body)
        row = maker._check_connections(runner)[0]
        assert row.status == {
            "captured": "Passed", "unbound": "Failed",
            "unknown_activation": "Blocked", "malformed_inventory": "Error",
        }[variant], row.result
        assert row.evidence["dependencyCoverageComplete"] is (variant in {"captured", "unbound"})
        assert all(call.request.method == "GET" for call in http.calls)
        assert not any("/components" in call.request.url for call in http.calls)
        if variant == "captured":
            assert row.evidence["requiredReferences"] > 0
        # The integration producer consumes the same captured native/flow reads,
        # rather than guessing from names or rereading every active flow.
        payload["bot"] = _body(next(
            item for item in _capture("agentbuilder_readiness.yaml")
            if item["request"]["method"] == "POST" and "/minimalBots/api/" in item["request"]["uri"]
        ))["bot"]
        integration_rows = maker_integrations.run_optional_integration_checks(runner)
        wd = next(item for item in integration_rows if item.checkpoint_id == "WD-INTEGRATION-001")
        if variant == "unknown_activation":
            assert wd.status == "Blocked"
            assert "Discovery was incomplete" in wd.result
        else:
            assert wd.evidence["applicability"] == "enabled"
            binding = next(item for item in integration_rows if item.checkpoint_id == "WD-CONN-001")
            assert binding.status == {"captured": "Passed", "unbound": "Failed", "malformed_inventory": "Blocked"}[variant]
            assert ("Exact bindings were verified" if variant == "captured" else "not verified healthy") in binding.result


def test_workday_manual_portal_check_is_optional_without_changing_connect(monkeypatch):
    calls = []
    names = (
        "_check_workday_da_package_installed", "_check_runtime_flow_catalog",
        "_check_delegated_flow_authorization", "_check_reviewed_workday_topics",
        "_check_runtime_template_wiring", "_check_agent_flow_attachment",
    )
    # Pure orchestration: producers' existing captured/documented tests own API behavior.
    for name in names:
        monkeypatch.setattr(workday_da, name, lambda _runner, name=name: calls.append(name) or [])
    workday_da.run_workday_da_checks(SimpleNamespace(), include_manual=False)
    assert calls == list(names[:-1])
    calls.clear()
    workday_da.run_workday_da_checks(SimpleNamespace())
    assert calls == list(names)


@pytest.mark.parametrize("mismatch", ["account", "tenant", "environment", "dataverse"])
def test_target_and_account_mismatches_never_proceed_to_native_reads(setup_workspace, mismatch):
    ws = setup_workspace
    args = SimpleNamespace(
        agent_slug="hr", environment_id=None, environment_url=None, validation_realm=None,
        ring=None, preferred_username="maker@example.test", tenant_id=TENANT_ID,
    )
    if mismatch == "account":
        ws.auth.return_value = ("read-token", TENANT_ID, "other@example.test")
    elif mismatch == "tenant":
        ws.auth.return_value = ("read-token", ENV_ID, "maker@example.test")
    elif mismatch == "environment":
        args.environment_id = TENANT_ID
    else:
        ws.config["dataverseEndpoint"] = "https://orgmocktenant.crm.dynamics.com"
        args.environment_url = "https://different.crm.dynamics.com"
    with responses.RequestsMock() as http:
        result = maker.run_maker_diagnostics(args, ws.config)
        assert not http.calls
    assert result.overall == "SOME_CHECKS_UNVERIFIED"
    assert result.results[0].status == "Blocked"
    assert not result.failed


def test_report_distinguishes_uncertainty_and_preserves_original_results(tmp_path):
    rows = [
        CheckResult("ONE", "Agent setup", "High", status, status, "<script>alert(1)</script>",
                    "Ask the owner. [Unsafe](javascript:alert(1))")
        for status in ("Passed", "Failed", "Blocked", "Warning")
    ]
    runner = FlightCheckRunner(scope="full")
    runner.register("Agent setup", lambda _: rows)
    result = runner.run()
    result.diagnostic_only = True
    result.overall = maker_diagnostic_outcome(result)
    before = deepcopy(result)
    save_results(result, str(tmp_path))
    assert result == before
    html = (tmp_path / "report.html").read_text(encoding="utf-8")
    for expected in ("Problem found", "Could not verify", "Manual verification", "Who can help", "not release approval"):
        assert expected in html
    assert "<script>alert(1)</script>" not in html
    assert 'href="javascript:' not in html
    assert "Ready for deployment" not in html
    assert "<form" not in html
    assert versioned_run_result_to_dict(result)["diagnosticOnly"] is True


@pytest.mark.parametrize("state", ["Active", "Inactive", "unknown", "unused", "absent"])
def test_optional_native_servicenow_does_not_require_legacy_templates(setup_workspace, state):
    """Pure applicability logic over the captured direct ServiceNow contract."""
    payload = _body(_capture("env004_dependencies.yaml")[1])
    topic = next(
        change for change in payload["botComponentChanges"]
        if "shared_service-now" in json.dumps(change)
    )
    topic["component"]["status"] = state
    payload["botComponentChanges"] = [] if state in {"unused", "absent"} else [topic]
    if state == "absent":
        payload["connectionReferenceChanges"] = []
    payload["bot"] = setup_workspace.content["bot"]
    audit = _connection_dependencies.ConnectionAudit()
    runner = SimpleNamespace(
        _da_native_snapshot={"changeset": payload}, _da_connection_audit=audit,
    )
    rows = maker_integrations.run_optional_integration_checks(runner)
    integration = next(row for row in rows if row.checkpoint_id == "SN-INTEGRATION-001")
    expected = {
        "Active": "enabled", "Inactive": "disabled", "unknown": "unknown",
        "unused": "configured", "absent": "not_configured",
    }[state]
    assert integration.evidence["applicability"] == expected
    if state == "Active":
        assert "active conversations" in integration.result
        assert next(row for row in rows if row.checkpoint_id == "SN-CONN-001").status == "Blocked"
        assert "Connection Settings" in rows[-1].remediation
    elif state == "unknown":
        assert "Discovery was incomplete" in integration.result
        assert "do not assume" in integration.remediation
    else:
        assert integration.status == "NotConfigured"
        assert not integration.remediation
    assert not any(row.checkpoint_id in {"SN-TEMPLATE-001", "SN-FLOW-001"} for row in rows)


def test_optional_workday_distinguishes_custom_flow_from_enabled_oob_pack(setup_workspace):
    payload = _body(_capture("env004_dependencies.yaml")[1])
    topic = next(
        change for change in payload["botComponentChanges"]
        if "InvokeFlowAction" in json.dumps(change)
    )
    topic["component"]["status"] = "Active"
    payload["botComponentChanges"] = [topic]
    payload["bot"] = setup_workspace.content["bot"]
    interactions = _capture("env004_dependencies.yaml")
    flows = {
        item["request"]["uri"].split("/flows/")[1].split("?")[0]: _body(item)
        for item in interactions if "/flows/" in item["request"]["uri"]
    }
    runner = SimpleNamespace(
        _da_native_snapshot={"changeset": payload}, _maker_flow_details=flows,
        _da_connection_audit=_connection_dependencies.ConnectionAudit(),
    )
    maker_integrations.run_optional_integration_checks(runner)
    assert runner.maker_integrations["Workday"]["applicability"] == "enabled"
    assert runner.maker_workday_extension is False
    assert maker._check_workday(runner) == []
    reviewed = workday_da.reviewed_workday_topic_schemas(payload["bot"]["schemaName"])
    topic["component"]["schemaName"] = sorted(reviewed)[0]
    maker_integrations.run_optional_integration_checks(runner)
    assert runner.maker_workday_extension is True
    topic["component"]["status"] = "Inactive"
    maker_integrations.run_optional_integration_checks(runner)
    assert runner.maker_integrations["Workday"]["applicability"] == "disabled"
    assert maker._check_workday(runner) == []


@pytest.mark.parametrize("state", ["Inactive", "unknown", "duplicate"])
def test_maker_workday_inventory_does_not_require_unused_catalog_topics(setup_workspace, state):
    """Pure snapshot inspection keeps optional topic selection out of Connect gates."""
    ws = setup_workspace
    payload = deepcopy(ws.content)
    topic = deepcopy(_body(_capture("env004_dependencies.yaml")[1])["botComponentChanges"][0])
    schema = payload["bot"]["schemaName"]
    system_topics = []
    for suffix in workday_da._REQUIRED_SYSTEM_TOPIC_SUFFIXES:
        system_topic = deepcopy(topic)
        system_topic["component"]["schemaName"] = f"{schema}.topic.{suffix}"
        system_topic["component"]["status"] = "Active"
        system_topics.append(system_topic)
    topic["component"]["schemaName"] = f"{schema}.topic.WorkdayEmployeeID"
    topic["component"]["status"] = "Active" if state == "duplicate" else state
    payload["botComponentChanges"] = system_topics + (
        [topic, deepcopy(topic)] if state == "duplicate" else [topic]
    )
    runner = SimpleNamespace(
        config=ws.config, agent_slug="hr", env_id=ENV_ID, maker_diagnostics=True,
        agentbuilder=object(),
        _da_native_snapshot={"agentId": ws.config["agents"][0]["botId"], "environmentId": ENV_ID, "changeset": payload},
    )
    row = workday_da._check_reviewed_workday_topics(runner)[0]
    assert row.status == {"Inactive": "Passed", "unknown": "Blocked", "duplicate": "Failed"}[state]
    assert "Unused optional conversations are not required" in row.result
    assert "7 of 7 required system topics present" in row.result
    assert "activate each" not in row.remediation
    if state == "duplicate":
        assert "resolve duplicate schemas" in row.remediation
    elif state == "unknown":
        assert "Copilot Studio" in row.remediation
    else:
        assert not row.remediation


@pytest.mark.parametrize("linkage", ["absent", "not_returned", "malformed"])
def test_optional_dataverse_metadata_does_not_invent_a_requirement(setup_workspace, linkage):
    item = next(
        item for item in _capture("flightcheck_pp_admin.yaml")
        if item["request"]["method"] == "GET" and "api.bap.microsoft.com" in item["request"]["uri"]
        and "/environments/" in item["request"]["uri"]
    )
    environment = _body(item)
    if linkage == "not_returned":
        environment["properties"].pop("linkedEnvironmentMetadata")
    else:
        environment["properties"]["linkedEnvironmentMetadata"] = None if linkage == "absent" else {}
    rows = maker._check_environment(SimpleNamespace(
        _da_native_snapshot={"changeset": setup_workspace.content},
        _maker_environment_snapshot=environment, env_id=environment["name"], ring="prod",
    ))
    row = next(row for row in rows if row.checkpoint_id == "ENV-002")
    if linkage == "absent":
        assert row.status == "NotConfigured"
        assert "does not require Dataverse" in row.result
        assert not row.remediation
    else:
        assert row.status == "Blocked"
        assert "did not establish" in row.result
        assert "Do not provision Dataverse" in row.remediation


@pytest.mark.parametrize("malformed", [False, True])
def test_cloud_instructions_validate_recorded_template_segments(setup_workspace, malformed):
    content = deepcopy(setup_workspace.content)
    gpt = next(c["component"] for c in content["botComponentChanges"] if c["component"]["$kind"] == "GptComponent")
    gpt["metadata"]["instructions"]["segments"] = [{"$kind": "UnsupportedSegment"}] if malformed else []
    runner = SimpleNamespace(_da_native_snapshot={"changeset": content})
    row = next(row for row in maker._check_agent_configuration(runner) if row.checkpoint_id == "DA-INSTRUCTIONS-001")
    assert row.status == ("Blocked" if malformed else "Failed")
    assert ("supported authoring format" if malformed else "no nonempty text") in row.result
    assert "Copilot Studio" in row.remediation


@pytest.mark.parametrize("broken", [False, True])
def test_integration_binding_failure_is_scoped_to_its_reference(setup_workspace, broken):
    payload = _body(_capture("env004_dependencies.yaml")[1])
    topic = next(change for change in payload["botComponentChanges"] if "shared_service-now" in json.dumps(change))
    topic["component"]["status"] = "Active"
    payload["botComponentChanges"] = [topic]
    payload["bot"] = setup_workspace.content["bot"]
    reference = _connection_dependencies.Reference(
        "agent", "selected-servicenow", maker_integrations.CONNECTORS["ServiceNow"], "verified-physical-id",
        failures=["Wrong physical connector"] if broken else [],
    )
    audit = _connection_dependencies.ConnectionAudit(
        references=[reference], failures=["An unrelated Workday reference failed."],
    )
    rows = maker_integrations.run_optional_integration_checks(SimpleNamespace(
        _da_native_snapshot={"changeset": payload}, _da_connection_audit=audit,
    ))
    row = next(row for row in rows if row.checkpoint_id == "SN-CONN-001")
    assert row.status == ("Failed" if broken else "Passed")
    assert ("not verified healthy" if broken else "Exact bindings were verified") in row.result
    assert ("Connection Settings" in row.remediation) is broken


@pytest.mark.parametrize("state", ["Started", "Stopped", None])
def test_optional_servicenow_invoked_flow_states_reuse_captured_detail(setup_workspace, state):
    """Pure flow classification uses the validated full Flow detail shape."""
    flow_item = next(
        item for item in _capture("flightcheck_flow_licensing.yaml")
        if item["request"]["method"] == "GET" and "/flows/" in item["request"]["uri"]
        and item["response"]["status"]["code"] == 200
    )
    flow = _body(flow_item)
    flow["properties"]["state"] = state
    connector = maker_integrations.CONNECTORS["ServiceNow"]
    flow_ref = next(iter(flow["properties"]["connectionReferences"].values()))
    flow_ref["apiDefinition"]["id"] = "/providers/Microsoft.PowerApps/apis/" + connector
    payload = _body(_capture("env004_dependencies.yaml")[1])
    topic = next(change for change in payload["botComponentChanges"] if "InvokeFlowAction" in json.dumps(change))
    topic["component"]["status"] = "Active"
    flow_id = next(node["flowId"] for node in _connection_dependencies._nodes(topic) if node.get("$kind") == "InvokeFlowAction")
    payload["botComponentChanges"] = [topic]
    payload["bot"] = setup_workspace.content["bot"]
    reference = _connection_dependencies.Reference("agent", "selected-servicenow", connector, "verified-id", [flow_id])
    runner = SimpleNamespace(
        _da_native_snapshot={"changeset": payload},
        _maker_flow_details={flow_id: flow},
        _da_connection_audit=_connection_dependencies.ConnectionAudit(references=[reference]),
    )
    rows = maker_integrations.run_optional_integration_checks(runner)
    row = next(row for row in rows if row.checkpoint_id == "SN-FLOW-001")
    assert row.status == {"Started": "Passed", "Stopped": "Failed", None: "Blocked"}[state]
    assert "Inspected 1 invoked flow" in row.result
    assert ("Power Automate" in row.remediation) is (state != "Started")


def test_report_keeps_approved_shell_full_private_metadata_and_zero_totals(tmp_path):
    runner = FlightCheckRunner(scope="full")
    runner.register("Optional integrations", lambda _: [
        CheckResult("SN-INTEGRATION-001", "ServiceNow", "High", "NotConfigured",
                    "Optional ServiceNow", "No active use", evidence={"applicability": "disabled"}),
    ])
    result = runner.run()
    result.diagnostic_only = True
    result.overall = maker_diagnostic_outcome(result)
    assert result.overall == "SETUP_CHECKS_PASSED"
    result.validation_context = {
        "agentName": "An <escaped> agent", "agentId": ENV_ID, "environmentId": ENV_ID,
        "accountEmail": "maker@example.test",
    }
    save_results(result, str(tmp_path))
    html = (tmp_path / "report.html").read_text(encoding="utf8")
    for expected in (
        'class="report"', 'class="brand-title"', 'class="meta"', 'class="hr"',
        'class="reading-guide"', 'class="actions-panel"', 'class="syn-no">Stage 1',
        "Completed in:", ENV_ID, "maker@example.test", "An &lt;escaped&gt; agent",
    ):
        assert expected in html
    assert re.findall(r'<span class="stat [^"]+">.*?<b>(\d+)</b>', html) == ["0", "0", "0", "0", "0", "0", "1"]
    assert "Status totals table" not in html
    assert "<table" not in html
    assert 'class="action-table"' not in html


@pytest.mark.parametrize("applicability,reviewed", [
    ("enabled", True), ("disabled", True), ("not_configured", False),
    ("unknown", True), ("enabled", False),
])
def test_manual_workday_settings_are_scoped_and_do_not_claim_success(applicability, reviewed):
    runner = SimpleNamespace(
        maker_integrations={"Workday": {"applicability": applicability}},
        maker_workday_extension=reviewed,
    )
    rows = maker._check_manual_verification(runner)
    if applicability != "enabled" or not reviewed:
        assert rows == []
        return
    assert len(rows) == 1
    row = rows[0]
    assert row.checkpoint_id == "WD-DA-ATTACH-001"
    assert row.status == "Manual"
    assert "no validated read-only API" in row.result
    assert "not a confirmed configuration defect" in row.result
    assert len(row.evidence["expectedFlowNames"]) == 2
    assert row.evidence["expectedConnectionReferences"] == [
        "ESS Workday Runtime", "ESS Workday Runtime REST Execution",
    ]
    assert len(row.evidence["manualVerificationSteps"]) == 4
    assert "Allow permission to share parameters" in row.remediation
    assert "Settings > Connection Settings" in row.remediation
    assert "Manage" in row.remediation
    assert "connection references" in row.description
    assert "install or repair" in row.evidence["ifMissingOrIncorrect"]
    assert "Do not remove unrelated" in row.remediation
    assert row.roles
    checker = FlightCheckRunner(scope="full")
    checker.register("Manual verification", lambda _: rows)
    result = checker.run()
    result.diagnostic_only = True
    result.overall = maker_diagnostic_outcome(result)
    assert result.overall == "CHECKED_WITH_NOTES"
    assert cli._run_exit_code(result) == 0
    assert result.passed == 0


def test_customer_report_unifies_categories_and_exposes_purpose_status_and_steps(tmp_path):
    manual = maker._check_manual_verification(SimpleNamespace(
        maker_integrations={"Workday": {"applicability": "enabled"}}, maker_workday_extension=True,
    ))[0]
    rows = [
        CheckResult("WD-CONN-001", "Workday", "High", "Passed", "Bindings", "Bound."),
        CheckResult("WD-DA-FLOW-001", "Workday DA", "High", "Passed", "Flows", "Active."),
        CheckResult("DV-CONN-001", "Workday Extension", "High", "Failed", "Runtime binding", "Unbound.",
                    "Open Connection Settings and bind the runtime reference.", roles=["Power Platform Admin"]),
        CheckResult("DA-AGENT-001", "Native Agent", "High", "Blocked", "Agent access", "Access unavailable.",
                    "Ask the agent owner to confirm access.", roles=["ESS Maker / Agent Developer"]),
        manual,
    ]
    runner = FlightCheckRunner(scope="full")
    runner.register("Source categories", lambda _: rows)
    result = runner.run()
    result.diagnostic_only = True
    result.overall = maker_diagnostic_outcome(result)
    original = deepcopy(result)
    save_results(result, str(tmp_path))
    assert result == original
    html = (tmp_path / "report.html").read_text(encoding="utf8")
    assert html.count('<div class="syn-name">Workday</div>') == 1
    assert '<div class="syn-name">Workday DA</div>' not in html
    assert '<div class="syn-name">Workday Extension</div>' not in html
    assert "<h2>Readiness at a glance</h2>" in html
    assert "Setup at a glance" not in html
    assert 'aria-label="Status legend and totals"' in html
    assert 'class="dot green"' in html and 'class="dot red"' in html
    header = html.split("</header>")[0]
    assert 'class="reading-guide"' in header and "<ul><li>" in header
    assert "FlightChecks: <b>5 total (4 automated, 1 manual)</b>" in header
    assert 'class="howto"' not in html
    findings = re.findall(r'<article class="finding"[^>]*>(.*?)</article>', html, re.S)
    assert len(findings) == len(rows)
    for row in rows:
        finding = next(item for item in findings if f">{row.checkpoint_id}</code>" in item)
        assert f">{row.status}</span>" in finding
        assert "<b>What this checks:</b> " in finding
        assert "<b>Result:</b> " in finding
        if row.status == "Passed":
            assert "Who should check or fix this:" not in finding and "Next step:" not in finding
        else:
            assert "<b>Who should check or fix this:</b> " in finding
            assert f'<b>{"Verification steps" if row.status == "Manual" else "Next step"}:</b> ' in finding
        assert '<details' not in finding and '<pre>' not in finding
        assert 'href="#technical-' in finding
    assert '<details class="finding"' not in html
    assert "Expand details" not in html and "Collapse details" not in html
    assert 'id="expand-all"' not in html and 'id="collapse-all"' not in html
    manual_section = html.split('id="manual-verification"')[1]
    assert "WD-DA-ATTACH-001" in manual_section
    assert "<b>Verification steps:</b> 1." in manual_section and "<br>2." in manual_section
    assert "If missing or incorrect" in manual_section
    assert "Who should check or fix this" in manual_section
    assert html.count('data-recorded-status="Manual"') == 1
    assert "bind the runtime reference" in html
    assert "No corrective action is indicated" not in html
    assert html.count("rerun relevant checks after configuration changes.") == 1
    assert "repeat(2,minmax(0,1fr))" in html
    assert "<form" not in html and 'type="checkbox"' not in html
    assert result.results[1].category == "Workday DA"
    assert re.findall(r'data-filter="[^"]+"[^>]*>([^<]+)</button>', html) == [
        "All", "Passed", "Failed", "Warnings", "Manual",
    ]
    assert "Treat this local report as private" not in html
    assert "The header contains the account" not in html
    assert "<b>Who should check or fix this:</b> Environment Maker user</p>" in manual_section
    assert "Ask the Environment Maker user to confirm access." in html
    assert "<p>Agent owner</p>" not in html
    assert 'data-kind="unverified" data-filter-group="warnings"' in html
    assert 'data-kind="manual" data-filter-group="manual"' in html


def test_technical_appendix_preserves_observations_without_repeating_manual_metadata(tmp_path):
    from html import unescape

    instructions = ["Inspect the intended policy.", "Compare the permitted employee access."]
    reason = "This setting needs manual inspection."
    purpose = "Published employee access"
    metadata = {
        "agentSlug": "hr", "verificationScope": {"agentId": ENV_ID, "targetVerified": True},
        "apiContract": "manual: no supported automatic assertion", "assertionScope": "selected-agent",
        "manualVerificationSteps": instructions, "ifMissingOrIncorrect": "Repair only the confirmed policy mismatch.",
        "verificationReason": reason, "expectedSetting": purpose,
    }
    rows = [
        CheckResult("DA-RUNTIME-001", "Runtime", "High", "Manual", purpose, reason,
                    evidence=metadata, doc_link="https://learn.microsoft.com/example"),
        CheckResult("PRE-001", "Licensing", "High", "Manual", "License inventory", "Read denied.",
                    evidence={**metadata, "httpStatus": 403, "readLimitation": "Inventory read denied.",
                              "expectedSetting": "Specific expected value", "verificationReason": "Distinct read context"}),
        CheckResult("CHECK-ERROR", "Agent", "High", "Error", "Service observation", "Read failed.",
                    evidence={"httpStatus": 503, "detail": "<script>unexpected</script>",
                              "verificationScope": {"targetVerified": False}}),
    ]
    runner = FlightCheckRunner(scope="full")
    runner.register("Support appendix", lambda _: rows)
    result = runner.run()
    result.diagnostic_only = True
    original = deepcopy(result)
    save_results(result, str(tmp_path))
    assert result == original
    payload = json.loads((tmp_path / "results.json").read_text(encoding="utf8"))
    assert payload["results"][0]["evidence"] == metadata
    html = (tmp_path / "report.html").read_text(encoding="utf8")
    assert html.index('id="technical-details"') > html.index('id="manual-verification"')
    assert 'id="technical-search"' in html and 'id="no-technical-match"' in html
    assert "Recorded status:" not in html
    assert "manualVerificationSteps" not in html
    assert html.count("Inspect the intended policy.") == 2
    entries = re.findall(r'<details class="technical-entry"[^>]*>(.*?)</details>', html, re.S)
    assert len(entries) == len(rows)
    assert "No additional technical observations" in entries[0]
    assert "<pre>" not in entries[0]
    assert json.loads(unescape(re.search(r"<pre>(.*?)</pre>", entries[1], re.S)[1])) == {
        "httpStatus": 403, "readLimitation": "Inventory read denied.",
        "expectedSetting": "Specific expected value", "verificationReason": "Distinct read context",
    }
    assert json.loads(unescape(re.search(r"<pre>(.*?)</pre>", entries[2], re.S)[1])) == rows[2].evidence
    assert "<script>unexpected</script>" not in html
    for index, row in enumerate(rows):
        assert f'id="technical-{index}" data-check-id="{row.checkpoint_id}"' in html
        assert f'href="#finding-{index}"' in entries[index]
    finding = next(
        item for item in re.findall(r'<article class="finding"[^>]*>(.*?)</article>', html, re.S)
        if ">DA-RUNTIME-001</code>" in item
    )
    assert "Setup documentation" in finding


@pytest.mark.parametrize("category", ["Local authored files", "Local Files", "Local files"])
def test_source_file_category_names_the_agent_workspace_without_changing_recorded_category(category):
    from flightcheck.runner import _generate_html_report

    row = CheckResult("CONFIG-007", category, "High", "Passed", "Agent instructions", "Instructions present.")
    runner = FlightCheckRunner(scope="full")
    runner.register(category, lambda _: [row])
    result = runner.run()
    result.diagnostic_only = True
    before = deepcopy(result)
    html = _generate_html_report(result)
    assert '<div class="syn-name">Agent</div>' in html
    assert 'href="#cat-agent"' in html
    assert 'id="cat-agent"' in html
    assert f'<div class="syn-name">{category}</div>' not in html
    assert result == before
    assert row.category == category


@pytest.mark.parametrize("extra,expected", [
    (None, "Skipped"), ("modelDescription: Find leave information.\n", "Skipped"),
    ("modelDescription: '[TODO]'\n", "Failed"),
])
def test_da_local_cli_aggregates_parse_limits_and_known_description_defects(setup_workspace, monkeypatch, extra, expected):
    ws = setup_workspace
    topics = ws.root / "workspace" / "agents" / "hr" / "topics"
    topics.mkdir()
    (topics / "broken.mcs.yml").write_text("modelDescription: [\n", encoding="utf-8")
    if extra:
        (topics / "leave.mcs.yml").write_text(extra, encoding="utf-8")
    (ws.root / ".local" / "config.json").write_text(json.dumps(ws.config), encoding="utf-8")
    monkeypatch.setattr("sys.argv", [
        "flightcheck", "--scope", "local", "--output", "report", "--no-open", "--no-telemetry",
    ])
    with pytest.raises(SystemExit):
        cli.main()
    data = json.loads((ws.root / "report" / "results.json").read_text(encoding="utf-8"))
    rows = [row for row in data["results"] if row["checkpoint_id"] == "CONFIG-014"]
    assert len(rows) == 1
    assert rows[0]["status"] == expected
    assert "broken.mcs.yml" in rows[0]["result"]
    assert rows[0]["evidence"]["unparseableFiles"] == ["broken.mcs.yml"]
    if expected == "Failed":
        assert rows[0]["evidence"]["placeholderDescriptions"]
    ws.auth.assert_not_called()


def test_agent_group_combines_cloud_and_source_checks_without_merging_observations():
    from flightcheck.runner import _generate_html_report

    cloud = ["DA-AGENT-001", "DA-CONTENT-001", "ESS-SOLN-001", "CONFIG-012", "DA-AUTH-001", "DA-INSTRUCTIONS-001"]
    local = ["CONFIG-007", "CONFIG-005", "TOPIC-011", "CONFIG-014"]
    rows = [
        CheckResult(key, "Native Agent" if key in cloud else "Local Files", "High", "Passed",
                    "Cloud configuration" if key in cloud else "Local source only", "Observed.")
        for key in cloud + local
    ]
    runner = FlightCheckRunner(scope="full")
    runner.register("Observations", lambda _: rows)
    result = runner.run()
    result.diagnostic_only = True
    before = deepcopy(result)
    html = _generate_html_report(result)
    assert html.count('<div class="syn-name">Agent</div>') == 1
    assert '10 recorded check(s)' in html
    assert "Local source only" in html and "Cloud configuration" in html
    assert result == before
    assert len(re.findall(r'<article class="finding"', html)) == 10


@pytest.mark.parametrize("use_alias", [False, True])
def test_focused_manual_report_keeps_supporting_links_and_original_results(use_alias):
    from flightcheck.runner import _generate_html_report

    runner = FlightCheckRunner(scope="checkpoint")
    runner.register("Observations", lambda _: [
        CheckResult("DA-AGENT-001", "Native Agent", "High", "Passed", "Agent access", "Verified."),
        CheckResult(
            "WD-RUN-001", "Workday", "High", "Manual", "Recent response", "No recent response.",
            evidence={"manualVerificationSteps": ["Use the selected Test pane.", "Rerun this checkpoint."]},
            custom_tags=["Workday Litmus Test"],
        ),
    ])
    result = runner.run()
    result.diagnostic_only = True
    result.coverage = {
        "requested": ["LEGACY-SELECTOR" if use_alias else "WD-RUN-001"],
        "aliases": {"LEGACY-SELECTOR": ["WD-RUN-001"]} if use_alias else {},
        "planned": ["DA-AGENT-001", "WD-RUN-001"], "emitted": ["DA-AGENT-001", "WD-RUN-001"],
        "automaticCompleted": 1, "manual": 1, "notApplicable": 0, "limitations": 0,
    }
    before = deepcopy(result)
    html = _generate_html_report(result)
    cards = re.findall(r'<article class="finding"[^>]*>(.*?)</article>', html, re.S)
    assert len(cards) == 1 and "Workday Litmus Test" in cards[0]
    assert "Use the selected Test pane." in cards[0]
    assert "Supporting validation:" in html
    assert 'href="#finding-1">View requested finding</a>' in html
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    assert all(fragment in ids for fragment in re.findall(r'href="#([^"]+)"', html))
    assert result == before


def test_customer_header_hides_internal_metadata_without_changing_legacy_header():
    runner = FlightCheckRunner(scope="full")
    result = runner.run()
    result.validation_context = {
        "agentName": "Employee Self-Service", "agentId": ENV_ID, "environmentId": ENV_ID,
        "accountEmail": "maker@example.test", "serviceRing": "prod",
    }
    legacy = _render_header(result, "verdict-ready", "", "Complete", "Summary")
    assert "Scope:" in legacy
    assert "Re-run:" in legacy
    result.diagnostic_only = True
    customer = _render_header(result, "verdict-ready", "", "Complete", "Summary")
    assert "Service ring:" not in customer
    assert "Scope:" not in customer
    assert "Re-run:" not in customer
    assert ENV_ID in customer and "maker@example.test" in customer
    assert "Run:" in customer and "Completed in:" in customer
    assert "FlightChecks: <b>0 total (0 automated, 0 manual)</b>" in customer
    assert result.validation_context["serviceRing"] == "prod"


@pytest.mark.parametrize("status,evidence,group", [
    ("Passed", {}, "passed"), ("Failed", {}, "problem"),
    ("Warning", {}, "warnings"), ("Error", {}, "warnings"),
    ("Blocked", {}, "warnings"), ("Skipped", {}, "warnings"),
    ("Blocked", {"reviewOwner": "administrator"}, "manual"),
    ("Manual", {}, "manual"), ("NotConfigured", {"applicability": "disabled"}, "optional"),
    ("Passed", {"dependencyCoverageComplete": False}, "warnings"),
])
def test_simple_tabs_preserve_recorded_status_and_optional_dispositions(status, evidence, group):
    from flightcheck.maker_report import _render_finding

    row = CheckResult(
        "CHECK-001", "Agent", "High", status, "Check purpose", "Recorded finding.",
        remediation="Inspect the intended configuration.", roles=["ESS Maker / Agent Developer"],
        custom_tags=["Customer alias"],
        evidence={**evidence, "ifMissingOrIncorrect": "Repair only confirmed defects."},
    )
    original = deepcopy(row)
    html = _render_finding(row, 0)
    assert f'data-filter-group="{group}"' in html
    assert f'data-recorded-status="{status}"' in html
    left, right = html.split('<div class="finding-status">', 1)
    assert '<code class="check-id">CHECK-001</code><strong>Check purpose</strong></h3>' in left
    assert 'class="custom-tags"' not in left
    status_column = right.split('</div></div><div class="finding-body">', 1)[0]
    assert re.search(r'<span class="pill [^"]+">[^<]+</span><ul class="custom-tags"', status_column)
    assert '<li class="custom-tag">Customer alias</li>' in status_column
    assert row.status == status
    if group == "passed":
        assert "Who should check or fix this:" not in html
        assert "Next step:" not in html and "If missing or incorrect:" not in html
        assert row.remediation not in html and "Environment Maker user" not in html
    else:
        assert "Who should check or fix this:" in html and "Environment Maker user" in html
        assert ("Verification steps:" if group == "manual" else "Next step:") in html
        assert "Repair only confirmed defects." in html
    assert row == original
