# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end tests for the Workday Entra-app FlightCheck checks (skill-3).

Mocks the Microsoft Graph endpoints each check reads with ``responses``,
then runs the ACTUAL production emitters from
``solutions/ess-maker-skills/scripts/flightcheck/checks/entra_app.py``
against the mocked tenant state. Graph is a ``validatable``-tier API
(public CSDL + MS Learn), so no cassette is required — see
``tests/fixtures/cassettes/INDEX.md`` "API tier registry" (the
/applications, /oauth2PermissionGrants, /servicePrincipals and
/applicationTemplates endpoints are all listed there).

Checkpoints under test (each runnable in isolation via ``--checkpoint``):

* ``WD-ENTRA-SCOPE-001`` — the Workday integration app exposes
  ``user_impersonation``, pre-authorizes the Workday connector
  (``4e4707ca``), and requests the Graph delegated permissions
  openid / profile / User.Read.
* ``WD-ENTRA-CONSENT-001`` — tenant-wide admin consent
  (``oauth2PermissionGrant`` with consentType ``AllPrincipals``) covering
  those three scopes.
* ``WD-ASSIGN-001`` — enterprise-app user assignment. Delegates to the
  shared ``build_assignment_results`` helper (exhaustively covered by
  ``test_authentication.py`` under AUTH-005); here we only pin that it
  emits under the WD-ASSIGN-001 / "Entra App" identity.
* ``WD-ENTRA-NAMEID-001`` — a ``claimsMappingPolicy`` overriding the SAML
  NameID claim (degrades to MANUAL when the policy route is unreadable).
* ``WD-ENTRA-SIGNOPT-001`` — portal-only signing option, always MANUAL.

