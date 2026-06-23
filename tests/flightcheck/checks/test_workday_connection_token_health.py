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
        assert wd_101.remediation.startswith("Validated:")
        assert "healthy" in wd_101.remediation.lower()


class TestBadConfig:
    @responses.activate
    def test_aadsts50173_grant_expired_fails_with_pinned_remediation(
        self, runner: _MinimalRunner
    ) -> None:
        """The canonical scenario from the cassette: connection in
        Error state with ``error.code = "Unauthorized"`` and the
        AADSTS code embedded in the longer ``error.message`` prose
        (this is the exact shape captured in
        ``tests/fixtures/cassettes/flightcheck_pp_admin.yaml`` lines
        2661-2680). WD-CONN-101 should FAIL, name the connection,
        name the connection owner, extract the AADSTS50173 code from
        the message, and surface the grant-expired hint — NOT the
        generic Unauthorized hint."""
        from flightcheck.checks.workday import _check_connection_token_health

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(
                    status="Error",
                    display_name="Workday SOAP — ISU",
                    # Production shape: code is "Unauthorized" (coarse
                    # PP classification), AADSTS code lives in message.
                    error_code="Unauthorized",
                    error_message=(
                        "Failed to refresh access token for service: "
                        "aadcertificate. Error: Failed to acquire token "
                        "from AAD: AADSTS50173: The provided grant has "
                        "expired due to it being revoked."
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
        # Result quotes the *AADSTS* code, not the generic "Unauthorized"
        # — extracted from message rather than blindly read from code.
        assert "AADSTS50173" in wd_101.result
        assert "Workday SOAP — ISU" in wd_101.result
        assert "isu.admin@contoso.com" in wd_101.result
        # Remediation pins the AADSTS-specific hint, not the generic
        # "Unauthorized" hint that the coarse code would map to.
        assert "grant expired" in wd_101.remediation.lower()
        assert "Re-authenticate" in wd_101.remediation
        assert "isu.admin@contoso.com" in wd_101.remediation

    @responses.activate
    def test_aadsts70008_refresh_token_expired_picks_inactivity_hint(
        self, runner: _MinimalRunner
    ) -> None:
        """Same realistic shape (code=Unauthorized, AADSTS in message),
        but a different AADSTS code maps to a different hint."""
        from flightcheck.checks.workday import _check_connection_token_health

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(
                    status="Error",
                    display_name="Workday SOAP — User",
                    error_code="Unauthorized",
                    error_message=(
                        "Failed to acquire token: AADSTS70008: The "
                        "refresh token has expired due to inactivity."
                    ),
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
    def test_unauthenticated_connection_falls_back_to_code_field(
        self, runner: _MinimalRunner
    ) -> None:
        """The cassette also captures connections that were never
        authenticated — ``code = "Unauthenticated"``, ``message =
        "This connection is not authenticated."``. There is NO AADSTS
        code in the message, so WD-CONN-101 should fall back to
        looking up the ``code`` field and pick the
        ``Unauthenticated`` hint (sign-in needed)."""
        from flightcheck.checks.workday import _check_connection_token_health

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(
                    status="Error",
                    display_name="Workday SOAP — Never Auth'd",
                    error_code="Unauthenticated",
                    error_message="This connection is not authenticated.",
                    account_name="newuser@contoso.com",
                ),
            ],
        ))

        results = _check_connection_token_health(runner)
        wd_101 = _result_by_id(results, "WD-CONN-101")
        assert wd_101.status == "Failed"
        assert "Unauthenticated" in wd_101.result
        assert "not authenticated" in wd_101.remediation.lower()
        assert "newuser@contoso.com" in wd_101.remediation

    @responses.activate
    def test_unrecognized_aadsts_code_in_message_falls_back_to_generic_hint(
        self, runner: _MinimalRunner
    ) -> None:
        """If Power Platform surfaces an AADSTS code we don't have in
        our mapping, WD-CONN-101 still fails, surfaces the code
        verbatim from the message, and gives a generic re-auth hint."""
        from flightcheck.checks.workday import _check_connection_token_health

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(
                    status="Error",
                    display_name="Workday SOAP — Misc",
                    error_code="Unauthorized",
                    error_message=(
                        "Failed: AADSTS99999: Some new auth failure mode "
                        "we have not seen before."
                    ),
                ),
            ],
        ))

        results = _check_connection_token_health(runner)
        wd_101 = _result_by_id(results, "WD-CONN-101")
        assert wd_101.status == "Failed"
        # Extracted from message, not the code field.
        assert "AADSTS99999" in wd_101.result
        assert "unrecognized aadsts" in wd_101.remediation.lower()
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
                    error_code="Unauthorized",
                    error_message=(
                        "Failed to refresh access token: AADSTS50173: "
                        "The provided grant has expired."
                    ),
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
        Now that ``PPAdminClient._get_all`` surfaces 401/403 as a
        structured error dict, WD-CONN-101 reports a WARNING naming the
        missing role instead of a misleading NotConfigured."""
        from flightcheck.checks.workday import _check_connection_token_health

        responses.add(**pp.insufficient_permissions(env_id=runner.env_id))

        results = _check_connection_token_health(runner)
        wd_101 = _result_by_id(results, "WD-CONN-101")
        assert wd_101.status == "Warning"
        assert "Power Platform Admin" in wd_101.remediation

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


# ───────────────────────────────────────────────────────────────────────
# Owner-fallback tests
#
# Admin-scope listings of connections owned by other users frequently
# return ``accountName: null``. WD-CONN-101 must fall through to
# ``createdBy.userPrincipalName`` / ``createdBy.displayName`` so the
# operator gets the most actionable owner identity available, instead
# of an unhelpful "(unknown owner)".
#
# Observed live on 2026-05-21 in env PROD - ESS + WD + SNow: 7 Workday
# connections with ``accountName: null`` but
# ``createdBy.userPrincipalName: lmoulet@EmployeeHub.onmicrosoft.com``.
# ───────────────────────────────────────────────────────────────────────


class TestOwnerFallback:
    @responses.activate
    def test_falls_back_to_created_by_upn_when_account_name_null(
        self, runner: _MinimalRunner
    ) -> None:
        """``accountName`` is empty but ``createdBy.userPrincipalName``
        is set → result shows the UPN, not "(unknown owner)"."""
        from flightcheck.checks.workday import _check_connection_token_health

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(
                    status="Error",
                    display_name="Workday",
                    error_code="Unauthorized",
                    error_message="Failed: AADSTS50173: grant expired.",
                    account_name="",  # admin-scope shape
                    created_by_upn="lmoulet@example.com",
                    created_by_display_name="Laurent Moulet",
                ),
            ],
        ))

        results = _check_connection_token_health(runner)
        wd_101 = _result_by_id(results, "WD-CONN-101")
        assert "lmoulet@example.com" in wd_101.result
        assert "lmoulet@example.com" in wd_101.remediation
        assert "(unknown owner)" not in wd_101.result

    @responses.activate
    def test_falls_back_to_created_by_display_name_when_upn_also_missing(
        self, runner: _MinimalRunner
    ) -> None:
        """Owner-fallback chain: accountName empty AND createdBy.UPN
        empty → use createdBy.displayName as the last actionable
        identity."""
        from flightcheck.checks.workday import _check_connection_token_health

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(
                    status="Error",
                    display_name="Workday",
                    error_code="Unauthorized",
                    error_message="Failed: AADSTS50173: grant expired.",
                    account_name="",
                    created_by_display_name="Service Principal — Workday Importer",
                ),
            ],
        ))

        results = _check_connection_token_health(runner)
        wd_101 = _result_by_id(results, "WD-CONN-101")
        assert "Service Principal — Workday Importer" in wd_101.result

    @responses.activate
    def test_unknown_owner_when_all_identity_fields_missing(
        self, runner: _MinimalRunner
    ) -> None:
        """All owner-identity fields missing → preserve the
        ``(unknown owner)`` literal so operators don't see a confusing
        bare colon."""
        from flightcheck.checks.workday import _check_connection_token_health

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(
                    status="Error",
                    display_name="Workday",
                    error_code="Unauthorized",
                    error_message="Failed: AADSTS50173: grant expired.",
                    account_name="",
                    # createdBy.* not overridden — default builder
                    # populates Mock User; clear with empty strings
                    created_by_upn="",
                    created_by_display_name="",
                ),
            ],
        ))

        results = _check_connection_token_health(runner)
        wd_101 = _result_by_id(results, "WD-CONN-101")
        assert "(unknown owner)" in wd_101.result


# ───────────────────────────────────────────────────────────────────────
# Severity tiering + in-use cross-reference tests
#
# WD-CONN-101 splits unhealthy connections into two buckets:
#   - FAILED: unhealthy AND referenced by a flow (will break runtime)
#   - WARNING: unhealthy AND not referenced by any flow (cleanup task)
#
# When flow enumeration is unavailable (no flow mock registered,
# get_flows raises, etc.) the check conservatively treats every
# unhealthy connection as in-use → FAILED. This preserves backward
# compatibility with the original tests above (which don't register
# a flows mock) and avoids silently demoting real flow-breakers.
# ───────────────────────────────────────────────────────────────────────


@pytest.fixture
def pp_client_with_flow_token(pp_client, fake_token: str):
    """A pp_client with both _token AND _flow_token set, so the
    in-use lookup (via pp.get_flows()) can be exercised by tests
    that register a flow mock. The two tokens live on different
    audiences in production — the test fixture reuses the same
    fake_token for both since the responses library doesn't
    validate the bearer value."""
    pp_client._flow_token = fake_token
    return pp_client


@pytest.fixture
def runner_with_flow_token(pp_client_with_flow_token) -> _MinimalRunner:
    return _MinimalRunner(
        pp_admin=pp_client_with_flow_token, env_id=pp.MOCK_ENV_ID
    )


class TestSeverityTiering:
    @responses.activate
    def test_config_needed_orphan_is_warning_not_failed(
        self, runner_with_flow_token: _MinimalRunner
    ) -> None:
        """ConfigurationNeeded + no flow uses the connection ⇒ WARNING
        (orphan cleanup), not FAILED. This is the 3-of-7 scenario
        observed live in PROD - ESS + WD + SNow on 2026-05-21."""
        from flightcheck.checks.workday import _check_connection_token_health

        responses.add(**pp.list_connections(
            env_id=runner_with_flow_token.env_id,
            connections=[
                pp.workday_connection(
                    status="Error",
                    display_name="Workday",
                    connection_name="shared-workdaysoap-orphan-001",
                    error_code="ConfigurationNeeded",
                    error_message="Parameter value missing.",
                    account_name="",
                    created_by_upn="lmoulet@example.com",
                ),
            ],
        ))
        # No flows reference this connection ⇒ orphan.
        responses.add(**pp.list_flows(
            env_id=runner_with_flow_token.env_id,
            flows=[],
        ))

        results = _check_connection_token_health(runner_with_flow_token)
        wd_101 = _result_by_id(results, "WD-CONN-101")
        assert wd_101.status == "Warning"
        assert "orphan" in wd_101.result.lower()
        assert "not referenced by any flow" in wd_101.result.lower()
        assert "ConfigurationNeeded" in wd_101.result

    @responses.activate
    def test_config_needed_in_use_is_failed_not_warning(
        self, runner_with_flow_token: _MinimalRunner
    ) -> None:
        """ConfigurationNeeded but a flow references the connection ⇒
        FAILED (the flow will break at runtime — operator must finish
        configuration)."""
        from flightcheck.checks.workday import _check_connection_token_health

        conn_name = "shared-workdaysoap-inuse-002"
        responses.add(**pp.list_connections(
            env_id=runner_with_flow_token.env_id,
            connections=[
                pp.workday_connection(
                    status="Error",
                    display_name="Workday",
                    connection_name=conn_name,
                    error_code="ConfigurationNeeded",
                    error_message="Parameter value missing.",
                ),
            ],
        ))
        responses.add(**pp.list_flows(
            env_id=runner_with_flow_token.env_id,
            flows=[
                pp.flow(
                    display_name="Get Worker — Workday",
                    connection_references={
                        "shared_workdaysoap_01": pp.workday_connection_reference(
                            connection_name=conn_name,
                        ),
                    },
                ),
            ],
        ))

        results = _check_connection_token_health(runner_with_flow_token)
        wd_101 = _result_by_id(results, "WD-CONN-101")
        assert wd_101.status == "Failed"
        assert "referenced by a flow" in wd_101.result.lower()
        assert "ConfigurationNeeded" in wd_101.result

    @responses.activate
    def test_auth_failure_with_no_flows_mock_remains_failed(
        self, runner: _MinimalRunner
    ) -> None:
        """No flows mock registered ⇒ in-use lookup returns None ⇒
        conservative "treat as in-use" ⇒ FAILED. This is the
        backwards-compat path for the original TestBadConfig tests."""
        from flightcheck.checks.workday import _check_connection_token_health

        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(
                    status="Error",
                    display_name="Workday",
                    error_code="Unauthorized",
                    error_message="Failed: AADSTS50173: grant expired.",
                ),
            ],
        ))

        results = _check_connection_token_health(runner)
        wd_101 = _result_by_id(results, "WD-CONN-101")
        assert wd_101.status == "Failed"

    @responses.activate
    def test_mixed_orphan_and_in_use_emits_two_results(
        self, runner_with_flow_token: _MinimalRunner
    ) -> None:
        """Mix of in-use AADSTS failure + orphan ConfigurationNeeded ⇒
        TWO WD-CONN-101 results: one FAILED for the in-use auth-broken
        one, one WARNING for the orphan unconfigured one."""
        from flightcheck.checks.workday import _check_connection_token_health

        in_use_name = "shared-workdaysoap-inuse-aaa"
        orphan_name = "shared-workdaysoap-orphan-bbb"
        responses.add(**pp.list_connections(
            env_id=runner_with_flow_token.env_id,
            connections=[
                pp.workday_connection(
                    status="Error",
                    display_name="Workday",
                    connection_name=in_use_name,
                    error_code="Unauthorized",
                    error_message="Failed: AADSTS50173: grant expired.",
                    account_name="active.owner@example.com",
                ),
                pp.workday_connection(
                    status="Error",
                    display_name="Workday",
                    connection_name=orphan_name,
                    error_code="ConfigurationNeeded",
                    error_message="Parameter value missing.",
                    account_name="",
                    created_by_upn="leftover.creator@example.com",
                ),
            ],
        ))
        responses.add(**pp.list_flows(
            env_id=runner_with_flow_token.env_id,
            flows=[
                pp.flow(
                    display_name="Active Workday Flow",
                    connection_references={
                        "shared_workdaysoap_01": pp.workday_connection_reference(
                            connection_name=in_use_name,
                        ),
                    },
                ),
            ],
        ))

        results = _check_connection_token_health(runner_with_flow_token)
        wd_101_results = [r for r in results if r.checkpoint_id == "WD-CONN-101"]
        assert len(wd_101_results) == 2, (
            f"Expected one FAILED + one WARNING, got: "
            f"{[(r.status, r.result[:60]) for r in wd_101_results]}"
        )
        statuses = {r.status for r in wd_101_results}
        assert statuses == {"Failed", "Warning"}

        failed = next(r for r in wd_101_results if r.status == "Failed")
        warning = next(r for r in wd_101_results if r.status == "Warning")
        # FAILED bucket has the in-use connection; WARNING has the orphan.
        assert "AADSTS50173" in failed.result
        assert "active.owner@example.com" in failed.result
        assert "ConfigurationNeeded" not in failed.result
        assert "ConfigurationNeeded" in warning.result
        assert "leftover.creator@example.com" in warning.result
        assert "AADSTS50173" not in warning.result


# ───────────────────────────────────────────────────────────────────────
# Remediation content tests
#
# The whole point of WD-CONN-101 is to give the operator a finding they
# can act on without leaving the FlightCheck output. These tests pin
# the actionable elements: connection id suffix, owner, creation date,
# deep link to the maker portal, and the pre-filled PowerShell
# Remove-AdminPowerAppConnection command for orphan cleanup.
# ───────────────────────────────────────────────────────────────────────


class TestRemediationContent:
    @responses.activate
    def test_orphan_remediation_contains_powershell_delete_command(
        self, runner_with_flow_token: _MinimalRunner
    ) -> None:
        """Orphan connections get a pre-filled Remove-AdminPowerAppConnection
        command with env id, connection name, and connector name."""
        from flightcheck.checks.workday import _check_connection_token_health

        conn_name = "shared-workdaysoap-de1e7e-01"
        responses.add(**pp.list_connections(
            env_id=runner_with_flow_token.env_id,
            connections=[
                pp.workday_connection(
                    status="Error",
                    display_name="Workday",
                    connection_name=conn_name,
                    error_code="ConfigurationNeeded",
                    error_message="Parameter value missing.",
                ),
            ],
        ))
        responses.add(**pp.list_flows(env_id=runner_with_flow_token.env_id, flows=[]))

        results = _check_connection_token_health(runner_with_flow_token)
        wd_101 = _result_by_id(results, "WD-CONN-101")
        assert wd_101.status == "Warning"
        assert "Remove-AdminPowerAppConnection" in wd_101.remediation
        assert f"-EnvironmentName {runner_with_flow_token.env_id}" in wd_101.remediation
        assert f"-ConnectionName {conn_name}" in wd_101.remediation
        assert "-ConnectorName shared_workdaysoap" in wd_101.remediation

    @responses.activate
    def test_in_use_auth_failed_remediation_contains_maker_url(
        self, runner_with_flow_token: _MinimalRunner
    ) -> None:
        """In-use auth-failed connections must include the maker portal
        URL where the owner can re-authenticate."""
        from flightcheck.checks.workday import _check_connection_token_health

        conn_name = "shared-workdaysoap-inuse-cc"
        responses.add(**pp.list_connections(
            env_id=runner_with_flow_token.env_id,
            connections=[
                pp.workday_connection(
                    status="Error",
                    display_name="Workday",
                    connection_name=conn_name,
                    error_code="Unauthorized",
                    error_message="Failed: AADSTS50173: grant expired.",
                    account_name="owner@example.com",
                ),
            ],
        ))
        responses.add(**pp.list_flows(
            env_id=runner_with_flow_token.env_id,
            flows=[
                pp.flow(
                    display_name="Workday Flow",
                    connection_references={
                        "ref": pp.workday_connection_reference(connection_name=conn_name),
                    },
                ),
            ],
        ))

        results = _check_connection_token_health(runner_with_flow_token)
        wd_101 = _result_by_id(results, "WD-CONN-101")
        assert wd_101.status == "Failed"
        maker_url = (
            f"https://make.powerautomate.com/environments/"
            f"{runner_with_flow_token.env_id}/connections"
        )
        assert maker_url in wd_101.remediation
        # Auth-failed in-use must NOT suggest the delete command — it's
        # in use, deleting would break the flow.
        assert "Remove-AdminPowerAppConnection" not in wd_101.remediation

    @responses.activate
    def test_result_includes_id_suffix_owner_and_date(
        self, runner_with_flow_token: _MinimalRunner
    ) -> None:
        """Every detail line must include the connection's short id
        suffix (so the operator can tell apart 3 connections all named
        "Workday"), the owner, and the creation date."""
        from flightcheck.checks.workday import _check_connection_token_health

        # Connection name embeds a recognizable 8-hex segment.
        conn_name = "shared-workdaysoap-deadbeef-2222-3333-4444-555555555555"
        responses.add(**pp.list_connections(
            env_id=runner_with_flow_token.env_id,
            connections=[
                pp.workday_connection(
                    status="Error",
                    display_name="Workday",
                    connection_name=conn_name,
                    error_code="ConfigurationNeeded",
                    error_message="Parameter value missing.",
                    account_name="",
                    created_by_upn="creator@example.com",
                    created_time="2026-02-17T06:08:43.0592278Z",
                ),
            ],
        ))
        responses.add(**pp.list_flows(env_id=runner_with_flow_token.env_id, flows=[]))

        results = _check_connection_token_health(runner_with_flow_token)
        wd_101 = _result_by_id(results, "WD-CONN-101")
        # Short id suffix from the connection name.
        assert "id=deadbeef" in wd_101.result
        # Owner fell through to createdBy.UPN.
        assert "owner=creator@example.com" in wd_101.result
        # Creation date in YYYY-MM-DD form (no time component).
        assert "created=2026-02-17" in wd_101.result
