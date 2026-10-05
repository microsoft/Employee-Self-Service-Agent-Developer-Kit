# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Integration tests for WD-RUN-001 (Workday shared-flow run health).

Mocks the Power Automate runtime runs endpoint with ``responses``,
instantiates a real PPAdminClient with a pre-populated token, and runs
the production ``_check_workday_run_health`` against the mocked state.

Same pattern as test_workday_connections.py. The detection model
(run status alone is insufficient; the flow catches Workday faults and
still reports status=Succeeded, so the Response action name is the real
signal) was confirmed live against a real ESS Workday tenant — see the
WD-RUN-001 comment in checks/workday.py and the mock builder docstring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
import responses

from tests.conftest import require_validated_mock
from tests.mocks import pp_admin as pp

require_validated_mock(pp)

_FLOW_ID = "00000000-0000-0000-0000-000000007101"


@dataclass
class _MinimalRunner:
    pp_admin: Any
    env_id: str
    _workday_flows: list = field(default_factory=list)


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
        _workday_flows=[pp.flow(flow_id=_FLOW_ID, display_name="ESS HR Workday")],
    )


def _only(results: list):
    assert len(results) == 1, [r.checkpoint_id for r in results]
    return results[0]


class TestGoodState:
    @responses.activate
    def test_all_recent_runs_succeeded_passes(self, runner: _MinimalRunner) -> None:
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[
                pp.flow_run(run_id="r1", flow_id=_FLOW_ID, status="Succeeded"),
                pp.flow_run(run_id="r2", flow_id=_FLOW_ID, status="Succeeded"),
            ],
        ))

        r = _only(_check_workday_run_health(runner))
        assert r.checkpoint_id == "WD-RUN-001"
        assert r.status == "Passed"
        assert "All 2 most recent Workday flow run(s) succeeded" in r.result
        assert r.remediation == ""

    @responses.activate
    def test_run_check_stashes_failure_signal_on_runner(
        self, runner: _MinimalRunner
    ) -> None:
        """Wiring pin: WD-RUN-001 records the classified failure signal on the
        runner so the suppression step can consume it. A caught Workday fault
        ⟹ auth_proven + workday_fault."""
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[
                pp.flow_run(run_id="f1", flow_id=_FLOW_ID, status="Succeeded",
                            response_name="Respond_to_Copilot_with_failure_errorMessage"),
            ],
        ))

        _check_workday_run_health(runner)
        sig = runner._workday_run_failure_signal
        assert sig["auth_proven"] is True
        assert sig["workday_fault"] is True
        assert sig["hard_failure"] is False

    @responses.activate
    def test_recent_successes_with_a_few_failures_still_passes(
        self, runner: _MinimalRunner
    ) -> None:
        """The litmus-test behaviour: a couple of failures among recent
        successes is NOT a deterministic break — the integration is wired up,
        so readiness PASSES (the failures are likely scenario/permission
        specific). This is the case the '2 of 69 failed' feedback fixed."""
        from flightcheck.checks.workday import _check_workday_run_health

        runs = [pp.flow_run(run_id=f"ok{i}", flow_id=_FLOW_ID, status="Succeeded")
                for i in range(8)]
        runs += [
            pp.flow_run(run_id="bad1", flow_id=_FLOW_ID, status="Succeeded",
                        response_name="Respond_to_Copilot_with_failure_errorMessage"),
            pp.flow_run(run_id="bad2", flow_id=_FLOW_ID, status="Failed",
                        response_name="Respond_to_Copilot_with_XmlTemplate_To_Json_Failed",
                        error={"code": "ActionFailed", "message": "An action failed."}),
        ]
        responses.add(**pp.list_flow_runs(env_id=runner.env_id, flow_id=_FLOW_ID, runs=runs))

        r = _only(_check_workday_run_health(runner))
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
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[
                pp.flow_run(run_id="f1", flow_id=_FLOW_ID, status="Succeeded",
                            response_name="Respond_to_Copilot_with_failure_errorMessage"),
                pp.flow_run(run_id="f2", flow_id=_FLOW_ID, status="Failed",
                            response_name="Respond_to_Copilot_with_XmlTemplate_To_Json_Failed",
                            error={"code": "ActionFailed", "message": "An action failed."}),
            ],
        ))

        r = _only(_check_workday_run_health(runner))
        assert r.status == "Failed"
        assert "All 2 most recent Workday flow run(s) FAILED" in r.result
        assert "deterministically broken" in r.result
        assert "make.powerautomate.com" in r.remediation
        assert "revoked" in r.remediation.lower()

    @responses.activate
    def test_single_failed_run_fails(self, runner: _MinimalRunner) -> None:
        """Only one run and it failed → no recent success → FAIL (per the
        explicit requirement)."""
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[
                pp.flow_run(
                    run_id="hard", flow_id=_FLOW_ID, status="Failed",
                    response_name="Respond_to_Copilot_with_XmlTemplate_To_Json_Failed",
                    error={"code": "ActionFailed", "message": "An action failed."},
                ),
            ],
        ))

        r = _only(_check_workday_run_health(runner))
        assert r.status == "Failed"
        assert "The most recent Workday flow run FAILED and no fresh run succeeded" in r.result
        assert "flow run Failed" in r.result


