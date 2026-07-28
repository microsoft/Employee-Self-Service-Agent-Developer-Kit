# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for SN-RUN-001 (ServiceNow shared-flow run health).

Mocks the Power Automate runtime runs endpoint with ``responses``,
instantiates a real PPAdminClient with a pre-populated token, and runs
the production ``_check_servicenow_run_health`` against the mocked state.

Same pattern (and same runtime runs endpoint) as test_workday_run_health.py,
but the response-action names are the CONFIRMED ServiceNow ones (captured live
2026-06 from 3 environments with real ServiceNow run history —
ESS_MODEL_UPGRADE_PREVIEW_FRE_2, test_CA, SunbreakDev Workday+Snow — via
tests/captures/record_flightcheck_servicenow_runs.py):

  * orchestrator SUCCESS -> status=Succeeded, response.name="Respond_to_Copilot"
  * orchestrator FAILURE -> status=Failed,    response.name="Respond_to_Copilot_-_Failure"
  * child/utility flows   -> NON-Copilot actions ("Respond_to_a_Power_App_or_flow_-_Success",
                             "Respond_back_to_Orchestrator_-_Success", ...) -> non-scoring

This differs from Workday (single shared flow; caught faults stay Succeeded).
See the SN-RUN-001 comment in checks/servicenow.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
import responses

from tests.conftest import require_validated_mock
from tests.mocks import pp_admin as pp

require_validated_mock(pp)

_FLOW_ID = "00000000-0000-0000-0000-000000007201"

# Confirmed-live ServiceNow orchestrator response actions.
_SUCCESS = "Respond_to_Copilot"
_FAILURE = "Respond_to_Copilot_-_Failure"
# A child/utility flow response action (non-Copilot -> non-scoring).
_CHILD = "Respond_to_a_Power_App_or_flow_-_Success"


def _ok(run_id: str):
    """A user-facing orchestrator SUCCESS run."""
    return pp.flow_run(run_id=run_id, flow_id=_FLOW_ID, status="Succeeded",
                       response_name=_SUCCESS)


def _fail(run_id: str):
    """A user-facing orchestrator FAILURE run (status=Failed, as observed)."""
    return pp.flow_run(run_id=run_id, flow_id=_FLOW_ID, status="Failed",
                       response_name=_FAILURE,
                       error={"code": "ActionFailed", "message": "An action failed."})


def _child(run_id: str, response_name: str = _CHILD):
    """A succeeded child/utility flow run (responds to parent, not Copilot)."""
    return pp.flow_run(run_id=run_id, flow_id=_FLOW_ID, status="Succeeded",
                       response_name=response_name)


@dataclass
class _MinimalRunner:
    pp_admin: Any
    env_id: str
    _servicenow_flows: list = field(default_factory=list)


@pytest.fixture
def pp_client(fake_token: str):
    from flightcheck.pp_admin_client import PPAdminClient

    client = PPAdminClient(tenant_id="00000000-0000-0000-0000-000000001111")
    client._token = fake_token
    client._flow_token = fake_token
    return client


@pytest.fixture
def runner(pp_client) -> _MinimalRunner:
    return _MinimalRunner(
        pp_admin=pp_client,
        env_id=pp.MOCK_ENV_ID,
        _servicenow_flows=[pp.flow(flow_id=_FLOW_ID, display_name="ESS ServiceNow HRSD")],
    )


def _only(results: list):
    assert len(results) == 1, [r.checkpoint_id for r in results]
    return results[0]


class TestGoodState:
    @responses.activate
    def test_all_recent_runs_succeeded_passes(self, runner: _MinimalRunner) -> None:
        from flightcheck.checks.servicenow import _check_servicenow_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[_ok("r1"), _ok("r2")],
        ))

        r = _only(_check_servicenow_run_health(runner))
        assert r.checkpoint_id == "SN-RUN-001"
        assert r.status == "Passed"
        assert "All 2 most recent ServiceNow flow run(s) succeeded" in r.result
        assert r.remediation == ""

    @responses.activate
    def test_recent_successes_with_a_few_failures_still_passes(
        self, runner: _MinimalRunner
    ) -> None:
        """The litmus-test behaviour: a couple of failures among recent
        successes is NOT a deterministic break — the integration is wired up,
        so readiness PASSES (the failures are likely scenario/permission
        specific)."""
        from flightcheck.checks.servicenow import _check_servicenow_run_health

        runs = [_ok(f"ok{i}") for i in range(8)] + [_fail("bad1"), _fail("bad2")]
        responses.add(**pp.list_flow_runs(env_id=runner.env_id, flow_id=_FLOW_ID, runs=runs))

        r = _only(_check_servicenow_run_health(runner))
        assert r.status == "Passed"
        assert "the integration is working" in r.result
        assert "2 recent run(s) failed" in r.result
        assert r.remediation == ""