Per ``tests/AGENTS.md`` every GOOD/BAD/WARNING test asserts on specific
phrases from BOTH ``result`` and ``remediation`` (not just ``status``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest
import responses
from responses import matchers

from tests.conftest import require_validated_mock
from tests.mocks import graph as gr

require_validated_mock(gr)


# ───────────────────────────────────────────────────────────────────────
# Test doubles
# ───────────────────────────────────────────────────────────────────────


@dataclass
class _MinimalRunner:
    """Stand-in for FlightCheckRunner. ``run_entra_app_checks`` reads only
    ``runner.graph`` and ``runner.config``."""

    graph: Any
    config: dict[str, Any] = field(default_factory=dict)


class _RaisingGraph:
    """Fake Graph client whose first call raises — exercises the
    per-emitter WARNING guard in ``run_entra_app_checks`` without any
    network. Truthy so the emitters don't short-circuit to SKIPPED."""

    def __bool__(self) -> bool:
        return True

    def __getattr__(self, _name: str):
        def _boom(*_a: Any, **_k: Any):
            raise RuntimeError("boom")

        return _boom


def _make_graph_client(tenant_id: str = gr.MOCK_TENANT_ID):
    """Real GraphClient with a fake bearer token so its requests are
    intercepted by ``responses`` rather than hitting Graph."""
    from flightcheck.graph_client import GraphClient

    client = GraphClient(tenant_id)
    client._token = "REDACTED_TOKEN"  # noqa: S105 — test fixture
    return client


@pytest.fixture
def graph():
    return _make_graph_client()


def _result_by_id(results: list, checkpoint_id: str):
    matches = [r for r in results if r.checkpoint_id == checkpoint_id]
    assert len(matches) >= 1, (
        f"Expected at least one result for {checkpoint_id}, got "
        f"{[r.checkpoint_id for r in results]}"
    )
    return matches[0]


def _register_app_discovery(*, service_principals=None, applications=None) -> None:
    """Register the two lookups ``_resolve_workday_app`` always performs:
    the gallery template lookup and the servicePrincipals lookup, plus the
    /applications lookup when an SP is found."""
    responses.add(**gr.list_application_templates())
    responses.add(**gr.list_service_principals(service_principals=service_principals))
    if applications is not None:
        responses.add(**gr.list_applications(applications=applications))


def _register_grants_for(client_id: str, grants) -> None:
    """Register a /oauth2PermissionGrants mock scoped to one ``clientId``.

    Unlike the default filter-agnostic mock, this matches on the exact
    ``$filter=clientId eq '<id>'`` the consent check sends, so a test can
    register *different* grants per service principal and thereby prove
    WD-ENTRA-CONSENT-001 queried the SP it actually intended to."""
    kwargs = gr.list_oauth2_permission_grants(grants=grants)
    kwargs["match"] = [
        matchers.query_param_matcher({"$filter": f"clientId eq '{client_id}'"})
    ]
    responses.add(**kwargs)


# ───────────────────────────────────────────────────────────────────────
# WD-ENTRA-SCOPE-001 — scope exposed + connector pre-auth + Graph perms
# ───────────────────────────────────────────────────────────────────────


class TestScopeExposed:
    @responses.activate
    def test_fully_configured_returns_passed(self, graph) -> None:
        from flightcheck.checks.entra_app import _check_scope_exposed

        _register_app_discovery(applications=[gr.application()])

        result = _check_scope_exposed(graph, {})[0]

        assert result.checkpoint_id == "WD-ENTRA-SCOPE-001"
        assert result.category == "Entra App"
        assert result.status == "Passed"
        assert result.priority == "Critical"
        assert "user_impersonation" in result.result
        assert gr.WORKDAY_CONNECTOR_APP_ID in result.result
        assert "openid, profile, User.Read" in result.result

    @responses.activate
    def test_missing_scope_returns_failed(self, graph) -> None:
        from flightcheck.checks.entra_app import _check_scope_exposed

        _register_app_discovery(applications=[gr.application(expose_scope=False)])

        result = _check_scope_exposed(graph, {})[0]

        assert result.status == "Failed"
        assert "'user_impersonation' API scope is not exposed" in result.result
        assert "Expose an API" in result.remediation
        assert gr.WORKDAY_CONNECTOR_APP_ID in result.remediation

    @responses.activate
    def test_missing_preauth_returns_failed(self, graph) -> None:
        from flightcheck.checks.entra_app import _check_scope_exposed

        _register_app_discovery(
            applications=[gr.application(preauthorize_connector=False)]
        )

        result = _check_scope_exposed(graph, {})[0]

        assert result.status == "Failed"
        collapsed = " ".join(result.result.split())
        assert "is not pre-authorized" in collapsed
        assert gr.WORKDAY_CONNECTOR_APP_ID in collapsed
        assert "pre-authorize the Workday connector" in result.remediation

    @responses.activate
    def test_missing_graph_perms_returns_failed(self, graph) -> None:
        from flightcheck.checks.entra_app import _check_scope_exposed

        _register_app_discovery(applications=[gr.application(graph_permissions=False)])

        result = _check_scope_exposed(graph, {})[0]

        assert result.status == "Failed"
        collapsed = " ".join(result.result.split())
        assert "Graph delegated permission(s) not requested" in collapsed
        assert "openid" in collapsed and "User.Read" in collapsed
        assert "API permissions" in result.remediation

    def test_no_graph_returns_skipped(self) -> None:
        from flightcheck.checks.entra_app import _check_scope_exposed

        result = _check_scope_exposed(None, {})[0]

        assert result.status == "Skipped"
        assert "Graph client not available" in result.result

    @responses.activate
    def test_app_not_found_returns_skipped(self, graph) -> None:
        from flightcheck.checks.entra_app import _check_scope_exposed

        # Template resolves, but no service principal exists → app not found.
        _register_app_discovery(service_principals=[])

        result = _check_scope_exposed(graph, {})[0]

        assert result.status == "Skipped"
        assert "No Workday integration app registration found" in result.result
        assert "provision-workday-entra-app" in result.remediation


# ───────────────────────────────────────────────────────────────────────
# WD-ENTRA-CONSENT-001 — admin consent granted
# ───────────────────────────────────────────────────────────────────────


class TestAdminConsent:
    @responses.activate
    def test_admin_consent_granted_returns_passed(self, graph) -> None:
        from flightcheck.checks.entra_app import _check_admin_consent

        _register_app_discovery(applications=[gr.application()])
        responses.add(**gr.list_oauth2_permission_grants())

        result = _check_admin_consent(graph, {})[0]

        assert result.checkpoint_id == "WD-ENTRA-CONSENT-001"
        assert result.status == "Passed"
        assert result.priority == "Critical"
        assert "admin consent granted" in result.result.lower()
        assert "openid, profile, User.Read" in result.result

    @responses.activate
    def test_no_grant_returns_failed(self, graph) -> None:
        from flightcheck.checks.entra_app import _check_admin_consent

        _register_app_discovery(applications=[gr.application()])
        responses.add(**gr.list_oauth2_permission_grants(grants=[]))

        result = _check_admin_consent(graph, {})[0]

        assert result.status == "Failed"
        assert "No tenant-wide admin consent" in result.result
        assert "Grant admin consent" in result.remediation
        assert "consent-capable role" in result.remediation

    @responses.activate
    def test_user_only_consent_returns_failed(self, graph) -> None:
        from flightcheck.checks.entra_app import _check_admin_consent

        _register_app_discovery(applications=[gr.application()])
        # A user-scoped ("Principal") grant does NOT satisfy admin consent.
        responses.add(
            **gr.list_oauth2_permission_grants(
                grants=[gr.oauth2_permission_grant(consent_type="Principal")]
            )
        )

        result = _check_admin_consent(graph, {})[0]

        assert result.status == "Failed"
        assert "No tenant-wide admin consent" in result.result
        assert "AllPrincipals" in result.result

    @responses.activate
    def test_partial_consent_returns_failed(self, graph) -> None:
        from flightcheck.checks.entra_app import _check_admin_consent

        _register_app_discovery(applications=[gr.application()])
        responses.add(
            **gr.list_oauth2_permission_grants(
                grants=[gr.oauth2_permission_grant(scope="openid profile")]
            )
        )

        result = _check_admin_consent(graph, {})[0]

        assert result.status == "Failed"
        assert "does not cover" in result.result
        assert "user.read" in result.result
        assert "Re-grant admin consent" in result.remediation

    def test_no_graph_returns_skipped(self) -> None:
        from flightcheck.checks.entra_app import _check_admin_consent

        result = _check_admin_consent(None, {})[0]

        assert result.status == "Skipped"


class TestSelectWorkdaySP:
    """Unit coverage for ``_select_workday_sp`` — the disambiguation that
    picks the operator's configured Workday SP out of the several that a
    tenant may provision from the same SSO gallery template."""

    def test_prefers_sp_matching_config_app_id(self) -> None:
        from flightcheck.checks.entra_app import _select_workday_sp

        sps = [{"id": "sp-a", "appId": "app-a"}, {"id": "sp-b", "appId": "app-b"}]

        assert _select_workday_sp(sps, "app-b")["id"] == "sp-b"

    def test_match_is_case_insensitive(self) -> None:
        from flightcheck.checks.entra_app import _select_workday_sp

        sps = [{"id": "sp-a", "appId": "APP-A"}, {"id": "sp-b", "appId": "APP-B"}]

        assert _select_workday_sp(sps, "app-b")["id"] == "sp-b"

    def test_falls_back_to_first_when_hint_matches_nothing(self) -> None:
        from flightcheck.checks.entra_app import _select_workday_sp

        sps = [{"id": "sp-a", "appId": "app-a"}, {"id": "sp-b", "appId": "app-b"}]

        assert _select_workday_sp(sps, "app-zzz")["id"] == "sp-a"

    def test_falls_back_to_first_when_no_hint(self) -> None:
        from flightcheck.checks.entra_app import _select_workday_sp

        sps = [{"id": "sp-a", "appId": "app-a"}, {"id": "sp-b", "appId": "app-b"}]

        assert _select_workday_sp(sps, "")["id"] == "sp-a"

    def test_empty_list_returns_none(self) -> None:
        from flightcheck.checks.entra_app import _select_workday_sp

        assert _select_workday_sp([], "app-a") is None


class TestWorkdayHints:
    """``_workday_hints`` resolves the entraAppId/entraAppObjectId disambiguation
    hints from ``runner.config`` first, then falls back to the Workday connect
    config (``.local/connect/workday/config.json``) — the file the playbooks
    actually write but the FlightCheck runner does not load."""

    @staticmethod
    def _write_connect_config(tmp_path, payload: dict) -> None:
        connect = tmp_path / ".local" / "connect" / "workday"
        connect.mkdir(parents=True)
        (connect / "config.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def test_runner_config_wins(self, tmp_path, monkeypatch) -> None:
        from flightcheck.checks.entra_app import _workday_hints

        self._write_connect_config(tmp_path, {"entraAppId": "connect-app"})
        monkeypatch.chdir(tmp_path)

        assert _workday_hints(
            {"entraAppId": "cfg-app", "entraAppObjectId": "cfg-obj"}
        ) == ("cfg-app", "cfg-obj")

    def test_falls_back_to_connect_config(self, tmp_path, monkeypatch) -> None:
        from flightcheck.checks.entra_app import _workday_hints

        self._write_connect_config(
            tmp_path, {"entraAppId": "app-x", "entraAppObjectId": "obj-x"}
        )
        monkeypatch.chdir(tmp_path)

        assert _workday_hints({}) == ("app-x", "obj-x")

    def test_partial_runner_config_completed_from_connect(
        self, tmp_path, monkeypatch
    ) -> None:
        from flightcheck.checks.entra_app import _workday_hints

        self._write_connect_config(tmp_path, {"entraAppObjectId": "obj-x"})
        monkeypatch.chdir(tmp_path)

        # entraAppId from runner.config; entraAppObjectId filled from connect.
        assert _workday_hints({"entraAppId": "app-r"}) == ("app-r", "obj-x")

    def test_missing_connect_config_returns_empty(
        self, tmp_path, monkeypatch
    ) -> None:
        from flightcheck.checks.entra_app import _workday_hints

        monkeypatch.chdir(tmp_path)

        assert _workday_hints({}) == ("", "")


class TestAdminConsentDisambiguatesServicePrincipal:
    """Regression (live-observed false FAILED): when a tenant has several
    service principals provisioned from the same Workday SSO gallery
    template, consent must be evaluated against the app THIS deployment
    configured (``config['entraAppId']``) — not whichever SP the directory
    returns first. The reproduction had ``sps[0]`` be an unrelated 'Workday'
    app holding only ``user_impersonation`` while the configured app carried
    the full openid/profile/User.Read admin grant."""

    # An unrelated Workday-template SP that sorts first and lacks full consent.
    _OTHER_SP_ID = "00000000-0000-0000-0000-0000000050aa"
    _OTHER_APP_ID = "00000000-0000-0000-0000-0000000050ab"
    # The app this deployment actually configured (config entraAppId).
    _OURS_SP_ID = "00000000-0000-0000-0000-0000000050cc"
    _OURS_APP_ID = "00000000-0000-0000-0000-0000000050cd"

    @pytest.fixture(autouse=True)
    def _isolate_from_connect_config(self, tmp_path, monkeypatch):
        """Run in a clean cwd so ``_workday_hints`` cannot pick up a stray
        ``.local/connect/workday/config.json`` — these tests drive the hint
        exclusively through ``runner.config``."""
        monkeypatch.chdir(tmp_path)

    def _register_two_workday_sps(self) -> None:
        _register_app_discovery(
            service_principals=[
                gr.service_principal(
                    sp_id=self._OTHER_SP_ID,
                    app_id=self._OTHER_APP_ID,
                    display_name="Workday",
                ),
                gr.service_principal(
                    sp_id=self._OURS_SP_ID,
                    app_id=self._OURS_APP_ID,
                    display_name="Workday MSFT DPT6",
                ),
            ],
            applications=[gr.application(app_id=self._OURS_APP_ID)],
        )
        _register_grants_for(
            self._OTHER_SP_ID,
            [gr.oauth2_permission_grant(
                client_id=self._OTHER_SP_ID, scope="user_impersonation")],
        )
        _register_grants_for(
            self._OURS_SP_ID,
            [gr.oauth2_permission_grant(
                client_id=self._OURS_SP_ID, scope="openid profile User.Read")],
        )

    @responses.activate
    def test_config_hint_selects_configured_sp_returns_passed(self, graph) -> None:
        from flightcheck.checks.entra_app import _check_admin_consent

        self._register_two_workday_sps()

        result = _check_admin_consent(graph, {"entraAppId": self._OURS_APP_ID})[0]

        assert result.status == "Passed"
        assert "openid, profile, User.Read" in result.result

    @responses.activate
    def test_without_hint_first_sp_wins_returns_failed(self, graph) -> None:
        from flightcheck.checks.entra_app import _check_admin_consent

        self._register_two_workday_sps()

        # No hint → falls back to sps[0] (the unrelated app), whose only
        # tenant-wide grant is user_impersonation → all three scopes missing.
        result = _check_admin_consent(graph, {})[0]

        assert result.status == "Failed"
        assert "does not cover" in result.result
        assert "user.read" in result.result


# ───────────────────────────────────────────────────────────────────────
# WD-ASSIGN-001 — enterprise-app user assignment (shared helper)
# ───────────────────────────────────────────────────────────────────────


class TestAppAssignment:
    """WD-ASSIGN-001 delegates to build_assignment_results (fully covered
    under AUTH-005). These tests pin that skill-3 renders it under the
    WD-ASSIGN-001 / "Entra App" identity."""

    @responses.activate
    def test_group_assigned_returns_passed(self, graph) -> None:
        from flightcheck.checks.entra_app import _check_app_assignment

        responses.add(**gr.list_application_templates())
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
                        principal_type="Group", principal_display_name="ESS Users"
                    )
                ]
            )
        )

        result = _result_by_id(_check_app_assignment(graph, {}), "WD-ASSIGN-001")

        assert result.category == "Entra App"
        assert result.status == "Passed"
        assert result.priority == "Critical"
        assert "ESS Users" in result.result

    @responses.activate
    def test_no_assignment_returns_failed(self, graph) -> None:
        from flightcheck.checks.entra_app import _check_app_assignment

        responses.add(**gr.list_application_templates())
        responses.add(
            **gr.list_service_principals(
                service_principals=[
                    gr.service_principal(app_role_assignment_required=True)
                ]
            )
        )
        responses.add(**gr.list_app_role_assignments(assignments=[]))

        result = _result_by_id(_check_app_assignment(graph, {}), "WD-ASSIGN-001")

        assert result.status == "Failed"
        assert "0 users/groups assigned" in result.result
        assert "Users and groups" in result.remediation


