# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end integration tests for the Workday connection token-health
FlightCheck check (WD-CONN-101).

WD-CONN-101 inspects the structured ``statuses[0].error.{code,message}``
block on each Workday connection record returned by the PowerApps
connections API and surfaces a failure with a remediation pinned to
the specific Entra error code (AADSTS50173 grant-expired,
AADSTS70008 refresh-token-expired-due-to-inactivity, etc.).

Same mock surface as ``test_workday_connections.py`` (the ``pp_admin``
mock module is ``MOCK_STATUS = "validated"``, cassette
``tests/fixtures/cassettes/flightcheck_pp_admin.yaml``); same
endpoint as WD-CONN-001, no new cassette required.
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
    driven through `responses` mocks. Same pattern as
    test_workday_connections.py."""
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
    def test_all_connections_connected_passes(self, runner: _MinimalRunner) -> None:
        from flightcheck.checks.workday import _check_connection_token_health

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(status="Connected", display_name="Workday SOAP — ISU"),
                pp.workday_connection(status="Connected", display_name="Workday SOAP — User"),
            ],
        ))

        results = _check_connection_token_health(runner)
        wd_101 = _result_by_id(results, "WD-CONN-101")
        assert wd_101.status == "Passed"
        assert wd_101.priority == "High"
        assert "All 2 Workday connection(s)" in wd_101.result
        assert "healthy" in wd_101.result.lower()
        assert wd_101.remediation == ""


class TestBadConfig:
    @responses.activate
    def test_aadsts50173_grant_expired_fails_with_pinned_remediation(
        self, runner: _MinimalRunner
    ) -> None:
        """The canonical scenario from the cassette: AADSTS50173, grant
        expired/revoked. WD-CONN-101 should FAIL, name the connection,
        name the connection owner, and quote the AADSTS code in both
        the result and the remediation."""
        from flightcheck.checks.workday import _check_connection_token_health

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(
                    status="Error",
                    display_name="Workday SOAP — ISU",
                    error_code="AADSTS50173",
                    error_message=(
                        "Failed to refresh access token. AADSTS50173: The "
                        "provided grant has expired due to it being revoked."
                    ),
                    account_name="isu.admin@contoso.com",
                ),
            ],
        ))

        results = _check_connection_token_health(runner)
        wd_101 = _result_by_id(results, "WD-CONN-101")
        assert wd_101.status == "Failed"
        assert wd_101.priority == "High"
        assert "1 of 1" in wd_101.result
        assert "AADSTS50173" in wd_101.result
        assert "Workday SOAP — ISU" in wd_101.result
        assert "isu.admin@contoso.com" in wd_101.result
        # Remediation pins the specific AADSTS hint, not a generic message.
        assert "AADSTS" not in wd_101.remediation  # hint is text, not the code
        assert "grant expired" in wd_101.remediation.lower()
        assert "Re-authenticate" in wd_101.remediation
        assert "isu.admin@contoso.com" in wd_101.remediation

    @responses.activate
    def test_aadsts70008_refresh_token_expired_picks_inactivity_hint(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_connection_token_health

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(
                    status="Error",
                    display_name="Workday SOAP — User",
                    error_code="AADSTS70008",
                    error_message="The refresh token has expired due to inactivity.",
                    account_name="svc.workday@contoso.com",
                ),
            ],
        ))

        results = _check_connection_token_health(runner)
        wd_101 = _result_by_id(results, "WD-CONN-101")
        assert wd_101.status == "Failed"
        assert "AADSTS70008" in wd_101.result
        assert "inactivity" in wd_101.remediation.lower()
        assert "svc.workday@contoso.com" in wd_101.remediation

    @responses.activate
    def test_unrecognized_error_code_falls_back_to_generic_hint(
        self, runner: _MinimalRunner
    ) -> None:
        """If Power Platform surfaces an error code not in our known
        AADSTS mapping, WD-CONN-101 still fails, surfaces the code
        verbatim, and tells the operator to re-authenticate."""
        from flightcheck.checks.workday import _check_connection_token_health

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(
                    status="Error",
                    display_name="Workday SOAP — Misc",
                    error_code="AADSTS99999",
                    error_message="Some new auth failure mode we have not seen.",
                ),
            ],
        ))

        results = _check_connection_token_health(runner)
        wd_101 = _result_by_id(results, "WD-CONN-101")
        assert wd_101.status == "Failed"
        assert "AADSTS99999" in wd_101.result
        assert "unrecognized token-health error" in wd_101.remediation.lower()
        assert "Re-authenticate" in wd_101.remediation


class TestMixedState:
    @responses.activate
    def test_one_healthy_one_expired_fails_with_only_expired_in_remediation(
        self, runner: _MinimalRunner
    ) -> None:
        """A healthy + an expired connection: WD-CONN-101 reports
        FAILED ("1 of 2 unhealthy") and the remediation text only
        mentions the failing one. The healthy connection must NOT
        appear in the remediation (otherwise an operator might
        re-authenticate the wrong account)."""
        from flightcheck.checks.workday import _check_connection_token_health

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(
                    status="Connected",
                    display_name="Workday SOAP — Healthy",
                    account_name="healthy.user@contoso.com",
                ),
                pp.workday_connection(
                    status="Error",
                    display_name="Workday SOAP — Broken",
                    error_code="AADSTS50173",
                    account_name="broken.user@contoso.com",
                ),
            ],
        ))

        results = _check_connection_token_health(runner)
        wd_101 = _result_by_id(results, "WD-CONN-101")
        assert wd_101.status == "Failed"
        assert "1 of 2" in wd_101.result
        assert "Workday SOAP — Broken" in wd_101.result
        assert "broken.user@contoso.com" in wd_101.result
        assert "Workday SOAP — Healthy" not in wd_101.result
        assert "healthy.user@contoso.com" not in wd_101.remediation
        assert "broken.user@contoso.com" in wd_101.remediation


class TestEdgeCases:
    @responses.activate
    def test_no_workday_connections_returns_not_configured(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_connection_token_health

        responses.add(**pp.list_connections(env_id=runner.env_id, connections=[]))

        results = _check_connection_token_health(runner)
        wd_101 = _result_by_id(results, "WD-CONN-101")
        assert wd_101.status == "NotConfigured"
        assert "No Workday connections" in wd_101.result
        assert "configure" in wd_101.remediation.lower()

    @responses.activate
    def test_non_workday_connections_filtered_out(
        self, runner: _MinimalRunner
    ) -> None:
        """A broken Office365 connection must NOT trip WD-CONN-101;
        the filter limits the check to Workday connections only."""
        from flightcheck.checks.workday import _check_connection_token_health

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.non_workday_connection(display_name="Office 365", status="Error"),
            ],
        ))

        results = _check_connection_token_health(runner)
        wd_101 = _result_by_id(results, "WD-CONN-101")
        assert wd_101.status == "NotConfigured"

    @responses.activate
    def test_403_from_bap_returns_warning(self, runner: _MinimalRunner) -> None:
        """403 from BAP — the operator's account lacks PP Admin role.
        Per the existing pattern in WD-CONN-001 this surfaces as a
        WARNING, not a misleading NotConfigured. Note: WD-CONN-001
        currently mis-reports this scenario (latent bug pinned in
        test_workday_connections.py::test_403_from_bap_is_misreported_as_not_configured);
        WD-CONN-101 sits behind the same client method so it shares
        the same buggy "looks like empty list" behavior. Pin the
        current behavior here so a fix to PPAdminClient._get_all
        will surface this test for an update at the same time."""
        from flightcheck.checks.workday import _check_connection_token_health

        responses.add(**pp.insufficient_permissions(env_id=runner.env_id))

        results = _check_connection_token_health(runner)
        wd_101 = _result_by_id(results, "WD-CONN-101")
        # Current buggy behavior — same root cause as WD-CONN-001's pin.
        # When PPAdminClient._get_all is fixed to surface 401/403 as a
        # structured error dict (see test_workday_connections.py edge
        # test for the recommended fix), flip this assertion to:
        #   assert wd_101.status == "Warning"
        #   assert "Power Platform" in wd_101.remediation
        assert wd_101.status == "NotConfigured"

    def test_skips_when_env_id_missing(self, pp_client) -> None:
        """No env_id → empty list (no result), don't crash, don't make
        a request."""
        from flightcheck.checks.workday import _check_connection_token_health

        runner_no_env = _MinimalRunner(pp_admin=pp_client, env_id="")
        results = _check_connection_token_health(runner_no_env)
        assert results == []

    def test_skips_when_pp_admin_missing(self) -> None:
        """No pp_admin client (auth failed earlier) → empty list, no
        crash. Defensive: WD-CONN-001 today crashes in this case
        (calls pp.get_connections() unconditionally); WD-CONN-101 is
        new code so we add the guard here."""
        from flightcheck.checks.workday import _check_connection_token_health

        runner_no_pp = _MinimalRunner(pp_admin=None, env_id=pp.MOCK_ENV_ID)
        results = _check_connection_token_health(runner_no_pp)
        assert results == []
