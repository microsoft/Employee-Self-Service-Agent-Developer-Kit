# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Integration tests for INFRA-003's opt-in ``--runtime-reachability`` egress path.

Unlike the default local probe (test_infra_003_reachability.py, stdlib
only), the live path drives the real Power Automate transient-flow
lifecycle over HTTP, so these tests replay the validated cassette shapes
through the ``tests.mocks.power_automate`` builders (cardinal rule:
validated-tier API => cassette-backed mock + a test that replays it).

Covered:
- egress-reachable  (invoke returns an int reachableStatusCode) -> PASS
- egress-blocked    (invoke returns null)                       -> FAIL
- indeterminate     (create fails)  -> MANUAL guidance (no local fallback)
- guaranteed cleanup (the created flow is always DELETEd; orphan sweep runs)
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import responses

from tests.conftest import require_validated_mock
from tests.mocks import power_automate as pa

from flightcheck.checks.infrastructure import (
    check_external_endpoint_reachability,
)
from flightcheck.runner import Priority, Role, Status

require_validated_mock(pa)


# ───────────────────────────────────────────────────────────────────────
# Fixtures
# ───────────────────────────────────────────────────────────────────────


def _live_runner(connections: dict[str, Any], *, pp: Any = None) -> SimpleNamespace:
    """A runner with --runtime-reachability on and every egress prerequisite present."""
    return SimpleNamespace(
        config={"connections": connections},
        runtime_reachability=True,
        pp_admin=pp if pp is not None else SimpleNamespace(
            flow_headers={"Authorization": "Bearer flow-token"}
        ),
        env_id=pa.MOCK_ENV_ID,
        env_url=pa.MOCK_ENV_URL,
        dv_token="dv-token",
    )


def _register_lifecycle(*, reachable_status_code: int | None) -> None:
    """Register one full create/activate/callback/invoke/delete lifecycle
    plus the orphan-sweep GET (used for both the pre- and post-run sweep)."""
    responses.add(**pa.find_workflows())            # orphan sweep (pre + post)
    responses.add(**pa.create_workflow())
    responses.add(**pa.activate_workflow())
    responses.add(**pa.list_callback_url())
    responses.add(**pa.invoke_probe(reachable_status_code=reachable_status_code))
    responses.add(**pa.delete_workflow())



# ───────────────────────────────────────────────────────────────────────
# Reachable / blocked from the environment's own egress
# ───────────────────────────────────────────────────────────────────────


class TestLiveProbeOutcomes:
    @responses.activate
    def test_reachable_status_code_passes_with_egress_wording(self):
        _register_lifecycle(reachable_status_code=302)
        runner = _live_runner({"Workday": {"baseUrl": "https://wd.example.com"}})

        results = check_external_endpoint_reachability(runner)

        assert len(results) == 1
        row = results[0]
        assert row.status == Status.PASSED.value
        assert row.checkpoint_id == "INFRA-003"
        assert row.priority == Priority.CRITICAL.value
        # Reachability came from the egress, not the local machine.
        assert "Reachable from Power Platform egress (HTTP 302)" in row.result
        assert "environment's own egress" in row.result
        # The local "necessary but not sufficient" caveat must NOT apply.
        assert "necessary but not sufficient" not in row.result
        assert row.remediation == ""

    @responses.activate
    def test_null_status_code_fails_as_egress_blocked(self):
        _register_lifecycle(reachable_status_code=None)
        runner = _live_runner({"ServiceNow": {"instanceUrl": "https://sn.example.com"}})

        results = check_external_endpoint_reachability(runner)

        assert len(results) == 1
        row = results[0]
        assert row.status == Status.FAILED.value
        assert "UNREACHABLE from Power Platform egress" in row.result
        assert "DLP block" in row.result
        # Five-field Shared Steps role-aware finding is still emitted (AC5).
        assert "Probable cause:" in row.remediation
        assert "Configuration Area or Scope:" in row.remediation
        assert "What it implies:" in row.remediation
        assert "Next steps:" in row.remediation
        assert "Responsible role:" in row.remediation
        assert "Impact:" not in row.remediation
        assert Role.SERVICENOW_ADMIN.value in row.roles
        assert Role.POWER_PLATFORM_ADMIN.value in row.roles


# ───────────────────────────────────────────────────────────────────────
# Cleanup / idempotency (AC7) — the transient flow is always deleted
# ───────────────────────────────────────────────────────────────────────


