# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""End-to-end integration tests for the ServiceNow connection FlightCheck
check (SN-CONN-001 summary + per-connection SN-CONN-{N}).

Pattern mirrors ``test_workday_connections.py``: mocks the PowerApps
``/connections`` endpoint with ``responses``, instantiates a real
``PPAdminClient`` with a pre-populated token, calls the production
``servicenow._check_connections`` helper, and asserts on the resulting
``CheckResult`` list.

The shared helper this consumer routes through
(``connections.check_connector_connections``) is unit-tested separately
in ``test_connections_helpers.py``; this file focuses on the
ServiceNow-specific wiring:

* The ``connector_keyword=["service-now", "servicenow"]`` list catches
  BOTH alias forms (the canonical ``shared_service-now`` apiId and the
  unhyphenated alias some UI surfaces emit).
* Non-ServiceNow connections (Workday, Office 365, SharePoint) MUST be
  filtered out of summary counts — without this, a healthy Workday
  connection would silently mask a broken ServiceNow one.
* The summary row uses checkpoint prefix ``SN-CONN-001`` and category
  ``ServiceNow``; per-connection rows continue at ``SN-CONN-002``.
* The not-configured remediation must reference ``/connect servicenow``
  so operators have a one-line fix path.
* The doc_link must point at the ServiceNow integration docs.
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
    """Real PPAdminClient with pre-populated token — same shape as
    test_workday_connections.py uses; bypasses MSAL by writing the
    ``_token`` field directly."""
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
# Connector-keyword routing — the ServiceNow-specific contract.
# ───────────────────────────────────────────────────────────────────────


class TestConnectorKeywordRouting:
    """Pins which connections SN-CONN-001 considers in-scope.

    The Power Platform connector ID for ServiceNow is
    ``shared_service-now`` (hyphenated). Some user-renamed connections
    and older docs use the unhyphenated ``servicenow`` form, so
    servicenow.py routes through the list-keyword variant of
    ``check_connector_connections``. Both aliases MUST hit the same
    summary row.
    """

    @responses.activate
    def test_connection_with_hyphenated_alias_is_in_scope(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.servicenow import _check_connections
        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[pp.servicenow_connection(
                status="Connected", display_name="ServiceNow HRSD",
                api_name="shared_service-now",
            )],
        ))

        results = _check_connections(runner)
        summary = _result_by_id(results, "SN-CONN-001")
        assert summary.status == "Passed"
        assert summary.category == "ServiceNow"
        assert "1 total" in summary.result

    @responses.activate
    def test_connection_with_unhyphenated_alias_is_in_scope(
        self, runner: _MinimalRunner
    ) -> None:
        # Some user-renamed connections and older Power Platform UI
        # surfaces emit ``servicenow`` (no hyphen). servicenow.py
        # specifically lists both aliases so neither variant escapes
        # the keyword filter.
        from flightcheck.checks.servicenow import _check_connections
        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[pp.servicenow_connection(
                status="Connected",
                display_name="ServiceNow Renamed",
                api_name="shared_servicenow",
            )],
        ))

        results = _check_connections(runner)
        summary = _result_by_id(results, "SN-CONN-001")
        assert summary.status == "Passed"
        assert "1 total" in summary.result

    @responses.activate
    def test_workday_and_office365_connections_are_filtered_out(
        self, runner: _MinimalRunner
    ) -> None:
        """A tenant that runs ServiceNow alongside Workday + O365 must
        get SN-CONN-001 counts based on the ServiceNow connections only.
        Without this, a healthy Workday connection could mask a broken
        ServiceNow one — the same silent-failure mode the
        ``test_non_workday_connections_are_filtered_out`` test in
        test_workday_connections.py guards against in reverse.
        """
        from flightcheck.checks.servicenow import _check_connections
        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.servicenow_connection(status="Error", display_name="SN Broken"),
                pp.workday_connection(status="Connected", display_name="Workday OK"),
                pp.non_workday_connection(display_name="Office 365"),
                pp.non_workday_connection(display_name="SharePoint"),
            ],
        ))

        results = _check_connections(runner)
        summary = _result_by_id(results, "SN-CONN-001")
        assert summary.status == "Failed"
        # ServiceNow-only counts — 1 errored, 0 connected. Workday +
        # Office 365 + SharePoint do NOT contribute.
        assert "1 total" in summary.result
        assert "0 connected" in summary.result
        assert "1 errored" in summary.result
        # Exactly one per-connection detail row (SN-CONN-002) because
        # only one connection matches the keyword.
        details = [r for r in results if r.checkpoint_id != "SN-CONN-001"]
        assert len(details) == 1
        assert details[0].checkpoint_id == "SN-CONN-002"
        assert "SN Broken" in details[0].description


