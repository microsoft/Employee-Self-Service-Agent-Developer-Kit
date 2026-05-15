# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end integration tests for the Workday connection FlightCheck
check (WD-CONN-001 + per-connection WD-CONN-{N}).

Mocks the Power Platform Admin (PowerApps) connections endpoint with
`responses`, instantiates a real PPAdminClient with a pre-populated
token, runs the actual production check function from
solutions/ess-maker-skills/scripts/flightcheck/checks/workday.py against
the mocked state, and asserts on the resulting CheckResult list.

Same pattern as test_workday_env_vars.py; consult that file for the
template.
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
    """A real PPAdminClient with a pre-populated token, ready to be
    driven through `responses` mocks. We bypass authenticate() (which
    would launch interactive MSAL) by setting the private _token field
    directly — this is the standard test pattern for production code
    that mixes auth and HTTP into one class."""
    from flightcheck.pp_admin_client import PPAdminClient

    client = PPAdminClient(tenant_id="00000000-0000-0000-0000-000000001111")
    client._token = fake_token
    return client


@pytest.fixture
def runner(pp_client) -> _MinimalRunner:
    return _MinimalRunner(pp_admin=pp_client, env_id=pp.MOCK_ENV_ID)


def _result_by_id(results: list, checkpoint_id: str):
    matches = [r for r in results if r.checkpoint_id == checkpoint_id]
    assert len(matches) == 1, (
        f"Expected exactly one result for {checkpoint_id}, got {len(matches)}: "
        f"{[r.checkpoint_id for r in results]}"
    )
    return matches[0]


# ───────────────────────────────────────────────────────────────────────


class TestGoodConfig:
    @responses.activate
    def test_single_connected_workday_connection_passes(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_connections

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[pp.workday_connection(status="Connected")],
        ))

        results = _check_connections(runner)

        wd_001 = _result_by_id(results, "WD-CONN-001")
        assert wd_001.status == "Passed"
        assert "1 total" in wd_001.result
        assert "1 connected" in wd_001.result
        assert "0 errored" in wd_001.result
        # Per-connection detail
        wd_002 = _result_by_id(results, "WD-CONN-002")
        assert wd_002.status == "Passed"
        assert "Connected" in wd_002.result

    @responses.activate
    def test_multiple_connected_workday_connections_pass(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_connections

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(status="Connected", display_name="Workday SOAP — ISU"),
                pp.workday_connection(status="Connected", display_name="Workday SOAP — User"),
                pp.workday_connection(status="Connected", display_name="Workday OAuth"),
            ],
        ))

        results = _check_connections(runner)
        wd_001 = _result_by_id(results, "WD-CONN-001")
        assert wd_001.status == "Passed"
        assert "3 total" in wd_001.result
        assert "3 connected" in wd_001.result
        # Three per-connection detail entries (WD-CONN-002, 003, 004)
        for cid in ("WD-CONN-002", "WD-CONN-003", "WD-CONN-004"):
            assert _result_by_id(results, cid).status == "Passed"

    @responses.activate
    def test_non_workday_connections_are_filtered_out(
        self, runner: _MinimalRunner
    ) -> None:
        """An environment with O365/SharePoint/Dataverse but no Workday
        should be reported as NOT_CONFIGURED, not as "all healthy" just
        because the non-Workday connections are connected."""
        from flightcheck.checks.workday import _check_connections

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.non_workday_connection(display_name="Office 365"),
                pp.non_workday_connection(display_name="Dataverse"),
            ],
        ))

        results = _check_connections(runner)
        wd_001 = _result_by_id(results, "WD-CONN-001")
        assert wd_001.status == "NotConfigured"
        assert "No Workday connections" in wd_001.result
        assert "/connect" not in wd_001.remediation.lower()  # this isn't a /connect prompt path
        assert "configure" in wd_001.remediation.lower()


class TestBadConfig:
    @responses.activate
    def test_all_workday_connections_errored_returns_failed(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_connections

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(status="Error", display_name="Workday SOAP — ISU"),
                pp.workday_connection(status="Error", display_name="Workday OAuth"),
            ],
        ))

        results = _check_connections(runner)
        wd_001 = _result_by_id(results, "WD-CONN-001")

        assert wd_001.status == "Failed", (
            f"Expected WD-CONN-001 to FAIL when all Workday connections are "
            f"errored, got status={wd_001.status} result={wd_001.result!r}"
        )
        assert wd_001.priority == "High"
        assert "0 connected" in wd_001.result
        assert "2 errored" in wd_001.result
        assert "Re-authenticate" in wd_001.remediation
        # Both per-connection details should fail with re-auth remediation
        for cid in ("WD-CONN-002", "WD-CONN-003"):
            r = _result_by_id(results, cid)
            assert r.status == "Failed"
            assert "Re-authenticate" in r.remediation

    @responses.activate
    def test_no_workday_connections_returns_not_configured(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_connections

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[],
        ))

        results = _check_connections(runner)
        wd_001 = _result_by_id(results, "WD-CONN-001")
        assert wd_001.status == "NotConfigured"
        assert "No Workday connections" in wd_001.result
        assert "configure" in wd_001.remediation.lower()


