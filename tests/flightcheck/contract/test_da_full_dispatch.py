# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure planning and CLI orchestration contracts, not fabricated API responses."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import auth
from flightcheck import cli, registry
from flightcheck.checks import native_agent, publishing
from flightcheck.da_contract import DA_CATALOG, DAFeature, DAFeatureEvidence
from flightcheck.da_execution import build_da_execution_plan, da_full_requested
from flightcheck.runner import CheckResult, FlightCheckRunner, Priority, Role, Status


ENV_ID = "00000000-0000-0000-0000-000000002222"
TENANT_ID = "00000000-0000-0000-0000-000000001111"
BOT_ID = "00000000-0000-0000-0000-000000003333"
ACCOUNT = "maker@example.test"


def _config(*, dataverse=False):
    config = {
        "realm": "dev",
        "ring": "prod",
        "environmentId": ENV_ID,
        "tenantId": TENANT_ID,
        "powerPlatformApiEndpoint": (
            "https://0000000000000000000000000000222."
            "2.environment.api.powerplatform.com"
        ),
        "activeAgent": "hr",
        "agents": [
            {"slug": "hr", "botId": BOT_ID, "schemaName": "gptagent_hr", "releaseLine": "da"},
            {
                "slug": "it",
                "botId": "00000000-0000-0000-0000-000000004444",
                "schemaName": "legacy_it",
                "releaseLine": "ca",
            },
        ],
        "agent": {"slug": "it", "schemaName": "stale_copy", "releaseLine": "ca"},
    }
    if dataverse:
        config["dataverseEndpoint"] = "https://org.crm.dynamics.com"
    return config


def _passed(checkpoint_id):
    return CheckResult(
        checkpoint_id, "Dispatch test", Priority.HIGH.value, Status.PASSED.value,
        "Orchestration test row", "No evaluator or external API is exercised.",
        roles=[Role.ESS_MAKER.value],
    )


def test_planning_keeps_exact_subject_and_registry_independent_of_dataverse():
    profiles = dict(registry.PROFILES)
    config = _config()
    before = copy.deepcopy(config)
    native = build_da_execution_plan(config)
    hybrid = build_da_execution_plan(_config(dataverse=True))

    assert native.profile.checkpoint_ids == hybrid.profile.checkpoint_ids
    assert native.requirements.clients == {
        registry.AGENTBUILDER, registry.CONNECTIVITY, registry.POWERPLATFORM,
    }
    assert hybrid.requirements.clients == native.requirements.clients | {registry.PP_ADMIN}
    assert native.config["agents"] == [config["agents"][0]]
    assert native.config["agent"]["botId"] == BOT_ID
    assert config == before
    assert registry.PROFILES == profiles
    assert native.requirements.ordered_fns[0][0] == "Native Agent"
    assert len({fn for _, fn in native.requirements.ordered_fns}) == len(
        native.requirements.ordered_fns
    )
    assert {fn for _, fn in native.requirements.ordered_fns}.isdisjoint({
        cli.run_external_systems_checks, cli.run_workday_checks, cli.run_servicenow_checks,
        cli.run_local_file_checks,
    })


@pytest.mark.parametrize("slug, expected", [(None, True), ("hr", True), ("it", False)])
def test_routing_uses_selected_metadata_not_native_endpoint(slug, expected):
    config = _config(dataverse=True)
    assert da_full_requested(config, slug) is expected
    config.pop("powerPlatformApiEndpoint")
    assert da_full_requested(config, slug) is expected


@pytest.mark.parametrize("selection", ["unknown", "../hr", "ambiguous", "unselected"])
def test_bad_selection_cannot_fall_back_to_a_sibling(selection):
    config = _config()
    if selection == "ambiguous":
        config["agents"].append(dict(config["agents"][0]))
    elif selection == "unselected":
        config.pop("activeAgent")
        config.pop("agent")
    else:
        config["activeAgent"] = selection
    assert da_full_requested(config)
    with pytest.raises(ValueError):
        build_da_execution_plan(config)