class TestAppAssignmentScopesToConfiguredApp:
    """Regression (live-observed false FAILED): a tenant routinely has
    several service principals provisioned from the same Workday SSO gallery
    template (dev / test / prod, demos, Okta trials). WD-ASSIGN-001 must
    assess only the app THIS deployment configured (``config['entraAppId']``)
    — evaluating unrelated siblings that nobody assigned drives a false
    FAILED. The reproduction had 6 Workday SPs where the configured app was
    correctly assigned but four siblings had zero assignments."""

    # Unrelated Workday-template SP that sorts first and has no assignments.
    _OTHER_SP_ID = "00000000-0000-0000-0000-0000000060aa"
    _OTHER_APP_ID = "00000000-0000-0000-0000-0000000060ab"
    # The app this deployment actually configured (config entraAppId).
    _OURS_SP_ID = "00000000-0000-0000-0000-0000000060cc"
    _OURS_APP_ID = "00000000-0000-0000-0000-0000000060cd"

    @pytest.fixture(autouse=True)
    def _isolate_from_connect_config(self, tmp_path, monkeypatch):
        """Run in a clean cwd so ``_workday_hints`` cannot pick up a stray
        ``.local/connect/workday/config.json`` — these tests drive the hint
        exclusively through ``config``."""
        monkeypatch.chdir(tmp_path)

    def _register_two_workday_sps(self) -> None:
        responses.add(**gr.list_application_templates())
        responses.add(
            **gr.list_service_principals(
                service_principals=[
                    gr.service_principal(
                        sp_id=self._OTHER_SP_ID,
                        app_id=self._OTHER_APP_ID,
                        display_name="Workday",
                        app_role_assignment_required=True,
                    ),
                    gr.service_principal(
                        sp_id=self._OURS_SP_ID,
                        app_id=self._OURS_APP_ID,
                        display_name="Workday MSFT DPT6",
                        app_role_assignment_required=True,
                    ),
                ]
            )
        )

    @responses.activate
    def test_hint_scopes_to_configured_sp_returns_passed(self, graph) -> None:
        from flightcheck.checks.entra_app import _check_app_assignment

        self._register_two_workday_sps()
        # Only the configured SP is assessed → only its assignments queried.
        responses.add(
            **gr.list_app_role_assignments(
                sp_id=self._OURS_SP_ID,
                assignments=[
                    gr.app_role_assignment(
                        principal_type="Group",
                        principal_display_name="EmployeeHub",
                    )
                ],
            )
        )

        result = _result_by_id(
            _check_app_assignment(graph, {"entraAppId": self._OURS_APP_ID}),
            "WD-ASSIGN-001",
        )

        assert result.status == "Passed"
        assert "EmployeeHub" in result.result

    @responses.activate
    def test_without_hint_sibling_zero_assignments_drives_failed(self, graph) -> None:
        from flightcheck.checks.entra_app import _check_app_assignment

        self._register_two_workday_sps()
        # No hint → every Workday SP is assessed, including the unrelated
        # sibling with zero assignments → overall FAILED (the noise scoping
        # removes).
        responses.add(
            **gr.list_app_role_assignments(sp_id=self._OTHER_SP_ID, assignments=[])
        )
        responses.add(
            **gr.list_app_role_assignments(
                sp_id=self._OURS_SP_ID,
                assignments=[
                    gr.app_role_assignment(
                        principal_type="Group",
                        principal_display_name="EmployeeHub",
                    )
                ],
            )
        )

        result = _result_by_id(_check_app_assignment(graph, {}), "WD-ASSIGN-001")

        assert result.status == "Failed"

    @responses.activate
    def test_hint_not_matching_any_sp_returns_skipped(self, graph) -> None:
        from flightcheck.checks.entra_app import _check_app_assignment

        self._register_two_workday_sps()
        # Configured appId matches none of the tenant's Workday SSO SPs →
        # SKIPPED (no assignment endpoint is queried).
        stranger = "00000000-0000-0000-0000-0000000060ff"

        result = _result_by_id(
            _check_app_assignment(graph, {"entraAppId": stranger}),
            "WD-ASSIGN-001",
        )

        assert result.status == "Skipped"
        assert stranger in result.result
        assert "was not found" in result.result


