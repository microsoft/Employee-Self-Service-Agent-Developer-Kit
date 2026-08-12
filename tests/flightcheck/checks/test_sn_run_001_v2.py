# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""AC12 coverage for SN-RUN-001 v2 active ServiceNow connector probe.

Mirrors tests/flightcheck/checks/test_wd_run_001_v2.py. Only the ServiceNow
connection binding and error-map assertions differ; the transient-flow
lifecycle, consent gating, and orphan sweep are the shared harness exercised
identically for both vendors.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import requests
import responses

from tests.conftest import require_validated_mock
from tests.mocks import power_automate as pa
from tests.mocks import pp_admin as pp

from flightcheck.checks.servicenow import _check_servicenow_active_run_health
from flightcheck.runner import Status

require_validated_mock(pa)
require_validated_mock(pp)

_FLOW_ID = "00000000-0000-0000-0000-000000007201"
_CONNECTION_ID = "00000000-0000-0000-0000-00000000sn01"


class _PP:
    flow_headers = {"Authorization": "******"}

    def __init__(
        self,
        *,
        connections: list[dict[str, Any]] | None = None,
        runs: list[dict[str, Any]] | None = None,
    ) -> None:
        self._connections = connections if connections is not None else [
            _servicenow_connection()
        ]
        # ServiceNow success = status Succeeded AND response.name
        # "Respond_to_Copilot" (the SN orchestrator success branch), which
        # differs from the Workday value the mock defaults to.
        self._runs = runs if runs is not None else [
            pp.flow_run(
                run_id="ok",
                flow_id=_FLOW_ID,
                status="Succeeded",
                response_name="Respond_to_Copilot",
            )
        ]

    def get_connections(self, _env_id: str) -> list[dict[str, Any]]:
        return self._connections

    def get_flow_runs(self, _env_id: str, _flow_id: str) -> list[dict[str, Any]]:
        return self._runs


def _servicenow_connection(
    *,
    connection_name: str = _CONNECTION_ID,
    runtime_source: str | None = "embedded",
    owner_upn: str | None = None,
) -> dict[str, Any]:
    conn = pp.servicenow_connection(
        connection_name=connection_name,
        display_name="ServiceNow ISU",
    )
    if runtime_source is not None:
        conn["properties"].update({"runtimeSource": runtime_source})
    if owner_upn is not None:
        # owner_upn="" models a record that does not expose its owner
        # (createdBy absent), which the selector treats as "owner unknown".
        if owner_upn == "":
            conn["properties"].pop("createdBy", None)
        else:
            conn["properties"]["createdBy"] = {
                "userPrincipalName": owner_upn,
                "email": owner_upn,
                "type": "User",
            }
    return conn


def _runner(
    *,
    runtime_reachability: bool = True,
    runtime_reachability_declined: bool = False,
    pp_client: Any | None = None,
    config: dict[str, Any] | None = None,
    operator_upn: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        pp_admin=pp_client if pp_client is not None else _PP(),
        env_id=pa.MOCK_ENV_ID,
        env_url=pa.MOCK_ENV_URL,
        dv_token="dv-token",
        runtime_reachability=runtime_reachability,
        runtime_reachability_declined=runtime_reachability_declined,
        config=config or {},
        _operator_upn=operator_upn,
        _servicenow_flows=[pp.flow(flow_id=_FLOW_ID, display_name="ESS HR ServiceNow")],
    )