def test_selected_native_metadata_overrides_defaults_by_presence():
    config = _config()
    config["realm"] = "prod"
    config["agents"][0].update(realm="dev", agentBuilderApiVersion="")
    plan = build_da_execution_plan(config)
    assert plan.config["realm"] == "dev"
    assert plan.config["agentBuilderApiVersion"] == ""
    config["agents"][0]["environmentId"] = TENANT_ID
    with pytest.raises(ValueError, match="consistent"):
        build_da_execution_plan(config)


def test_unknown_and_disabled_features_remain_distinct_without_dispatching_legacy():
    unknown = build_da_execution_plan(_config())
    disabled = build_da_execution_plan(
        _config(), features={DAFeature.WORKDAY: DAFeatureEvidence(False, "target-bound evidence")},
    )
    enabled = build_da_execution_plan(
        _config(), features={DAFeature.WORKDAY: DAFeatureEvidence(True, "target-bound evidence")},
    )
    assert "WD-DA-PKG-001" in dict(unknown.pending)
    assert "WD-DA-PKG-001" not in dict(disabled.pending)
    assert "WD-DA-PKG-001" in enabled.profile.checkpoint_ids
    assert registry.GRAPH not in enabled.requirements.clients
    row = unknown.coverage_check(None)[0]
    assert row.status == Status.BLOCKED.value
    assert len(row.evidence["coverage"]) == len(DA_CATALOG)
    assert not any(key.startswith("WD-WF-") for key in unknown.profile.checkpoint_ids)
    assert unknown.matches("ENV-004-COVERAGE")
    assert unknown.matches("ENV-004-UR-001")
    assert not unknown.matches("DA-CONN-002")
    assert not unknown.matches("WD-WF-001")


def test_dependent_producer_does_not_execute_before_exact_agent_passes(monkeypatch):
    plan = build_da_execution_plan(_config())
    producer = Mock(return_value=[_passed("ESS-SOLN-001")])
    monkeypatch.setitem(
        registry.REGISTRY, "ESS-SOLN-001",
        replace(registry.REGISTRY["ESS-SOLN-001"], category_fn=producer),
    )
    guarded = plan.guard_producer(producer)
    runner = SimpleNamespace(results=[])
    assert guarded(runner)[0].status == Status.BLOCKED.value
    producer.assert_not_called()
    runner.results.append(_passed("DA-AGENT-001"))
    assert guarded(runner)[0].status == Status.PASSED.value
    producer.assert_called_once_with(runner)


def test_observed_realm_mismatch_stops_before_other_native_reads(monkeypatch):
    inspect = Mock(return_value={"realm": "dev", "alm": {"isEnrolled": False}})
    validate = Mock()
    client = Mock()
    monkeypatch.setattr(native_agent, "inspect_agent_route", inspect)
    monkeypatch.setattr(native_agent, "validate_existing_dev_connection", validate)
    runner = SimpleNamespace(
        config=_config(), agent_slug="hr", env_id=ENV_ID, agentbuilder=client,
        connectivity=None, validation_context={"realm": "prod"},
    )
    rows = native_agent.run_native_agent_checks(runner)
    assert rows[0].status == Status.FAILED.value
    assert "different deployment realm" in rows[0].result
    validate.assert_not_called()
    client.fetch_components.assert_not_called()


def test_publishing_does_not_execute_unselected_import_or_manual_checks(monkeypatch):
    export = Mock(return_value=_passed("PUB-001"))
    import_probe = Mock()
    monkeypatch.setattr(publishing, "_check_pub_001_export", export)
    monkeypatch.setattr(publishing, "_check_pub_002_import", import_probe)
    runner = SimpleNamespace(
        config=_config(), env_id=ENV_ID, agent_slug="hr",
        should_execute=lambda checkpoint_id: checkpoint_id == "PUB-001",
    )
    rows = publishing.run_publishing_checks(runner)
    assert [row.checkpoint_id for row in rows] == ["PUB-001"]
    export.assert_called_once()
    import_probe.assert_not_called()