class TestBadState:
    @responses.activate
    def test_all_recent_runs_failed_is_deterministic_break(
        self, runner: _MinimalRunner
    ) -> None:
        """No success in the recent window → deterministically broken → FAIL.
        Includes a Succeeded-but-non-success-Copilot-response run (the defensive
        'caught_failure' branch) alongside the observed status=Failed shape."""
        from flightcheck.checks.servicenow import _check_servicenow_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[
                # Defensive branch: Succeeded but the failure Copilot response.
                pp.flow_run(run_id="f1", flow_id=_FLOW_ID, status="Succeeded",
                            response_name=_FAILURE),
                _fail("f2"),  # the observed shape: status=Failed
            ],
        ))

        r = _only(_check_servicenow_run_health(runner))
        assert r.status == "Failed"
        assert "All 2 most recent ServiceNow flow run(s) FAILED" in r.result
        assert "deterministically broken" in r.result
        assert "Power Automate (" in r.remediation
        assert "revoked" in r.remediation.lower()

    @responses.activate
    def test_single_failed_run_fails(self, runner: _MinimalRunner) -> None:
        """Only one run and it failed → no recent success → FAIL (per the
        explicit requirement)."""
        from flightcheck.checks.servicenow import _check_servicenow_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID, runs=[_fail("hard")],
        ))

        r = _only(_check_servicenow_run_health(runner))
        assert r.status == "Failed"
        assert "All 1 most recent ServiceNow flow run(s) FAILED" in r.result
        assert "flow run Failed" in r.result


