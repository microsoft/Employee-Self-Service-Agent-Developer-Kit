# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end tests for the Authentication FlightCheck checks (AUTH-005).

Mocks the Microsoft Graph servicePrincipals + appRoleAssignedTo endpoints
with ``responses``, then runs the ACTUAL production check helper from
``solutions/ess-maker-skills/scripts/flightcheck/checks/authentication.py``
(``_check_workday_app_user_assignment``) against the mocked tenant state.

AUTH-005 traces to issue
microsoft/Employee-Self-Service-Agent-Developer-Kit#79: a Sev 2 deployment
failure where the customer's Workday Enterprise App had
``appRoleAssignmentRequired`` set without an ESS user/group assigned, and
the OBO/OAuth handshake on first agent access failed for ~3,000 end users.

These tests pin the four branches the check distinguishes plus the
status-bucketing rule:

* GOOD — ``appRoleAssignmentRequired=true`` and a Group is assigned →
  PASSED.
* BAD  — ``appRoleAssignmentRequired=true`` but no assignments →
  FAILED with remediation pointing at Entra → Enterprise Applications →
  Users and groups.
* WARNING (no enforcement) — ``appRoleAssignmentRequired=false`` →
  WARNING; deploy-time check cannot guarantee per-user access.
* WARNING (per-user only) — ``appRoleAssignmentRequired=true`` and only
  individual User principals are assigned (no Group).
* SKIPPED — no Workday SP exists in the tenant.

When the tenant has multiple Workday SPs, results are grouped by
status — one Failed row, one Warning row, one Passed row at most —
each listing every SP in that bucket. Per-SP rows would make the
readiness summary unreadable for tenants with several Workday apps
(SSO + OAuth + per-tenant implementation app)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import responses

from tests.conftest import require_validated_mock
from tests.mocks import graph as gr

require_validated_mock(gr)


# ───────────────────────────────────────────────────────────────────────
# Test runner — minimal stand-in for FlightCheckRunner that the
# authentication check needs. AUTH-005 only reads ``runner.graph``.
# ───────────────────────────────────────────────────────────────────────


@dataclass
class _MinimalRunner:
    graph: Any


def _make_graph_client(tenant_id: str = gr.MOCK_TENANT_ID):
    """Build a real GraphClient with a fake bearer token so requests it
    issues are intercepted by ``responses`` rather than hitting Graph."""
    from flightcheck.graph_client import GraphClient

    client = GraphClient(tenant_id)
    client._token = "REDACTED_TOKEN"  # noqa: S105 — test fixture
    return client


@pytest.fixture
def runner() -> _MinimalRunner:
    return _MinimalRunner(graph=_make_graph_client())


def _result_by_id(results: list, checkpoint_id: str):
    """Lookup helper: find the CheckResult with a given checkpoint_id."""
    matches = [r for r in results if r.checkpoint_id == checkpoint_id]
    assert len(matches) >= 1, (
        f"Expected at least one result for {checkpoint_id}, got "
        f"{[r.checkpoint_id for r in results]}"
    )
    return matches[0]


# ───────────────────────────────────────────────────────────────────────
# Tests
# ───────────────────────────────────────────────────────────────────────


class TestGoodConfig:
    """Workday SP requires user assignment AND a Group is assigned."""

    @responses.activate
    def test_group_assigned_returns_passed(self, runner: _MinimalRunner) -> None:
        from flightcheck.checks.authentication import (
            _check_workday_app_user_assignment,
        )

        responses.add(
            **gr.list_service_principals(
                service_principals=[
                    gr.service_principal(
                        display_name="Workday",
                        app_role_assignment_required=True,
                    )
                ]
            )
        )
        responses.add(
            **gr.list_app_role_assignments(
                assignments=[
                    gr.app_role_assignment(
                        principal_type="Group",
                        principal_display_name="ESS Users",
                    )
                ]
            )
        )

        results = _check_workday_app_user_assignment(runner.graph)
        auth_005 = _result_by_id(results, "AUTH-005")

        assert auth_005.status == "Passed"
        assert auth_005.priority == "Critical"
        assert "Workday" in auth_005.result
        assert "ESS Users" in auth_005.result
        assert "1 group(s)" in auth_005.result


