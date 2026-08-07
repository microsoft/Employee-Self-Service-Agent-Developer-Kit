# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""AC12 coverage for WD-RUN-001 v2 active Workday connector probe."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import requests
import responses

from tests.conftest import require_validated_mock
from tests.mocks import power_automate as pa
from tests.mocks import pp_admin as pp

from flightcheck.checks.workday import _check_workday_run_health
from flightcheck.runner import Status

require_validated_mock(pa)
require_validated_mock(pp)

_FLOW_ID = "00000000-0000-0000-0000-000000007101"
_CONNECTION_ID = "00000000-0000-0000-0000-00000000wd01"


class _PP:
    flow_headers = {"Authorization": "******"}

    def __init__(
        self,
        *,
        connections: list[dict[str, Any]] | None = None,
        runs: list[dict[str, Any]] | None = None,
    ) -> None:
        self._connections = connections if connections is not None else [
            _workday_connection()
        ]
        self._runs = runs if runs is not None else [
            pp.flow_run(run_id="ok", flow_id=_FLOW_ID, status="Succeeded")
        ]

    def get_connections(self, _env_id: str) -> list[dict[str, Any]]:
        return self._connections

    def get_flow_runs(self, _env_id: str, _flow_id: str) -> list[dict[str, Any]]:
        return self._runs


def _workday_connection(
    *,
    connection_name: str = _CONNECTION_ID,
    runtime_source: str | None = "embedded",
    display_name: str = "Workday SOAP ISU",
) -> dict[str, Any]:
    extra = {}
    if runtime_source is not None:
        extra["runtimeSource"] = runtime_source
    conn = pp.workday_connection(
        connection_name=connection_name,
        display_name=display_name,
    )
    conn["properties"].update(extra)
    return conn