class TestEdgeCases:
    @responses.activate
    def test_no_recent_runs_is_not_configured(self, runner: _MinimalRunner) -> None:
        from flightcheck.checks.servicenow import _check_servicenow_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID, runs=[],
        ))

        r = _only(_check_servicenow_run_health(runner))
        assert r.status == "NotConfigured"
        assert "No recent ServiceNow flow runs found" in r.result
        # Must steer the operator to connection status for the no-run case.
        assert "broken connection produces NO runs" in r.remediation
        assert "SN-CONN-001" in r.remediation

    @responses.activate
    def test_running_state_is_ignored(self, runner: _MinimalRunner) -> None:
        """An in-flight run (status=Running) is not scored as success or
        failure — only terminal runs count."""
        from flightcheck.checks.servicenow import _check_servicenow_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[pp.flow_run(run_id="live", flow_id=_FLOW_ID, status="Running",
                              response_name=_SUCCESS)],
        ))

        r = _only(_check_servicenow_run_health(runner))
        assert r.status == "NotConfigured"
        assert "No recent ServiceNow flow runs found" in r.result

    @responses.activate
    def test_cancelled_only_window_is_not_a_misleading_pass(
        self, runner: _MinimalRunner
    ) -> None:
        """A window of only Cancelled runs must NOT count as success (which
        would PASS and hide the manual conn/sec checks). Cancelled is
        inconclusive → non-scoring → NotConfigured."""
        from flightcheck.checks.servicenow import _check_servicenow_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[
                pp.flow_run(run_id="c1", flow_id=_FLOW_ID, status="Cancelled"),
                pp.flow_run(run_id="c2", flow_id=_FLOW_ID, status="Cancelled"),
            ],
        ))

        r = _only(_check_servicenow_run_health(runner))
        assert r.status == "NotConfigured"
        assert r.status != "Passed"

    @responses.activate
    def test_cancelled_runs_excluded_recent_success_still_passes(
        self, runner: _MinimalRunner
    ) -> None:
        """Cancelled runs are non-scoring, so genuine recent successes alongside
        them still PASS (a cancellation is not a ServiceNow failure)."""
        from flightcheck.checks.servicenow import _check_servicenow_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[
                pp.flow_run(run_id="c1", flow_id=_FLOW_ID, status="Cancelled"),
                _ok("s1"),
            ],
        ))

        r = _only(_check_servicenow_run_health(runner))
        assert r.status == "Passed"
        assert "1 most recent ServiceNow flow run(s) succeeded" in r.result

    @responses.activate
    def test_timedout_run_counts_as_failure(self, runner: _MinimalRunner) -> None:
        """A run-level TimedOut is a genuine run failure (not a success)."""
        from flightcheck.checks.servicenow import _check_servicenow_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[pp.flow_run(run_id="t1", flow_id=_FLOW_ID, status="TimedOut")],
        ))

        r = _only(_check_servicenow_run_health(runner))
        assert r.status == "Failed"
        assert "All 1 most recent ServiceNow flow run(s) FAILED" in r.result

    @responses.activate
    def test_child_flow_succeeded_runs_are_non_scoring(self, runner: _MinimalRunner) -> None:
        """ServiceNow is a multi-flow orchestration: child/utility flow runs
        respond to their PARENT, not to Copilot (response.name does NOT start
        with 'Respond_to_Copilot'), so a window of only child-flow successes
        must NOT score as success — it is inconclusive (NotConfigured), not a
        misleading PASS. Pins the live topology finding (2026-06)."""
        from flightcheck.checks.servicenow import _check_servicenow_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[
                _child("child1", response_name="Respond_to_a_Power_App_or_flow_-_Success"),
                _child("child2", response_name="Respond_back_to_Orchestrator_-_Success"),
            ],
        ))

        r = _only(_check_servicenow_run_health(runner))
        assert r.status == "NotConfigured"
        assert r.status != "Passed"
        assert "No recent ServiceNow flow runs found" in r.result

    @responses.activate
    def test_orchestrator_success_with_child_runs_passes(self, runner: _MinimalRunner) -> None:
        """A real user scenario produces one user-facing orchestrator run
        (responds to Copilot) plus several child-flow runs. Only the
        orchestrator run is scored, so the verdict is PASS counting just it —
        the child runs neither inflate nor deflate the result."""
        from flightcheck.checks.servicenow import _check_servicenow_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[
                _ok("orch"),
                _child("child1", response_name="Respond_to_a_Power_App_or_flow_-_Success"),
                _child("child2", response_name="Respond_back_to_Orchestrator_-_Success"),
            ],
        ))

        r = _only(_check_servicenow_run_health(runner))
        assert r.status == "Passed"
        assert "All 1 most recent ServiceNow flow run(s) succeeded" in r.result

    @responses.activate
    def test_403_is_skipped_with_permission_note(self, runner: _MinimalRunner) -> None:
        from flightcheck.checks.servicenow import _check_servicenow_run_health

        responses.add(**pp.insufficient_permissions(
            env_id=runner.env_id, endpoint="flow_runs", flow_id=_FLOW_ID,
        ))

        r = _only(_check_servicenow_run_health(runner))
        assert r.status == "Skipped"
        assert "Unable to read ServiceNow flow run history" in r.result
        assert "owner/maker access" in r.remediation

    def test_no_flows_means_no_run_health_row(self, pp_client) -> None:
        """With no ServiceNow flows, run_servicenow_checks returns early and
        SN-RUN-001 is never emitted.

        This pins the real production contract. `_check_servicenow_run_health`
        has no "no flows discovered" SKIPPED branch because its only caller,
        `run_servicenow_checks`, returns early when `_servicenow_flows` is
        empty (ServiceNow's sole install signal), so that branch was
        unreachable. The not-installed state is reported by SN-001 instead.
        """
        from flightcheck.checks.servicenow import run_servicenow_checks

        runner = _MinimalRunner(pp_admin=pp_client, env_id=pp.MOCK_ENV_ID, _servicenow_flows=[])
        results = run_servicenow_checks(runner)
        assert results == []

    def test_no_pp_admin_is_skipped(self) -> None:
        from flightcheck.checks.servicenow import _check_servicenow_run_health

        runner = _MinimalRunner(pp_admin=None, env_id=pp.MOCK_ENV_ID, _servicenow_flows=[])
        r = _only(_check_servicenow_run_health(runner))
        assert r.status == "Skipped"
        assert "Power Platform Admin API not available" in r.result


