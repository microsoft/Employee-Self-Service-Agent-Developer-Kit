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
from flightcheck.live_egress_probe import (
    interpret_connector_probe_response,
    interpret_probe_response,
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


class TestInterpretProbeResponse:
    """interpret_probe_response must separate a genuine egress block (explicit
    JSON null for a present key) from an UNDETERMINED probe (absent/malformed
    body). Only the former is FAIL; the latter is reachable=None -> MANUAL."""

    def test_int_status_is_reachable(self):
        result = interpret_probe_response(
            {"reachableStatusCode": 404, "actionStatus": "Failed"}
        )

        assert result.reachable is True
        assert result.status_code == 404

    def test_explicit_null_status_is_blocked(self):
        # Key present, value explicitly null: the flow ran and the HTTP action
        # got no response -> a real egress block -> FAIL.
        result = interpret_probe_response(
            {"reachableStatusCode": None, "actionStatus": "Failed"}
        )

        assert result.reachable is False

    def test_missing_key_is_undetermined(self):
        # Dict body but no reachableStatusCode: contract not satisfied -> we do
        # NOT know the result, so MANUAL (reachable None), never FAIL.
        result = interpret_probe_response({"actionStatus": "Succeeded"})

        assert result.reachable is None

    def test_non_dict_body_is_undetermined(self):
        # A None / unparseable trigger body must not be reported as a block.
        assert interpret_probe_response(None).reachable is None
        assert interpret_probe_response("not-json").reachable is None

    def test_bool_status_is_undetermined(self):
        # bool is an int subclass but is not a valid HTTP status code.
        assert interpret_probe_response({"reachableStatusCode": True}).reachable is None


class TestInterpretConnectorProbeResponse:
    """interpret_connector_probe_response maps a synchronous connector-probe
    body to a tri-state result. Only a Succeeded action is a pass; a failed
    action (or any error signal) is a fail; an absent/malformed body is
    undetermined (succeeded None), never a false fail."""

    def test_succeeded_action_passes_with_status(self):
        result = interpret_connector_probe_response(
            {"connectorActionStatus": "Succeeded", "connectorStatusCode": 200}
        )

        assert result.succeeded is True
        assert result.status_code == 200
        assert "HTTP 200" in result.detail

    def test_failed_action_fails_with_status_and_code(self):
        result = interpret_connector_probe_response(
            {
                "connectorActionStatus": "Failed",
                "connectorStatusCode": 400,
                "connectorErrorCode": "BadRequest",
            }
        )

        assert result.succeeded is False
        assert result.status_code == 400
        assert result.error_code == "BadRequest"

    def test_skipped_action_is_failure(self):
        # A Skipped connector action means the probe did not exercise egress
        # cleanly; treat it as a failure signal, not a pass.
        result = interpret_connector_probe_response(
            {"connectorActionStatus": "Skipped"}
        )

        assert result.succeeded is False

    def test_error_signal_without_status_is_failure(self):
        # No action status, but an error code is present -> fail, not undetermined.
        result = interpret_connector_probe_response(
            {"connectorErrorCode": "InternalServerError"}
        )

        assert result.succeeded is False
        assert result.error_code == "InternalServerError"

    def test_missing_action_status_is_undetermined(self):
        # Dict body but no action status and no error signal: contract not
        # satisfied -> undetermined, never a false fail.
        assert interpret_connector_probe_response({}).succeeded is None

    def test_non_dict_body_is_undetermined(self):
        assert interpret_connector_probe_response(None).succeeded is None
        assert interpret_connector_probe_response("not-json").succeeded is None

    def test_bool_status_is_ignored(self):
        # bool is an int subclass but is not a valid HTTP status code.
        result = interpret_connector_probe_response(
            {"connectorActionStatus": "Succeeded", "connectorStatusCode": True}
        )

        assert result.succeeded is True
        assert result.status_code is None

    def test_workday_prefixed_keys_are_read_as_fallback(self):
        # The live green body used workday* keys; the parser must accept them
        # when the connector* keys are absent.
        result = interpret_connector_probe_response(
            {"workdayActionStatus": "Succeeded", "workdayStatusCode": 200}
        )

        assert result.succeeded is True
        assert result.status_code == 200
