# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for solutions/ess-maker-skills/scripts/pp_env_client.py.

Pure-logic coverage of the host derivation and the user-connections parsing
helpers. No network, no MSAL.
"""

from __future__ import annotations

import pytest

import pp_env_client as ppe


SN_CONNECTOR = "/providers/Microsoft.PowerApps/apis/shared_service-now"
DV_CONNECTOR = "/providers/Microsoft.PowerApps/apis/shared_commondataserviceforapps"


def test_env_api_host_matches_captured_shape():
    assert (
        ppe.env_api_host("11a02d3a-172c-ef48-8b74-8e2975c2fb05")
        == "11a02d3a172cef488b748e2975c2fb.05.environment.api.powerplatform.com"
    )


def test_env_api_host_rejects_garbage():
    with pytest.raises(ValueError):
        ppe.env_api_host("")


def test_connector_short_name():
    assert ppe.connector_short_name(SN_CONNECTOR) == "shared_service-now"
    assert ppe.connector_short_name(SN_CONNECTOR + "/") == "shared_service-now"
    assert ppe.connector_short_name("") == ""


def _nested(flow_id, connectors):
    return {"flowBindings": {flow_id: {"connectors": connectors}}}


def test_iter_flow_connectors_nested_shape():
    data = _nested("f1", [{"connectorId": SN_CONNECTOR, "connectionId": "c1"}])
    pairs = list(ppe.iter_flow_connectors(data))
    assert pairs == [("f1", {"connectorId": SN_CONNECTOR, "connectionId": "c1"})]


def test_iter_flow_connectors_direct_array_shape():
    data = {"flowBindings": {"f1": [{"connectorId": SN_CONNECTOR}]}}
    assert list(ppe.iter_flow_connectors(data)) == [("f1", {"connectorId": SN_CONNECTOR})]


def test_iter_flow_connectors_tolerates_empty():
    assert list(ppe.iter_flow_connectors({})) == []
    assert list(ppe.iter_flow_connectors({"flowBindings": None})) == []


def test_find_connector_flows_filters_by_name():
    data = {
        "flowBindings": {
            "f1": {"connectors": [
                {"connectorId": SN_CONNECTOR, "connectionId": "c1"},
                {"connectorId": DV_CONNECTOR, "connectionId": "d1"},
            ]},
            "f2": {"connectors": [{"connectorId": DV_CONNECTOR}]},
        }
    }
    got = ppe.find_connector_flows(data, "shared_service-now")
    assert [fid for fid, _ in got] == ["f1"]


def test_connector_is_connected():
    assert ppe.connector_is_connected({"connectionId": "c1", "status": "Connected"})
    assert ppe.connector_is_connected({"connectionId": "c1", "status": "connected"})
    assert not ppe.connector_is_connected({"connectionId": None, "status": "Connected"})
    assert not ppe.connector_is_connected({"connectionId": "c1", "status": "NotConnected"})
    assert not ppe.connector_is_connected({"connectionId": "c1"})


# ── application-package helpers ──────────────────────────────────────────
def test_operation_id_from_header_parses_url():
    hdr = (
        "https://api.powerplatform.com/appmanagement/environments/env/"
        "operations/18a6d34e-15cb-446a-b4b7-20e55ca5b5bf?api-version=1"
    )
    assert ppe._operation_id_from_header(hdr) == "18a6d34e-15cb-446a-b4b7-20e55ca5b5bf"


def test_operation_id_from_header_tolerates_missing():
    assert ppe._operation_id_from_header(None) is None
    assert ppe._operation_id_from_header("https://x/y/z") is None


def test_find_application_package_case_insensitive():
    pkgs = [
        {"uniqueName": "msdyn_EssHRServiceNowHRSD", "state": "None"},
        {"uniqueName": "msdyn_CopilotForEmployeeSelfServiceHR", "state": "Installed"},
    ]
    assert ppe.find_application_package(pkgs, "msdyn_esshrservicenowhrsd")["state"] == "None"
    assert ppe.find_application_package(pkgs, "missing") is None
    assert ppe.find_application_package([], "x") is None


def test_package_is_installed():
    assert ppe.package_is_installed({"state": "Installed"})
    assert ppe.package_is_installed({"state": "installed"})
    assert not ppe.package_is_installed({"state": "None"})
    assert not ppe.package_is_installed({"state": "InstallFailed"})
    assert not ppe.package_is_installed(None)


def test_operation_terminal_and_succeeded():
    for s in ("Succeeded", "Failed", "Canceled", "succeeded"):
        assert ppe.operation_is_terminal(s)
    for s in ("NotStarted", "Running", None, ""):
        assert not ppe.operation_is_terminal(s)
    assert ppe.operation_succeeded("Succeeded")
    assert ppe.operation_succeeded("succeeded")
    assert not ppe.operation_succeeded("Failed")


def test_install_application_package_reads_operation_id_from_body():
    class _Resp:
        status_code = 202
        headers: dict = {}

        def raise_for_status(self):
            pass

        def json(self):
            return {"lastOperation": {"operationId": "op-from-body"}}

    client = ppe.PPEnvClient("tenant", "11a02d3a-172c-ef48-8b74-8e2975c2fb05")
    client._token = "t"  # skip auth
    import pp_env_client as mod

    captured = {}

    def _fake_post(url, **kwargs):
        captured["url"] = url
        return _Resp()

    original = mod.requests.post
    mod.requests.post = _fake_post
    try:
        out = client.install_application_package("msdyn_EssHRServiceNowHRSD")
    finally:
        mod.requests.post = original

    assert out["operation_id"] == "op-from-body"
    assert out["status_code"] == 202
    assert "api.powerplatform.com/appmanagement/environments/" in captured["url"]
    assert "/applicationPackages/msdyn_EssHRServiceNowHRSD/install" in captured["url"]


def test_install_application_package_falls_back_to_header():
    op_url = (
        "https://api.powerplatform.com/appmanagement/environments/env/"
        "operations/op-from-header?api-version=1"
    )

    class _Resp:
        status_code = 202
        headers = {"Operation-Location": op_url}

        def raise_for_status(self):
            pass

        def json(self):
            return {}

    client = ppe.PPEnvClient("tenant", "11a02d3a-172c-ef48-8b74-8e2975c2fb05")
    client._token = "t"
    import pp_env_client as mod

    original = mod.requests.post
    mod.requests.post = lambda url, **kwargs: _Resp()
    try:
        out = client.install_application_package("pkg")
    finally:
        mod.requests.post = original

    assert out["operation_id"] == "op-from-header"