class TestEdgeCases:
    @responses.activate
    def test_no_recent_runs_is_not_configured(self, runner: _MinimalRunner) -> None:
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID, runs=[],
        ))

        r = _only(_check_workday_run_health(runner))
        assert r.status == "NotConfigured"
        assert "No recent Workday flow runs found" in r.result
        # Must carry the guided user-assisted E2E remediation (sign in, run a
        # safe read-only scenario, re-run within the freshness window)...
        assert "sign in to ESS Copilot" in r.remediation
        assert "read-only" in r.remediation
        assert "60 minutes" in r.remediation
        # ...and still steer the operator to connection status for the no-run case.
        assert "broken connection produces NO runs" in r.remediation
        assert "WD-CONN-001" in r.remediation

    @responses.activate
    def test_running_state_is_ignored(self, runner: _MinimalRunner) -> None:
        """An in-flight run (status=Running) is not scored as success or
        failure — only terminal runs count. With no terminal run to grade, the
        check reports the run as in-progress (steer the operator to wait and
        re-run) rather than claiming no runtime traffic."""
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[pp.flow_run(run_id="live", flow_id=_FLOW_ID, status="Running")],
        ))

        r = _only(_check_workday_run_health(runner))
        assert r.status == "NotConfigured"
        assert r.status != "Passed" and r.status != "Failed"
        assert "No completed Workday flow runs yet to evaluate" in r.result
        assert "currently in progress" in r.result
        assert "Re-run /flightcheck once the in-progress run completes" in r.remediation

    @responses.activate
    def test_running_run_alongside_fresh_success_still_passes(
        self, runner: _MinimalRunner
    ) -> None:
        """An in-flight (Running) run must not suppress a genuine fresh success:
        the terminal success is graded and PASSES; the Running run is ignored."""
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[
                pp.flow_run(run_id="live", flow_id=_FLOW_ID, status="Running"),
                pp.flow_run(run_id="ok", flow_id=_FLOW_ID, status="Succeeded"),
            ],
        ))

        r = _only(_check_workday_run_health(runner))
        assert r.status == "Passed"
        assert "1 most recent Workday flow run(s) succeeded" in r.result

    @responses.activate
    def test_cancelled_only_window_is_not_a_misleading_pass(
        self, runner: _MinimalRunner
    ) -> None:
        """Pins the review fix: a window of only Cancelled runs must NOT count
        as success (which would PASS and hide the manual conn/sec checks).
        Cancelled is inconclusive → non-scoring → NotConfigured."""
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[
                pp.flow_run(run_id="c1", flow_id=_FLOW_ID, status="Cancelled"),
                pp.flow_run(run_id="c2", flow_id=_FLOW_ID, status="Cancelled"),
            ],
        ))

        r = _only(_check_workday_run_health(runner))
        assert r.status == "NotConfigured"
        assert r.status != "Passed"

    @responses.activate
    def test_cancelled_runs_excluded_recent_success_still_passes(
        self, runner: _MinimalRunner
    ) -> None:
        """Cancelled runs are non-scoring, so genuine recent successes alongside
        them still PASS (a cancellation is not a Workday failure)."""
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[
                pp.flow_run(run_id="c1", flow_id=_FLOW_ID, status="Cancelled"),
                pp.flow_run(run_id="s1", flow_id=_FLOW_ID, status="Succeeded"),
            ],
        ))

        r = _only(_check_workday_run_health(runner))
        assert r.status == "Passed"
        assert "1 most recent Workday flow run(s) succeeded" in r.result

    @responses.activate
    def test_timedout_run_counts_as_failure(self, runner: _MinimalRunner) -> None:
        """A run-level TimedOut is a genuine run failure (not a success)."""
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[pp.flow_run(run_id="t1", flow_id=_FLOW_ID, status="TimedOut")],
        ))

        r = _only(_check_workday_run_health(runner))
        assert r.status == "Failed"
        assert "The most recent Workday flow run FAILED and no fresh run succeeded" in r.result

    @responses.activate
    def test_403_is_skipped_with_permission_note(self, runner: _MinimalRunner) -> None:
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.insufficient_permissions(
            env_id=runner.env_id, endpoint="flow_runs", flow_id=_FLOW_ID,
        ))

        r = _only(_check_workday_run_health(runner))
        assert r.status == "Skipped"
        assert "Unable to read Workday flow run history" in r.result
        assert "owner/maker access" in r.remediation

    def test_no_flows_is_skipped(self, pp_client) -> None:
        from flightcheck.checks.workday import _check_workday_run_health

        runner = _MinimalRunner(pp_admin=pp_client, env_id=pp.MOCK_ENV_ID, _workday_flows=[])
        r = _only(_check_workday_run_health(runner))
        assert r.status == "Skipped"
        assert "No Workday flows discovered" in r.result

    def test_no_pp_admin_is_skipped(self) -> None:
        from flightcheck.checks.workday import _check_workday_run_health

        runner = _MinimalRunner(pp_admin=None, env_id=pp.MOCK_ENV_ID, _workday_flows=[])
        r = _only(_check_workday_run_health(runner))
        assert r.status == "Skipped"
        assert "Power Platform Admin API not available" in r.result


