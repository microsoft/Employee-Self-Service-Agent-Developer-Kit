# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end tests for the ServiceNow Entra-app FlightCheck checks (setup
skills 4/5).

Mocks the Microsoft Graph endpoints each check reads with ``responses``, then
runs the ACTUAL production emitters from
``solutions/ess-maker-skills/scripts/flightcheck/checks/servicenow_entra.py``
against the mocked tenant state. Graph is a ``validatable``-tier API (public
CSDL + MS Learn), so no cassette is required.

Unlike the Workday Entra checks, the ServiceNow apps are custom registrations
with NO gallery ``applicationTemplateId``; resolution is driven entirely by the
identifiers the setup playbooks persist (``entra.*`` / ``certificate.*``). These
tests therefore supply those identifiers via the runner config and mock the
object-id / appId-filter lookups the checks perform.

Checkpoints under test (each runnable in isolation via ``--checkpoint``):

* ``SN-ENTRA-SCOPE-001`` — the ServiceNow sign-in app exposes
  ``user_impersonation``, pre-authorizes the Power Platform ServiceNow
  connector (``c26b24aa``), and requests the Graph delegated permissions
  openid / profile / User.Read.
* ``SN-ENTRA-CONSENT-001`` — tenant-wide admin consent
  (``oauth2PermissionGrant`` with consentType ``AllPrincipals``) covering those
  three scopes.
* ``SN-ENTRA-CERT-001`` — the ServiceNow service-account app (App B) holds a
  non-expired ``AsymmetricX509Cert`` key credential.

Per ``tests/AGENTS.md`` every GOOD/BAD/WARNING test asserts on specific phrases
from BOTH ``result`` and ``remediation`` (not just ``status``).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

import pytest
import responses

from tests.conftest import require_validated_mock
from tests.mocks import graph as gr

require_validated_mock(gr)


# The Power Platform ServiceNow connector appId the sign-in app pre-authorizes.
SN_CONNECTOR_APP_ID = "c26b24aa-7874-4e06-ad55-7d06b1f79b63"

# Stable identifiers used across the tests (arbitrary but internally consistent).
SN_APP_ID = "11111111-1111-1111-1111-111111111111"
SN_APP_OBJECT_ID = "22222222-2222-2222-2222-222222222222"
SN_SP_ID = "33333333-3333-3333-3333-333333333333"
SN_APPB_ID = "44444444-4444-4444-4444-444444444444"
SN_APPB_OBJECT_ID = "55555555-5555-5555-5555-555555555555"

USER_CONFIG = {"entra": {"appId": SN_APP_ID, "objectId": SN_APP_OBJECT_ID}}
CERT_CONFIG = {
    "certificate": {"appBClientId": SN_APPB_ID, "appBObjectId": SN_APPB_OBJECT_ID}
}


# ───────────────────────────────────────────────────────────────────────
# Test doubles
# ───────────────────────────────────────────────────────────────────────


@dataclass
class _MinimalRunner:
    """Stand-in for FlightCheckRunner. ``run_servicenow_entra_checks`` reads
    only ``runner.graph`` and ``runner.config``."""

    graph: Any
    config: dict[str, Any] = field(default_factory=dict)


class _RaisingGraph:
    """Fake Graph client whose first call raises — exercises the per-emitter
    WARNING guard without any network. Truthy so emitters don't short-circuit
    to SKIPPED."""

    def __bool__(self) -> bool:
        return True

    def __getattr__(self, _name: str):
        def _boom(*_a: Any, **_k: Any):
            raise RuntimeError("boom")

        return _boom


def _make_graph_client(tenant_id: str = gr.MOCK_TENANT_ID):
    from flightcheck.graph_client import GraphClient

    client = GraphClient(tenant_id)
    client._token = "REDACTED_TOKEN"  # noqa: S105 — test fixture
    return client


@pytest.fixture
def graph():
    return _make_graph_client()


