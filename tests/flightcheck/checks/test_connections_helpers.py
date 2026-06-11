# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Unit + integration tests for the shared connection-status helpers in
``solutions/ess-maker-skills/scripts/flightcheck/checks/connections.py``.

This module owns three helpers used by every connector-specific check
(workday.py, servicenow.py, environment.py, and any future connector):

* ``get_connection_status(conn)`` — pure dict navigation; pulls the
  status string out of a BAP connection record.
* ``filter_connections_by_connector(all_conns, keyword)`` — filters a
  list of connections by case-insensitive substring match against
  ``properties.apiId`` + ``properties.displayName``. Accepts a single
  keyword or a list of keywords (OR semantics).
* ``check_connector_connections(...)`` — the generic check used by
  workday.py and servicenow.py. Discovers connections matching the
  keyword(s), reports a summary plus one per-connection row, and
  buckets the verdict per AGENTS.md design principle 7 (one summary
  CheckResult plus per-resource detail rows).

The first two are pure helpers and tested directly. The third is
exercised end-to-end through ``responses``-mocked PowerApps API
responses, mirroring the pattern in ``test_workday_connections.py``.

ServiceNow-specific behavior (the connector_keyword routing for
``_check_connections`` in servicenow.py) is covered separately by
``test_servicenow_connections.py`` so this file stays focused on the
shared infrastructure rather than any one consumer's plumbing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import responses

from tests.conftest import require_validated_mock
from tests.mocks import pp_admin as pp

require_validated_mock(pp)


# ───────────────────────────────────────────────────────────────────────
# get_connection_status — pure dict navigation
# ───────────────────────────────────────────────────────────────────────


class TestGetConnectionStatus:
    """Pure-unit tests for the status extractor.

    Real BAP responses put the status in ``properties.statuses[0].status``.
    The helper has to tolerate every shape the API has ever been observed
    to return — including responses missing the entire ``properties``
    block (which happens on connection records the caller doesn't have
    permission to read).
    """

    def test_returns_status_from_first_entry(self) -> None:
        conn = {"properties": {"statuses": [{"status": "Connected"}]}}
        from flightcheck.checks.connections import get_connection_status
        assert get_connection_status(conn) == "Connected"

    def test_returns_first_entry_when_multiple_present(self) -> None:
        # Real BAP responses sometimes return multiple status rows (e.g.
        # one per region for global tenants). The check uses the first
        # entry — pin that behaviour so it doesn't silently switch to
        # "any errored" or "all connected" without a deliberate change.
        from flightcheck.checks.connections import get_connection_status
        conn = {
            "properties": {
                "statuses": [
                    {"status": "Error"},
                    {"status": "Connected"},
                ]
            }
        }
        assert get_connection_status(conn) == "Error"

    def test_returns_unknown_when_statuses_list_is_empty(self) -> None:
        from flightcheck.checks.connections import get_connection_status
        assert get_connection_status({"properties": {"statuses": []}}) == "Unknown"

    def test_returns_unknown_when_statuses_key_missing(self) -> None:
        from flightcheck.checks.connections import get_connection_status
        assert get_connection_status({"properties": {}}) == "Unknown"

    def test_returns_unknown_when_properties_key_missing(self) -> None:
        # E.g. a connection record returned to a user without read access.
        from flightcheck.checks.connections import get_connection_status
        assert get_connection_status({}) == "Unknown"

    def test_returns_unknown_when_statuses_is_not_a_list(self) -> None:
        # The helper uses ``isinstance(statuses, list)`` as its guard;
        # pin the malformed-payload tolerance so a future refactor that
        # drops the isinstance check fails loudly.
        from flightcheck.checks.connections import get_connection_status
        assert get_connection_status({"properties": {"statuses": "Connected"}}) == "Unknown"

    def test_returns_unknown_when_status_field_missing_from_entry(self) -> None:
        # Entry exists but has no "status" key — fall back to "Unknown"
        # rather than KeyError-ing out into the runner's ERROR path.
        from flightcheck.checks.connections import get_connection_status
        conn = {"properties": {"statuses": [{"target": "token"}]}}
        assert get_connection_status(conn) == "Unknown"

    def test_returns_error_status_verbatim(self) -> None:
        # The check downstream compares against the literal string
        # "Connected"; any other value is treated as a failure. Pin that
        # arbitrary non-Connected strings are surfaced verbatim so the
        # operator sees what BAP actually returned (e.g.
        # "PendingConfirmation", "AccessDenied").
        from flightcheck.checks.connections import get_connection_status
        conn = {"properties": {"statuses": [{"status": "PendingConfirmation"}]}}
        assert get_connection_status(conn) == "PendingConfirmation"


