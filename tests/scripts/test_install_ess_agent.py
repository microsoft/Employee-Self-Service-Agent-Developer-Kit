# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the Employee Self-Service Marketplace application installer."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def test_catalog_resolves_all_parent_schema_combinations():
    import install_ess_agent

    mappings = install_ess_agent.load_parent_schemas()

    assert mappings == {
        ("cea", "hr"): "msdyn_CopilotForEmployeeSelfServiceHR",
        ("cea", "it"): "msdyn_CopilotForEmployeeSelfServiceIT",
        ("cea", "hub"): "msdyn_CopilotForEmployeeSelfServiceCore",
        ("da", "hr"): "msdyn_CopilotForEmployeeSelfServiceDAHR",
        ("da", "it"): "msdyn_CopilotForEmployeeSelfServiceDAIT",
        ("da", "hub"): "msdyn_CopilotForEmployeeSelfServiceCoreDA",
    }


def test_catalog_requires_all_parent_mappings(tmp_path: Path):
    import install_ess_agent

    catalog = tmp_path / "solution-catalog.md"
    catalog.write_text(
        """
## Parents

| # | Parent package | Parent schema name | Status | Reference |
| --- | --- | --- | --- | --- |
| 1 | Employee Self-Service HR | `schema` | Active (DA bundle) | _(none)_ |
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing parent schema mappings"):
        install_ess_agent.load_parent_schemas(catalog)


def test_installation_config_has_collision_safe_composite_keys():
    import install_ess_agent

    config = install_ess_agent.load_installation_config()

    assert set(config["installations"]) == {
        "da.hr",
        "da.it",
        "da.hub",
        "cea.hr",
        "cea.it",
        "cea.hub",
    }
    assert config["experiences"]["da"]["recommended"] is True
    assert config["experiences"]["cea"]["recommended"] is False
    assert len({
        entry["marketplaceApplication"]["uniqueName"]
        for entry in config["installations"].values()
    }) == 6


def test_installation_options_are_single_picker_in_da_then_cea_order():
    import install_ess_agent

    options = install_ess_agent.build_installation_options(
        install_ess_agent.load_installation_config()
    )

    assert [option["label"] for option in options] == [
        "DA: Employee Self-Service HR (Recommended)",
        "DA: Employee Self-Service IT (Recommended)",
        "DA: Employee Self-Service Hub (Recommended)",
        "CEA: Employee Self-Service HR",
        "CEA: Employee Self-Service IT",
        "CEA: Employee Self-Service Hub",
    ]
    assert [option["configKey"] for option in options] == [
        "da.esshr",
        "da.essit",
        "da.esshub",
        "cea.esshr",
        "cea.essit",
        "cea.esshub",
    ]


def test_installation_config_rejects_mismatched_composite_key(tmp_path: Path):
    import install_ess_agent

    config = install_ess_agent.load_installation_config()
    config["installations"]["da.hr"]["verticalKey"] = "it"
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match"):
        install_ess_agent.load_installation_config(config_path)


def test_installation_config_rejects_duplicate_application_name(tmp_path: Path):
    import install_ess_agent

    config = install_ess_agent.load_installation_config()
    config["installations"]["da.it"]["marketplaceApplication"]["uniqueName"] = (
        config["installations"]["da.hr"]["marketplaceApplication"]["uniqueName"]
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="assigned to more than one"):
        install_ess_agent.load_installation_config(config_path)


def test_installation_config_rejects_catalog_drift(tmp_path: Path):
    import install_ess_agent

    config = install_ess_agent.load_installation_config()
    config["installations"]["cea.hr"]["solution"]["parentUniqueName"] = (
        "msdyn_WrongSolution"
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match the parent schema"):
        install_ess_agent.load_installation_config(config_path)


def test_installation_config_requires_invoker_runtime_source(tmp_path: Path):
    import install_ess_agent

    config = install_ess_agent.load_installation_config()
    config["installations"]["da.it"]["requiredConnection"]["runtimeSource"] = (
        "embedded"
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="runtimeSource as 'invoker'"):
        install_ess_agent.load_installation_config(config_path)


class FakePPAdminClient:
    def __init__(self, tenant_id, environment_id="env-123", connections=None):
        self.tenant_id = tenant_id
        self.environment_id = environment_id
        self.connections = connections if connections is not None else [{
            "name": "alchemy-connection",
            "properties": {
                "apiId": "/providers/Microsoft.PowerApps/apis/shared_alchemy",
                "statuses": [{"status": "Connected"}],
            },
        }]
        self.authenticated = False

    def authenticate(self, *, include_flow=True):
        self.authenticated = True
        self.include_flow = include_flow

    def find_environment_id_by_dataverse_url(self, _env_url):
        return self.environment_id

    def get_connections(self, environment_id):
        assert environment_id == self.environment_id
        return self.connections


class FakePowerPlatformClient:
    def __init__(
        self,
        tenant_id,
        *,
        packages,
        install_result=None,
    ):
        self.tenant_id = tenant_id
        self.packages = list(packages)
        self.install_result = install_result or {}
        self.authenticated = False
        self.install_calls = []

    def authenticate(self):
        self.authenticated = True

    def list_environment_application_packages(self, _environment_id):
        if self.packages and isinstance(self.packages[0], list):
            return self.packages.pop(0)
        return self.packages

    def install_application_package(self, environment_id, unique_name):
        self.install_calls.append((environment_id, unique_name))
        return self.install_result


@patch("install_ess_agent.discover_tenant", return_value="tenant-123")
def test_install_reports_connection_permission_error(
    _mock_discover_tenant,
):
    import install_ess_agent

    pp_admin = FakePPAdminClient(
        "tenant-123",
        connections={"_error": "insufficient_permissions", "_status": 403},
    )
    powerplatform = FakePowerPlatformClient("tenant-123", packages=[])

    with pytest.raises(
        RuntimeError,
        match="cannot read connections",
    ):
        install_ess_agent.install_agent(
            "https://org.crm.dynamics.com",
            "da",
            "it",
            pp_admin_client_factory=lambda _tenant: pp_admin,
            powerplatform_client_factory=lambda _tenant: powerplatform,
        )

    assert not powerplatform.authenticated


@patch("install_ess_agent.discover_tenant", return_value="tenant-123")
def test_install_without_connection_requirement_skips_connection_api(
    _mock_discover_tenant,
):
    import install_ess_agent

    class NoConnectionAccessClient(FakePPAdminClient):
        def get_connections(self, _environment_id):
            pytest.fail("connection API should not be called")

    pp_admin = NoConnectionAccessClient("tenant-123")
    powerplatform = FakePowerPlatformClient(
        "tenant-123",
        packages=[{
            "uniqueName": "msdyn_CopilotForEmployeeSelfServiceCoreDA",
            "state": "Installed",
        }],
    )

    schema = install_ess_agent.install_agent(
        "https://org.crm.dynamics.com",
        "da",
        "hub",
        pp_admin_client_factory=lambda _tenant: pp_admin,
        powerplatform_client_factory=lambda _tenant: powerplatform,
    )

    assert schema == "msdyn_CopilotForEmployeeSelfServiceCoreDA"


@patch("install_ess_agent.discover_tenant", return_value="tenant-123")
def test_install_resolves_environment_and_polls_package_state(
    _mock_discover_tenant,
    capsys,
):
    import install_ess_agent

    pp_admin = FakePPAdminClient("tenant-123")
    powerplatform = FakePowerPlatformClient(
        "tenant-123",
        packages=[
            [{
                "uniqueName": "msdyn_CopilotForEmployeeSelfServiceDAIT",
                "state": "None",
            }],
            [{
                "uniqueName": "msdyn_CopilotForEmployeeSelfServiceDAIT",
                "state": "Installed",
            }],
        ],
        install_result={
            "lastOperation": {
                "state": "InstallRequested",
                "operationId": "operation-123",
            },
            "_operationId": "operation-123",
        },
    )
    states = []

    schema = install_ess_agent.install_agent(
        "https://org.crm.dynamics.com/",
        "da",
        "it",
        pp_admin_client_factory=lambda _tenant: pp_admin,
        powerplatform_client_factory=lambda _tenant: powerplatform,
        poll_interval_seconds=0,
        sleep=lambda _seconds: None,
        installation_state_callback=states.append,
    )

    assert schema == "msdyn_CopilotForEmployeeSelfServiceDAIT"
    assert pp_admin.authenticated
    assert pp_admin.include_flow is False
    assert powerplatform.authenticated
    assert powerplatform.install_calls == [
        ("env-123", "msdyn_CopilotForEmployeeSelfServiceDAIT")
    ]
    assert states == ["installing", "automatic-complete"]
    assert "Installation status (poll 1, 0s elapsed): Installed" in (
        capsys.readouterr().out
    )


@patch("install_ess_agent.discover_tenant", return_value="tenant-123")
def test_it_install_refuses_to_start_without_required_connection(
    _mock_discover_tenant,
):
    import install_ess_agent

    pp_admin = FakePPAdminClient("tenant-123", connections=[])
    powerplatform = FakePowerPlatformClient(
        "tenant-123",
        packages=[{
            "uniqueName": "msdyn_CopilotForEmployeeSelfServiceDAIT",
            "state": "None",
        }],
    )

    with pytest.raises(
        RuntimeError,
        match="requires an active Microsoft 365 Self-Help",
    ):
        install_ess_agent.install_agent(
            "https://org.crm.dynamics.com",
            "da",
            "it",
            pp_admin_client_factory=lambda _tenant: pp_admin,
            powerplatform_client_factory=lambda _tenant: powerplatform,
        )

    assert powerplatform.authenticated is False
    assert powerplatform.install_calls == []


def test_solution_catalog_uses_power_apps_connector_names():
    import install_ess_agent

    catalog = install_ess_agent.CATALOG_PATH.read_text(encoding="utf-8")

    assert "| Logical name | Connector |" not in catalog
    assert "| Child schema | Connector | Flow usage |" in catalog
    for friendly_name in (
        "Microsoft 365 Self-Help",
        "ServiceNow",
        "Microsoft Dataverse",
        "SAP OData",
        "Workday",
    ):
        assert f"Name: `{friendly_name}`" in catalog
    assert "Logical name: `new_sharedworkdaysoap_ff0df`" in catalog


def test_it_install_requires_selection_when_multiple_connections_exist():
    import install_ess_agent

    installation = install_ess_agent.load_installation_config()["installations"][
        "cea.it"
    ]
    connections = [
        {
            "name": name,
            "properties": {
                "apiId": "/providers/Microsoft.PowerApps/apis/shared_alchemy",
                "statuses": [{"status": "Connected"}],
            },
        }
        for name in ("alchemy-one", "alchemy-two")
    ]

    with pytest.raises(RuntimeError, match="Multiple connected instances"):
        install_ess_agent.validate_required_connection(
            installation,
            connections,
        )
    assert install_ess_agent.validate_required_connection(
        installation,
        connections,
        "alchemy-two",
    ) == "alchemy-two"


@patch("install_ess_agent.discover_tenant", return_value="tenant-123")
def test_install_skips_request_when_application_is_already_installed(
    _mock_discover_tenant,
):
    import install_ess_agent

    powerplatform = FakePowerPlatformClient(
        "tenant-123",
        packages=[{
            "uniqueName": "msdyn_CopilotForEmployeeSelfServiceHR",
            "state": "Installed",
        }],
    )

    schema = install_ess_agent.install_agent(
        "https://org.crm.dynamics.com",
        "cea",
        "hr",
        pp_admin_client_factory=FakePPAdminClient,
        powerplatform_client_factory=lambda _tenant: powerplatform,
    )

    assert schema == "msdyn_CopilotForEmployeeSelfServiceHR"
    assert powerplatform.install_calls == []


@patch("install_ess_agent.discover_tenant", return_value="tenant-123")
def test_install_polls_package_state_when_operation_id_is_absent(
    _mock_discover_tenant,
):
    import install_ess_agent

    schema_name = "msdyn_CopilotForEmployeeSelfServiceIT"
    powerplatform = FakePowerPlatformClient(
        "tenant-123",
        packages=[
            [{"uniqueName": schema_name, "state": "None"}],
            [{"uniqueName": schema_name, "state": "Installing"}],
            [{"uniqueName": schema_name, "state": "Installed"}],
        ],
        install_result={"_async": True, "_operationId": None},
    )

    schema = install_ess_agent.install_agent(
        "https://org.crm.dynamics.com",
        "cea",
        "it",
        pp_admin_client_factory=FakePPAdminClient,
        powerplatform_client_factory=lambda _tenant: powerplatform,
        poll_interval_seconds=0,
        sleep=lambda _seconds: None,
    )

    assert schema == schema_name


@patch("install_ess_agent.discover_tenant", return_value="tenant-123")
def test_install_reports_missing_marketplace_entitlement(
    _mock_discover_tenant,
):
    import install_ess_agent

    powerplatform = FakePowerPlatformClient("tenant-123", packages=[])

    with pytest.raises(RuntimeError, match="not available"):
        install_ess_agent.install_agent(
            "https://org.crm.dynamics.com",
            "da",
            "hr",
            pp_admin_client_factory=FakePPAdminClient,
            powerplatform_client_factory=lambda _tenant: powerplatform,
        )


@patch("install_ess_agent.discover_tenant", return_value="tenant-123")
def test_install_reports_application_install_permission_failure(
    _mock_discover_tenant,
):
    import install_ess_agent

    schema_name = "msdyn_CopilotForEmployeeSelfServiceDAHR"
    powerplatform = FakePowerPlatformClient(
        "tenant-123",
        packages=[{"uniqueName": schema_name, "state": "None"}],
        install_result={
            "_error": "insufficient_permissions",
            "_status": 403,
        },
    )

    with pytest.raises(RuntimeError, match="cannot install"):
        install_ess_agent.install_agent(
            "https://org.crm.dynamics.com",
            "da",
            "hr",
            pp_admin_client_factory=FakePPAdminClient,
            powerplatform_client_factory=lambda _tenant: powerplatform,
        )


@patch("install_ess_agent.discover_tenant", return_value="tenant-123")
def test_install_times_out_after_ten_minutes_and_reports_last_status(
    _mock_discover_tenant,
):
    import install_ess_agent

    schema_name = "msdyn_CopilotForEmployeeSelfServiceDAHR"
    powerplatform = FakePowerPlatformClient(
        "tenant-123",
        packages=[
            [{"uniqueName": schema_name, "state": "None"}],
            [{"uniqueName": schema_name, "state": "Installing"}],
            [{"uniqueName": schema_name, "state": "Installing"}],
        ],
        install_result={"_operationId": "operation-123"},
    )
    now = [0]
    messages = []

    def sleep(seconds):
        now[0] += seconds

    with pytest.raises(
        install_ess_agent.InstallationTimeoutError,
        match="10 minutes",
    ):
        install_ess_agent.install_agent(
            "https://org.crm.dynamics.com",
            "da",
            "hr",
            pp_admin_client_factory=FakePPAdminClient,
            powerplatform_client_factory=lambda _tenant: powerplatform,
            poll_interval_seconds=300,
            sleep=sleep,
            clock=lambda: now[0],
            status_callback=messages.append,
        )

    assert messages == [
        "Installation status (poll 1, 0s elapsed): Installing",
        "Installation status (poll 2, 300s elapsed): Installing",
    ]