def _register_connector_lifecycle(
    *,
    action_status: str | None = "Succeeded",
    status_code: int | None = 200,
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    responses.add(**pa.find_workflows())
    responses.add(**pa.create_workflow(name=pa.MOCK_SERVICENOW_PROBE_FLOW_NAME))
    responses.add(**pa.activate_workflow())
    responses.add(**pa.list_callback_url())
    responses.add(**pa.invoke_servicenow_connector_probe(
        action_status=action_status,
        status_code=status_code,
        error_code=error_code,
        error_message=error_message,
    ))
    responses.add(**pa.delete_workflow())
    responses.add(**pa.find_workflows())


def _run_single(runner: SimpleNamespace):
    results = _check_servicenow_active_run_health(runner)
    assert len(results) == 1
    return results[0]


@pytest.fixture(autouse=True)
def _clear_probe_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ESS_SN_PROBE_OPERATION_ID", raising=False)
    monkeypatch.delenv("ESS_SN_PROBE_PARAMS_JSON", raising=False)


class TestServiceNowActiveProbeMatrix:
    @responses.activate
    def test_healthy_pass_uses_connector_bound_managed_path(self) -> None:
        _register_connector_lifecycle()

        row = _run_single(_runner())

        assert row.status == Status.PASSED.value
        assert "retrieved data from ServiceNow" in row.result
        assert "ServiceNow service-account connection" in row.result
        assert "did not test custom scripted REST APIs" in row.result
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
        # Defensive 404 branch. The live ServiceNow endpoint-not-found shape is
        # a documented assumption pending the AC13 live capture, not yet a
        # live-verified error code.
        _register_connector_lifecycle(
            action_status="Failed",
            status_code=404,
            error_code="EndpointNotFound",
        )

        row = _run_single(_runner())

        assert row.status == Status.FAILED.value
        assert "table, or operation was not found" in row.result
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
        assert "role/ACL" in row.result
        assert "HTTP 403" in row.result

    @responses.activate
    def test_servicenow_business_error_names_indeterminate_layer(self) -> None:
        # HTTP 400 / BadRequest cannot distinguish a wrong endpoint / table /
        # operation from a ServiceNow business or validation fault; they share
        # one honest indeterminate bucket (mirrors the WD live-verified 400).
        _register_connector_lifecycle(
            action_status="Failed",
            status_code=400,
            error_code="BadRequest",
        )

        row = _run_single(_runner())

        assert row.status == Status.FAILED.value
        assert "cannot distinguish a wrong endpoint" in row.result
        assert "HTTP 400" in row.result

    @responses.activate
    def test_rate_limit_names_servicenow_throttle_layer(self) -> None:
        _register_connector_lifecycle(
            action_status="Failed",
            status_code=429,
            error_code="TooManyRequests",
        )

        row = _run_single(_runner())

        assert row.status == Status.FAILED.value
        assert "throttled" in row.result
        assert "HTTP 429" in row.result

    @responses.activate
    def test_server_error_names_connector_runtime_backend_layer(self) -> None:
        _register_connector_lifecycle(
            action_status="Failed",
            status_code=500,
            error_code="InternalServerError",
        )

        row = _run_single(_runner())

        assert row.status == Status.FAILED.value
        assert "server error" in row.result
        assert "HTTP 500" in row.result

    def test_consent_declined_falls_back_to_passive_run_history(self) -> None:
        row = _run_single(_runner(
            runtime_reachability=False,
            runtime_reachability_declined=True,
        ))

        assert row.status == Status.PASSED.value
        assert "All 1 most recent ServiceNow flow run(s) succeeded" in row.result
        assert "live ServiceNow connection test was not run" in row.result
        assert "recent ServiceNow connector run history" in row.result

    def test_no_connection_is_not_configured_not_failed(self) -> None:
        row = _run_single(_runner(pp_client=_PP(connections=[])))

        assert row.status == Status.NOT_CONFIGURED.value
        assert "no ServiceNow managed-connector connection was found" in row.result
        assert "live ServiceNow connection test did not run" in row.result

    @responses.activate
    def test_cleanup_on_invoke_error_deletes_created_flow(self) -> None:
        responses.add(**pa.find_workflows())
        responses.add(**pa.create_workflow(name=pa.MOCK_SERVICENOW_PROBE_FLOW_NAME))
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
                _servicenow_connection(runtime_source="invoker"),
            ]),
        ))

        assert row.status == Status.PASSED.value
        assert "OAuth-invoker ServiceNow connections" in row.result
        assert "recent ServiceNow connector run history" in row.result