@pytest.fixture(autouse=True)
def _isolate_connect_config(monkeypatch):
    """Ensure the config-file fallback never reads a real
    ``.local/connect/servicenow/config.json`` from the test host — every test
    supplies identifiers via the runner config instead."""
    from flightcheck.checks import servicenow_entra

    monkeypatch.setattr(servicenow_entra, "_load_connect_config", lambda: {})


def _sn_application(
    *,
    object_id: str = SN_APP_OBJECT_ID,
    app_id: str = SN_APP_ID,
    expose_scope: bool = True,
    preauthorize_connector: bool = True,
    graph_permissions: bool = True,
) -> dict[str, Any]:
    """A ServiceNow sign-in app — the Workday builder parameterized with the
    ServiceNow connector appId (there is no gallery template)."""
    return gr.application(
        object_id=object_id,
        app_id=app_id,
        display_name="ServiceNow Sign-In",
        expose_scope=expose_scope,
        preauthorize_connector=preauthorize_connector,
        connector_app_id=SN_CONNECTOR_APP_ID,
        graph_permissions=graph_permissions,
    )


def _appb_with_credentials(creds: list[dict[str, Any]]) -> dict[str, Any]:
    """App B (service-account app) carrying the given keyCredentials."""
    return {
        "id": SN_APPB_OBJECT_ID,
        "appId": SN_APPB_ID,
        "displayName": "ServiceNow Service Account",
        "keyCredentials": creds,
    }


# ───────────────────────────────────────────────────────────────────────
# SN-ENTRA-SCOPE-001 — scope exposed + connector pre-auth + Graph perms
# ───────────────────────────────────────────────────────────────────────


class TestScopeExposed:
    @responses.activate
    def test_fully_configured_returns_passed(self, graph) -> None:
        from flightcheck.checks.servicenow_entra import _check_scope_exposed

        responses.add(**gr.get_application(object_id=SN_APP_OBJECT_ID, app=_sn_application()))

        result = _check_scope_exposed(graph, USER_CONFIG)[0]

        assert result.checkpoint_id == "SN-ENTRA-SCOPE-001"
        assert result.category == "ServiceNow Entra App"
        assert result.status == "Passed"
        assert result.priority == "Critical"
        assert "user_impersonation" in result.result
        assert SN_CONNECTOR_APP_ID in result.result
        assert "openid, profile, User.Read" in result.result

    @responses.activate
    def test_missing_scope_returns_failed(self, graph) -> None:
        from flightcheck.checks.servicenow_entra import _check_scope_exposed

        responses.add(**gr.get_application(
            object_id=SN_APP_OBJECT_ID, app=_sn_application(expose_scope=False)))

        result = _check_scope_exposed(graph, USER_CONFIG)[0]

        assert result.status == "Failed"
        assert "'user_impersonation' API scope is not exposed" in result.result
        assert "Expose an API" in result.remediation
        assert SN_CONNECTOR_APP_ID in result.remediation

    @responses.activate
    def test_missing_preauth_returns_failed(self, graph) -> None:
        from flightcheck.checks.servicenow_entra import _check_scope_exposed

        responses.add(**gr.get_application(
            object_id=SN_APP_OBJECT_ID,
            app=_sn_application(preauthorize_connector=False)))

        result = _check_scope_exposed(graph, USER_CONFIG)[0]

        assert result.status == "Failed"
        collapsed = " ".join(result.result.split())
        assert "is not pre-authorized" in collapsed
        assert SN_CONNECTOR_APP_ID in collapsed
        assert "pre-authorize the ServiceNow connector" in result.remediation

    @responses.activate
    def test_missing_graph_perms_returns_failed(self, graph) -> None:
        from flightcheck.checks.servicenow_entra import _check_scope_exposed

        responses.add(**gr.get_application(
            object_id=SN_APP_OBJECT_ID,
            app=_sn_application(graph_permissions=False)))

        result = _check_scope_exposed(graph, USER_CONFIG)[0]

        assert result.status == "Failed"
        collapsed = " ".join(result.result.split())
        assert "Graph delegated permission(s) not requested" in collapsed
        assert "openid" in collapsed and "User.Read" in collapsed
        assert "API permissions" in result.remediation

    @responses.activate
    def test_resolves_via_appid_filter_when_no_object_id(self, graph) -> None:
        from flightcheck.checks.servicenow_entra import _check_scope_exposed

        # Only appId hint → resolution falls back to the /applications $filter.
        responses.add(**gr.list_applications(applications=[_sn_application()]))

        result = _check_scope_exposed(graph, {"entra": {"appId": SN_APP_ID}})[0]

        assert result.status == "Passed"
        assert "user_impersonation" in result.result

    def test_no_graph_returns_skipped(self) -> None:
        from flightcheck.checks.servicenow_entra import _check_scope_exposed

        result = _check_scope_exposed(None, USER_CONFIG)[0]

        assert result.status == "Skipped"
        assert "Graph client not available" in result.result

    def test_no_config_returns_skipped(self) -> None:
        from flightcheck.checks.servicenow_entra import _check_scope_exposed

        result = _check_scope_exposed(_make_graph_client(), {})[0]

        assert result.status == "Skipped"
        assert "No ServiceNow Entra app identifiers found" in result.result
        assert "S4.1" in result.remediation

    @responses.activate
    def test_app_not_found_returns_skipped(self, graph) -> None:
        from flightcheck.checks.servicenow_entra import _check_scope_exposed

        # Object-id lookup 404s and the appId filter returns nothing.
        responses.add(
            method="GET",
            url=f"{gr.GRAPH_BASE}/applications/{SN_APP_OBJECT_ID}",
            status=404,
            json={"error": {"code": "Request_ResourceNotFound"}},
        )
        responses.add(**gr.list_applications(applications=[]))

        result = _check_scope_exposed(graph, USER_CONFIG)[0]

        assert result.status == "Skipped"
        assert "was not found in this tenant" in result.result
        assert "S4.1" in result.remediation