class TestFreshness:
    """WD-RUN-001 user-assisted E2E freshness gate: only a run started within
    the last 60 minutes counts toward a PASS. A stale-only history yields a
    guided NOT_CONFIGURED (not a FAIL — stale history is not evidence of
    breakage)."""

    @staticmethod
    def _ts(minutes_ago: int) -> str:
        from datetime import datetime, timedelta, timezone
        dt = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")

    @responses.activate
    def test_stale_only_successes_is_guided_not_configured(
        self, runner: _MinimalRunner
    ) -> None:
        """All runs succeeded but all are older than the freshness window →
        NOT_CONFIGURED with guided sign-in remediation (an old success cannot
        prove the live path still works)."""
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[
                pp.flow_run(run_id="old1", flow_id=_FLOW_ID, status="Succeeded",
                            start_time=self._ts(180)),
                pp.flow_run(run_id="old2", flow_id=_FLOW_ID, status="Succeeded",
                            start_time=self._ts(240)),
            ],
        ))

        r = _only(_check_workday_run_health(runner))
        assert r.status == "NotConfigured"
        assert "last 60 minutes" in r.result
        assert "Older successes are not counted as a PASS" in r.result
        assert "sign in to ESS Copilot" in r.remediation.lower() or \
            "sign in to ess copilot" in r.remediation.lower()
        assert "read-only" in r.remediation

    @responses.activate
    def test_fresh_success_passes(self, runner: _MinimalRunner) -> None:
        """An explicit fresh success (inside the window) PASSES."""
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[
                pp.flow_run(run_id="fresh", flow_id=_FLOW_ID, status="Succeeded",
                            start_time=self._ts(5)),
            ],
        ))

        r = _only(_check_workday_run_health(runner))
        assert r.status == "Passed"
        assert "succeeded" in r.result.lower()

    @responses.activate
    def test_fresh_all_failed_is_failure(self, runner: _MinimalRunner) -> None:
        """A fresh run that failed (no fresh success) is a deterministic break
        → FAIL, not the guided NOT_CONFIGURED."""
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[
                pp.flow_run(run_id="f1", flow_id=_FLOW_ID, status="Failed",
                            response_name="Respond_to_Copilot_with_XmlTemplate_To_Json_Failed",
                            error={"code": "ActionFailed", "message": "An action failed."},
                            start_time=self._ts(3)),
            ],
        ))

        r = _only(_check_workday_run_health(runner))
        assert r.status == "Failed"
        assert "FAILED" in r.result

    @responses.activate
    def test_fresh_failure_with_stale_success_is_failure(
        self, runner: _MinimalRunner
    ) -> None:
        """A stale success does NOT rescue a fresh failure: only the fresh run
        is in the window, so the verdict is FAIL."""
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[
                pp.flow_run(run_id="freshfail", flow_id=_FLOW_ID, status="Failed",
                            response_name="Respond_to_Copilot_with_XmlTemplate_To_Json_Failed",
                            error={"code": "ActionFailed", "message": "An action failed."},
                            start_time=self._ts(2)),
                pp.flow_run(run_id="staleok", flow_id=_FLOW_ID, status="Succeeded",
                            start_time=self._ts(500)),
            ],
        ))

        r = _only(_check_workday_run_health(runner))
        assert r.status == "Failed"

    @responses.activate
    def test_unparseable_timestamps_is_guided_not_configured(
        self, runner: _MinimalRunner
    ) -> None:
        """If terminal runs exist but NONE has a parseable startTime, freshness
        cannot be proven. PASS requires a proven-fresh success, so the check
        refuses to grade (guided NOT_CONFIGURED) rather than fall back to a
        stale-tolerant window that could PASS on an unproven-fresh run."""
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[
                pp.flow_run(run_id="g1", flow_id=_FLOW_ID, status="Succeeded",
                            start_time="not-a-timestamp"),
            ],
        ))

        r = _only(_check_workday_run_health(runner))
        assert r.status == "NotConfigured"
        assert r.status != "Passed"
        assert "could not read a usable timestamp" in r.result
        assert "freshness cannot be verified" in r.result
        assert "sign in to ESS Copilot" in r.remediation.lower() or \
            "sign in to ess copilot" in r.remediation.lower()