# ───────────────────────────────────────────────────────────────────────
# filter_connections_by_connector — keyword routing
# ───────────────────────────────────────────────────────────────────────


def _conn(*, api_id: str = "", display_name: str = "") -> dict[str, Any]:
    """Minimal connection record for filter tests — only the two fields
    the filter actually reads. Using a full ``pp.connection(...)`` here
    would obscure what's being tested."""
    return {"properties": {"apiId": api_id, "displayName": display_name}}


class TestFilterConnectionsByConnector:
    """Pure-unit tests for the keyword filter.

    The filter checks the concatenation of ``apiId`` and ``displayName``
    so a connection matches if EITHER field contains the keyword. This
    matters in practice because the connector ID is the canonical
    identifier (e.g. ``shared_workdaysoap``) but the user-facing name is
    often the only thing humans can spot in the BAP UI.
    """

    def test_string_keyword_matches_api_id(self) -> None:
        from flightcheck.checks.connections import filter_connections_by_connector
        conns = [
            _conn(api_id="shared_workdaysoap", display_name="Whatever"),
            _conn(api_id="shared_office365", display_name="Whatever"),
        ]
        out = filter_connections_by_connector(conns, "workday")
        assert len(out) == 1
        assert out[0]["properties"]["apiId"] == "shared_workdaysoap"

    def test_string_keyword_matches_display_name(self) -> None:
        # Real environments sometimes have user-renamed connections where
        # apiId is opaque but displayName carries the connector name.
        from flightcheck.checks.connections import filter_connections_by_connector
        conns = [
            _conn(api_id="shared_unknown", display_name="My Workday Connection"),
            _conn(api_id="shared_unknown", display_name="My Office 365"),
        ]
        out = filter_connections_by_connector(conns, "workday")
        assert len(out) == 1
        assert "Workday" in out[0]["properties"]["displayName"]

    def test_match_is_case_insensitive(self) -> None:
        # apiId is typically lowercase but displayName is user-typed.
        # Mixed-case keywords / fields must still match.
        from flightcheck.checks.connections import filter_connections_by_connector
        conns = [
            _conn(api_id="SHARED_WORKDAYSOAP", display_name="WORKDAY UPPER"),
            _conn(api_id="shared_workdaysoap", display_name="workday lower"),
        ]
        out = filter_connections_by_connector(conns, "WoRkDaY")
        assert len(out) == 2

    def test_list_keyword_matches_either_alias(self) -> None:
        # ServiceNow's two aliases ("service-now" and "servicenow") are
        # the real motivating case for the list-keyword form.
        from flightcheck.checks.connections import filter_connections_by_connector
        conns = [
            _conn(api_id="shared_service-now", display_name="ServiceNow HRSD"),
            _conn(api_id="shared_servicenow", display_name="Custom Routing"),
            _conn(api_id="shared_workdaysoap", display_name="Workday"),
        ]
        out = filter_connections_by_connector(conns, ["service-now", "servicenow"])
        assert len(out) == 2

    def test_returns_empty_list_when_no_match(self) -> None:
        from flightcheck.checks.connections import filter_connections_by_connector
        conns = [
            _conn(api_id="shared_office365", display_name="Office 365"),
            _conn(api_id="shared_sharepointonline", display_name="SharePoint"),
        ]
        assert filter_connections_by_connector(conns, "workday") == []

    def test_returns_empty_list_for_empty_input(self) -> None:
        from flightcheck.checks.connections import filter_connections_by_connector
        assert filter_connections_by_connector([], "workday") == []
        assert filter_connections_by_connector([], ["a", "b"]) == []

    def test_tolerates_missing_properties_keys(self) -> None:
        # Records missing apiId or displayName must not raise — they
        # simply don't match the keyword. The check sees malformed
        # records sometimes when BAP returns a partial response.
        from flightcheck.checks.connections import filter_connections_by_connector
        conns = [
            {"properties": {}},          # both fields missing
            {},                          # properties block missing
            _conn(api_id="shared_workdaysoap"),
        ]
        out = filter_connections_by_connector(conns, "workday")
        assert len(out) == 1


