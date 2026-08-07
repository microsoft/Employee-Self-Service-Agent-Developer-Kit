# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import pytest

from setup_state import (
    EnvironmentType,
    JsonSetupStateRepository,
    ProductId,
    SetupState,
    SetupWorkflow,
)


def _connection(name, *, connector="shared_alchemy", status="Connected"):
    return {
        "name": name,
        "properties": {
            "apiId": f"/providers/Microsoft.PowerApps/apis/{connector}",
            "displayName": f"Connection {name}",
            "accountName": "maker@contoso.com",
            "statuses": [{"status": status}],
        },
    }


def _setup_state(path, *products):
    assert len(products) == 1
    state = SetupState()
    SetupWorkflow.set_scope(
        state,
        environment_id="environment-id",
        environment_name="Development",
        environment_type=EnvironmentType.DEV,
        tenant_endpoint="https://org.crm.dynamics.com",
    )
    SetupWorkflow.select_initial_product(state, products[0])
    JsonSetupStateRepository(path).save(state)


def test_installation_config_declares_only_it_connection_requirements():
    import install_ess_agent

    installations = install_ess_agent.load_installation_config()["installations"]

    assert installations["da.hr"]["requiredConnection"] is None
    assert installations["cea.hr"]["requiredConnection"] is None
    assert installations["da.it"]["requiredConnection"]["connectorApiName"] == (
        "shared_alchemy"
    )
    assert installations["da.it"]["requiredConnection"]["runtimeSource"] == (
        "invoker"
    )
    assert installations["cea.it"]["requiredConnection"]["connectorApiName"] == (
        "shared_alchemy"
    )
    assert installations["cea.it"]["requiredConnection"]["runtimeSource"] == (
        "invoker"
    )


def test_preflight_requires_manual_selection_for_multiple_connected_matches():
    import ess_connection_binding
    import install_ess_agent

    installation = install_ess_agent.load_installation_config()["installations"][
        "da.it"
    ]
    result = ess_connection_binding.build_preflight_result(
        installation,
        [
            _connection("one"),
            _connection("two"),
            _connection("broken", status="Error"),
            _connection("wrong", connector="shared_workdaysoap"),
        ],
        "environment-id",
    )

    assert result["status"] == "selection-required"
    assert [connection["name"] for connection in result["connections"]] == [
        "one",
        "two",
    ]
    assert result["selectedConnection"] is None


def test_preflight_auto_selects_only_connected_match():
    import ess_connection_binding
    import install_ess_agent

    installation = install_ess_agent.load_installation_config()["installations"][
        "cea.it"
    ]
    result = ess_connection_binding.build_preflight_result(
        installation,
        [_connection("alchemy")],
        "environment-id",
    )

    assert result["status"] == "ready"
    assert result["selectedConnection"]["name"] == "alchemy"


def test_inspect_reports_connection_permission_error(monkeypatch):
    import ess_connection_binding

    class FakePPAdmin:
        def __init__(self, tenant_id):
            assert tenant_id == "tenant"

        def authenticate(self, *, include_flow):
            assert include_flow is False

        def get_connections(self, environment_id):
            assert environment_id == "environment-id"
            return {"_error": "insufficient_permissions", "_status": 403}

    monkeypatch.setattr(
        ess_connection_binding,
        "discover_tenant",
        lambda _url: "tenant",
    )
    monkeypatch.setattr(
        ess_connection_binding,
        "derive_environment_id",
        lambda _url, _configured_id, _client: "environment-id",
    )

    with pytest.raises(RuntimeError, match="cannot read connections"):
        ess_connection_binding.inspect_connections(
            "https://org.crm.dynamics.com",
            "da",
            "it",
            pp_admin_client_factory=FakePPAdmin,
        )


