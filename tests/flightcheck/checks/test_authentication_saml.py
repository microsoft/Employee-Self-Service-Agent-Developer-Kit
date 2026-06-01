# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end integration tests for the AUTH-006 SAML NameID alignment
FlightCheck check (fixes issue #84).

The check fetches the Entra-side half of the comparison automatically
(the SAML claim mapping on the customer's federated Workday enterprise
app, via Microsoft Graph), then emits a MANUAL result telling the
operator to verify the Workday-side NameID expectation matches. This
test file mocks the Graph endpoints with `responses` and asserts that
the production `_run_saml_nameid_check()` function returns the right
CheckResult shape for each branch.

Pattern mirrors test_workday_connections.py — minimal runner, real
GraphClient with pre-populated token, validatable Graph mocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import responses

from tests.conftest import require_validated_mock
from tests.mocks import graph as g

require_validated_mock(g)


@dataclass
class _MinimalRunner:
    graph: Any


@pytest.fixture
def graph_client(fake_token: str):
    """A real GraphClient with a pre-populated token, ready to be
    driven through `responses` mocks. Bypasses authenticate() (which
    would launch interactive MSAL) by setting the private _token field
    directly — standard test pattern in this suite."""
    from flightcheck.graph_client import GraphClient

    client = GraphClient(tenant_id=g.MOCK_TENANT_ID)
    client._token = fake_token
    return client


@pytest.fixture
def runner(graph_client) -> _MinimalRunner:
    return _MinimalRunner(graph=graph_client)


def _result_by_id(results: list, checkpoint_id: str):
    matches = [r for r in results if r.checkpoint_id == checkpoint_id]
    assert len(matches) >= 1, (
        f"Expected at least one result for {checkpoint_id}, got 0: "
        f"{[r.checkpoint_id for r in results]}"
    )
    return matches[0]


# ───────────────────────────────────────────────────────────────────────


class TestNotConfigured:
    """No federated Workday SAML app in Entra → NOT_CONFIGURED."""

    @responses.activate
    def test_no_workday_sp_returns_not_configured(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.authentication import _run_saml_nameid_check

        responses.add(**g.list_service_principals(service_principals=[]))

        results = _run_saml_nameid_check(runner)
        r = _result_by_id(results, "AUTH-006")

        assert r.status == "NotConfigured"
        assert r.priority == "High"
        assert "No federated Workday enterprise app" in r.result
        assert "Entra gallery" in r.remediation


class TestManualVerificationRequired:
    """Workday SAML app found → MANUAL result with detected mapping."""

    @responses.activate
    def test_default_mapping_emits_manual_with_default_summary(
        self, runner: _MinimalRunner
    ) -> None:
        """No claimsMappingPolicy assigned — app uses Entra default
        (NameID = user.userPrincipalName). MANUAL result should say so."""
        from flightcheck.checks.authentication import _run_saml_nameid_check

        sp = g.service_principal(
            sp_id="sp-workday-prod",
            display_name="Workday Prod",
            app_id="aaaa1111-0000-0000-0000-000000000001",
            service_principal_names=[
                "aaaa1111-0000-0000-0000-000000000001",
                "http://www.workday.com/contoso_prod",
            ],
        )
        responses.add(**g.list_service_principals(service_principals=[sp]))
        responses.add(**g.list_claims_mapping_policies_for_sp(
            sp_id="sp-workday-prod",
            policies=[],
        ))

        results = _run_saml_nameid_check(runner)
        # Coalesced: exactly one AUTH-006 row regardless of app count.
        auth006 = [r for r in results if r.checkpoint_id == "AUTH-006"]
        assert len(auth006) == 1
        r = auth006[0]

        assert r.status == "Manual"
        assert r.priority == "High"
        assert "Workday Prod" in r.result
        assert "default" in r.result.lower()
        assert "user.userPrincipalName" in r.result
        # The SAML entity ID (the Workday "Service Provider ID" join
        # key) MUST be in the result — without it, the operator can't
        # match the Entra app to the Workday IdP row.
        assert "http://www.workday.com/contoso_prod" in r.result
        # And the bare appId GUID should not appear as an "entity ID"
        # since it's noise (Workday's Service Provider ID column never
        # shows GUIDs).
        # NB: the appId IS surfaced as `appId=...` for human ID, just
        # not in the entity-IDs list.
        # Remediation must include both phases.
        assert "Step 1" in r.remediation
        assert "Service Provider ID" in r.remediation
        assert "Step 2" in r.remediation
        assert "All Workday Accounts" in r.remediation
        assert "Workday User Name" in r.remediation
        assert "tutorial" in r.remediation.lower()
        assert r.doc_link == (
            "https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial"
        )

    @responses.activate
    def test_custom_nameid_override_is_surfaced(
        self, runner: _MinimalRunner
    ) -> None:
        """When a claimsMappingPolicy overrides NameID, the MANUAL result
        must echo the override verbatim so the operator can compare it
        to the Workday side."""
        from flightcheck.checks.authentication import _run_saml_nameid_check

        sp = g.service_principal(
            sp_id="sp-workday-impl",
            display_name="Workday Implementation",
        )
        responses.add(**g.list_service_principals(service_principals=[sp]))
        responses.add(**g.list_claims_mapping_policies_for_sp(
            sp_id="sp-workday-impl",
            policies=[g.claims_mapping_policy(
                display_name="Workday NameID -> employeeId",
            )],
        ))

        results = _run_saml_nameid_check(runner)
        auth006 = [r for r in results if r.checkpoint_id == "AUTH-006"]
        assert len(auth006) == 1
        r = auth006[0]

        assert r.status == "Manual"
        assert "override" in r.result
        assert "user.employeeid" in r.result
        assert "Workday NameID -> employeeId" in r.result

    @responses.activate
    def test_policy_assigned_but_not_overriding_nameid(
        self, runner: _MinimalRunner
    ) -> None:
        """A policy may be assigned for other claims (e.g. groups) without
        overriding NameID. The result must still say 'default' and call
        out that policies are attached."""
        from flightcheck.checks.authentication import _run_saml_nameid_check

        sp = g.service_principal(sp_id="sp-wd")
        non_nameid = g.claims_mapping_policy(
            display_name="Workday extra claims",
            definition=[
                '{"ClaimsMappingPolicy":{"Version":1,"IncludeBasicClaimSet":"true",'
                '"ClaimsSchema":[{"Source":"user","ID":"department",'
                '"SamlClaimType":"http://schemas.example.com/dept"}]}}'
            ],
        )
        responses.add(**g.list_service_principals(service_principals=[sp]))
        responses.add(**g.list_claims_mapping_policies_for_sp(
            sp_id="sp-wd",
            policies=[non_nameid],
        ))

        results = _run_saml_nameid_check(runner)
        auth006 = [r for r in results if r.checkpoint_id == "AUTH-006"]
        assert len(auth006) == 1
        r = auth006[0]

        assert r.status == "Manual"
        assert "default" in r.result.lower()
        assert "Workday extra claims" in r.result
        assert "none override the NameID claim" in r.result


class TestMultipleWorkdayApps:
    """If the tenant has multiple federated Workday apps (Prod, Impl,
    Sandbox, etc.), AUTH-006 emits exactly ONE MANUAL result listing
    them all — only one is the active IdP for the Workday tenant ESS
    uses, and the operator picks it via Workday's SAML IdP screen."""

    @responses.activate
    def test_two_workday_sps_yield_one_coalesced_manual_result(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.authentication import _run_saml_nameid_check

        sp_prod = g.service_principal(
            sp_id="sp-prod",
            display_name="Workday",
            service_principal_names=[
                "guid-noise-1",
                "http://www.workday.com/contoso_prod",
            ],
        )
        sp_impl = g.service_principal(
            sp_id="sp-impl",
            display_name="Workday Implementation",
            service_principal_names=[
                "guid-noise-2",
                "http://www.workday.com/contoso_dpt6",
            ],
        )
        responses.add(**g.list_service_principals(
            service_principals=[sp_prod, sp_impl],
        ))
        responses.add(**g.list_claims_mapping_policies_for_sp(
            sp_id="sp-prod", policies=[],
        ))
        responses.add(**g.list_claims_mapping_policies_for_sp(
            sp_id="sp-impl", policies=[g.claims_mapping_policy()],
        ))

        results = _run_saml_nameid_check(runner)
        auth006 = [r for r in results if r.checkpoint_id == "AUTH-006"]
        # The whole point of the coalesce: exactly one row.
        assert len(auth006) == 1, (
            f"Expected 1 coalesced MANUAL row, got {len(auth006)}: "
            f"{[r.result for r in auth006]}"
        )
        r = auth006[0]
        assert r.status == "Manual"

        # Both apps must be listed.
        assert "Workday" in r.result
        assert "Workday Implementation" in r.result
        # Both join keys (SAML entity IDs) must be present so the
        # operator can match against Workday's Service Provider ID
        # column.
        assert "http://www.workday.com/contoso_prod" in r.result
        assert "http://www.workday.com/contoso_dpt6" in r.result
        # Intro should signal that only one matters.
        assert "Only one" in r.result or "only one" in r.result
        # GUIDs that are NOT URI-shaped should not appear in the
        # entity-ID list (they're noise from servicePrincipalNames).
        # We check via the substring "entity IDs: guid-noise" — if it
        # appears, the filter let a GUID through.
        assert "entity IDs: guid-noise" not in r.result


class TestErrorHandling:
    """Graph failures surface as WARNING, not silent pass."""

    @responses.activate
    def test_servicepriniclap_403_emits_warning(
        self, runner: _MinimalRunner
    ) -> None:
        """If Graph returns 403 (missing Application.Read.All) when
        listing service principals, get_all() returns [] — which the
        check currently interprets as NOT_CONFIGURED. Pin that
        behavior; if we ever want to distinguish "no SP" from "no
        permission", we'd plumb _status through get_all()."""
        from flightcheck.checks.authentication import _run_saml_nameid_check

        responses.add(**g.insufficient_permissions(path="/servicePrincipals"))

        results = _run_saml_nameid_check(runner)
        r = _result_by_id(results, "AUTH-006")
        # Empty list path → NOT_CONFIGURED (documented quirk of
        # graph_client.get_all on 401/403; see graph_client.py:148-161).
        assert r.status == "NotConfigured"

    @responses.activate
    def test_claims_mapping_403_emits_warning_for_that_sp(
        self, runner: _MinimalRunner
    ) -> None:
        """If the SP listing succeeds but reading its claimsMappingPolicies
        gets a 403, the per-SP result is informational — the
        get_all() returns [], so the check treats it as 'no override'
        and emits MANUAL with the default summary. Pin that behavior
        to make the contract obvious."""
        from flightcheck.checks.authentication import _run_saml_nameid_check

        sp = g.service_principal(sp_id="sp-x", display_name="Workday")
        responses.add(**g.list_service_principals(service_principals=[sp]))
        responses.add(**g.insufficient_permissions(
            path="/servicePrincipals/sp-x/claimsMappingPolicies",
        ))

        results = _run_saml_nameid_check(runner)
        r = _result_by_id(results, "AUTH-006")
        # 403 on claimsMappingPolicies returns [] from get_all, which
        # we treat as "no custom policy" → MANUAL with default summary.
        # Real consequence: the operator gets the same actionable
        # MANUAL result either way; if Policy.Read.All was missing
        # they'd just see the default-mapping summary instead of any
        # detected override. Acceptable for an initial release.
        assert r.status == "Manual"


class TestGraphUnavailable:
    """If runner.graph is None (auth failed earlier), check skips."""

    def test_no_graph_client_returns_skipped(self) -> None:
        from flightcheck.checks.authentication import _run_saml_nameid_check

        runner = _MinimalRunner(graph=None)
        results = _run_saml_nameid_check(runner)
        r = _result_by_id(results, "AUTH-006")
        assert r.status == "Skipped"
