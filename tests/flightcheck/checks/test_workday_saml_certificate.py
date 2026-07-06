# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end integration tests for the WD-CONN-102 Workday SAML
signing certificate health FlightCheck check.

The check reads keyCredential metadata off the federated Workday SAML
enterprise app's servicePrincipal via Microsoft Graph (the Entra side
is fully automatable). It then emits one of:

  * NOT_CONFIGURED — no Workday SAML SP found (SAML SSO not used).
  * FAILED — SP exists but no AsymmetricX509Cert keyCredentials, or
    all certs expired, or the active cert is expired with a rollover
    waiting in the wings.
  * WARNING — active cert expiring within CERT_EXPIRY_WARN_DAYS or
    NotBefore is still in the future.
  * MANUAL — active cert is healthy; operator must compare the
    thumbprint against Workday's "Edit Tenant Setup - Security ->
    SAML Identity Providers" row because that is not exposed via any
    Workday API the kit talks to.

Pattern mirrors test_authentication_saml.py — minimal runner, real
GraphClient with pre-populated token, validatable Graph mocks (no
cassette required per tests/fixtures/cassettes/INDEX.md "API tier
registry": Microsoft Graph is validatable against
https://graph.microsoft.com/v1.0/$metadata).
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

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


def _expected_thumbprint_for(key_id: str) -> str:
    """Compute the colon-hex thumbprint the check produces from a
    key_id (matches the deterministic SHA-1 default the mock builder
    derives for customKeyIdentifier when omitted)."""
    digest = hashlib.sha1(key_id.encode("ascii")).digest()
    return ":".join(f"{b:02X}" for b in digest)


def _iso(dt: datetime) -> str:
    """Format a datetime as an ISO-8601 string with Z suffix (matches
    Graph's Edm.DateTimeOffset wire format)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ───────────────────────────────────────────────────────────────────────


class TestNotConfigured:
    """No federated Workday SAML app → NOT_CONFIGURED."""

    @responses.activate
    def test_no_workday_sp_returns_not_configured(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_saml_certificate_health

        responses.add(**g.list_service_principals(service_principals=[]))

        results = _check_saml_certificate_health(runner)
        r = _result_by_id(results, "WD-CONN-102")

        assert r.status == "NotConfigured"
        assert r.priority == "High"
        assert "No federated Workday SAML enterprise app" in r.result
        assert "ISU credentials" in r.result
        # Remediation must guide operator on what to do if they DO use SAML.
        assert "Entra gallery" in r.remediation
        assert "signing certificate" in r.remediation


class TestPermissionDenied:
    """Graph returns 401/403 → WARNING with consent guidance."""

    @responses.activate
    def test_probe_403_emits_warning(self, runner: _MinimalRunner) -> None:
        from flightcheck.checks.workday import _check_saml_certificate_health

        # /servicePrincipals listing returns 403 →
        # get_workday_saml_service_principals(raise_on_permission_error=True)
        # raises PermissionError → check emits WARNING.
        responses.add(
            method="GET",
            url=f"{g.GRAPH_BASE}/servicePrincipals",
            json={"error": {"code": "Forbidden"}},
            status=403,
        )

        results = _check_saml_certificate_health(runner)
        r = _result_by_id(results, "WD-CONN-102")

        assert r.status == "Warning"
        assert "HTTP 403" in r.result
        assert "Application.Read.All" in r.remediation


# ───────────────────────────────────────────────────────────────────────


class TestHealthyCertManual:
    """SP with one healthy active cert → MANUAL (operator must compare)."""

    @responses.activate
    def test_single_healthy_cert_emits_manual(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_saml_certificate_health

        # Cert valid from 2024 through far-future 2099.
        kc = g.key_credential(
            key_id="cert-healthy-1",
            end_date_time="2099-01-01T00:00:00Z",
            start_date_time="2024-01-01T00:00:00Z",
        )
        sp = g.service_principal(
            sp_id="sp-workday-prod",
            display_name="Workday Prod",
            app_id="aaaa1111-0000-0000-0000-000000000001",
            service_principal_names=[
                "aaaa1111-0000-0000-0000-000000000001",
                "http://www.workday.com/contoso_prod",
            ],
            key_credentials=[kc],
        )
        responses.add(**g.list_service_principals(service_principals=[sp]))

        results = _check_saml_certificate_health(runner)
        r = _result_by_id(results, "WD-CONN-102")

        assert r.status == "Manual"
        assert r.priority == "High"
        # Result text should surface the colon-hex thumbprint so the
        # operator can compare it byte-for-byte against Workday's view.
        assert _expected_thumbprint_for("cert-healthy-1") in r.result
        # SAML entity ID (Workday "Service Provider ID" join key) is
        # what lets the operator pick the right Entra app.
        assert "http://www.workday.com/contoso_prod" in r.result
        # Remediation must guide operator through both Workday phases.
        assert "Step 1" in r.remediation
        assert "Service Provider ID" in r.remediation
        assert "Step 2" in r.remediation
        assert "X509 Certificate" in r.remediation
        assert "match exactly" in r.remediation


class TestSignVerifyCoalescing:
    """A single SAML cert produces TWO keyCredential entries (Sign +
    Verify) with the same customKeyIdentifier. They must coalesce into
    ONE logical cert, not double-counted."""

    @responses.activate
    def test_sign_verify_pair_coalesces(self, runner: _MinimalRunner) -> None:
        from flightcheck.checks.workday import _check_saml_certificate_health

        # SAME customKeyIdentifier (derived from key_id default), TWO
        # entries with different usage values.
        sign_kc = g.key_credential(
            key_id="cert-paired",
            end_date_time="2099-01-01T00:00:00Z",
            usage="Sign",
        )
        verify_kc = g.key_credential(
            key_id="cert-paired",
            end_date_time="2099-01-01T00:00:00Z",
            usage="Verify",
        )
        sp = g.service_principal(
            sp_id="sp-workday-pair",
            display_name="Workday Paired",
            key_credentials=[sign_kc, verify_kc],
        )
        responses.add(**g.list_service_principals(service_principals=[sp]))

        results = _check_saml_certificate_health(runner)
        # Coalesced down to ONE logical cert ⇒ MANUAL on the single
        # healthy active cert (no rollover entries).
        r = _result_by_id(results, "WD-CONN-102")
        assert r.status == "Manual"
        # Both usages should appear together in the bracketed
        # [Sign+Verify] usage marker.
        assert "[Sign+Verify]" in r.result
        # Must NOT report two rollover certs (would mean we
        # double-counted the pair).
        assert "rollover:" not in r.result


class TestPreferredThumbprintSelectsActive:
    """When preferredTokenSigningKeyThumbprint is set, that cert is the
    'active' one even if other certs exist (rollover scenario)."""

    @responses.activate
    def test_preferred_thumbprint_selects_correct_active_cert(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_saml_certificate_health

        # Two certs: "old" (about to expire) and "new" (long-lived).
        # preferredTokenSigningKeyThumbprint points at "new".
        kc_old = g.key_credential(
            key_id="cert-old",
            end_date_time=_iso(datetime.now(timezone.utc) + timedelta(days=400)),
        )
        kc_new = g.key_credential(
            key_id="cert-new",
            end_date_time="2099-01-01T00:00:00Z",
        )
        # preferredTokenSigningKeyThumbprint is hex (no separators).
        new_thumbprint_no_colons = _expected_thumbprint_for("cert-new").replace(":", "")
        sp = g.service_principal(
            sp_id="sp-workday-rollover",
            display_name="Workday Rollover",
            key_credentials=[kc_old, kc_new],
            preferred_token_signing_key_thumbprint=new_thumbprint_no_colons,
        )
        responses.add(**g.list_service_principals(service_principals=[sp]))

        results = _check_saml_certificate_health(runner)
        r = _result_by_id(results, "WD-CONN-102")
        assert r.status == "Manual"
        # The "active" line should be the NEW cert.
        new_thumb = _expected_thumbprint_for("cert-new")
        old_thumb = _expected_thumbprint_for("cert-old")
        assert f"active: thumbprint={new_thumb}" in r.result
        # The OLD cert should appear as a rollover entry.
        assert f"rollover: thumbprint={old_thumb}" in r.result


class TestActiveExpiredRolloverExists:
    """When preferredTokenSigningKeyThumbprint points at an EXPIRED cert
    but another live cert is also present, the check must FAIL with the
    distinctive "active selection has not been updated" hint (operator
    forgot to flip preferredTokenSigningKeyThumbprint after uploading
    the rollover). Pins workday.py:2335-2349 branch
    (``reason="active_expired_rollover_exists"``), which is otherwise
    only covered by the ``all_expired`` path where every cert is dead."""

    @responses.activate
    def test_preferred_expired_with_live_rollover_emits_failed(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_saml_certificate_health

        # Active cert (by preferred thumbprint): expired 10 days ago.
        kc_expired_active = g.key_credential(
            key_id="cert-old-active",
            end_date_time=_iso(datetime.now(timezone.utc) - timedelta(days=10)),
        )
        # Rollover cert: still alive, long-lived.
        kc_live_rollover = g.key_credential(
            key_id="cert-new-rollover",
            end_date_time="2099-01-01T00:00:00Z",
        )
        # preferred points at the OLD/expired one (operator forgot to
        # update preferred after rolling over to the new cert).
        expired_thumb_no_colons = _expected_thumbprint_for(
            "cert-old-active"
        ).replace(":", "")
        sp = g.service_principal(
            sp_id="sp-workday-stale-preferred",
            display_name="Workday Stale Preferred",
            key_credentials=[kc_expired_active, kc_live_rollover],
            preferred_token_signing_key_thumbprint=expired_thumb_no_colons,
        )
        responses.add(**g.list_service_principals(service_principals=[sp]))

        results = _check_saml_certificate_health(runner)
        r = _result_by_id(results, "WD-CONN-102")
        assert r.status == "Failed"
        # The expired cert appears as the "active" line.
        expired_thumb = _expected_thumbprint_for("cert-old-active")
        live_thumb = _expected_thumbprint_for("cert-new-rollover")
        assert f"active: thumbprint={expired_thumb}" in r.result
        assert "EXPIRED" in r.result
        # The live cert appears as a "rollover" line — distinguishes
        # this branch from the all_expired path.
        assert f"rollover: thumbprint={live_thumb}" in r.result
        # Distinctive hint message produced ONLY by the
        # active_expired_rollover_exists branch.
        assert "rollover certificate exists" in r.result
        assert "active selection has not been updated" in r.result
        # Remediation must guide the operator to flip the preferred
        # selection (not just upload a new cert).
        assert "preferredTokenSigningKeyThumbprint" in r.remediation
        assert "SAML SSO into Workday will fail" in r.remediation


# ───────────────────────────────────────────────────────────────────────


class TestExpiringSoonWarning:
    """Active cert with <=30 days until NotAfter → WARNING (hardening)."""

    @responses.activate
    def test_expiring_in_15_days_emits_warning(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_saml_certificate_health

        kc = g.key_credential(
            key_id="cert-expiring",
            end_date_time=_iso(datetime.now(timezone.utc) + timedelta(days=15)),
        )
        sp = g.service_principal(
            sp_id="sp-workday-expiring",
            display_name="Workday Expiring",
            key_credentials=[kc],
        )
        responses.add(**g.list_service_principals(service_principals=[sp]))

        results = _check_saml_certificate_health(runner)
        r = _result_by_id(results, "WD-CONN-102")
        assert r.status == "Warning"
        # AGENTS.md principle 9 — hardening framing must be present.
        assert r.result.startswith("Hardening recommendation")
        assert "expiring soon" in r.result
        # Remediation must walk through the rotation.
        assert "rotation" in r.remediation.lower()
        assert "New Certificate" in r.remediation


class TestNotYetValidWarning:
    """Active cert with NotBefore in the future → WARNING."""

    @responses.activate
    def test_not_yet_valid_emits_warning(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_saml_certificate_health

        future_start = datetime.now(timezone.utc) + timedelta(days=5)
        kc = g.key_credential(
            key_id="cert-future",
            start_date_time=_iso(future_start),
            end_date_time="2099-01-01T00:00:00Z",
        )
        sp = g.service_principal(
            sp_id="sp-workday-future",
            display_name="Workday Future",
            key_credentials=[kc],
        )
        responses.add(**g.list_service_principals(service_principals=[sp]))

        results = _check_saml_certificate_health(runner)
        r = _result_by_id(results, "WD-CONN-102")
        assert r.status == "Warning"
        assert "not yet valid" in r.result


# ───────────────────────────────────────────────────────────────────────


class TestNoCertsFailed:
    """SP exists but no AsymmetricX509Cert keyCredentials → FAILED."""

    @responses.activate
    def test_sp_with_no_key_credentials_emits_failed(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_saml_certificate_health

        sp = g.service_principal(
            sp_id="sp-workday-nocert",
            display_name="Workday NoCert",
            key_credentials=[],
        )
        responses.add(**g.list_service_principals(service_principals=[sp]))

        results = _check_saml_certificate_health(runner)
        r = _result_by_id(results, "WD-CONN-102")
        assert r.status == "Failed"
        assert "NO X.509 signing certificate" in r.result
        assert "SAML SSO into Workday will fail" in r.remediation

    @responses.activate
    def test_non_x509_key_credentials_treated_as_no_certs(
        self, runner: _MinimalRunner
    ) -> None:
        """Only AsymmetricX509Cert keyCredentials count as SAML signing
        certs. Symmetric / X509CertAndPassword entries are filtered out."""
        from flightcheck.checks.workday import _check_saml_certificate_health

        # type_ overridden to something that isn't AsymmetricX509Cert.
        non_x509 = g.key_credential(
            key_id="cert-noisy",
            type_="Symmetric",
        )
        sp = g.service_principal(
            sp_id="sp-workday-noisy",
            display_name="Workday Noisy",
            key_credentials=[non_x509],
        )
        responses.add(**g.list_service_principals(service_principals=[sp]))

        results = _check_saml_certificate_health(runner)
        r = _result_by_id(results, "WD-CONN-102")
        assert r.status == "Failed"
        assert "NO X.509 signing certificate" in r.result


class TestAllExpiredFailed:
    """SP has only expired certs → FAILED."""

    @responses.activate
    def test_all_certs_expired_emits_failed(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_saml_certificate_health

        past = _iso(datetime.now(timezone.utc) - timedelta(days=30))
        kc = g.key_credential(
            key_id="cert-dead",
            end_date_time=past,
        )
        sp = g.service_principal(
            sp_id="sp-workday-dead",
            display_name="Workday Dead",
            key_credentials=[kc],
        )
        responses.add(**g.list_service_principals(service_principals=[sp]))

        results = _check_saml_certificate_health(runner)
        r = _result_by_id(results, "WD-CONN-102")
        assert r.status == "Failed"
        assert "EXPIRED" in r.result


# ───────────────────────────────────────────────────────────────────────


class TestBucketing:
    """Multiple SPs with different statuses → one CheckResult per
    distinct status, not one per SP (AGENTS.md principle 7)."""

    @responses.activate
    def test_multiple_sps_bucket_by_status(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_saml_certificate_health

        # SP1: healthy → MANUAL
        sp1 = g.service_principal(
            sp_id="sp-1",
            display_name="Workday Prod",
            key_credentials=[g.key_credential(
                key_id="cert-1",
                end_date_time="2099-01-01T00:00:00Z",
            )],
        )
        # SP2: no certs → FAILED
        sp2 = g.service_principal(
            sp_id="sp-2",
            display_name="Workday Sandbox",
            key_credentials=[],
        )
        # SP3: expiring soon → WARNING
        sp3 = g.service_principal(
            sp_id="sp-3",
            display_name="Workday Implementation",
            key_credentials=[g.key_credential(
                key_id="cert-3",
                end_date_time=_iso(
                    datetime.now(timezone.utc) + timedelta(days=5)
                ),
            )],
        )
        responses.add(**g.list_service_principals(
            service_principals=[sp1, sp2, sp3],
        ))

        results = _check_saml_certificate_health(runner)
        # Exactly 3 CheckResults — one per distinct status bucket.
        wd102 = [r for r in results if r.checkpoint_id == "WD-CONN-102"]
        assert len(wd102) == 3
        statuses = {r.status for r in wd102}
        assert statuses == {"Failed", "Warning", "Manual"}

        # The FAILED row must mention SP2, not SP1 or SP3.
        failed = next(r for r in wd102 if r.status == "Failed")
        assert "Workday Sandbox" in failed.result
        assert "Workday Prod" not in failed.result
        assert "Workday Implementation" not in failed.result

        # The MANUAL row must mention SP1, not SP2 or SP3.
        manual = next(r for r in wd102 if r.status == "Manual")
        assert "Workday Prod" in manual.result
        assert "Workday Sandbox" not in manual.result
        assert "Workday Implementation" not in manual.result


# ───────────────────────────────────────────────────────────────────────


class TestSelectClauseInRequestUrl:
    """The check MUST include `$select=...,keyCredentials,...` in the
    listing request because Graph omits keyCredentials from list
    responses unless explicitly projected. Without this, every SP
    would falsely appear to have zero certs (and FAILED would fire on
    every healthy tenant)."""

    @responses.activate
    def test_select_clause_includes_keycredentials(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_saml_certificate_health

        sp = g.service_principal(
            sp_id="sp-select-test",
            key_credentials=[g.key_credential(
                key_id="cert-select",
                end_date_time="2099-01-01T00:00:00Z",
            )],
        )
        responses.add(**g.list_service_principals(service_principals=[sp]))

        _check_saml_certificate_health(runner)

        # responses matches by URL path only; we have to inspect the
        # actual request URLs to verify the $select clause is wired.
        listing_calls = [
            c for c in responses.calls
            if "/servicePrincipals" in c.request.url
            and "keyCredentials" in c.request.url
        ]
        assert listing_calls, (
            "Production check never sent a /servicePrincipals request "
            f"with $select=keyCredentials. URLs called: "
            f"{[c.request.url for c in responses.calls]}"
        )
        # Both halves of the WD-CONN-102 select clause must be present.
        url = listing_calls[0].request.url
        assert "keyCredentials" in url
        assert "preferredTokenSigningKeyThumbprint" in url
        # SAML-only filter (not OIDC).
        assert "preferredSingleSignOnMode" in url
        assert "saml" in url


# ───────────────────────────────────────────────────────────────────────


class TestMalformedThumbprintIsNotFatal:
    """A malformed customKeyIdentifier (not valid base64 or wrong byte
    length) must not crash the check — it should still surface a
    diagnostic result so the operator sees something is off."""

    @responses.activate
    def test_malformed_custom_key_identifier_does_not_crash(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_saml_certificate_health

        # 10 bytes (not 20) — valid base64 but wrong length.
        short_b64 = base64.b64encode(b"\x00" * 10).decode("ascii")
        kc = g.key_credential(
            key_id="cert-short",
            custom_key_identifier=short_b64,
            end_date_time="2099-01-01T00:00:00Z",
        )
        sp = g.service_principal(
            sp_id="sp-workday-malformed",
            display_name="Workday Malformed",
            key_credentials=[kc],
        )
        responses.add(**g.list_service_principals(service_principals=[sp]))

        # Should not raise — the check should complete and produce a
        # result with the "(malformed)" annotation visible.
        results = _check_saml_certificate_health(runner)
        r = _result_by_id(results, "WD-CONN-102")
        assert "(malformed)" in r.result


# ───────────────────────────────────────────────────────────────────────


class TestNoGraphClientSkipped:
    """Runner without a graph attribute → SKIPPED (not a crash)."""

    def test_missing_graph_emits_skipped(self) -> None:
        from flightcheck.checks.workday import _check_saml_certificate_health

        runner = _MinimalRunner(graph=None)
        results = _check_saml_certificate_health(runner)
        r = _result_by_id(results, "WD-CONN-102")
        assert r.status == "Skipped"
        assert "Graph client unavailable" in r.result


class TestWireup:
    """WD-CONN-102 runs from run_workday_checks() even when no Workday
    flows or refs are installed — pre-deployment readiness."""

    def test_wired_in_before_early_return_guard(self) -> None:
        from flightcheck.checks.workday import run_workday_checks

        @dataclass
        class _Bare:
            graph: Any = None
            pp_admin: Any = None
            env_id: str | None = None
            _workday_flows: list | None = None
            config: dict | None = None

        bare = _Bare(_workday_flows=[], config={})

        # Patch _check_package_flavor so we don't have to mock
        # Dataverse for this wire-up test. Verify WD-CONN-102 still
        # runs (and gets SKIPPED because graph=None) even though the
        # downstream Workday block early-returns.
        with patch(
            "flightcheck.checks.workday._check_package_flavor",
            return_value=[],
        ):
            results = run_workday_checks(bare)

        ids = [r.checkpoint_id for r in results]
        assert "WD-CONN-102" in ids
        # Pin the early-return guard: with no flows and no detected
        # package flavor, downstream Workday workflow checks must not
        # fire. If this regresses, run_workday_checks() will start
        # emitting WD-FLOW-* results for tenants that have nothing
        # Workday-related installed.
        assert not any(i.startswith("WD-FLOW-") for i in ids)


class TestSkippedFlavorStaysNonInteractive:
    """Regression: the WD-CONN-102 setup-flow freeze.

    A Graph-only single-checkpoint run — ``--checkpoint WD-CONN-102`` /
    ``WD-CONN-010``, driven by skill-3
    (src/skills/setup/workday/provision-workday-entra-app.md) — authenticates
    ONLY Microsoft Graph, so ``_check_package_flavor`` (WD-PKG-001) has no
    Dataverse token and sets ``runner._workday_package_flavor = "skipped"``.

    The early-return guard in ``run_workday_checks`` must treat ``"skipped"``
    like ``None``/``"none"`` and stop before the deep Workday block. That block
    includes ``_check_workflows`` / ``_check_personal_data_write_permission``,
    which resolve a Test Employee ID and ISU username/password via
    ``input()`` / ``getpass.getpass()`` (gated only on ``sys.stdin.isatty()``).
    In VS Code's integrated terminal (a pty, so ``isatty()`` is True) those raw
    prompts never surface as pop-ups and nothing feeds stdin, so the headless,
    skill-launched process blocks forever — the reported "chat freeze".

    TODO: when the guard is fixed, this test stays green. If someone narrows
    the guard back to ``(None, "none")``, the ``input``/``getpass`` sentinels
    below fire and this test goes red.
    """

    def test_skipped_flavor_early_returns_without_prompting(self) -> None:
        from flightcheck.checks.workday import run_workday_checks

        @dataclass
        class _Bare:
            graph: Any = None
            pp_admin: Any = None
            env_url: str | None = None
            dv_token: str | None = None
            env_id: str | None = None
            _workday_flows: list | None = None
            config: dict | None = None

        # No env_url / dv_token => the REAL _check_package_flavor takes its
        # no-token branch and sets flavor="skipped" (no network call). This is
        # exactly the state a Graph-only single-checkpoint run produces.
        bare = _Bare(_workday_flows=[], config={})

        def _fail_on_prompt(*_args, **_kwargs):
            raise AssertionError(
                "run_workday_checks prompted for input on a Graph-only "
                "(flavor='skipped') run — the WD-CONN-102 freeze regressed. "
                "The deep Workday block must early-return when Dataverse is "
                "unavailable."
            )

        # Simulate the VS Code pty (isatty True) so the interactive prompt
        # guards WOULD fire if the deep block ran, and turn any prompt attempt
        # into a loud failure instead of a hang on stdin.
        with patch("sys.stdin.isatty", return_value=True), \
                patch("builtins.input", _fail_on_prompt), \
                patch(
                    "flightcheck.checks.workday.getpass.getpass",
                    _fail_on_prompt,
                ):
            results = run_workday_checks(bare)

        ids = [r.checkpoint_id for r in results]

        # WD-PKG-001 ran and recorded the no-Dataverse "skipped" state.
        pkg = _result_by_id(results, "WD-PKG-001")
        assert pkg.status == "Skipped"
        assert "Dataverse token not available" in pkg.result

        # The Graph-only pre-early-return checks still run: WD-CONN-102 is the
        # checkpoint the setup flow actually asked for (graph=None => Skipped).
        assert "WD-CONN-102" in ids

        # The deep Workday block must NOT run — none of the checks that need
        # Dataverse/ISU creds. Their presence would mean the guard let a
        # headless run reach the interactive credential prompts.
        assert not any(i.startswith("WD-WF-") for i in ids)
        assert not any(i.startswith("WD-FLOW-") for i in ids)
        assert not any(i.startswith("WD-ENV-") for i in ids)
        assert "WD-SEC-003" not in ids
        assert "WD-CONN-013" not in ids