# ───────────────────────────────────────────────────────────────────────
# SN-ENTRA-CONSENT-001 — admin consent granted
# ───────────────────────────────────────────────────────────────────────


class TestAdminConsent:
    @responses.activate
    def test_admin_consent_granted_returns_passed(self, graph) -> None:
        from flightcheck.checks.servicenow_entra import _check_admin_consent

        responses.add(**gr.list_service_principals(
            service_principals=[gr.service_principal(
                sp_id=SN_SP_ID, app_id=SN_APP_ID, display_name="ServiceNow",
                application_template_id=None)]))
        responses.add(**gr.list_oauth2_permission_grants(
            grants=[gr.oauth2_permission_grant(
                client_id=SN_SP_ID, scope="openid profile User.Read")]))

        result = _check_admin_consent(graph, USER_CONFIG)[0]

        assert result.checkpoint_id == "SN-ENTRA-CONSENT-001"
        assert result.status == "Passed"
        assert result.priority == "Critical"
        assert "admin consent granted" in result.result.lower()
        assert "openid, profile, User.Read" in result.result

    @responses.activate
    def test_no_grant_returns_failed(self, graph) -> None:
        from flightcheck.checks.servicenow_entra import _check_admin_consent

        responses.add(**gr.list_service_principals(
            service_principals=[gr.service_principal(
                sp_id=SN_SP_ID, app_id=SN_APP_ID, application_template_id=None)]))
        responses.add(**gr.list_oauth2_permission_grants(grants=[]))

        result = _check_admin_consent(graph, USER_CONFIG)[0]

        assert result.status == "Failed"
        assert "No tenant-wide admin consent" in result.result
        assert "Grant admin consent" in result.remediation
        assert "consent-capable role" in result.remediation

    @responses.activate
    def test_user_only_consent_returns_failed(self, graph) -> None:
        from flightcheck.checks.servicenow_entra import _check_admin_consent

        responses.add(**gr.list_service_principals(
            service_principals=[gr.service_principal(
                sp_id=SN_SP_ID, app_id=SN_APP_ID, application_template_id=None)]))
        responses.add(**gr.list_oauth2_permission_grants(
            grants=[gr.oauth2_permission_grant(
                client_id=SN_SP_ID, consent_type="Principal")]))

        result = _check_admin_consent(graph, USER_CONFIG)[0]

        assert result.status == "Failed"
        assert "No tenant-wide admin consent" in result.result
        assert "AllPrincipals" in result.result

    @responses.activate
    def test_partial_consent_returns_failed(self, graph) -> None:
        from flightcheck.checks.servicenow_entra import _check_admin_consent

        responses.add(**gr.list_service_principals(
            service_principals=[gr.service_principal(
                sp_id=SN_SP_ID, app_id=SN_APP_ID, application_template_id=None)]))
        responses.add(**gr.list_oauth2_permission_grants(
            grants=[gr.oauth2_permission_grant(
                client_id=SN_SP_ID, scope="openid profile")]))

        result = _check_admin_consent(graph, USER_CONFIG)[0]

        assert result.status == "Failed"
        assert "does not cover" in result.result
        assert "user.read" in result.result
        assert "Re-grant admin consent" in result.remediation

    @responses.activate
    def test_sp_not_found_returns_skipped(self, graph) -> None:
        from flightcheck.checks.servicenow_entra import _check_admin_consent

        responses.add(**gr.list_service_principals(service_principals=[]))

        result = _check_admin_consent(graph, USER_CONFIG)[0]

        assert result.status == "Skipped"
        assert "enterprise application was not found" in result.result

    def test_no_config_returns_skipped(self) -> None:
        from flightcheck.checks.servicenow_entra import _check_admin_consent

        result = _check_admin_consent(_make_graph_client(), {})[0]

        assert result.status == "Skipped"
        assert "No ServiceNow Entra app identifiers found" in result.result

    def test_no_graph_returns_skipped(self) -> None:
        from flightcheck.checks.servicenow_entra import _check_admin_consent

        result = _check_admin_consent(None, USER_CONFIG)[0]

        assert result.status == "Skipped"