class _OrchestrationRunner(FlightCheckRunner):
    """Record producer registration without testing external API contracts."""

    last = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        type(self).last = self
        self.producers = []

    def register(self, category, fn):
        if category in {"Native Agent", "Environment", "DA Baseline", "DA Integrations",
                        "Workday DA", "Workday Extension", "Solution", "Local Files", "Publishing"}:
            self.producers.append(category)

            def dispatch_rows(runner):
                return [
                    _passed(checkpoint_id)
                    for checkpoint_id in runner.execution_targets
                    if (
                        registry.DA_CHECKPOINT_OVERRIDES.get(checkpoint_id)
                        or registry.resolve(checkpoint_id)
                    ).category_fn is unwrap(fn)
                ]

            super().register(category, dispatch_rows)
        else:
            super().register(category, fn)


@pytest.fixture
def da_cli(tmp_path, monkeypatch):
    config = _config()
    local = tmp_path / ".local"
    local.mkdir()
    monkeypatch.chdir(tmp_path)
    native_auth = Mock(return_value=("native-token", TENANT_ID, ACCOUNT))
    native_client = Mock(return_value=object())
    connectivity_client = Mock(return_value=object())
    admin = Mock(signed_in_username=ACCOUNT)
    admin.find_environment_id_by_dataverse_url.return_value = ENV_ID
    admin_client = Mock(return_value=admin)
    licensing = Mock(signed_in_username=ACCOUNT)
    licensing_client = Mock(return_value=licensing)
    monkeypatch.setattr(cli, "authenticate_flightcheck", native_auth)
    monkeypatch.setattr(cli, "AgentBuilderClient", native_client)
    monkeypatch.setattr(cli, "ConnectivityClient", connectivity_client)
    monkeypatch.setattr(cli, "PPAdminClient", admin_client)
    monkeypatch.setattr(cli, "PowerPlatformClient", licensing_client)
    monkeypatch.setattr(cli, "FlightCheckRunner", _OrchestrationRunner)
    prepare = Mock(side_effect=lambda _runner, _args, execution: (execution, None))
    monkeypatch.setattr(cli, "_prepare_da_integration_execution", prepare)
    monkeypatch.setattr(auth, "discover_tenant", lambda _url: TENANT_ID)

    def forbidden(*_args, **_kwargs):
        pytest.fail("DA full must not use legacy discovery or unrelated clients")

    for name in ("GraphClient", "PVAClient", "AzureArmClient"):
        monkeypatch.setattr(cli, name, forbidden)
    monkeypatch.setattr(auth, "authenticate", forbidden)
    monkeypatch.setattr(cli, "_resolve_target_selection", forbidden)
    monkeypatch.setattr(cli, "_print_prioritized_summary", lambda *_a, **_k: None)
    telemetry = Mock()
    monkeypatch.setattr(cli, "_emit_run_telemetry", telemetry)
    browser = Mock()
    monkeypatch.setattr(cli, "open_report_in_browser", browser)
    captured = {}

    def save(result, output):
        captured["result"] = result
        # Exercise the real versioned JSON + HTML persistence for the scope.
        from flightcheck.runner import save_results

        save_results(result, output)

    monkeypatch.setattr(cli, "save_results", save)

    def run(*extra, no_open=True, configured=True):
        if configured:
            (local / "config.json").write_text(json.dumps(config), encoding="utf-8")
        monkeypatch.setattr(
            "sys.argv",
            [
                "cli.py", *(["--no-open"] if no_open else []), "--no-telemetry", "--quiet-auth",
                "--preferred-username", ACCOUNT, "--output", str(tmp_path / "out"), *extra,
            ],
        )
        with pytest.raises(SystemExit) as exc:
            cli.main()
        return exc.value.code

    return SimpleNamespace(
        config=config, run=run, captured=captured, native_auth=native_auth,
        native_client=native_client, connectivity_client=connectivity_client,
        admin=admin, admin_client=admin_client, telemetry=telemetry, browser=browser,
        output=tmp_path / "out", licensing=licensing, licensing_client=licensing_client,
        prepare=prepare,
    )


