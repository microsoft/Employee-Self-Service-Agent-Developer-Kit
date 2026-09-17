# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the DA Workday extension package installer.

Mirrors the mocking pattern in ``tests/scripts/test_install_ess_agent.py``:
fake ``PPAdminClient``/``PowerPlatformClient`` factories stand in for the
real Power Platform REST APIs, and ``discover_tenant`` is patched so no
network call is made.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


class FakePPAdminClient:
    def __init__(self, tenant_id, environment_id="env-123"):
        self.tenant_id = tenant_id
        self.environment_id = environment_id
        self.authenticated = False

    def authenticate(self, *, include_flow=True):
        self.authenticated = True
        self.include_flow = include_flow

    def find_environment_id_by_dataverse_url(self, _env_url):
        return self.environment_id


class FakePowerPlatformClient:
    def __init__(self, tenant_id, *, packages, install_result=None):
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


@patch("install_workday_da_extension.discover_tenant", return_value="tenant-123")
def test_not_listed_when_marketplace_catalog_has_no_match(_mock_discover_tenant):
    import install_workday_da_extension as m

    powerplatform = FakePowerPlatformClient("tenant-123", packages=[])

    with pytest.raises(m.ExtensionNotListedError, match="msdyn_essdahrworkday"):
        m.install_workday_da_extension(
            "https://org.crm.dynamics.com",
            "hr",
            pp_admin_client_factory=FakePPAdminClient,
            powerplatform_client_factory=lambda _tenant: powerplatform,
        )

    # Never attempts an install call against a package that isn't listed.
    assert powerplatform.install_calls == []


@patch("install_workday_da_extension.discover_tenant", return_value="tenant-123")
def test_skips_install_when_hr_extension_already_installed(_mock_discover_tenant):
    import install_workday_da_extension as m

    powerplatform = FakePowerPlatformClient(
        "tenant-123",
        packages=[{"uniqueName": "msdyn_essdahrworkday", "state": "Installed"}],
    )

    schema = m.install_workday_da_extension(
        "https://org.crm.dynamics.com",
        "hr",
        pp_admin_client_factory=FakePPAdminClient,
        powerplatform_client_factory=lambda _tenant: powerplatform,
    )

    assert schema == "msdyn_essdahrworkday"
    assert powerplatform.install_calls == []


@patch("install_workday_da_extension.discover_tenant", return_value="tenant-123")
def test_installs_and_polls_until_installed(_mock_discover_tenant):
    import install_workday_da_extension as m

    schema_name = "msdyn_essdahrworkday"
    powerplatform = FakePowerPlatformClient(
        "tenant-123",
        packages=[
            [{"uniqueName": schema_name, "state": "None"}],
            [{"uniqueName": schema_name, "state": "Installing"}],
            [{"uniqueName": schema_name, "state": "Installed"}],
        ],
        install_result={"_operationId": "operation-123"},
    )

    schema = m.install_workday_da_extension(
        "https://org.crm.dynamics.com",
        "hr",
        pp_admin_client_factory=FakePPAdminClient,
        powerplatform_client_factory=lambda _tenant: powerplatform,
        poll_interval_seconds=0,
        sleep=lambda _seconds: None,
    )

    assert schema == schema_name
    assert powerplatform.install_calls == [("env-123", schema_name)]


@patch("install_workday_da_extension.discover_tenant", return_value="tenant-123")
def test_times_out_and_reports_last_status(_mock_discover_tenant):
    import install_workday_da_extension as m

    schema_name = "msdyn_essdahrworkday"
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

    def sleep(seconds):
        now[0] += seconds

    with pytest.raises(m.InstallationTimeoutError, match="10 minutes"):
        m.install_workday_da_extension(
            "https://org.crm.dynamics.com",
            "hr",
            pp_admin_client_factory=FakePPAdminClient,
            powerplatform_client_factory=lambda _tenant: powerplatform,
            poll_interval_seconds=300,
            sleep=sleep,
            clock=lambda: now[0],
        )


@patch("install_workday_da_extension.discover_tenant", return_value="tenant-123")
def test_rejects_unsupported_it_vertical(_mock_discover_tenant):
    import install_workday_da_extension as m

    with pytest.raises(ValueError, match="ESS DA IT Agent is not supported"):
        m.install_workday_da_extension(
            "https://org.crm.dynamics.com",
            "it",
            pp_admin_client_factory=FakePPAdminClient,
            powerplatform_client_factory=lambda _tenant: FakePowerPlatformClient(
                "tenant-123", packages=[]
            ),
        )


@patch("install_workday_da_extension.discover_tenant", return_value="tenant-123")
def test_reports_install_permission_failure(_mock_discover_tenant):
    import install_workday_da_extension as m

    schema_name = "msdyn_essdahrworkday"
    powerplatform = FakePowerPlatformClient(
        "tenant-123",
        packages=[{"uniqueName": schema_name, "state": "None"}],
        install_result={"_error": "insufficient_permissions", "_status": 403},
    )

    with pytest.raises(RuntimeError, match="cannot install"):
        m.install_workday_da_extension(
            "https://org.crm.dynamics.com",
            "hr",
            pp_admin_client_factory=FakePPAdminClient,
            powerplatform_client_factory=lambda _tenant: powerplatform,
        )