# ───────────────────────────────────────────────────────────────────────
# check_connector_connections — end-to-end through PPAdminClient
# ───────────────────────────────────────────────────────────────────────


@dataclass
class _MinimalRunner:
    pp_admin: Any
    env_id: Any


@pytest.fixture
def pp_client(fake_token: str):
    """Real PPAdminClient with a pre-populated token — same pattern as
    test_workday_connections.py. Bypasses authenticate() (which would
    launch interactive MSAL) by setting ``_token`` directly so
    ``responses``-mocked PowerApps URLs do the actual driving."""
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


class TestCheckConnectorConnectionsSkipsCleanly:
    """Both halves of the auth contract — no env_id OR no pp_admin —
    must produce a SKIPPED row rather than crashing the runner."""

    def test_skipped_when_env_id_missing(self, pp_client) -> None:
        from flightcheck.checks.connections import check_connector_connections
        runner = _MinimalRunner(pp_admin=pp_client, env_id=None)
        results = check_connector_connections(
            runner,
            connector_keyword="anything",
            checkpoint_prefix="X-CONN",
            category="Generic",
            not_found_remediation="n/a",
        )
        r = _result_by_id(results, "X-CONN-001")
        assert r.status == "Skipped"
        assert "not available" in r.result.lower()

    def test_skipped_when_pp_admin_none(self) -> None:
        from flightcheck.checks.connections import check_connector_connections
        runner = _MinimalRunner(pp_admin=None, env_id="anything")
        results = check_connector_connections(
            runner,
            connector_keyword="anything",
            checkpoint_prefix="X-CONN",
            category="Generic",
            not_found_remediation="n/a",
        )
        assert len(results) == 1
        assert results[0].status == "Skipped"


class TestCheckConnectorConnectionsHandlesApiErrors:
    """Three failure shapes the helper has to absorb:

    1. ``pp_admin.get_connections`` returns an ``_error`` dict — only
       hit when a caller stubs the client (real ``get_connections``
       swallows 401/403 silently into ``[]`` per ``_get_all``).
    2. ``pp_admin.get_connections`` raises an unhandled exception —
       must NOT crash the runner; turns into a WARNING row.
    3. Real HTTP 401/403 on ``/connections`` — the silent-empty path
       inherited from ``_get_all``. The helper currently cannot
       distinguish this from "no matching connections" and emits
       ``NotConfigured``. Pinned here so the surprise behavior is
       visible and a future fix can flip the assertion deliberately.
    """

    def test_warning_when_get_connections_returns_error_dict(self) -> None:
        # The helper branches on ``isinstance(all_conns, dict) and "_error" in all_conns``.
        # Real PPAdminClient.get_connections doesn't currently return
        # this shape (see _get_all line 183-184 — 401/403 swallowed
        # into []) but the branch exists for callers that DO. Stub the
        # client directly so we exercise it.
        from flightcheck.checks.connections import check_connector_connections

        class StubClient:
            def get_connections(self, env_id):
                return {"_error": "insufficient_permissions", "_status": 403}

        runner = _MinimalRunner(pp_admin=StubClient(), env_id="env-1")
        results = check_connector_connections(
            runner,
            connector_keyword="workday",
            checkpoint_prefix="X-CONN",
            category="Generic",
            not_found_remediation="n/a",
        )
        r = _result_by_id(results, "X-CONN-001")
        assert r.status == "Warning"
        assert "Unable to list connections" in r.result
        assert "admin role" in r.remediation.lower()

    def test_warning_when_get_connections_raises(self) -> None:
        # A non-HTTP exception (e.g. a connection client patched in a
        # test, or a network library raising) must be caught and turned
        # into a WARNING result rather than aborting the whole run.
        from flightcheck.checks.connections import check_connector_connections

        class BoomClient:
            def get_connections(self, env_id):
                raise RuntimeError("simulated transport blowup")

        runner = _MinimalRunner(pp_admin=BoomClient(), env_id="env-1")
        results = check_connector_connections(
            runner,
            connector_keyword="workday",
            checkpoint_prefix="X-CONN",
            category="Generic",
            not_found_remediation="n/a",
        )
        r = _result_by_id(results, "X-CONN-001")
        assert r.status == "Warning"
        assert "simulated transport blowup" in r.result

    @responses.activate
    def test_http_403_silently_degrades_to_not_configured(
        self, runner: _MinimalRunner
    ) -> None:
        """A real 401/403 on ``/connections`` is swallowed by
        ``PPAdminClient._get_all`` into an empty list (see
        pp_admin_client.py:183-184). The helper has no way to tell
        "missing admin role" from "no matching connections" and emits
        ``NotConfigured``.

        This is a known silent-failure mode — the same trap AUTH-006
        and ENV-009 added explicit probe queries to work around. Pin
        the current behavior so a future fix (probe + WARNING split)
        flips this assertion intentionally rather than silently.
        """
        from flightcheck.checks.connections import check_connector_connections
        responses.add(**pp.list_connections(env_id=runner.env_id, connections=[], status=403))

        results = check_connector_connections(
            runner,
            connector_keyword="workday",
            checkpoint_prefix="X-CONN",
            category="Generic",
            not_found_remediation="Run /connect workday to configure.",
        )
        r = _result_by_id(results, "X-CONN-001")
        # TODO: when get_connections is augmented with a probe (like
        # AUTH-006 / ENV-009), flip this to status == "Warning" with
        # a permissions remediation.
        assert r.status == "NotConfigured"