class TestBadConfig:
    """Workday SP requires user assignment but nothing is assigned —
    the Sev 2 customer-incident scenario AUTH-005 was filed for."""

    @responses.activate
    def test_no_assignments_returns_critical_failure(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.authentication import (
            _check_workday_app_user_assignment,
        )

        responses.add(
            **gr.list_service_principals(
                service_principals=[
                    gr.service_principal(app_role_assignment_required=True)
                ]
            )
        )
        responses.add(**gr.list_app_role_assignments(assignments=[]))

        results = _check_workday_app_user_assignment(runner.graph)
        auth_005 = _result_by_id(results, "AUTH-005")

        assert auth_005.status == "Failed", (
            f"Expected AUTH-005 to FAIL when no assignments exist, got "
            f"status={auth_005.status} result={auth_005.result!r}"
        )
        assert auth_005.priority == "Critical"
        # Result is the current state — terse, no impact prose.
        assert "0 users/groups assigned" in auth_005.result
        assert "user assignment required" in auth_005.result
        # Impact + fix steps live in remediation, not result.
        assert "OBO/OAuth handshake" in auth_005.remediation
        assert "Users and groups" in auth_005.remediation
        assert "ESS user security group" in auth_005.remediation
        assert auth_005.doc_link.startswith(
            "https://learn.microsoft.com/en-us/copilot/microsoft-365/employee-self-service"
        )


class TestEdgeCases:
    @responses.activate
    def test_assignment_required_false_returns_warning(
        self, runner: _MinimalRunner
    ) -> None:
        """When the customer left 'User assignment required?' = No, the
        Workday SP can issue tokens to any licensed user in the tenant —
        ESS still works, but the impersonation surface is the whole
        tenant and you lose deploy-time provable access control. Warn
        as a hardening recommendation."""
        from flightcheck.checks.authentication import (
            _check_workday_app_user_assignment,
        )

        responses.add(
            **gr.list_service_principals(
                service_principals=[
                    gr.service_principal(app_role_assignment_required=False)
                ]
            )
        )

        results = _check_workday_app_user_assignment(runner.graph)
        auth_005 = _result_by_id(results, "AUTH-005")

        assert auth_005.status == "Warning"
        # Result describes the observable state and what it means.
        assert "set to No" in auth_005.result
        assert "any licensed user" in auth_005.result
        # Remediation frames this as hardening, not a functional fix,
        # and explains why Yes is better before saying how to set it.
        assert "Hardening recommendation" in auth_005.remediation
        assert "not a functional blocker" in auth_005.remediation
        assert "Assignment required?" in auth_005.remediation
        assert "ESS user security group" in auth_005.remediation

    @responses.activate
    def test_only_individual_users_assigned_returns_warning(
        self, runner: _MinimalRunner
    ) -> None:
        """User assignment required + only individual Users assigned (no
        Group). This works at runtime today, but breaks the moment a new
        ESS user is onboarded — warn so the customer migrates to a group."""
        from flightcheck.checks.authentication import (
            _check_workday_app_user_assignment,
        )

        responses.add(
            **gr.list_service_principals(
                service_principals=[
                    gr.service_principal(app_role_assignment_required=True)
                ]
            )
        )
        responses.add(
            **gr.list_app_role_assignments(
                assignments=[
                    gr.app_role_assignment(
                        principal_type="User",
                        principal_display_name="alice@contoso.com",
                    ),
                    gr.app_role_assignment(
                        assignment_id="00000000-0000-0000-0000-000000005102",
                        principal_id="00000000-0000-0000-0000-000000005103",
                        principal_type="User",
                        principal_display_name="bob@contoso.com",
                    ),
                ]
            )
        )

        results = _check_workday_app_user_assignment(runner.graph)
        auth_005 = _result_by_id(results, "AUTH-005")

        assert auth_005.status == "Warning"
        assert "individual user" in auth_005.result
        assert "security groups" in auth_005.result
        assert "security group" in auth_005.remediation

    @responses.activate
    def test_no_workday_sp_in_tenant_returns_skipped(
        self, runner: _MinimalRunner
    ) -> None:
        """Customer hasn't installed the Workday Enterprise App yet — the
        check is N/A until they do, but should not crash or false-pass."""
        from flightcheck.checks.authentication import (
            _check_workday_app_user_assignment,
        )

        responses.add(**gr.list_service_principals(service_principals=[]))

        results = _check_workday_app_user_assignment(runner.graph)
        auth_005 = _result_by_id(results, "AUTH-005")

        assert auth_005.status == "Skipped"
        assert "No Enterprise Application" in auth_005.result
        assert "Workday" in auth_005.result
        assert "Entra gallery" in auth_005.remediation

    def test_skips_when_no_graph_client(self) -> None:
        """No Graph client (auth opted out) — return SKIPPED, don't crash,
        don't try to make an HTTP call."""
        from flightcheck.checks.authentication import (
            _check_workday_app_user_assignment,
        )

        results = _check_workday_app_user_assignment(graph=None)

        assert len(results) == 1
        assert results[0].checkpoint_id == "AUTH-005"
        assert results[0].status == "Skipped"
        assert "Graph client not available" in results[0].result

    @responses.activate
    def test_multiple_workday_sps_grouped_by_status(
        self, runner: _MinimalRunner
    ) -> None:
        """Some tenants register both a SAML SSO app and an OAuth flavor —
        the check must evaluate each independently but emit at most one
        row per status, so the readiness summary doesn't get a separate
        row for every Workday SP."""
        from flightcheck.checks.authentication import (
            _check_workday_app_user_assignment,
        )

        sp_sso_id = "00000000-0000-0000-0000-000000005201"
        sp_oauth_id = "00000000-0000-0000-0000-000000005301"

        responses.add(
            **gr.list_service_principals(
                service_principals=[
                    gr.service_principal(
                        sp_id=sp_sso_id,
                        app_id="00000000-0000-0000-0000-000000005202",
                        display_name="Workday SSO",
                        app_role_assignment_required=True,
                    ),
                    gr.service_principal(
                        sp_id=sp_oauth_id,
                        app_id="00000000-0000-0000-0000-000000005302",
                        display_name="Workday OAuth",
                        app_role_assignment_required=False,
                    ),
                ]
            )
        )
        # Only the first SP needs an appRoleAssignedTo lookup (the second
        # is short-circuited by the False branch). Mock the first.
        responses.add(
            **gr.list_app_role_assignments(
                sp_id=sp_sso_id,
                assignments=[
                    gr.app_role_assignment(
                        resource_id=sp_sso_id,
                        principal_type="Group",
                        principal_display_name="ESS Users",
                    )
                ],
            )
        )

        results = _check_workday_app_user_assignment(runner.graph)

        auth_005_results = [r for r in results if r.checkpoint_id == "AUTH-005"]
        # One row per distinct status — here Passed (SSO) + Warning (OAuth).
        assert len(auth_005_results) == 2

        statuses = {r.status for r in auth_005_results}
        assert statuses == {"Passed", "Warning"}

        # Each row names the SP it covers.
        by_status = {r.status: r for r in auth_005_results}
        assert "Workday SSO" in by_status["Passed"].result
        assert "Workday OAuth" in by_status["Warning"].result

    @responses.activate
    def test_two_failing_sps_collapse_to_one_failed_row(
        self, runner: _MinimalRunner
    ) -> None:
        """Two Workday SPs in the same FAILED state must produce ONE
        Failed row that lists both apps, not two separate rows."""
        from flightcheck.checks.authentication import (
            _check_workday_app_user_assignment,
        )

        sp_a_id = "00000000-0000-0000-0000-000000005401"
        sp_b_id = "00000000-0000-0000-0000-000000005402"

        responses.add(
            **gr.list_service_principals(
                service_principals=[
                    gr.service_principal(
                        sp_id=sp_a_id,
                        app_id="00000000-0000-0000-0000-000000005411",
                        display_name="Workday Prod",
                        app_role_assignment_required=True,
                    ),
                    gr.service_principal(
                        sp_id=sp_b_id,
                        app_id="00000000-0000-0000-0000-000000005412",
                        display_name="Workday Impl",
                        app_role_assignment_required=True,
                    ),
                ]
            )
        )
        responses.add(**gr.list_app_role_assignments(sp_id=sp_a_id, assignments=[]))
        responses.add(**gr.list_app_role_assignments(sp_id=sp_b_id, assignments=[]))

        results = _check_workday_app_user_assignment(runner.graph)

        auth_005_results = [r for r in results if r.checkpoint_id == "AUTH-005"]
        assert len(auth_005_results) == 1, (
            f"Expected one Failed row covering both SPs, got "
            f"{[(r.status, r.result) for r in auth_005_results]}"
        )
        assert auth_005_results[0].status == "Failed"
        # Both SPs are surfaced in the combined result.
        assert "Workday Prod" in auth_005_results[0].result
        assert "Workday Impl" in auth_005_results[0].result
        assert "2 Workday Enterprise App(s)" in auth_005_results[0].result