class TestClassifyRun:
    """Unit tests for _classify_run pinned to the CONFIRMED live shapes."""

    def test_orchestrator_success(self):
        from flightcheck.checks.servicenow import _classify_run
        assert _classify_run({"properties": {"status": "Succeeded",
                                              "response": {"name": _SUCCESS}}}) == "success"

    def test_orchestrator_failure_status_failed(self):
        from flightcheck.checks.servicenow import _classify_run
        assert _classify_run({"properties": {"status": "Failed",
                                              "response": {"name": _FAILURE}}}) == "hard_failure"

    def test_succeeded_failure_branch_is_caught_failure(self):
        from flightcheck.checks.servicenow import _classify_run
        assert _classify_run({"properties": {"status": "Succeeded",
                                              "response": {"name": _FAILURE}}}) == "caught_failure"

    def test_child_flow_success_is_pending(self):
        from flightcheck.checks.servicenow import _classify_run
        assert _classify_run({"properties": {"status": "Succeeded",
                                              "response": {"name": _CHILD}}}) == "pending"
        assert _classify_run({"properties": {"status": "Succeeded",
                                              "response": {"name": "Respond_back_to_Orchestrator_-_Success"}}}) == "pending"


class TestManualConnSecSuppression:
    """`_suppress_manual_conn_sec_when_runs_healthy` hides MANUAL ServiceNow
    connection/security rows only when SN-RUN-001 PASSED."""

    @staticmethod
    def _cr(checkpoint_id, status):
        from flightcheck.runner import CheckResult, Priority
        return CheckResult(
            checkpoint_id=checkpoint_id, category="ServiceNow",
            priority=Priority.HIGH.value, status=status,
            description="x", result="x", roles=["ServiceNow Admin"],
        )

    def _build(self, run_status):
        from flightcheck.runner import Status
        return [
            self._cr("SN-RUN-001", run_status),
            self._cr("SN-CONN-010", Status.MANUAL.value),   # connection (manual)
            self._cr("SN-CONN-102", Status.MANUAL.value),   # connection (manual)
            self._cr("SN-SEC-003", Status.MANUAL.value),    # security (manual)
            self._cr("SN-CONN-001", Status.PASSED.value),   # connection status (not manual)
            self._cr("SN-FLOW-001", Status.MANUAL.value),   # flow manual (NOT conn/sec)
        ]

    def test_passed_run_health_hides_manual_conn_sec(self) -> None:
        from flightcheck.checks.servicenow import _suppress_manual_conn_sec_when_runs_healthy
        from flightcheck.runner import Status

        out = _suppress_manual_conn_sec_when_runs_healthy(self._build(Status.PASSED.value))
        ids = {r.checkpoint_id for r in out}
        assert "SN-CONN-010" not in ids
        assert "SN-CONN-102" not in ids
        assert "SN-SEC-003" not in ids
        # Non-manual conn check and the (non conn/sec) flow manual stay.
        assert "SN-CONN-001" in ids
        assert "SN-FLOW-001" in ids
        assert "SN-RUN-001" in ids

    def test_failed_run_health_keeps_manual_conn_sec(self) -> None:
        from flightcheck.checks.servicenow import _suppress_manual_conn_sec_when_runs_healthy
        from flightcheck.runner import Status

        out = _suppress_manual_conn_sec_when_runs_healthy(self._build(Status.FAILED.value))
        ids = {r.checkpoint_id for r in out}
        assert {"SN-CONN-010", "SN-CONN-102", "SN-SEC-003"} <= ids

    def test_not_configured_run_health_keeps_manual_conn_sec(self) -> None:
        """No traffic yet (e.g. fresh pre-deploy) — manual checks stay visible."""
        from flightcheck.checks.servicenow import _suppress_manual_conn_sec_when_runs_healthy
        from flightcheck.runner import Status

        out = _suppress_manual_conn_sec_when_runs_healthy(self._build(Status.NOT_CONFIGURED.value))
        ids = {r.checkpoint_id for r in out}
        assert {"SN-CONN-010", "SN-CONN-102", "SN-SEC-003"} <= ids