class TestCheckConnectorConnectionsBucketing:
    """Verdict + per-connection bucketing — the core operator-facing
    contract of the helper. Each scenario uses a generic prefix
    (``X-CONN``) so the test pins the helper's behaviour rather than
    any one consumer's wiring."""

    @responses.activate
    def test_not_configured_when_no_matching_connection(
        self, runner: _MinimalRunner
    ) -> None:
        # Environment has connections but none match the keyword — must
        # be NOT_CONFIGURED (using the caller-supplied remediation), not
        # FAILED. Failing here would mis-fire on tenants that don't use
        # this connector at all.
        from flightcheck.checks.connections import check_connector_connections
        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.non_workday_connection(display_name="Office 365"),
                pp.non_workday_connection(display_name="SharePoint"),
            ],
        ))

        results = check_connector_connections(
            runner,
            connector_keyword="workday",
            checkpoint_prefix="X-CONN",
            category="Generic",
            not_found_remediation="Run /connect workday to configure.",
            doc_link="https://example.test/docs",
        )
        assert len(results) == 1
        r = results[0]
        assert r.status == "NotConfigured"
        assert r.checkpoint_id == "X-CONN-001"
        assert "No Generic connections" in r.result
        assert r.remediation == "Run /connect workday to configure."
        assert r.doc_link == "https://example.test/docs"

    @responses.activate
    def test_all_connected_summary_passes_with_per_connection_details(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.connections import check_connector_connections
        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(status="Connected", display_name="Workday A"),
                pp.workday_connection(status="Connected", display_name="Workday B"),
            ],
        ))

        results = check_connector_connections(
            runner,
            connector_keyword="workday",
            checkpoint_prefix="X-CONN",
            category="Generic",
            not_found_remediation="n/a",
        )
        # Summary + 2 per-connection rows.
        assert len(results) == 3
        summary = _result_by_id(results, "X-CONN-001")
        assert summary.status == "Passed"
        assert "2 total" in summary.result
        assert "2 connected" in summary.result
        assert "0 errored" in summary.result
        assert summary.remediation == ""  # no remediation when all connected

        # Per-connection rows: X-CONN-002 and X-CONN-003.
        for cid in ("X-CONN-002", "X-CONN-003"):
            r = _result_by_id(results, cid)
            assert r.status == "Passed"
            assert "Status: Connected" in r.result
            assert r.remediation == ""

    @responses.activate
    def test_all_errored_summary_fails_with_reauth_remediation(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.connections import check_connector_connections
        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(status="Error", display_name="Workday A"),
                pp.workday_connection(status="Error", display_name="Workday B"),
            ],
        ))

        results = check_connector_connections(
            runner,
            connector_keyword="workday",
            checkpoint_prefix="X-CONN",
            category="Generic",
            not_found_remediation="n/a",
        )
        summary = _result_by_id(results, "X-CONN-001")
        assert summary.status == "Failed"
        assert "0 connected" in summary.result
        assert "2 errored" in summary.result
        assert "Re-authenticate" in summary.remediation
        # Per-connection rows surface the bad-state remediation by name.
        for cid, name in (("X-CONN-002", "Workday A"), ("X-CONN-003", "Workday B")):
            r = _result_by_id(results, cid)
            assert r.status == "Failed"
            assert name in r.remediation
            assert "Re-authenticate" in r.remediation

    @responses.activate
    def test_mixed_state_summary_passes_but_per_connection_flags_errored(
        self, runner: _MinimalRunner
    ) -> None:
        """One healthy + one broken: the summary PASSES (because at least
        one connection works — keeps the verdict bucket usable for
        partial-degraded tenants) while the per-connection row for the
        broken one FAILS with the targeted re-auth remediation.

        This is the most operationally important scenario: things mostly
        work, but one user-facing flow is silently broken. The summary's
        non-zero ``errored`` count + the per-connection FAILED row are
        the only signal the operator gets.
        """
        from flightcheck.checks.connections import check_connector_connections
        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(status="Connected", display_name="Healthy"),
                pp.workday_connection(status="Error", display_name="Broken"),
            ],
        ))

        results = check_connector_connections(
            runner,
            connector_keyword="workday",
            checkpoint_prefix="X-CONN",
            category="Generic",
            not_found_remediation="n/a",
        )
        summary = _result_by_id(results, "X-CONN-001")
        assert summary.status == "Passed"
        assert "1 connected" in summary.result
        assert "1 errored" in summary.result
        assert "Re-authenticate" in summary.remediation

        # Per-connection rows split healthy / broken.
        details = {r.checkpoint_id: r for r in results if r.checkpoint_id != "X-CONN-001"}
        passed = [r for r in details.values() if r.status == "Passed"]
        failed = [r for r in details.values() if r.status == "Failed"]
        assert len(passed) == 1
        assert len(failed) == 1
        assert "Healthy" in passed[0].description
        assert "Broken" in failed[0].description
        assert "Broken" in failed[0].remediation

    @responses.activate
    def test_non_matching_connections_are_filtered_from_summary_counts(
        self, runner: _MinimalRunner
    ) -> None:
        """Office 365 / SharePoint connections in the same environment
        must not inflate the summary counts — only the keyword-matched
        connections count towards "total / connected / errored". Without
        this, a healthy Office 365 connection could silently mask a
        broken Workday one."""
        from flightcheck.checks.connections import check_connector_connections
        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[
                pp.workday_connection(status="Error", display_name="Workday Broken"),
                pp.non_workday_connection(display_name="Office 365"),
                pp.non_workday_connection(display_name="SharePoint"),
            ],
        ))

        results = check_connector_connections(
            runner,
            connector_keyword="workday",
            checkpoint_prefix="X-CONN",
            category="Generic",
            not_found_remediation="n/a",
        )
        summary = _result_by_id(results, "X-CONN-001")
        assert summary.status == "Failed"
        assert "1 total" in summary.result  # 1 Workday, not 3
        assert "0 connected" in summary.result
        assert "1 errored" in summary.result
        # Only one per-connection row (X-CONN-002).
        per_conn = [r for r in results if r.checkpoint_id != "X-CONN-001"]
        assert len(per_conn) == 1


class TestCheckConnectorConnectionsMetadataPassthrough:
    """Verifies the caller-supplied configuration (prefix, category,
    remediation, doc_link) shows up verbatim on the resulting rows."""

    @responses.activate
    def test_custom_prefix_and_category_propagate_to_every_row(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.connections import check_connector_connections
        responses.add(**pp.list_connections(
            env_id=runner.env_id,
            connections=[pp.workday_connection(status="Connected")],
        ))

        results = check_connector_connections(
            runner,
            connector_keyword="workday",
            checkpoint_prefix="ZZZ",
            category="MyCategory",
            not_found_remediation="n/a",
            doc_link="https://docs.example.test/zzz",
        )
        # All rows are MyCategory; summary uses the supplied prefix.
        assert {r.category for r in results} == {"MyCategory"}
        assert any(r.checkpoint_id == "ZZZ-001" for r in results)
        # doc_link shows up on the summary row.
        summary = _result_by_id(results, "ZZZ-001")
        assert summary.doc_link == "https://docs.example.test/zzz"
        # Per-connection row uses the same prefix continuation.
        assert any(r.checkpoint_id == "ZZZ-002" for r in results)