class TestServiceNowProbeConfig:
    """Lock the AC13 live-verified read-only default (PROD, 2026-08-11):
    GetRecords with {tableType: sys_user, sysparm_limit: 1} returned HTTP 200
    from a real ServiceNow instance through the managed connector."""

    def test_default_operation_and_params_are_the_live_verified_read(self) -> None:
        from flightcheck.checks.servicenow import (
            _SN_DEFAULT_READ_OPERATION,
            _servicenow_probe_config,
        )

        operation_id, params, error = _servicenow_probe_config(_runner())

        assert error is None
        assert operation_id == _SN_DEFAULT_READ_OPERATION == "GetRecords"
        assert params == {"tableType": "sys_user", "sysparm_limit": "1"}


class TestServiceNowProbeConnectionOwnership:
    """AC3/AC9 ownership selection through the shared
    select_operator_owned_connection helper. A transient probe flow only
    activates with a connection the /flightcheck operator owns (confirmed live,
    PROD 2026-08-11: a non-owned connection returns ConnectionAuthorizationFailed
    at activate). These lock the three ownership outcomes."""

    _OPERATOR = "operator@essagentic.onmicrosoft.com"
    _OTHER = "someone.else@essagentic.onmicrosoft.com"

    @responses.activate
    def test_operator_owned_connection_runs_active_probe(self) -> None:
        _register_connector_lifecycle()

        row = _run_single(_runner(
            operator_upn=self._OPERATOR,
            pp_client=_PP(connections=[
                _servicenow_connection(owner_upn=self._OTHER),
                _servicenow_connection(owner_upn=self._OPERATOR),
            ]),
        ))

        assert row.status == Status.PASSED.value
        assert "retrieved data from ServiceNow" in row.result

    def test_all_connections_owned_by_others_fall_back_to_passive(self) -> None:
        # No @responses.activate: the active probe must NOT be attempted when
        # the operator owns none of the connections. It falls back to the
        # passive run-history read, and must NOT report NOT_CONFIGURED.
        row = _run_single(_runner(
            operator_upn=self._OPERATOR,
            pp_client=_PP(connections=[
                _servicenow_connection(owner_upn=self._OTHER),
            ]),
        ))

        assert row.status == Status.PASSED.value
        assert row.status != Status.NOT_CONFIGURED.value
        assert "does not own" in row.result
        assert "recent ServiceNow connector run history" in row.result

    @responses.activate
    def test_unknown_owner_connection_is_tried_not_blocked(self) -> None:
        # Owner not exposed on the record: try rather than block (no regression
        # on tenants that hide createdBy). The active probe still runs.
        _register_connector_lifecycle()

        row = _run_single(_runner(
            operator_upn=self._OPERATOR,
            pp_client=_PP(connections=[
                _servicenow_connection(owner_upn=""),
            ]),
        ))

        assert row.status == Status.PASSED.value
        assert "retrieved data from ServiceNow" in row.result

    def test_env_override_operation_and_params_win(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from flightcheck.checks.servicenow import _servicenow_probe_config

        monkeypatch.setenv("ESS_SN_PROBE_OPERATION_ID", "ListRecords")
        monkeypatch.setenv(
            "ESS_SN_PROBE_PARAMS_JSON", '{"tableType": "incident"}'
        )

        operation_id, params, error = _servicenow_probe_config(_runner())

        assert error is None
        assert operation_id == "ListRecords"
        assert params == {"tableType": "incident"}

    def test_mutating_operation_override_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from flightcheck.checks.servicenow import _servicenow_probe_config

        monkeypatch.setenv("ESS_SN_PROBE_OPERATION_ID", "CreateRecord")

        operation_id, _params, error = _servicenow_probe_config(_runner())

        assert operation_id is None
        assert error is not None
        assert "read-only" in error
