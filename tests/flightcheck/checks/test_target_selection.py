# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Check-level tests for the standalone-flightcheck target selection feature.

A tenant can have several Workday SAML enterprise apps (dev / test / prod
instances provisioned from the same gallery template) and several
ServiceNow connections. When the operator runs the *standalone* flightcheck
they can now pin the one they are verifying, so:

  * WD-CONN-102 (``workday._check_saml_certificate_health``) scopes to the
    single Workday SSO app whose ``appId`` matches the resolved
    ``entraAppId`` hint (the same ``_workday_hints`` plumbing AUTH-005 /
    WD-ASSIGN-001 use), instead of lumping every SAML app together.
  * SN-CONN-* (``servicenow._check_connections`` →
    ``connections.check_connector_connections``) narrows to the connection
    the operator pinned by ``name`` or ``displayName`` substring.

Both narrowings are opt-in: a pin that matches nothing is ignored (validate
all, never mask a real target as "not configured"), and no pin at all keeps
the pre-existing all-targets behavior — which is what ``--checkpoint`` mode
(setup gates) relies on to stay deterministic.

Graph and Power Platform Admin mocks are validated builders (no cassette
required per the API tier registry).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
import responses

from tests.conftest import require_validated_mock
from tests.mocks import graph as g
from tests.mocks import pp_admin as pp

require_validated_mock(g)
require_validated_mock(pp)


# appIds for two distinct Workday SAML enterprise apps in the same tenant.
_APP_PROD = "aaaa1111-0000-0000-0000-000000000001"
_APP_SANDBOX = "bbbb2222-0000-0000-0000-000000000002"
_APP_UNKNOWN = "cccc3333-0000-0000-0000-000000000003"


@dataclass
class _WorkdayRunner:
    """Runner shape WD-CONN-102 reads: a Graph client plus the config dict
    that carries the ``entraAppId`` pin (written by the CLI selection)."""

    graph: Any
    config: dict = field(default_factory=dict)


@dataclass
class _ServiceNowRunner:
    """Runner shape SN-CONN-* reads: pp_admin + env_id + the connection pin."""

    pp_admin: Any
    env_id: str
    servicenow_connection_pin: str = ""


@pytest.fixture
def pp_client(fake_token: str):
    from flightcheck.pp_admin_client import PPAdminClient

    client = PPAdminClient(tenant_id="00000000-0000-0000-0000-000000001111")
    client._token = fake_token
    return client


def _wd102(results: list) -> list:
    return [r for r in results if r.checkpoint_id == "WD-CONN-102"]


def _two_workday_sps() -> list[dict]:
    """A healthy prod app (→ MANUAL) and a certless sandbox app (→ FAILED)."""
    prod = g.service_principal(
        sp_id="sp-workday-prod",
        display_name="Workday Prod",
        app_id=_APP_PROD,
        key_credentials=[g.key_credential(
            key_id="cert-prod",
            end_date_time="2099-01-01T00:00:00Z",
        )],
    )
    sandbox = g.service_principal(
        sp_id="sp-workday-sandbox",
        display_name="Workday Sandbox",
        app_id=_APP_SANDBOX,
        key_credentials=[],
    )
    return [prod, sandbox]


# ───────────────────────────────────────────────────────────────────────
# WD-CONN-102 — Workday SSO-app scoping
# ───────────────────────────────────────────────────────────────────────


class TestWorkdaySsoAppScoping:
    """The ``entraAppId`` hint narrows WD-CONN-102 to one Workday SAML app."""

    @pytest.fixture(autouse=True)
    def _isolate_connect_config(self, tmp_path, monkeypatch):
        # ``_workday_hints`` falls back to reading
        # ``.local/connect/workday/config.json`` from the CWD when the config
        # dict carries no ``entraAppId``; chdir to an empty temp dir so a
        # developer's real connect config can't leak a pin into the no-pin
        # (unscoped) scoping test.
        monkeypatch.chdir(tmp_path)

    @responses.activate
    def test_matching_pin_narrows_to_selected_app(self) -> None:
        from flightcheck.checks.workday import _check_saml_certificate_health

        runner = _WorkdayRunner(
            graph=self._graph(),
            config={"entraAppId": _APP_PROD},
        )
        responses.add(**g.list_service_principals(
            service_principals=_two_workday_sps(),
        ))

        results = _check_saml_certificate_health(runner)
        wd102 = _wd102(results)

        # Only the pinned (healthy prod) app is evaluated → a single MANUAL
        # row, and NO FAILED row for the excluded sandbox app.
        assert {r.status for r in wd102} == {"Manual"}
        manual = wd102[0]
        assert "Workday Prod" in manual.result
        assert "Workday Sandbox" not in manual.result
        # The scoping is called out in the result so the operator knows the
        # other tenant apps were intentionally skipped, not missed.
        assert "Scoped to the configured Workday SSO app" in manual.result
        assert _APP_PROD in manual.result
        # Remediation content is unchanged by scoping (both Workday phases).
        assert "Service Provider ID" in manual.remediation
        assert "X509 Certificate" in manual.remediation

    @responses.activate
    def test_non_matching_pin_validates_all_with_note(self) -> None:
        from flightcheck.checks.workday import _check_saml_certificate_health

        runner = _WorkdayRunner(
            graph=self._graph(),
            config={"entraAppId": _APP_UNKNOWN},
        )
        responses.add(**g.list_service_principals(
            service_principals=_two_workday_sps(),
        ))

        results = _check_saml_certificate_health(runner)
        wd102 = _wd102(results)

        # Pin matches no discovered SAML app (e.g. operator pinned the OAuth
        # Workday app): fall back to validating every app so nothing is
        # silently dropped — both buckets appear.
        assert {r.status for r in wd102} == {"Manual", "Failed"}
        note = "is not among the Workday SAML"
        for r in wd102:
            assert note in r.result
            assert _APP_UNKNOWN in r.result
        failed = next(r for r in wd102 if r.status == "Failed")
        assert "Workday Sandbox" in failed.result
        # Failed remediation still guides the cert-upload fix on both sides.
        assert "SAML Signing" in failed.remediation
        assert "X509 Certificate" in failed.remediation

    @responses.activate
    def test_no_pin_keeps_all_apps_unscoped(self) -> None:
        from flightcheck.checks.workday import _check_saml_certificate_health

        runner = _WorkdayRunner(graph=self._graph(), config={})
        responses.add(**g.list_service_principals(
            service_principals=_two_workday_sps(),
        ))

        results = _check_saml_certificate_health(runner)
        wd102 = _wd102(results)

        # No pin → pre-existing behavior: every app validated, no scope note.
        assert {r.status for r in wd102} == {"Manual", "Failed"}
        for r in wd102:
            assert "Scoped to the configured Workday SSO app" not in r.result
            assert "is not among the Workday SAML" not in r.result

    def _graph(self):
        from flightcheck.graph_client import GraphClient

        # Real client with a token so `responses` can intercept; the token
        # value is irrelevant to the mocked HTTP.
        client = GraphClient(tenant_id=g.MOCK_TENANT_ID)
        client._token = "fake-token-for-responses"  # noqa: S105 — test stub
        return client