@pytest.mark.parametrize("available", [True, False])
def test_discovered_workday_recomposes_cli_clients_and_persists_new_requirements(da_cli, available):
    def prepare(runner, _args, execution):
        if available:
            runner.env_url = "https://org.crm.dynamics.com"
            runner.dv_token = "verified-dependency-token"
            runner.pp_admin = da_cli.admin
        else:
            runner._da_dataverse_error = "Verified dependency authentication is unavailable."
        return build_da_execution_plan(
            execution.config, features={
                DAFeature.WORKDAY: DAFeatureEvidence(True, "selected dependency discovery"),
                DAFeature.SERVICENOW: DAFeatureEvidence(False, "selected dependency discovery"),
            }, environment_url=runner.env_url,
        ), None

    da_cli.prepare.side_effect = prepare
    assert da_cli.run("--scope", "full") == 1
    result = da_cli.captured["result"]
    assert "WD-DA-PKG-001" in result.profile_checkpoints
    assert "WD-DA-MAKER-001" in result.profile_checkpoints
    assert registry.GRAPH not in result.client_availability
    assert result.client_availability[registry.DATAVERSE]["available"] is available
    if available:
        assert result.client_availability[registry.DATAVERSE]["authenticatedAccountVerified"]
    else:
        assert "authentication is unavailable" in result.client_availability[registry.DATAVERSE]["reason"]
        assert any(row.checkpoint_id == "PROFILE-CLIENT-DATAVERSE" for row in result.results)


@pytest.mark.parametrize("dataverse", [False, True])
@pytest.mark.parametrize("api_version", [None, "2024-10-01"])
def test_full_cli_uses_verified_read_only_plan_and_persists_gaps(da_cli, dataverse, api_version):
    if dataverse:
        da_cli.config["dataverseEndpoint"] = "https://org.crm.dynamics.com"
    if api_version:
        da_cli.config["agentBuilderApiVersion"] = api_version

    assert da_cli.run("--scope", "full", "--environment-id", ENV_ID) == 1
    result = da_cli.captured["result"]
    assert result.scope == "full"
    assert result.profile == "da:full"
    assert result.overall == "NOT_READY"
    runner = _OrchestrationRunner.last
    assert runner.producers == [
        "Native Agent", "Environment", "Environment", "DA Baseline", "DA Integrations",
        "Solution", "Local Files", "Publishing",
    ]
    assert runner.config["agents"] == [da_cli.config["agents"][0]]
    assert runner.connection_agent_ids == (BOT_ID,)
    assert runner.connection_dependency_token.keywords["account_hint"] == ACCOUNT
    da_cli.native_auth.assert_called_once()
    assert da_cli.native_auth.call_args.kwargs == {
        "account_hint": ACCOUNT, "include_connectivity": True, "allow_write": False,
        "emit_account_identity": False, "return_account_identity": True,
    }
    assert da_cli.native_client.call_args.kwargs["api_version"] == (
        api_version or cli.DEFAULT_API_VERSION
    )
    assert (
        da_cli.connectivity_client.call_args.kwargs["api_version"]
        == da_cli.native_client.call_args.kwargs["api_version"]
    )
    assert runner.runtime_reachability is False
    assert runner.alm_import_probe is False
    assert set(result.client_availability) == (
        {registry.AGENTBUILDER, registry.CONNECTIVITY, registry.PP_ADMIN, registry.POWERPLATFORM}
        if dataverse else {registry.AGENTBUILDER, registry.CONNECTIVITY, registry.POWERPLATFORM}
    )
    if dataverse:
        da_cli.admin.authenticate.assert_called_once_with(
            preferred_username=ACCOUNT, include_flow=False,
        )
        da_cli.admin.find_environment_id_by_dataverse_url.assert_called_once_with(
            da_cli.config["dataverseEndpoint"],
        )
    else:
        da_cli.admin_client.assert_not_called()
    assert all(state["authenticatedAccountVerified"] for state in result.client_availability.values())
    saved = json.loads((da_cli.output / "results.json").read_text(encoding="utf-8"))
    assessment = saved["da_assessment"]
    assert saved["contract"]["daAssessment"] == assessment
    assert assessment["schemaVersion"] == "flightcheck.da.assessment.v1"
    assert assessment["deploymentReadiness"] == "INCOMPLETE"
    assert assessment["counts"]["catalogDefinitions"] == len(DA_CATALOG)
    assert assessment["counts"]["observedRows"] == len(result.results)
    assert "DA-PLAN-COVERAGE" in json.dumps(saved)
    html = (da_cli.output / "report.html").read_text(encoding="utf-8")
    assert "DA-PLAN-COVERAGE" in html
    assert "Full DA dispatch remains incomplete" in html
    assert "DA deployment readiness" in html
    assert "Coverage reconciliation" in html
    assert da_cli.telemetry.call_args.kwargs["scope"] == "full"
    da_cli.licensing.authenticate.assert_called_once_with(preferred_username=ACCOUNT)