def test_bind_updates_exact_solution_reference_and_persists_s_states(
    tmp_path,
    monkeypatch,
):
    import ess_connection_binding

    class FakePPAdmin:
        def __init__(self, tenant_id):
            self.tenant_id = tenant_id

        def authenticate(self, *, include_flow):
            assert include_flow is False

        def find_environment_id_by_dataverse_url(self, env_url):
            return "environment-id"

        def get_connections(self, environment_id):
            assert environment_id == "environment-id"
            return [_connection("alchemy-connection")]

    reference_id = "11111111-1111-1111-1111-111111111111"
    solution_id = "22222222-2222-2222-2222-222222222222"
    query_results = iter([
        [{
            "connectionreferenceid": reference_id,
            "connectionreferencelogicalname": (
                "msdyn_copilotforemployeeselfservicedait.shared_alchemy."
                "shared-alchemy-8262076a-e778-450b-8a35-5ae815712319"
            ),
            "connectorid": "/providers/Microsoft.PowerApps/apis/shared_alchemy",
            "connectionid": None,
            "statuscode": 1,
        }],
        [{"objectid": reference_id, "_solutionid_value": solution_id}],
        [{
            "solutionid": solution_id,
            "uniquename": "msdyn_CopilotForEmployeeSelfServiceDAIT",
        }],
        [{
            "connectionreferenceid": reference_id,
            "connectionid": "alchemy-connection",
        }],
        [{
            "botid": "33333333-3333-3333-3333-333333333333",
            "name": "Employee Self-Service IT",
            "schemaname": "msdyn_CopilotForEmployeeSelfServiceDAIT",
        }],
    ])
    updates = []
    monkeypatch.setattr(ess_connection_binding, "discover_tenant", lambda url: "tenant")
    monkeypatch.setattr(ess_connection_binding, "authenticate", lambda url: "token")
    monkeypatch.setattr(
        ess_connection_binding,
        "query_all",
        lambda *args, **kwargs: next(query_results),
    )
    monkeypatch.setattr(
        ess_connection_binding,
        "update_record",
        lambda *args: updates.append(args),
    )
    state_path = tmp_path / "config.json"
    _setup_state(state_path, ProductId.DA_ESSIT)
    state = JsonSetupStateRepository(state_path).load()
    SetupWorkflow.update_product_installation(
        state,
        ProductId.DA_ESSIT,
        "installing",
    )
    SetupWorkflow.update_product_installation(
        state,
        ProductId.DA_ESSIT,
        "installed",
    )
    JsonSetupStateRepository(state_path).save(state)

    result = ess_connection_binding.bind_connection(
        "https://org.crm.dynamics.com",
        "da",
        "it",
        "alchemy-connection",
        state_path=state_path,
        pp_admin_client_factory=FakePPAdmin,
    )

    assert result["status"] == "bound"
    assert result["attestationRequired"] is True
    assert result["connectionSettingsUrl"] == (
        "https://copilotstudio.microsoft.com/environments/"
        "environment-id/copilots/"
        "33333333-3333-3333-3333-333333333333/settings/connectionSettings"
    )
    assert updates[0][-1] == {"connectionid": "alchemy-connection"}
    state = JsonSetupStateRepository(state_path).load()
    product = state.products["da.essit"]
    assert (
        product.installation_status
        == "connection-attestation-required"
    )
    assert product.connection_name == "alchemy-connection"
    assert product.agent_name == "Employee Self-Service IT"
    assert product.connection_settings_url == result["connectionSettingsUrl"]


def test_hr_binding_marks_connection_not_required(tmp_path, monkeypatch):
    import ess_connection_binding

    state_path = tmp_path / "config.json"
    _setup_state(state_path, ProductId.CEA_ESSHR)
    state = JsonSetupStateRepository(state_path).load()
    SetupWorkflow.update_product_installation(
        state,
        ProductId.CEA_ESSHR,
        "installing",
    )
    SetupWorkflow.update_product_installation(
        state,
        ProductId.CEA_ESSHR,
        "installed",
    )
    JsonSetupStateRepository(state_path).save(state)

    result = ess_connection_binding.bind_connection(
        "https://org.crm.dynamics.com",
        "cea",
        "hr",
        None,
        state_path=state_path,
    )

    assert result["status"] == "not-required"
    state = JsonSetupStateRepository(state_path).load()
    assert state.products["cea.esshr"].installation_status == "bound"
    assert state.products["cea.esshr"].requires_connection_attestation is False


def test_cli_accepts_hub_vertical(monkeypatch, capsys):
    import ess_connection_binding

    monkeypatch.setattr(
        ess_connection_binding,
        "inspect_connections",
        lambda _url, experience, vertical: {
            "required": False,
            "status": "not-required",
            "experience": experience,
            "vertical": vertical,
        },
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "ess_connection_binding.py",
            "inspect",
            "--url",
            "https://org.crm.dynamics.com",
            "--experience",
            "da",
            "--vertical",
            "hub",
        ],
    )

    ess_connection_binding.main()

    assert '"vertical": "hub"' in capsys.readouterr().out


def test_connection_settings_url_escapes_path_segments():
    import ess_connection_binding

    assert ess_connection_binding.connection_settings_url(
        "environment/id",
        "agent id",
    ) == (
        "https://copilotstudio.microsoft.com/environments/"
        "environment%2Fid/copilots/agent%20id/settings/connectionSettings"
    )