class TestManualConnSecSuppression:
    """`_suppress_manual_conn_sec_when_runs_healthy` hides MANUAL Workday
    connection/security rows only when WD-RUN-001 PASSED."""

    @staticmethod
    def _cr(checkpoint_id, status):
        from flightcheck.runner import CheckResult, Priority
        return CheckResult(
            checkpoint_id=checkpoint_id, category="Workday",
            priority=Priority.HIGH.value, status=status,
            description="x", result="x", roles=["Workday Admin"],
        )

    def _build(self, run_status):
        from flightcheck.runner import Status
        return [
            self._cr("WD-RUN-001", run_status),
            self._cr("WD-CONN-010", Status.MANUAL.value),   # federation (manual)
            self._cr("WD-CONN-102", Status.MANUAL.value),   # SAML cert (manual)
            self._cr("WD-SEC-003", Status.MANUAL.value),    # personal-data (manual)
            self._cr("WD-CONN-001", Status.PASSED.value),   # connection status (not manual)
            self._cr("WD-WF-CAT-001", Status.MANUAL.value),  # workflow manual (NOT conn/sec)
        ]

    def test_passed_run_health_hides_manual_conn_sec(self) -> None:
        from flightcheck.checks.workday import _suppress_manual_conn_sec_when_runs_healthy
        from flightcheck.runner import Status

        out = _suppress_manual_conn_sec_when_runs_healthy(self._build(Status.PASSED.value))
        ids = {r.checkpoint_id for r in out}
        assert "WD-CONN-010" not in ids
        assert "WD-CONN-102" not in ids
        assert "WD-SEC-003" not in ids
        # Non-manual conn check and the (non conn/sec) workflow manual stay.
        assert "WD-CONN-001" in ids
        assert "WD-WF-CAT-001" in ids
        assert "WD-RUN-001" in ids

    def test_profile_mode_preserves_declared_manual_rows(self) -> None:
        from types import SimpleNamespace

        from flightcheck.checks.workday import (
            _suppress_manual_conn_sec_when_runs_healthy,
        )
        from flightcheck.runner import Status

        runner = SimpleNamespace(preserve_workday_manual_rows=True)
        out = _suppress_manual_conn_sec_when_runs_healthy(
            self._build(Status.PASSED.value),
            runner,
        )

        ids = {row.checkpoint_id for row in out}
        assert {"WD-CONN-010", "WD-CONN-102", "WD-SEC-003"} <= ids

    def test_failed_run_health_keeps_manual_conn_sec(self) -> None:
        from flightcheck.checks.workday import _suppress_manual_conn_sec_when_runs_healthy
        from flightcheck.runner import Status

        out = _suppress_manual_conn_sec_when_runs_healthy(self._build(Status.FAILED.value))
        ids = {r.checkpoint_id for r in out}
        assert {"WD-CONN-010", "WD-CONN-102", "WD-SEC-003"} <= ids

    def test_not_configured_run_health_keeps_manual_conn_sec(self) -> None:
        """No traffic yet (e.g. fresh pre-deploy) — manual checks stay visible."""
        from flightcheck.checks.workday import _suppress_manual_conn_sec_when_runs_healthy
        from flightcheck.runner import Status

        out = _suppress_manual_conn_sec_when_runs_healthy(self._build(Status.NOT_CONFIGURED.value))
        ids = {r.checkpoint_id for r in out}
        assert {"WD-CONN-010", "WD-CONN-102", "WD-SEC-003"} <= ids