# ───────────────────────────────────────────────────────────────────────
# Verdicts per environment state.
# ───────────────────────────────────────────────────────────────────────


class TestGoodConfig:
    @responses.activate
    def test_single_connected_servicenow_connection_passes(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.servicenow import _check_connections
        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[pp.servicenow_connection(status="Connected")],
        ))

        results = _check_connections(runner)
        summary = _result_by_id(results, "SN-CONN-001")
        assert summary.status == "Passed"
        assert summary.category == "ServiceNow"
        assert "1 total" in summary.result
        assert "1 connected" in summary.result
        assert "0 errored" in summary.result
        # Per-connection detail row
        detail = _result_by_id(results, "SN-CONN-002")
        assert detail.status == "Passed"
        assert "Status: Connected" in detail.result

    @responses.activate
    def test_hrsd_and_itsm_connections_both_pass(
        self, runner: _MinimalRunner
    ) -> None:
        # A common shape: one HRSD-focused and one ITSM-focused
        # ServiceNow connection, both healthy. Both must surface in
        # the summary and get their own per-connection row.
        from flightcheck.checks.servicenow import _check_connections
        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.servicenow_connection(status="Connected", display_name="ServiceNow HRSD"),
                pp.servicenow_connection(status="Connected", display_name="ServiceNow ITSM"),
            ],
        ))

        results = _check_connections(runner)
        summary = _result_by_id(results, "SN-CONN-001")
        assert summary.status == "Passed"
        assert "2 total" in summary.result
        assert "2 connected" in summary.result
        for cid in ("SN-CONN-002", "SN-CONN-003"):
            assert _result_by_id(results, cid).status == "Passed"


class TestBadConfig:
    @responses.activate
    def test_all_servicenow_connections_errored_returns_failed(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.servicenow import _check_connections
        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.servicenow_connection(status="Error", display_name="SN HRSD"),
                pp.servicenow_connection(status="Error", display_name="SN ITSM"),
            ],
        ))

        results = _check_connections(runner)
        summary = _result_by_id(results, "SN-CONN-001")
        assert summary.status == "Failed", (
            f"Expected SN-CONN-001 FAILED when all ServiceNow connections "
            f"are errored, got status={summary.status} result={summary.result!r}"
        )
        assert summary.priority == "High"
        assert "0 connected" in summary.result
        assert "2 errored" in summary.result
        assert "Re-authenticate" in summary.remediation
        # Both per-connection rows fail with targeted re-auth remediation.
        for cid in ("SN-CONN-002", "SN-CONN-003"):
            r = _result_by_id(results, cid)
            assert r.status == "Failed"
            assert "Re-authenticate" in r.remediation

    @responses.activate
    def test_no_servicenow_connections_returns_not_configured(
        self, runner: _MinimalRunner
    ) -> None:
        """Empty connections list — clean tenant, ServiceNow not set up
        yet. Must be NOT_CONFIGURED with the `/connect servicenow`
        hint, not FAILED."""
        from flightcheck.checks.servicenow import _check_connections
        responses.add(**pp.list_connections(env_id=runner.env_id, connections=[]))

        results = _check_connections(runner)
        summary = _result_by_id(results, "SN-CONN-001")
        assert summary.status == "NotConfigured"
        assert "No ServiceNow connections" in summary.result
        # The /connect prompt is the operator's one-line fix path —
        # losing it would turn this into an unactionable status row.
        assert "/connect servicenow" in summary.remediation

    @responses.activate
    def test_only_non_servicenow_connections_returns_not_configured(
        self, runner: _MinimalRunner
    ) -> None:
        """Environment has Workday and Office 365 but no ServiceNow.
        Must be NOT_CONFIGURED, not 'all healthy' just because the
        non-ServiceNow connections are connected."""
        from flightcheck.checks.servicenow import _check_connections
        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(status="Connected"),
                pp.non_workday_connection(display_name="Office 365"),
            ],
        ))

        results = _check_connections(runner)
        summary = _result_by_id(results, "SN-CONN-001")
        assert summary.status == "NotConfigured"
        assert "No ServiceNow connections" in summary.result
        assert "/connect servicenow" in summary.remediation