# ───────────────────────────────────────────────────────────────────────
# SN-CONN-* — ServiceNow connection scoping
# ───────────────────────────────────────────────────────────────────────


class TestServiceNowConnectionScoping:
    """The connection pin narrows SN-CONN-001 to one ServiceNow connection."""

    def _two_connections(self):
        return [
            pp.servicenow_connection(
                status="Connected",
                display_name="ServiceNow Prod",
                connection_name="servicenow-prod-001",
            ),
            pp.servicenow_connection(
                status="Connected",
                display_name="ServiceNow Dev",
                connection_name="servicenow-dev-002",
            ),
        ]

    @responses.activate
    def test_pin_by_name_narrows_to_one(self, pp_client) -> None:
        from flightcheck.checks.servicenow import _check_connections

        runner = _ServiceNowRunner(
            pp_admin=pp_client,
            env_id=pp.MOCK_ENV_ID,
            servicenow_connection_pin="servicenow-prod-001",
        )
        responses.add(**pp.list_connections(
            env_id=runner.env_id, connections=self._two_connections(),
        ))

        results = _check_connections(runner)
        summary = next(r for r in results if r.checkpoint_id == "SN-CONN-001")

        assert summary.status == "Passed"
        assert "1 total" in summary.result
        assert "(scoped to selected connection 'servicenow-prod-001')" in summary.result

    @responses.activate
    def test_pin_by_displayname_substring_narrows(self, pp_client) -> None:
        from flightcheck.checks.servicenow import _check_connections

        runner = _ServiceNowRunner(
            pp_admin=pp_client,
            env_id=pp.MOCK_ENV_ID,
            servicenow_connection_pin="Dev",
        )
        responses.add(**pp.list_connections(
            env_id=runner.env_id, connections=self._two_connections(),
        ))

        results = _check_connections(runner)
        summary = next(r for r in results if r.checkpoint_id == "SN-CONN-001")
        detail = [r for r in results if r.checkpoint_id.startswith("SN-CONN-0")
                  and r.checkpoint_id != "SN-CONN-001"]

        assert "1 total" in summary.result
        assert "(scoped to selected connection 'Dev')" in summary.result
        # The surviving detail row is the Dev connection, not Prod.
        assert any("ServiceNow Dev" in r.description for r in detail)
        assert not any("ServiceNow Prod" in r.description for r in detail)

    @responses.activate
    def test_non_matching_pin_validates_all(self, pp_client) -> None:
        from flightcheck.checks.servicenow import _check_connections

        runner = _ServiceNowRunner(
            pp_admin=pp_client,
            env_id=pp.MOCK_ENV_ID,
            servicenow_connection_pin="does-not-exist",
        )
        responses.add(**pp.list_connections(
            env_id=runner.env_id, connections=self._two_connections(),
        ))

        results = _check_connections(runner)
        summary = next(r for r in results if r.checkpoint_id == "SN-CONN-001")

        # Stale/typo'd pin must never mask real connections: validate all.
        assert "2 total" in summary.result
        assert "(scoped to selected connection" not in summary.result

    @responses.activate
    def test_no_pin_validates_all(self, pp_client) -> None:
        from flightcheck.checks.servicenow import _check_connections

        runner = _ServiceNowRunner(
            pp_admin=pp_client, env_id=pp.MOCK_ENV_ID,
        )  # no pin
        responses.add(**pp.list_connections(
            env_id=runner.env_id, connections=self._two_connections(),
        ))

        results = _check_connections(runner)
        summary = next(r for r in results if r.checkpoint_id == "SN-CONN-001")

        assert "2 total" in summary.result
        assert "(scoped to selected connection" not in summary.result