class TestLiveProbeCleanup:
    @responses.activate
    def test_created_flow_is_deleted(self):
        _register_lifecycle(reachable_status_code=200)
        runner = _live_runner({"Workday": {"baseUrl": "https://wd.example.com"}})

        check_external_endpoint_reachability(runner)

        methods = [c.request.method for c in responses.calls]
        assert "POST" in methods       # create
        assert "DELETE" in methods     # cleanup of the transient flow
        # Orphan sweep ran (the GET $filter) both before and after.
        assert methods.count("GET") >= 2

    @responses.activate
    def test_pre_run_orphan_from_crashed_prior_run_is_swept(self):
        # A leftover probe flow exists; the pre-run sweep must delete it.
        responses.add(**pa.find_workflows(workflows=[pa.workflow_row()]))
        responses.add(**pa.delete_workflow())       # sweep of the orphan
        responses.add(**pa.create_workflow())
        responses.add(**pa.activate_workflow())
        responses.add(**pa.list_callback_url())
        responses.add(**pa.invoke_probe(reachable_status_code=200))
        # find is re-used for the post sweep (empty after orphan gone is not
        # required — responses reuses the single GET registration).
        runner = _live_runner({"Workday": {"baseUrl": "https://wd.example.com"}})

        results = check_external_endpoint_reachability(runner)

        assert results[0].status == Status.PASSED.value
        assert sum(c.request.method == "DELETE" for c in responses.calls) >= 1

    @responses.activate
    def test_delete_failure_keeps_result_and_never_raises(self):
        # The probe answered (reachable) but the cleanup DELETE is refused (403,
        # e.g. insufficient rights). The run must still return the valid PASS
        # result and never raise; the residue is left for the orphan sweep to
        # reap on this or the next run.
        responses.add(**pa.find_workflows())            # orphan sweep (pre + post)
        responses.add(**pa.create_workflow())
        responses.add(**pa.activate_workflow())
        responses.add(**pa.list_callback_url())
        responses.add(**pa.invoke_probe(reachable_status_code=200))
        responses.add(**pa.delete_workflow(status=403))  # cleanup refused
        runner = _live_runner({"Workday": {"baseUrl": "https://wd.example.com"}})

        results = check_external_endpoint_reachability(runner)

        row = results[0]
        assert row.status == Status.PASSED.value
        assert "Reachable from Power Platform egress" in row.result
        # Cleanup was still attempted despite the refusal.
        assert any(c.request.method == "DELETE" for c in responses.calls)


# ───────────────────────────────────────────────────────────────────────
# delete_probe_flow — cleanup is best-effort, retries once, never raises
# ───────────────────────────────────────────────────────────────────────


class TestDeleteProbeFlow:
    @responses.activate
    def test_403_is_non_retryable_and_returns_false(self):
        from flightcheck.live_egress_probe import delete_probe_flow

        responses.add(**pa.delete_workflow(status=403))

        ok = delete_probe_flow(pa.MOCK_ENV_URL, "dv-token", pa.MOCK_WORKFLOW_ID)

        assert ok is False
        # 403 is non-retryable: no PATCH deactivate + retry, just the one DELETE.
        assert [c.request.method for c in responses.calls] == ["DELETE"]

    @responses.activate
    def test_409_deactivates_then_deletes_successfully(self):
        from flightcheck.live_egress_probe import delete_probe_flow

        # An active flow refuses deletion (409) -> deactivate (PATCH) -> retry
        # DELETE succeeds (204).
        responses.add(**pa.delete_workflow(status=409))
        responses.add(**pa.activate_workflow())          # PATCH statecode (deactivate)
        responses.add(**pa.delete_workflow(status=204))

        ok = delete_probe_flow(pa.MOCK_ENV_URL, "dv-token", pa.MOCK_WORKFLOW_ID)

        assert ok is True
        assert [c.request.method for c in responses.calls] == ["DELETE", "PATCH", "DELETE"]


# ───────────────────────────────────────────────────────────────────────
# Indeterminate egress probe -> MANUAL guidance (no local fallback)
# ───────────────────────────────────────────────────────────────────────


class TestLiveProbeIndeterminate:
    @responses.activate
    def test_create_failure_is_manual_not_local_probe(self):
        # Flow creation fails (500) -> the egress result is indeterminate. The
        # local probe was removed, so the endpoint is reported MANUAL with
        # guidance, never a laptop probe.
        responses.add(**pa.find_workflows())
        responses.add(**pa.create_workflow(status=500))
        runner = _live_runner({"Workday": {"baseUrl": "https://wd.example.com"}})

        results = check_external_endpoint_reachability(runner)

        assert len(results) == 1
        row = results[0]
        assert row.status == Status.MANUAL.value
        assert "UNDETERMINED from the egress probe" in row.result
        assert "[local only]" not in row.result
        assert "necessary but not sufficient" not in row.result
        # Guidance points back at the egress probe + manual verification.
        assert "--runtime-reachability" in row.remediation
        assert Role.WORKDAY_ADMIN.value in row.roles
        assert Role.POWER_PLATFORM_ADMIN.value in row.roles

    def test_missing_prerequisites_is_manual_guidance(self):
        # --runtime-reachability requested but no pp_admin / env / token on the
        # runner: the egress probe can't run, so MANUAL guidance (no local probe).
        runner = SimpleNamespace(
            config={"connections": {"Workday": {"baseUrl": "https://wd.example.com"}}},
            runtime_reachability=True,
        )

        results = check_external_endpoint_reachability(runner)

        assert len(results) == 1
        row = results[0]
        assert row.status == Status.MANUAL.value
        assert "could not run" in row.result
        assert "NOT tested" in row.result
        assert "--runtime-reachability" in row.remediation