# ───────────────────────────────────────────────────────────────────────
# WD-ENTRA-NAMEID-001 — SAML NameID claimsMappingPolicy
# ───────────────────────────────────────────────────────────────────────


class TestNameIdMapping:
    @responses.activate
    def test_override_policy_returns_passed(self, graph) -> None:
        from flightcheck.checks.entra_app import _check_nameid_mapping

        _register_app_discovery(applications=[gr.application()])
        responses.add(**gr.list_claims_mapping_policies_for_sp())

        result = _check_nameid_mapping(graph, {})[0]

        assert result.checkpoint_id == "WD-ENTRA-NAMEID-001"
        assert result.status == "Passed"
        assert result.priority == "High"
        assert "overriding the SAML NameID claim" in result.result

    @responses.activate
    def test_no_policy_returns_failed(self, graph) -> None:
        from flightcheck.checks.entra_app import _check_nameid_mapping

        _register_app_discovery(applications=[gr.application()])
        responses.add(**gr.list_claims_mapping_policies_for_sp(policies=[]))

        result = _check_nameid_mapping(graph, {})[0]

        assert result.status == "Failed"
        assert "No claimsMappingPolicy overriding the SAML NameID claim" in result.result
        assert "user.userPrincipalName" in result.result
        assert "claimsMappingPolicy" in result.remediation

    @responses.activate
    def test_unreadable_policy_returns_manual(self, graph) -> None:
        from flightcheck.checks.entra_app import _check_nameid_mapping

        _register_app_discovery(applications=[gr.application()])
        # 403 on the claimsMappingPolicies route → cannot distinguish
        # "no policy" from "can't read", so degrade to MANUAL.
        responses.add(
            **gr.insufficient_permissions(
                path=f"/servicePrincipals/{gr.MOCK_WORKDAY_SP_ID}/claimsMappingPolicies"
            )
        )

        result = _check_nameid_mapping(graph, {})[0]

        assert result.status == "Manual"
        assert "Cannot read claimsMappingPolicies" in result.result
        assert "Policy.Read.All" in result.remediation

    def test_no_graph_returns_skipped(self) -> None:
        from flightcheck.checks.entra_app import _check_nameid_mapping

        result = _check_nameid_mapping(None, {})[0]

        assert result.status == "Skipped"


