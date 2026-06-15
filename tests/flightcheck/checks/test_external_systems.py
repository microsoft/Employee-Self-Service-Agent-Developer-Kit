# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Integration tests for external-system discovery (EXT-001, WD-001,
SN-001, SAP-001) in ``flightcheck.checks.external_systems``.

Pattern mirrors ``test_servicenow_connections.py``: mock the Power
Automate admin flow-listing endpoint with ``responses`` via the
validated ``pp_admin`` builders, instantiate a real ``PPAdminClient``
with a pre-populated token, run ``run_external_systems_checks``, and
assert on the resulting CheckResults.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import responses

from tests.conftest import require_validated_mock
from tests.mocks import pp_admin as pp

require_validated_mock(pp)


@dataclass
class _MinimalRunner:
    pp_admin: Any
    env_id: str


@pytest.fixture
def pp_client(fake_token: str):
    from flightcheck.pp_admin_client import PPAdminClient
    client = PPAdminClient(tenant_id="00000000-0000-0000-0000-000000001111")
    client._token = fake_token
    client._flow_token = fake_token  # flow listing uses a separate token
    return client


@pytest.fixture
def runner(pp_client) -> _MinimalRunner:
    return _MinimalRunner(pp_admin=pp_client, env_id=pp.MOCK_ENV_ID)


def _by_id(results, cid):
    matches = [r for r in results if r.checkpoint_id == cid]
    assert len(matches) == 1, [r.checkpoint_id for r in results]
    return matches[0]


@responses.activate
def test_all_three_solutions_detected(runner):
    from flightcheck.checks.external_systems import run_external_systems_checks
    responses.add(**pp.list_flows(env_id=runner.env_id, flows=[
        pp.flow(display_name="Workday Get Worker", env_id=runner.env_id),
        pp.flow(display_name="ServiceNow HRSD Case Lookup", env_id=runner.env_id),
        pp.flow(display_name="SAP SuccessFactors Time Off", env_id=runner.env_id),
    ]))

    results = run_external_systems_checks(runner)

    wd = _by_id(results, "WD-001")
    assert wd.status == "Passed"
    assert "1 Workday flow(s)" in wd.result

    sn = _by_id(results, "SN-001")
    assert sn.status == "Passed"
    assert "1 ServiceNow flow(s)" in sn.result
    assert "1 HRSD" in sn.result  # categorization surfaced

    sap = _by_id(results, "SAP-001")
    assert sap.status == "Passed"
    assert "1 SAP flow(s)" in sap.result


@responses.activate
def test_none_detected_reports_not_configured(runner):
    from flightcheck.checks.external_systems import run_external_systems_checks
    responses.add(**pp.list_flows(env_id=runner.env_id, flows=[
        pp.flow(display_name="Some Unrelated Flow", env_id=runner.env_id),
    ]))

    results = run_external_systems_checks(runner)

    for cid, system in (("WD-001", "Workday"), ("SN-001", "ServiceNow"),
                        ("SAP-001", "SAP SuccessFactors")):
        r = _by_id(results, cid)
        assert r.status == "NotConfigured"
        assert "No" in r.result
        assert "extension pack" in r.remediation


@responses.activate
def test_ext001_warns_when_flow_listing_fails(runner):
    from flightcheck.checks.external_systems import run_external_systems_checks

    class _RaisingPP:
        def get_flows(self, env_id):
            raise RuntimeError("flow API unavailable")

    runner.pp_admin = _RaisingPP()
    results = run_external_systems_checks(runner)

    ext = _by_id(results, "EXT-001")
    assert ext.status == "Warning"
    assert "Unable to list flows" in ext.result
    assert "flow API unavailable" in ext.result


def test_skips_when_no_env_id():
    from flightcheck.checks.external_systems import run_external_systems_checks
    assert run_external_systems_checks(_MinimalRunner(pp_admin=None, env_id=None)) == []