# ───────────────────────────────────────────────────────────────────────
# SN-ENTRA-CERT-001 — certificate credential on the service-account app
# ───────────────────────────────────────────────────────────────────────


class TestCertificate:
    @responses.activate
    def test_valid_cert_returns_passed(self, graph) -> None:
        from flightcheck.checks.servicenow_entra import _check_certificate

        cred = gr.key_credential(usage="Verify", type_="AsymmetricX509Cert")
        responses.add(**gr.get_application(
            object_id=SN_APPB_OBJECT_ID,
            app=_appb_with_credentials([cred])))

        result = _check_certificate(graph, CERT_CONFIG)[0]

        assert result.checkpoint_id == "SN-ENTRA-CERT-001"
        assert result.status == "Passed"
        assert result.priority == "Critical"
        assert "valid certificate credential" in result.result
        assert "AsymmetricX509Cert" in result.result

    @responses.activate
    def test_no_cert_returns_failed(self, graph) -> None:
        from flightcheck.checks.servicenow_entra import _check_certificate

        responses.add(**gr.get_application(
            object_id=SN_APPB_OBJECT_ID, app=_appb_with_credentials([])))

        result = _check_certificate(graph, CERT_CONFIG)[0]

        assert result.status == "Failed"
        assert "no certificate (AsymmetricX509Cert) key credential" in result.result
        assert "Upload the public signing certificate" in result.remediation

    @responses.activate
    def test_expired_cert_returns_failed(self, graph) -> None:
        from flightcheck.checks.servicenow_entra import _check_certificate

        cred = gr.key_credential(
            usage="Verify", type_="AsymmetricX509Cert",
            end_date_time="2000-01-01T00:00:00Z")
        responses.add(**gr.get_application(
            object_id=SN_APPB_OBJECT_ID,
            app=_appb_with_credentials([cred])))

        result = _check_certificate(graph, CERT_CONFIG)[0]

        assert result.status == "Failed"
        assert "all are expired" in result.result
        assert "Upload a current signing certificate" in result.remediation

    @responses.activate
    def test_thumbprint_match_returns_passed(self, graph) -> None:
        from flightcheck.checks.servicenow_entra import _check_certificate

        thumb_hex = "A1B2C3D4E5F60718293A4B5C6D7E8F9001122334"
        cki = base64.b64encode(bytes.fromhex(thumb_hex)).decode()
        cred = gr.key_credential(
            usage="Verify", type_="AsymmetricX509Cert",
            custom_key_identifier=cki)
        responses.add(**gr.get_application(
            object_id=SN_APPB_OBJECT_ID,
            app=_appb_with_credentials([cred])))

        config = {"certificate": {**CERT_CONFIG["certificate"],
                                  "certThumbprint": thumb_hex}}
        result = _check_certificate(graph, config)[0]

        assert result.status == "Passed"
        assert "valid certificate credential" in result.result

    @responses.activate
    def test_thumbprint_mismatch_returns_warning(self, graph) -> None:
        from flightcheck.checks.servicenow_entra import _check_certificate

        cred = gr.key_credential(usage="Verify", type_="AsymmetricX509Cert")
        responses.add(**gr.get_application(
            object_id=SN_APPB_OBJECT_ID,
            app=_appb_with_credentials([cred])))

        config = {"certificate": {**CERT_CONFIG["certificate"],
                                  "certThumbprint": "00" * 20}}
        result = _check_certificate(graph, config)[0]

        assert result.status == "Warning"
        assert "recorded in config" in result.result
        assert "certificate.certThumbprint" in result.remediation

    @responses.activate
    def test_appb_not_found_returns_skipped(self, graph) -> None:
        from flightcheck.checks.servicenow_entra import _check_certificate

        responses.add(
            method="GET",
            url=f"{gr.GRAPH_BASE}/applications/{SN_APPB_OBJECT_ID}",
            status=404,
            json={"error": {"code": "Request_ResourceNotFound"}},
        )
        responses.add(**gr.list_applications(applications=[]))

        result = _check_certificate(graph, CERT_CONFIG)[0]

        assert result.status == "Skipped"
        assert "was not found in this tenant" in result.result

    def test_no_config_returns_skipped(self) -> None:
        from flightcheck.checks.servicenow_entra import _check_certificate

        result = _check_certificate(_make_graph_client(), {})[0]

        assert result.status == "Skipped"
        assert "No ServiceNow Entra app identifiers found" in result.result

    def test_no_graph_returns_skipped(self) -> None:
        from flightcheck.checks.servicenow_entra import _check_certificate

        result = _check_certificate(None, CERT_CONFIG)[0]

        assert result.status == "Skipped"


# ───────────────────────────────────────────────────────────────────────
# run_servicenow_entra_checks — orchestration + per-emitter WARNING guard
# ───────────────────────────────────────────────────────────────────────


class TestRunAll:
    def test_emits_all_three_checkpoints_when_graph_absent(self) -> None:
        from flightcheck.checks.servicenow_entra import run_servicenow_entra_checks

        runner = _MinimalRunner(graph=None, config={})
        results = run_servicenow_entra_checks(runner)

        ids = {r.checkpoint_id for r in results}
        assert ids == {
            "SN-ENTRA-SCOPE-001",
            "SN-ENTRA-CONSENT-001",
            "SN-ENTRA-CERT-001",
        }
        assert all(r.status == "Skipped" for r in results)

    def test_emitter_exception_degrades_to_warning(self) -> None:
        from flightcheck.checks.servicenow_entra import run_servicenow_entra_checks

        runner = _MinimalRunner(
            graph=_RaisingGraph(),
            config={**USER_CONFIG, **CERT_CONFIG},
        )
        results = run_servicenow_entra_checks(runner)

        assert len(results) == 3
        assert all(r.status == "Warning" for r in results)
        assert all("Unable to verify" in r.result for r in results)