# ───────────────────────────────────────────────────────────────────────
# WD-ENTRA-SIGNOPT-001 — portal-only signing option (always MANUAL)
# ───────────────────────────────────────────────────────────────────────


class TestSigningOption:
    def test_always_manual(self) -> None:
        from flightcheck.checks.entra_app import _check_signing_option

        # No Graph calls at all — portal-only, so passing None is fine.
        result = _check_signing_option(None, {})[0]

        assert result.checkpoint_id == "WD-ENTRA-SIGNOPT-001"
        assert result.status == "Manual"
        assert result.priority == "High"
        assert "portal-only" in result.result
        assert "Sign SAML response and assertion" in result.remediation

    def test_personalized_idp_values_when_config_present(self) -> None:
        from flightcheck.checks.entra_app import _check_signing_option

        # With the captured Entra tenant + app ids, the attestation names the
        # customer's own IdP identifiers Workday must trust — still MANUAL,
        # still portal-only, and the fixed target value is retained.
        config = {
            "tenant": "acme_dpt1",
            "tenantId": "00000000-0000-0000-0000-000000000000",
            "entraAppId": "11111111-1111-1111-1111-111111111111",
        }
        result = _check_signing_option(None, config)[0]

        assert result.status == "Manual"
        assert "portal-only" in result.result
        assert "Sign SAML response and assertion" in result.remediation
        # Customer-specific, config-derived IdP values.
        assert "acme_dpt1" in result.remediation
        assert (
            "https://sts.windows.net/00000000-0000-0000-0000-000000000000/"
            in result.remediation
        )
        assert (
            "https://login.microsoftonline.com/"
            "00000000-0000-0000-0000-000000000000/saml2" in result.remediation
        )
        assert (
            "api://11111111-1111-1111-1111-111111111111" in result.remediation
        )
        assert "federationmetadata" in result.remediation


