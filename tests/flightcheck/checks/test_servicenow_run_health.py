# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Integration tests for SN-RUN-001 (ServiceNow shared-flow run health).

Mocks the Power Automate runtime runs endpoint with ``responses``,
instantiates a real PPAdminClient with a pre-populated token, and runs
the production ``_check_servicenow_run_health`` against the mocked state.

Same pattern (and same runtime runs endpoint) as test_workday_run_health.py.
The detection model — run status alone is insufficient; the ESS shared flow
catches faults and still reports status=Succeeded, so the Response action name
is the real signal — was confirmed live against the ESS Workday shared flow
(see WD-RUN-001) and ported here: the ServiceNow shared flow uses the same
single success Response action (``Respond_to_Copilot_with_Success``). See the
SN-RUN-001 comment in checks/servicenow.py.
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
            runs=[
                pp.flow_run(run_id="r1", flow_id=_FLOW_ID, status="Succeeded"),
                pp.flow_run(run_id="r2", flow_id=_FLOW_ID, status="Succeeded"),
            ],
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

        runs = [pp.flow_run(run_id=f"ok{i}", flow_id=_FLOW_ID, status="Succeeded")
                for i in range(8)]
        runs += [
            pp.flow_run(run_id="bad1", flow_id=_FLOW_ID, status="Succeeded",
                        response_name="Respond_to_Copilot_with_failure_errorMessage"),
            pp.flow_run(run_id="bad2", flow_id=_FLOW_ID, status="Failed",
                        response_name="Respond_to_Copilot_with_failure_errorMessage",
                        error={"code": "ActionFailed", "message": "An action failed."}),
        ]
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
        Includes a caught failure (status=Succeeded but failure branch) to pin
        that run status alone is not the signal."""
        from flightcheck.checks.servicenow import _check_servicenow_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[
                pp.flow_run(run_id="f1", flow_id=_FLOW_ID, status="Succeeded",
                            response_name="Respond_to_Copilot_with_failure_errorMessage"),
                pp.flow_run(run_id="f2", flow_id=_FLOW_ID, status="Failed",
                            response_name="Respond_to_Copilot_with_failure_errorMessage",
                            error={"code": "ActionFailed", "message": "An action failed."}),
            ],
        ))

        r = _only(_check_servicenow_run_health(runner))
        assert r.status == "Failed"
        assert "All 2 most recent ServiceNow flow run(s) FAILED" in r.result
        assert "deterministically broken" in r.result
        assert "make.powerautomate.com" in r.remediation
        assert "revoked" in r.remediation.lower()

    @responses.activate
    def test_single_failed_run_fails(self, runner: _MinimalRunner) -> None:
        """Only one run and it failed → no recent success → FAIL (per the
        explicit requirement)."""
        from flightcheck.checks.servicenow import _check_servicenow_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[
                pp.flow_run(
                    run_id="hard", flow_id=_FLOW_ID, status="Failed",
                    response_name="Respond_to_Copilot_with_failure_errorMessage",
                    error={"code": "ActionFailed", "message": "An action failed."},
                ),
            ],
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
            runs=[pp.flow_run(run_id="live", flow_id=_FLOW_ID, status="Running")],
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
                pp.flow_run(run_id="s1", flow_id=_FLOW_ID, status="Succeeded"),
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
    def test_403_is_skipped_with_permission_note(self, runner: _MinimalRunner) -> None:
        from flightcheck.checks.servicenow import _check_servicenow_run_health

        responses.add(**pp.insufficient_permissions(
            env_id=runner.env_id, endpoint="flow_runs", flow_id=_FLOW_ID,
        ))

        r = _only(_check_servicenow_run_health(runner))
        assert r.status == "Skipped"
        assert "Unable to read ServiceNow flow run history" in r.result
        assert "owner/maker access" in r.remediation

    def test_no_flows_is_skipped(self, pp_client) -> None:
        from flightcheck.checks.servicenow import _check_servicenow_run_health

        runner = _MinimalRunner(pp_admin=pp_client, env_id=pp.MOCK_ENV_ID, _servicenow_flows=[])
        r = _only(_check_servicenow_run_health(runner))
        assert r.status == "Skipped"
        assert "No ServiceNow flows discovered" in r.result

    def test_no_pp_admin_is_skipped(self) -> None:
        from flightcheck.checks.servicenow import _check_servicenow_run_health

        runner = _MinimalRunner(pp_admin=None, env_id=pp.MOCK_ENV_ID, _servicenow_flows=[])
        r = _only(_check_servicenow_run_health(runner))
        assert r.status == "Skipped"
        assert "Power Platform Admin API not available" in r.result


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