class TestMixedState:
    @responses.activate
    def test_one_connected_one_errored_passes_overall_but_flags_errored(
        self, runner: _MinimalRunner
    ) -> None:
        """One healthy + one broken — WD-CONN-001 PASSES (because there's
        at least one working connection) but the per-connection detail
        for the broken one FAILS with re-auth remediation. This is the
        most operationally important scenario: things mostly work but
        one customer-facing flow is silently broken."""
        from flightcheck.checks.workday import _check_connections

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(status="Connected", display_name="Workday SOAP — ISU"),
                pp.workday_connection(status="Error", display_name="Workday OAuth"),
            ],
        ))

        results = _check_connections(runner)

        wd_001 = _result_by_id(results, "WD-CONN-001")
        assert wd_001.status == "Passed"
        assert "1 connected" in wd_001.result
        assert "1 errored" in wd_001.result
        assert "Re-authenticate" in wd_001.remediation

        # First connection (Connected) should be PASSED
        wd_002 = _result_by_id(results, "WD-CONN-002")
        assert wd_002.status == "Passed"
        # Second connection (Error) should be FAILED with re-auth remediation
        wd_003 = _result_by_id(results, "WD-CONN-003")
        assert wd_003.status == "Failed"
        assert "Re-authenticate 'Workday OAuth'" in wd_003.remediation


class TestEdgeCases:
    @responses.activate
    def test_403_from_bap_is_misreported_as_not_configured(
        self, runner: _MinimalRunner
    ) -> None:
        """Regression: latent bug. PPAdminClient._get_all returns an
        empty list on 401/403, but PPAdminClient._get (single-item
        getter) returns {"_error": "..."} dict. The check expects the
        dict shape from get_connections() and only reports WARNING when
        it sees one — but get_connections() uses _get_all, so a 403
        silently looks identical to "no Workday connections" and the
        operator is told to configure connections rather than told
        their account lacks PP Admin role.

        Severity: medium. The check still surfaces a non-PASS result so
        the operator knows something is off, but the remediation
        message points at the wrong action.

        TODO (production fix, choose one):
          (a) Make _get_all also return {"_error": "...", "_status": ...}
              dict on 401/403 (mirrors _get), and update _check_connections
              to handle that shape from get_connections.
          (b) Make _get_all raise a typed exception on 401/403 and let
              callers decide whether to swallow it.

        See solutions/ess-maker-skills/scripts/flightcheck/pp_admin_client.py:131-144.
        Flip this test to expect WARNING when fixed.
        """
        from flightcheck.checks.workday import _check_connections

        responses.add(**pp.insufficient_permissions(env_id=runner.env_id))

        results = _check_connections(runner)
        wd_001 = _result_by_id(results, "WD-CONN-001")
        # Buggy behavior: 403 is indistinguishable from empty list.
        assert wd_001.status == "NotConfigured", (
            "PPAdminClient was fixed to surface 403 as a structured error — "
            "flip this test to assert WARNING + 'Power Platform Admin' "
            "in the remediation."
        )
        assert "No Workday connections" in wd_001.result
        # Once fixed, this assertion should change to:
        #   assert wd_001.status == "Warning"
        #   assert "Power Platform Admin" in wd_001.remediation

    def test_skips_when_env_id_missing(self, pp_client) -> None:
        """No env_id (e.g. derive_environment_id failed) — check returns
        an empty list rather than crashing or making a request."""
        from flightcheck.checks.workday import _check_connections

        runner_no_env = _MinimalRunner(pp_admin=pp_client, env_id="")
        results = _check_connections(runner_no_env)
        assert results == []

    @responses.activate
    def test_pending_confirmation_status_treated_as_errored(
        self, runner: _MinimalRunner
    ) -> None:
        """PendingConfirmation isn't 'Connected' — should count as errored.
        Pins the current behavior that any non-'Connected' status fails;
        update if the production code grows finer-grained handling."""
        from flightcheck.checks.workday import _check_connections

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(status="PendingConfirmation"),
            ],
        ))

        results = _check_connections(runner)
        wd_001 = _result_by_id(results, "WD-CONN-001")
        assert wd_001.status == "Failed"
        assert "0 connected" in wd_001.result
        assert "1 errored" in wd_001.result