# ───────────────────────────────────────────────────────────────────────
# run_entra_app_checks — dispatch, SKIPPED fan-out, WARNING guard
# ───────────────────────────────────────────────────────────────────────


class TestDispatch:
    @responses.activate
    def test_all_five_checkpoints_emitted(self, graph) -> None:
        from flightcheck.checks.entra_app import run_entra_app_checks

        responses.add(**gr.list_application_templates())
        responses.add(**gr.list_service_principals())
        responses.add(**gr.list_applications())
        responses.add(**gr.list_oauth2_permission_grants())
        responses.add(**gr.list_app_role_assignments())
        responses.add(**gr.list_claims_mapping_policies_for_sp())

        results = run_entra_app_checks(_MinimalRunner(graph=graph, config={}))

        ids = {r.checkpoint_id for r in results}
        assert {
            "WD-ENTRA-SCOPE-001",
            "WD-ENTRA-CONSENT-001",
            "WD-ASSIGN-001",
            "WD-ENTRA-NAMEID-001",
            "WD-ENTRA-SIGNOPT-001",
        } <= ids
        assert all(r.category == "Entra App" for r in results)

    def test_no_graph_skips_all_but_signopt(self) -> None:
        from flightcheck.checks.entra_app import run_entra_app_checks

        results = run_entra_app_checks(_MinimalRunner(graph=None, config={}))

        by_id = {r.checkpoint_id: r for r in results}
        assert by_id["WD-ENTRA-SCOPE-001"].status == "Skipped"
        assert by_id["WD-ENTRA-CONSENT-001"].status == "Skipped"
        assert by_id["WD-ASSIGN-001"].status == "Skipped"
        assert by_id["WD-ENTRA-NAMEID-001"].status == "Skipped"
        # Portal-only — MANUAL regardless of auth.
        assert by_id["WD-ENTRA-SIGNOPT-001"].status == "Manual"

    def test_unexpected_error_becomes_warning(self) -> None:
        from flightcheck.checks.entra_app import run_entra_app_checks

        results = run_entra_app_checks(
            _MinimalRunner(graph=_RaisingGraph(), config={})
        )

        scope = _result_by_id(results, "WD-ENTRA-SCOPE-001")
        assert scope.status == "Warning"
        assert "Unable to verify WD-ENTRA-SCOPE-001" in scope.result
        assert "RuntimeError" in scope.result
        # A single failing emitter must not abort the rest — SIGNOPT
        # still emits its MANUAL attestation.
        assert _result_by_id(results, "WD-ENTRA-SIGNOPT-001").status == "Manual"