def test_invalid_evidence_file_fails_before_authentication(da_cli, tmp_path, capsys):
    path = tmp_path / "evidence.json"
    path.write_text('{"schemaVersion":"unsupported","records":[]}', encoding="utf-8")
    assert da_cli.run("--da-evidence", str(path)) == 1
    assert "flightcheck.da.evidence.v1" in capsys.readouterr().out
    da_cli.native_auth.assert_not_called()


def test_da_full_reconciles_coverage_without_applying_connect_acceptance(da_cli, monkeypatch):
    family_gate = Mock(side_effect=AssertionError("DA full must not apply Connect family acceptance."))
    checkpoint_gate = Mock(side_effect=AssertionError("DA full must not apply Connect checkpoint acceptance."))
    monkeypatch.setattr(cli, "_profile_family_cardinality_check", family_gate)
    monkeypatch.setattr(cli, "_profile_checkpoint_contract_check", checkpoint_gate)
    da_cli.prepare.side_effect = lambda runner, args, execution: (
        build_da_execution_plan(
            execution.config,
            features={DAFeature.WORKDAY: DAFeatureEvidence(True, "selected dependency discovery")},
        ), None,
    )
    assert da_cli.run("--scope", "full") == 1
    result = da_cli.captured["result"]
    assert "WD-ENTRA-SCOPE-001" in result.profile_checkpoints
    assert result.da_assessment["counts"]["catalogDefinitions"] == len(DA_CATALOG)
    assert result.da_assessment["deploymentReadiness"] == "INCOMPLETE"
    assert not any(row.checkpoint_id.startswith(("PROFILE-FAMILY-", "PROFILE-CHECKPOINT-"))
                   for row in result.results)
    family_gate.assert_not_called()
    checkpoint_gate.assert_not_called()


@pytest.mark.parametrize("configured", [False, True])
def test_explicit_da_url_uses_same_contract_without_reading_or_replacing_saved_target(da_cli, configured, tmp_path):
    da_cli.config["environmentId"] = "00000000-0000-0000-0000-000000009999"
    da_cli.config["dataverseEndpoint"] = "https://unrelated.crm.dynamics.com"
    assert da_cli.run(
        "--scope", "full", "--da-target-url",
        f"https://copilotstudio.microsoft.com/environments/{ENV_ID}/copilots/{BOT_ID}/tools?agentBackend=cosmos",
        "--agent-schema-name", "gptagent_hr", "--validation-realm", "dev",
        configured=configured,
    ) == 1
    runner = _OrchestrationRunner.last
    assert runner.config["environmentId"] == ENV_ID
    assert runner.config["agent"]["botId"] == BOT_ID
    assert runner.config.get("dataverseEndpoint") is None
    assert runner.config["activeAgent"] == "flightcheck-only"
    result = da_cli.captured["result"]
    assert result.profile == "da:full"
    assert result.da_assessment["counts"]["catalogDefinitions"] == len(DA_CATALOG)
    assert da_cli.native_auth.call_args.kwargs["allow_write"] is False
    path = tmp_path / ".local" / "config.json"
    assert path.exists() is configured
    if configured:
        assert json.loads(path.read_text(encoding="utf-8")) == da_cli.config


@pytest.mark.parametrize("extra", [
    (), ("--agent-schema-name", "gptagent_hr"),
    ("--agent-schema-name", "gptagent_hr", "--validation-realm", "dev", "--scope", "workday"),
    ("--agent-schema-name", "gptagent_hr", "--validation-realm", "dev", "--ring", "test"),
    ("--agent-schema-name", "gptagent_hr", "--validation-realm", "dev", "--environment-id", TENANT_ID),
])
def test_explicit_da_url_rejects_incomplete_or_conflicting_target_before_authentication(da_cli, extra):
    assert da_cli.run(
        "--da-target-url", f"https://copilotstudio.microsoft.com/environments/{ENV_ID}/copilots/{BOT_ID}",
        *extra, configured=False,
    ) == 2
    da_cli.native_auth.assert_not_called()


