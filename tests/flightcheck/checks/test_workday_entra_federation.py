# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end integration tests for the WD-CONN-010 Workday
single-Entra-tenant federation alignment FlightCheck check
(fixes issue #43).

WD-CONN-010 mirrors the AUTH-006 MANUAL pattern: gather everything
programmatically observable on the Entra side (the federated Workday
SAML enterprise apps in the current Entra tenant, via Microsoft Graph)
and delegate the Workday-side comparison to the operator. The check is
shipped despite there being no Workday API surface to query — per
``solutions/ess-maker-skills/scripts/flightcheck/AGENTS.md`` design
principle #2, this is precisely the case the MANUAL status pattern was
introduced for.

The wiring/placement test at the bottom is a regression guard for the
single most likely mistake when modifying ``run_workday_checks``:
moving the WD-CONN-010 call to AFTER the no-Workday early-return gate
would silently disable the check on the pre-install scenario that
issue #43 specifically asks to cover.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
import re
import responses

from tests.conftest import require_validated_mock
from tests.mocks import graph as g

require_validated_mock(g)


@dataclass
class _MinimalRunner:
    graph: Any = None
    _workday_flows: list = field(default_factory=list)


@pytest.fixture
def graph_client(fake_token: str):
    """Real GraphClient with a pre-populated token. Bypasses
    authenticate() (which would launch interactive MSAL) by setting the
    private _token field directly — the same pattern test_authentication_saml.py
    uses for AUTH-006.
    """
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


class TestNoLocalWorkdayApp:
    """No federated Workday SAML app in this Entra tenant.

    Per the rubber-duck review, the result text MUST NOT claim "the
    conflict scenario doesn't apply" — only that the kit cannot
    identify a local Workday SAML app. The remediation MUST still
    walk the operator through the manual Workday-side verification
    for the pre-install / foreign-tenant scenario.
    """

    @responses.activate
    def test_no_workday_sp_returns_not_configured(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import (
            _check_entra_workday_federation_alignment,
        )

        responses.add(**g.list_service_principals(service_principals=[]))
        responses.add(**g.list_service_principals(service_principals=[]))

        results = _check_entra_workday_federation_alignment(runner)
        r = _result_by_id(results, "WD-CONN-010")

        assert r.status == "NotConfigured"
        assert r.priority == "High"
        assert r.category == "Workday"
        # Current Entra tenant ID must be surfaced even in the
        # no-local-app case — it's the anchor for the manual check.
        assert g.MOCK_TENANT_ID in r.result
        # The filter must be disclosed so operators understand the
        # blind spot (renamed Workday apps wouldn't match).
        assert "startswith(displayName,'Workday')" in r.result
        # Must NOT claim safety — the foreign-tenant scenario still
        # applies pre-install. Rubber-duck blocking issue #1.
        assert "doesn't apply" not in r.result.lower()
        assert "does not apply" not in r.result.lower()
        # Remediation must still include the manual Workday steps
        # for the pre-install scenario.
        assert "Edit Tenant Setup - Security" in r.remediation
        assert "SAML Identity Providers" in r.remediation
        # And must point at the issuer URL as the tenant-ID source —
        # NOT the entity ID / appId (rubber-duck blocking issue #2).
        # CodeQL's `py/incomplete-url-substring-sanitization` rule is
        # globally suppressed for this URL-shaped assertion pattern
        # (see `.github/codeql/codeql-config.yml` for the rationale).
        assert re.search(r"https://sts\.windows\.net/", r.remediation)
        assert "Issuer" in r.remediation or "issuer" in r.remediation


class TestManualVerificationRequired:
    """Workday SAML app(s) found → MANUAL result with the current
    Entra tenant ID, the per-app entity IDs, and a remediation that
    points at the Workday IdP issuer (NOT the entity ID / appId /
    cert subject — those don't carry the Entra tenant ID).
    """

    @responses.activate
    def test_single_workday_app_emits_manual(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import (
            _check_entra_workday_federation_alignment,
        )

        sp = g.service_principal(
            sp_id="sp-workday-prod",
            display_name="Workday Prod",
            app_id="aaaa1111-0000-0000-0000-000000000001",
            service_principal_names=[
                "aaaa1111-0000-0000-0000-000000000001",
                "http://www.workday.com/contoso_prod",
            ],
        )
        # Filtered /servicePrincipals call returns one Workday SP.
        responses.add(**g.list_service_principals(service_principals=[sp]))

        results = _check_entra_workday_federation_alignment(runner)
        wd_conn = [r for r in results if r.checkpoint_id == "WD-CONN-010"]
        assert len(wd_conn) == 1, (
            f"Expected exactly 1 WD-CONN-010 row, got {len(wd_conn)}"
        )
        r = wd_conn[0]

        assert r.status == "Manual"
        assert r.priority == "High"
        assert r.category == "Workday"

        # Result must surface the CURRENT Entra tenant ID — this is
        # the anchor value the operator compares against the
        # Workday-side IdP issuer in the manual step.
        assert g.MOCK_TENANT_ID in r.result
        # App identity + entity IDs (the Workday "Service Provider ID"
        # join key) must both be present.
        assert "Workday Prod" in r.result
        assert "http://www.workday.com/contoso_prod" in r.result
        # The bare appId GUID must NOT appear in the entity-ID list
        # (Workday's Service Provider ID column never shows GUIDs).
        # We allow it once via the explicit appId={app_id} label, but
        # it must not appear inside the entity-IDs CSV.
        entity_ids_segment = r.result.split("entity IDs:")[1].split("\n")[0]
        assert "aaaa1111-0000-0000-0000-000000000001" not in entity_ids_segment

        # Remediation must include BOTH phases.
        assert "Step 1" in r.remediation
        assert "Service Provider ID" in r.remediation
        assert "Step 2" in r.remediation
        # Rubber-duck blocking issue #2: the tenant-ID comparison
        # MUST point at the SAML issuer URL (which actually embeds
        # the Entra tenant ID), NOT the entity ID / appId / cert
        # subject (which do not). See codeql-config.yml for why the
        # URL-shaped substring check below doesn't trip CodeQL.
        assert re.search(r"https://sts\.windows\.net/", r.remediation)
        assert "Issuer" in r.remediation or "federation metadata" in r.remediation
        # And the current tenant ID must appear in the remediation
        # too so operators know what value to compare against.
        assert g.MOCK_TENANT_ID in r.remediation
        # Explicit conflict warning — the whole point of the check —
        # belongs in remediation, not result (principle #8: result is
        # observed state only).
        assert "silently break" not in r.result
        assert "silently break" in r.remediation
        assert "foreign" in r.remediation.lower() or "different" in r.remediation.lower()
        # Doc link must point at the MS Learn Workday SSO tutorial
        # (the same authoritative page AUTH-006 cites).
        assert r.doc_link == (
            "https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial"
        )


class TestMultipleWorkdayApps:
    """When the tenant has multiple federated Workday apps (Prod,
    Implementation, Sandbox, etc.), WD-CONN-010 emits exactly ONE
    coalesced MANUAL result listing them all — mirrors AUTH-006's
    multi-app collapse contract (principle 7: bucket by status,
    never one row per resource).
    """

    @responses.activate
    def test_two_workday_sps_yield_one_coalesced_manual_result(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import (
            _check_entra_workday_federation_alignment,
        )

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
        # Filtered /servicePrincipals call returns both Workday SPs.
        responses.add(**g.list_service_principals(
            service_principals=[sp_prod, sp_impl],
        ))

        results = _check_entra_workday_federation_alignment(runner)
        wd_conn = [r for r in results if r.checkpoint_id == "WD-CONN-010"]
        # Coalesce contract: exactly one row regardless of app count.
        assert len(wd_conn) == 1, (
            f"Expected 1 coalesced MANUAL row, got {len(wd_conn)}: "
            f"{[x.result for x in wd_conn]}"
        )
        r = wd_conn[0]
        assert r.status == "Manual"

        # Both apps must be listed.
        assert "Workday" in r.result
        assert "Workday Implementation" in r.result
        # Both join keys (SAML entity IDs) must be present.
        assert "http://www.workday.com/contoso_prod" in r.result
        assert "http://www.workday.com/contoso_dpt6" in r.result
        # GUID noise must be filtered out of the entity-IDs CSV.
        assert "entity IDs: guid-noise" not in r.result


class TestPermissionGaps:
    """Missing Application.Read.All consent must surface as WARNING
    with a remediation pointing at the specific permission needed —
    never as a silent NOT_CONFIGURED. AUTH-006 introduced this
    raise-on-permission-error pattern (originally as a probe; PR #125
    consolidated it into a kwarg on `get_service_principals`);
    WD-CONN-010 inherits the same trap and must mirror the same fix.
    """

    @responses.activate
    def test_serviceprincipals_403_emits_warning_with_consent_remediation(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import (
            _check_entra_workday_federation_alignment,
        )

        # /servicePrincipals returns 403 on the filtered list call;
        # get_service_principals(raise_on_permission_error=True) turns
        # it into PermissionError, which the check catches → WARNING.
        responses.add(**g.insufficient_permissions(path="/servicePrincipals"))

        results = _check_entra_workday_federation_alignment(runner)
        r = _result_by_id(results, "WD-CONN-010")
        assert r.status == "Warning", (
            f"Expected Warning, got {r.status} — confidently-wrong "
            "NOT_CONFIGURED on 403 is the silent-failure mode the "
            "AUTH-006 raise-on-permission-error pattern prevents."
        )
        assert "Application.Read.All" in r.remediation
        assert "403" in r.result
        # The check MUST NOT proceed to surface a "Detected apps" list
        # when it couldn't read the SP list in the first place.
        assert "Detected apps" not in r.result


class TestGraphUnavailable:
    """If runner.graph is None (auth failed earlier), check skips
    cleanly with a SKIPPED result — never crashes.
    """

    def test_no_graph_client_returns_skipped(self) -> None:
        from flightcheck.checks.workday import (
            _check_entra_workday_federation_alignment,
        )

        runner = _MinimalRunner(graph=None)
        results = _check_entra_workday_federation_alignment(runner)
        r = _result_by_id(results, "WD-CONN-010")
        assert r.status == "Skipped"
        assert r.priority == "High"
        assert r.category == "Workday"


# ───────────────────────────────────────────────────────────────────────
# Wiring / placement regression guard
# ───────────────────────────────────────────────────────────────────────


class TestRunWorkdayChecksWiring:
    """Pins the placement contract for WD-CONN-010 within
    ``run_workday_checks``.

    The check MUST run BEFORE the no-Workday early-return gate in
    ``run_workday_checks`` so that operators preparing to wire up
    Entra Integrated Workday SSO on a tenant that doesn't yet have
    Workday deployed still get the manual-verification warning —
    that's the customer-incident scenario issue #43 was filed to
    cover.

    Without this test, a future refactor that moves the
    ``_check_entra_workday_federation_alignment(runner)`` call below
    the ``if not wd_flows and flavor in (None, "none"): return``
    gate would silently disable the check on the exact tenants it
    most needs to fire on, and the per-helper tests above would all
    still pass.
    """

    def test_wd_conn_010_runs_when_no_workday_install_signals(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from flightcheck.checks import workday as wd_mod

        # Patch out WD-PKG-001 so the test doesn't need a real
        # Dataverse mock setup — we only care about WD-CONN-010
        # placement here. The fake sets flavor="none" exactly as
        # the real check would on a tenant with no Workday refs.
        def fake_pkg(runner, *, wd_flows):
            runner._workday_package_flavor = "none"
            runner._workday_connection_refs = []
            return []

        monkeypatch.setattr(wd_mod, "_check_package_flavor", fake_pkg)

        # graph=None → WD-CONN-010 returns SKIPPED quickly, but it
        # DID get invoked, which is the contract we're pinning.
        runner = _MinimalRunner(graph=None, _workday_flows=[])
        results = wd_mod.run_workday_checks(runner)

        # WD-CONN-010 must appear — proving it ran BEFORE the
        # `if not wd_flows and flavor in (None, "none"): return` gate.
        wd_conn_010 = [r for r in results if r.checkpoint_id == "WD-CONN-010"]
        assert len(wd_conn_010) == 1, (
            "WD-CONN-010 missing from run_workday_checks output when "
            "no-Workday-install signals are present. Likely cause: the "
            "_check_entra_workday_federation_alignment(runner) call was "
            "moved BELOW the early-return gate. Move it back ABOVE the "
            "gate — see issue #43 / WD-CONN-010 placement comment in "
            "checks/workday.py."
        )
        assert wd_conn_010[0].status == "Skipped"

        # And the downstream Workday-only checks (which the gate
        # is designed to skip) MUST NOT have run. If any of these
        # appear, the gate is broken, which would also be a
        # regression worth catching.
        downstream_ids = {"WD-ENV-001", "WD-ENV-002", "WD-ENV-003"}
        present = {r.checkpoint_id for r in results}
        assert not (present & downstream_ids), (
            "Downstream Workday checks ran despite no Workday install — "
            f"early-return gate appears broken. Present IDs: {present}"
        )
