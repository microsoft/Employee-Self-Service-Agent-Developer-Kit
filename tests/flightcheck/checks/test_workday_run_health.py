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
        assert "All 1 most recent Workday flow run(s) FAILED" in r.result
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
        # Must steer the operator to connection status for the no-run case.
        assert "broken connection produces NO runs" in r.remediation
        assert "WD-CONN-001" in r.remediation

    @responses.activate
    def test_running_state_is_ignored(self, runner: _MinimalRunner) -> None:
        """An in-flight run (status=Running) is not scored as success or
        failure — only terminal runs count."""
        from flightcheck.checks.workday import _check_workday_run_health

        responses.add(**pp.list_flow_runs(
            env_id=runner.env_id, flow_id=_FLOW_ID,
            runs=[pp.flow_run(run_id="live", flow_id=_FLOW_ID, status="Running")],
        ))

        r = _only(_check_workday_run_health(runner))
        assert r.status == "NotConfigured"
        assert "No recent Workday flow runs found" in r.result

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