@pytest.mark.parametrize("url", [
    f"http://copilotstudio.microsoft.com/environments/{ENV_ID}/copilots/{BOT_ID}",
    f"https://example.test/?url=https://copilotstudio.microsoft.com/environments/{ENV_ID}/copilots/{BOT_ID}",
    f"https://copilotstudio.microsoft.com/?target=environments/{ENV_ID}/copilots/{BOT_ID}",
    f"https://copilotstudio.microsoft.com/environments/{ENV_ID}",
])
def test_explicit_da_url_requires_recognized_agent_path(da_cli, url):
    assert da_cli.run(
        "--da-target-url", url, "--agent-schema-name", "gptagent_hr",
        "--validation-realm", "dev", configured=False,
    ) == 2
    da_cli.native_auth.assert_not_called()


@pytest.mark.parametrize("mode", [
    ("--scope", "workday"), ("--profile", "workday-da:final"), ("--checkpoint", "ENV-004"),
])
def test_evidence_option_cannot_change_connect_or_other_scopes(da_cli, mode):
    assert da_cli.run(*mode, "--da-evidence", "not-read.json") == 2
    da_cli.native_auth.assert_not_called()


@pytest.mark.parametrize("failure", ["missing", "error", "account", "environment"])
def test_hybrid_mapping_is_independent_even_with_explicit_id(da_cli, failure):
    da_cli.config["dataverseEndpoint"] = "https://org.crm.dynamics.com"
    if failure == "missing":
        da_cli.admin.find_environment_id_by_dataverse_url.return_value = None
    elif failure == "error":
        da_cli.admin.find_environment_id_by_dataverse_url.side_effect = RuntimeError("unavailable")
    elif failure == "account":
        da_cli.admin.signed_in_username = "other@example.test"
    else:
        da_cli.admin.find_environment_id_by_dataverse_url.return_value = BOT_ID
    assert da_cli.run("--environment-id", ENV_ID) == 1
    da_cli.native_auth.assert_not_called()
    da_cli.native_client.assert_not_called()
    if failure != "environment":
        assert da_cli.captured["result"].client_availability["agentbuilder"]["available"] is False


@pytest.mark.parametrize("failure", ["account", "tenant", "endpoint", "ring", "selection"])
def test_wrong_native_identity_never_constructs_clients(da_cli, failure):
    if failure == "account":
        da_cli.native_auth.return_value = ("token", TENANT_ID, "other@example.test")
    elif failure == "tenant":
        da_cli.native_auth.return_value = ("token", BOT_ID, ACCOUNT)
    elif failure == "endpoint":
        da_cli.config["powerPlatformApiEndpoint"] = da_cli.config[
            "powerPlatformApiEndpoint"
        ].replace("0000222.2.", "0000333.3.")
    elif failure == "ring":
        da_cli.config["ring"] = "test"
    else:
        da_cli.config["activeAgent"] = "missing"
    assert da_cli.run() == 1
    da_cli.native_client.assert_not_called()


@pytest.mark.parametrize("flag", ["--alm-import-probe", "--runtime-reachability"])
def test_full_da_rejects_mutating_options_before_authentication(da_cli, flag):
    assert da_cli.run(flag) == 2
    da_cli.native_auth.assert_not_called()


def test_canonical_setup_per_agent_realm_does_not_require_global_duplicate(da_cli):
    da_cli.config["agents"][0]["realm"] = da_cli.config.pop("realm")
    assert da_cli.run() == 1
    assert da_cli.captured["result"].validation_context["realm"] == "dev"
    da_cli.native_auth.assert_called_once()


def test_full_da_preserves_default_report_opening(da_cli):
    assert da_cli.run(no_open=False) == 1
    da_cli.browser.assert_called_once_with(str(da_cli.output))


def test_capacity_auth_uses_native_verified_tenant_when_setup_has_no_tenant_id(da_cli):
    da_cli.config.pop("tenantId")
    assert da_cli.run() == 1
    da_cli.licensing_client.assert_called_once_with(TENANT_ID)
    assert da_cli.captured["result"].client_availability["powerplatform"]["available"] is True