class TestComputeRunFailureSignal:
    """`_compute_run_failure_signal` summarises the recent-window failure
    categories that drive error-aware manual-check suppression."""

    @staticmethod
    def _row(kind, resp):
        return {"kind": kind, "resp": resp}

    def test_success_is_auth_proven_only(self) -> None:
        from flightcheck.checks.workday import (
            _compute_run_failure_signal, _WD_SUCCESS_RESPONSE_ACTION,
        )
        sig = _compute_run_failure_signal(
            [self._row("success", _WD_SUCCESS_RESPONSE_ACTION)]
        )
        assert sig["auth_proven"] is True
        assert sig["workday_fault"] is False
        assert sig["hard_failure"] is False

    def test_caught_workday_fault_sets_auth_and_fault(self) -> None:
        from flightcheck.checks.workday import (
            _compute_run_failure_signal, _WD_WORKDAY_FAULT_RESPONSE,
        )
        sig = _compute_run_failure_signal(
            [self._row("caught_failure", _WD_WORKDAY_FAULT_RESPONSE)]
        )
        # A caught Workday SOAP fault proves the token was accepted (auth) AND
        # carries the permission/credential signal.
        assert sig["auth_proven"] is True
        assert sig["workday_fault"] is True

    def test_template_transform_is_auth_proven_without_fault(self) -> None:
        from flightcheck.checks.workday import (
            _compute_run_failure_signal, _WD_TEMPLATE_TRANSFORM_RESPONSE,
        )
        sig = _compute_run_failure_signal(
            [self._row("caught_failure", _WD_TEMPLATE_TRANSFORM_RESPONSE)]
        )
        assert sig["auth_proven"] is True
        assert sig["workday_fault"] is False

    def test_template_retrieval_is_uninformative(self) -> None:
        from flightcheck.checks.workday import (
            _compute_run_failure_signal, _WD_TEMPLATE_RETRIEVAL_RESPONSE,
        )
        sig = _compute_run_failure_signal(
            [self._row("caught_failure", _WD_TEMPLATE_RETRIEVAL_RESPONSE)]
        )
        # Pre-call config error — rules nothing out about auth or permission.
        assert sig == {
            "auth_proven": False, "workday_fault": False, "hard_failure": False,
        }

    def test_hard_failure_is_not_auth_proven(self) -> None:
        from flightcheck.checks.workday import _compute_run_failure_signal
        sig = _compute_run_failure_signal([self._row("hard_failure", "?")])
        assert sig["auth_proven"] is False
        assert sig["workday_fault"] is False
        assert sig["hard_failure"] is True