def _runner(
    *,
    runtime_reachability: bool = True,
    runtime_reachability_declined: bool = False,
    pp_client: Any | None = None,
    config: dict[str, Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        pp_admin=pp_client if pp_client is not None else _PP(),
        env_id=pa.MOCK_ENV_ID,
        env_url=pa.MOCK_ENV_URL,
        dv_token="dv-token",
        runtime_reachability=runtime_reachability,
        runtime_reachability_declined=runtime_reachability_declined,
        config=config or {},
        _workday_flows=[pp.flow(flow_id=_FLOW_ID, display_name="ESS HR Workday")],
    )


def _register_connector_lifecycle(
    *,
    action_status: str | None = "Succeeded",
    status_code: int | None = 200,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    responses.add(**pa.find_workflows())
    responses.add(**pa.create_workflow(name=pa.MOCK_WORKDAY_PROBE_FLOW_NAME))
    responses.add(**pa.activate_workflow())
    responses.add(**pa.list_callback_url())
    responses.add(**pa.invoke_workday_connector_probe(
        action_status=action_status,
        status_code=status_code,
        error_code=error_code,
        error_message=error_message,
    ))
    responses.add(**pa.delete_workflow())
    responses.add(**pa.find_workflows())


def _run_single(runner: SimpleNamespace):
    results = _check_workday_run_health(runner)
    assert len(results) == 1
    return results[0]


@pytest.fixture(autouse=True)
def _clear_probe_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ESS_WD_PROBE_OPERATION_ID", raising=False)
    monkeypatch.delenv("ESS_WD_PROBE_PARAMS_JSON", raising=False)


class TestWorkdayActiveProbeMatrix:
    @responses.activate
    def test_healthy_pass_uses_connector_bound_managed_path(self) -> None:
        _register_connector_lifecycle()

        row = _run_single(_runner())

        assert row.status == Status.PASSED.value
        assert "retrieved data from Workday" in row.result
        assert "Workday service-account connection" in row.result
        # Shows the connection's display name, not the opaque BAP GUID (N2).
        assert "Workday SOAP ISU" in row.result
        assert _CONNECTION_ID not in row.result
        assert "did not test custom SOAP integrations" in row.result
        assert row.remediation == ""

    @responses.activate
    def test_dns_fail_names_network_dns_layer(self) -> None:
        _register_connector_lifecycle(
            action_status="Failed",
            status_code=None,
            error_code="DnsResolutionFailed",
        )

        row = _run_single(_runner())

        assert row.status == Status.FAILED.value
        assert "name resolution failed" in row.result
        assert "no HTTP status" in row.result

    @responses.activate
    def test_tls_cert_fail_names_network_tls_layer(self) -> None:
        _register_connector_lifecycle(
            action_status="Failed",
            status_code=None,
            error_code="TlsCertificateValidationFailed",
        )

        row = _run_single(_runner())

        assert row.status == Status.FAILED.value
        assert "TLS failed" in row.result

    @responses.activate
    def test_firewall_dlp_block_names_network_firewall_dlp_layer(self) -> None:
        _register_connector_lifecycle(
            action_status="Failed",
            status_code=None,
            error_code="DlpPolicyBlocked",
        )

        row = _run_single(_runner())

        assert row.status == Status.FAILED.value
        assert "traffic was blocked" in row.result

    @responses.activate
    def test_endpoint_misconfig_names_endpoint_configuration_layer(self) -> None:
        # Defensive 404 branch. Live Workday endpoint-not-found actually
        # returns HTTP 400 / BadRequest (see the indeterminate test below);
        # this 404 path is a documented assumption, not a live-captured shape.
        _register_connector_lifecycle(
            action_status="Failed",
            status_code=404,
            error_code="EndpointNotFound",
        )

        row = _run_single(_runner())

        assert row.status == Status.FAILED.value
        assert "endpoint or operation was not found" in row.result
        assert "HTTP 404" in row.result

    @responses.activate
    def test_authz_fail_names_authorization_layer(self) -> None:
        _register_connector_lifecycle(
            action_status="Failed",
            status_code=403,
            error_code="Unauthorized",
        )

        row = _run_single(_runner())

        assert row.status == Status.FAILED.value
        assert "authorization rejected the request" in row.result
        assert "HTTP 403" in row.result

    @responses.activate
    def test_http_400_badrequest_degrades_to_passive_not_failed(self) -> None:
        # Live-verified: a wrong endpoint/operation ("Unrecognized service
        # definition for path") and a Workday business fault ("You must
        # provide valid XML for the SOAP request body") BOTH surface as
        # HTTP 400 / BadRequest with no distinguishing synchronous signal.
        # A 400 reached Workday and got a structured rejection, so it cannot
        # prove the maker's connection is unhealthy (the default GetWorkerMe
        # operation may simply be unsupported in this tenant). It must degrade
        # to the passive run-history signal, NOT emit a FAILED that blames the
        # connection.
        _register_connector_lifecycle(
            action_status="Failed",
            status_code=400,
            error_code="BadRequest",
        )

        row = _run_single(_runner())

        # Falls back to passive run history (1 recent Succeeded run) -> PASSED,
        # never FAILED.
        assert row.status != Status.FAILED.value
        assert row.status == Status.PASSED.value
        assert "inconclusive" in row.result
        assert "HTTP 400" in row.result
        assert "cannot prove the connection is unhealthy" in row.result
        # A Workday call WAS made, so the copy must not claim otherwise.
        assert "No new Workday call was made" not in row.result

    @responses.activate
    def test_http_400_without_history_does_not_fabricate_verdict(self) -> None:
        # A 400 with no assessable run history must not claim history was read
        # and must not FAIL the connection.
        _register_connector_lifecycle(
            action_status="Failed",
            status_code=400,
            error_code="BadRequest",
        )

        row = _run_single(_runner(pp_client=_PP(runs=[])))

        assert row.status != Status.FAILED.value
        assert "inconclusive" in row.result
        assert "could not be assessed either" in row.result

    @responses.activate
    def test_server_error_names_connector_runtime_backend_layer(self) -> None:
        # Live-verified: an unhealthy/expired connection returns HTTP 500 /
        # InternalServerError from the connector runtime / Workday backend.
        _register_connector_lifecycle(
            action_status="Failed",
            status_code=500,
            error_code="InternalServerError",
        )

        row = _run_single(_runner())

        assert row.status == Status.FAILED.value
        assert "returned a server error" in row.result
        assert "HTTP 500" in row.result

    def test_consent_declined_falls_back_to_passive_run_history(self) -> None:
        row = _run_single(_runner(
            runtime_reachability=False,
            runtime_reachability_declined=True,
        ))

        assert row.status == Status.PASSED.value
        assert "All 1 most recent Workday flow run(s) succeeded" in row.result
        assert "live Workday connection test was not run" in row.result
        assert "recent Workday connector run history" in row.result

    def test_no_connection_is_not_configured_not_failed(self) -> None:
        row = _run_single(_runner(pp_client=_PP(connections=[])))

        assert row.status == Status.NOT_CONFIGURED.value
        assert "no Workday managed-connector connection was found" in row.result
        assert "live Workday connection test did not run" in row.result

    @responses.activate
    def test_cleanup_on_invoke_error_deletes_created_flow(self) -> None:
        responses.add(**pa.find_workflows())
        responses.add(**pa.create_workflow(name=pa.MOCK_WORKDAY_PROBE_FLOW_NAME))
        responses.add(**pa.activate_workflow())
        responses.add(**pa.list_callback_url())

        def _raise_connection_error(_request):
            raise requests.ConnectionError("simulated invoke failure")

        responses.add_callback(
            responses.POST,
            pa.MOCK_CALLBACK_URL,
            callback=_raise_connection_error,
        )
        responses.add(**pa.delete_workflow())
        responses.add(**pa.find_workflows())

        row = _run_single(_runner())

        assert row.status == Status.PASSED.value
        assert "could not complete" in row.result
        assert any(c.request.method == "DELETE" for c in responses.calls)

    def test_oauth_invoker_only_connection_falls_back_to_passive(self) -> None:
        row = _run_single(_runner(
            pp_client=_PP(connections=[
                _workday_connection(runtime_source="invoker"),
            ]),
        ))

        assert row.status == Status.PASSED.value
        assert "OAuth-invoker Workday connections" in row.result
        assert "recent Workday connector run history" in row.result

    @responses.activate
    def test_service_account_selection_is_deterministic_by_guid(self) -> None:
        # BAP does not guarantee connection list order. With more than one ISU /
        # service-account Workday connection, the probe must pick the same one
        # every run (lexicographically-first GUID), not whichever BAP happened
        # to return first. Passing the connections in reverse order must still
        # select connection "aaa".
        _register_connector_lifecycle()
        conn_a = _workday_connection(
            connection_name="wd-conn-aaa", display_name="Workday ISU A"
        )
        conn_b = _workday_connection(
            connection_name="wd-conn-bbb", display_name="Workday ISU B"
        )

        row = _run_single(_runner(pp_client=_PP(connections=[conn_b, conn_a])))

        assert row.status == Status.PASSED.value
        assert "Workday ISU A" in row.result
        assert "Workday ISU B" not in row.result

    def test_passive_fallback_without_history_does_not_claim_history(
        self,
    ) -> None:
        runner = _runner(
            runtime_reachability=False,
            runtime_reachability_declined=True,
        )
        runner._workday_flows = []  # passive cannot read any run history

        row = _run_single(runner)

        assert row.status == Status.SKIPPED.value
        assert "live Workday connection test was not run" in row.result
        assert "could not be assessed either" in row.result
        assert (
            "assessed from recent Workday connector run history"
            not in row.result
        )

    def test_passive_failed_still_claims_history_assessed(self) -> None:
        row = _run_single(_runner(
            runtime_reachability=False,
            runtime_reachability_declined=True,
            pp_client=_PP(runs=[
                pp.flow_run(run_id="bad", flow_id=_FLOW_ID, status="Failed"),
            ]),
        ))

        assert row.status == Status.FAILED.value
        assert "live Workday connection test was not run" in row.result
        assert "assessed from recent Workday connector run history" in row.result

    def test_passive_not_configured_does_not_claim_history_assessed(
        self,
    ) -> None:
        row = _run_single(_runner(
            runtime_reachability=False,
            runtime_reachability_declined=True,
            pp_client=_PP(runs=[]),
        ))

        assert row.status == Status.NOT_CONFIGURED.value
        assert "No recent Workday flow runs found" in row.result
        assert "live Workday connection test was not run" in row.result
        assert "could not be assessed either" in row.result
        assert (
            "assessed from recent Workday connector run history"
            not in row.result
        )