class TestMixedState:
    @responses.activate
    def test_one_connected_one_errored_passes_overall_but_flags_errored(
        self, runner: _MinimalRunner
    ) -> None:
        """One healthy + one broken — SN-CONN-001 PASSES (because at
        least one ServiceNow connection works) but the per-connection
        detail for the broken one FAILS with re-auth remediation.

        This is the most operationally important scenario for any
        connector: things mostly work, but one customer-facing flow
        is silently broken. The summary's non-zero ``errored`` count
        + the per-connection FAILED row are the only signal the
        operator gets.
        """
        from flightcheck.checks.servicenow import _check_connections
        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.servicenow_connection(status="Connected", display_name="SN Healthy"),
                pp.servicenow_connection(status="Error", display_name="SN Broken"),
            ],
        ))

        results = _check_connections(runner)
        summary = _result_by_id(results, "SN-CONN-001")
        assert summary.status == "Passed"
        assert "1 connected" in summary.result
        assert "1 errored" in summary.result
        # Summary remediation surfaces the re-auth hint because at
        # least one connection needs operator attention.
        assert "Re-authenticate" in summary.remediation
        # Healthy connection passes; broken connection fails with
        # name-specific remediation.
        per_conn = {r.checkpoint_id: r for r in results if r.checkpoint_id != "SN-CONN-001"}
        statuses = {r.status for r in per_conn.values()}
        assert statuses == {"Passed", "Failed"}
        broken = next(r for r in per_conn.values() if r.status == "Failed")
        assert "SN Broken" in broken.description
        assert "SN Broken" in broken.remediation


# ───────────────────────────────────────────────────────────────────────
# Metadata propagation — category, prefix, doc_link.
# ───────────────────────────────────────────────────────────────────────


class TestMetadataPropagation:
    @responses.activate
    def test_all_rows_use_servicenow_category_and_sn_conn_prefix(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.servicenow import _check_connections
        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.servicenow_connection(status="Connected", display_name="SN A"),
                pp.servicenow_connection(status="Connected", display_name="SN B"),
            ],
        ))

        results = _check_connections(runner)
        # Every row carries the "ServiceNow" category — important for
        # the prioritized report layout (bucket-by-category sections).
        assert {r.category for r in results} == {"ServiceNow"}
        # Every checkpoint id starts with SN-CONN-, and the summary
        # is SN-CONN-001 specifically.
        ids = [r.checkpoint_id for r in results]
        assert all(cid.startswith("SN-CONN-") for cid in ids)
        assert "SN-CONN-001" in ids

    @responses.activate
    def test_summary_doc_link_points_at_servicenow_integration_docs(
        self, runner: _MinimalRunner
    ) -> None:
        # No fabricated URLs — the link must be the canonical ESS
        # ServiceNow integration page that other parts of the kit
        # already reference.
        from flightcheck.checks.servicenow import _check_connections
        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[pp.servicenow_connection(status="Connected")],
        ))

        results = _check_connections(runner)
        summary = _result_by_id(results, "SN-CONN-001")
        assert summary.doc_link.endswith("/employee-self-service/servicenow")
        assert summary.doc_link.startswith("https://learn.microsoft.com/")


# ───────────────────────────────────────────────────────────────────────
# Skip path — pp_admin or env_id unavailable.
# ───────────────────────────────────────────────────────────────────────


class TestSkipsCleanly:
    """``servicenow._check_connections`` delegates to the shared helper,
    which emits SKIPPED when ``pp_admin`` or ``env_id`` is missing.
    Pin that the ServiceNow consumer surfaces this with the correct
    category/prefix so the runner still tracks the checkpoint."""

    def test_skipped_when_env_id_missing(self, pp_client) -> None:
        from flightcheck.checks.servicenow import _check_connections
        runner = _MinimalRunner(pp_admin=pp_client, env_id=None)
        results = _check_connections(runner)
        r = _result_by_id(results, "SN-CONN-001")
        assert r.status == "Skipped"
        assert r.category == "ServiceNow"

    def test_skipped_when_pp_admin_missing(self) -> None:
        from flightcheck.checks.servicenow import _check_connections
        runner = _MinimalRunner(pp_admin=None, env_id="env-1")
        results = _check_connections(runner)
        assert results[0].status == "Skipped"
        assert results[0].category == "ServiceNow"