class TestErrorAwareManualSuppression:
    """The refined `_suppress_manual_conn_sec_when_runs_healthy` removes a manual
    check only on positive evidence its failure DOMAIN is not the culprit."""

    @staticmethod
    def _cr(checkpoint_id, status):
        from flightcheck.runner import CheckResult, Priority
        return CheckResult(
            checkpoint_id=checkpoint_id, category="Workday",
            priority=Priority.HIGH.value, status=status,
            description="x", result="x", roles=["Workday Admin"],
        )

    def _build(self, run_status):
        from flightcheck.runner import Status
        return [
            self._cr("WD-RUN-001", run_status),
            self._cr("WD-CONN-010", Status.MANUAL.value),
            self._cr("WD-CONN-102", Status.MANUAL.value),
            self._cr("WD-SEC-003", Status.MANUAL.value),
        ]

    @staticmethod
    def _runner(signal):
        from types import SimpleNamespace
        return SimpleNamespace(_workday_run_failure_signal=signal)

    def _ids_after(self, run_status, signal):
        from flightcheck.checks.workday import _suppress_manual_conn_sec_when_runs_healthy
        from flightcheck.runner import Status
        status = getattr(Status, run_status).value
        out = _suppress_manual_conn_sec_when_runs_healthy(
            self._build(status), self._runner(signal)
        )
        return {r.checkpoint_id for r in out}

    def test_caught_fault_shows_only_permission(self) -> None:
        ids = self._ids_after("FAILED", {
            "auth_proven": True, "workday_fault": True, "hard_failure": False,
        })
        assert "WD-CONN-010" not in ids
        assert "WD-CONN-102" not in ids
        assert "WD-SEC-003" in ids

    def test_transform_only_shows_all_via_safety_net(self) -> None:
        # auth_proven + no fault would rule out ALL three manual checks while
        # runs are unhealthy — contradictory, so the safety net shows them all
        # rather than leave the operator with zero guidance.
        ids = self._ids_after("FAILED", {
            "auth_proven": True, "workday_fault": False, "hard_failure": False,
        })
        assert {"WD-CONN-010", "WD-CONN-102", "WD-SEC-003"} <= ids

    def test_safety_net_holds_with_hard_failure_present(self) -> None:
        # Same rule-out-everything situation but with a hard failure too — still
        # show all (the break is outside the modelled manual domains).
        ids = self._ids_after("FAILED", {
            "auth_proven": True, "workday_fault": False, "hard_failure": True,
        })
        assert {"WD-CONN-010", "WD-CONN-102", "WD-SEC-003"} <= ids

    def test_hard_failure_only_keeps_all(self) -> None:
        # No Workday response, nothing proven -> nothing ruled out -> keep all.
        ids = self._ids_after("FAILED", {
            "auth_proven": False, "workday_fault": False, "hard_failure": True,
        })
        assert {"WD-CONN-010", "WD-CONN-102", "WD-SEC-003"} <= ids

    def test_uninformative_signal_keeps_all(self) -> None:
        ids = self._ids_after("FAILED", {
            "auth_proven": False, "workday_fault": False, "hard_failure": False,
        })
        assert {"WD-CONN-010", "WD-CONN-102", "WD-SEC-003"} <= ids

    def test_fault_plus_hard_shows_only_permission(self) -> None:
        # The caught fault proves SSO works, so the hard failure is not SSO.
        ids = self._ids_after("FAILED", {
            "auth_proven": True, "workday_fault": True, "hard_failure": True,
        })
        assert "WD-CONN-010" not in ids
        assert "WD-CONN-102" not in ids
        assert "WD-SEC-003" in ids

    def test_passed_short_circuits_regardless_of_signal(self) -> None:
        # Even a permission-implicating signal is overridden by a clean PASS.
        ids = self._ids_after("PASSED", {
            "auth_proven": True, "workday_fault": True, "hard_failure": False,
        })
        assert {"WD-CONN-010", "WD-CONN-102", "WD-SEC-003"}.isdisjoint(ids)


class TestPrereqGate:
    """Ordering gate: when an env/connection/flow prerequisite already FAILED
    earlier in the run, the guided NOT_CONFIGURED remediation steers the
    operator at that specific rung first, because a live Copilot → Workday run
    cannot succeed until the broken rung is fixed."""

    @staticmethod
    def _failed(checkpoint_id):
        from flightcheck.runner import CheckResult, Priority, Status
        return CheckResult(
            checkpoint_id=checkpoint_id, category="Workday",
            priority=Priority.HIGH.value, status=Status.FAILED.value,
            description="x", result="x", roles=["Workday Admin"],
        )

    @staticmethod
    def _passed(checkpoint_id):
        from flightcheck.runner import CheckResult, Priority, Status
        return CheckResult(
            checkpoint_id=checkpoint_id, category="Workday",
            priority=Priority.PASSED.value if hasattr(Priority, "PASSED") else Priority.HIGH.value,
            status=Status.PASSED.value,
            description="x", result="x", roles=["Workday Admin"],
        )

    @responses.activate
    def test_no_runs_with_failed_connection_redirects_to_that_rung(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID, runs=[],
        ))

        prior = [self._passed("WD-ENV-001"), self._failed("WD-CONN-101")]
        r = _only(_check_workday_run_health(runner, prior))
        assert r.status == "NotConfigured"
        # Steer at the failed rung first...
        assert "prerequisite check failed" in r.remediation.lower()
        assert "WD-CONN-101" in r.remediation
        # ...but still carry the guided user-assisted E2E steps after it.
        assert "sign in to ESS Copilot" in r.remediation

    @responses.activate
    def test_stale_run_with_failed_env_redirects_to_that_rung(
        self, runner: _MinimalRunner
    ) -> None:
        from datetime import datetime, timedelta, timezone

        from flightcheck.checks.workday import _check_workday_run_health

        def _ts(minutes_ago: int) -> str:
            dt = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
            return dt.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[pp.flow_run(run_id="old", flow_id=_FLOW_ID,
                              status="Succeeded", start_time=_ts(180))],
        ))

        prior = [self._failed("WD-ENV-101")]
        r = _only(_check_workday_run_health(runner, prior))
        assert r.status == "NotConfigured"
        assert "WD-ENV-101" in r.remediation

    @responses.activate
    def test_no_failed_prereq_keeps_generic_guided_text(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID, runs=[],
        ))

        # All prerequisites green → no redirect, generic guided remediation.
        prior = [self._passed("WD-ENV-001"), self._passed("WD-CONN-101")]
        r = _only(_check_workday_run_health(runner, prior))
        assert r.status == "NotConfigured"
        assert "prerequisite check failed" not in r.remediation.lower()
        assert "sign in to ESS Copilot" in r.remediation

    @responses.activate
    def test_non_prereq_failure_does_not_trigger_redirect(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID, runs=[],
        ))

        # A failed non-prerequisite check (e.g. a workflow SOAP test) must NOT
        # redirect — only env/connection/flow rungs gate the live run.
        prior = [self._failed("WD-WF-001")]
        r = _only(_check_workday_run_health(runner, prior))
        assert r.status == "NotConfigured"
        assert "prerequisite check failed" not in r.remediation.lower()


class TestNegativeSkewClamp:
    """Minor clock skew between this host and Power Automate must never render a
    negative age (e.g. "-1 minute(s) ago"); the age is clamped at 0."""

    @staticmethod
    def _future_ts(minutes_ahead: int) -> str:
        from datetime import datetime, timedelta, timezone
        dt = datetime.now(timezone.utc) + timedelta(minutes=minutes_ahead)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")

    @responses.activate
    def test_inflight_future_timestamp_clamps_age_to_zero(
        self, runner: _MinimalRunner
    ) -> None:
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[pp.flow_run(run_id="skewed", flow_id=_FLOW_ID,
                              status="Running", start_time=self._future_ts(3))],
        ))

        r = _only(_check_workday_run_health(runner))
        assert r.status == "NotConfigured"
        assert "started about 0 minute(s) ago" in r.result
        assert "minute(s) ago" in r.result
        assert "-" not in r.result.split("minute(s) ago")[0].split("about ")[-1]

