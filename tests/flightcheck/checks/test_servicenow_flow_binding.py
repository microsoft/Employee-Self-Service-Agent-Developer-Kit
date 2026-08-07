# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the ServiceNow flow invoker-connection FlightCheck (SN-FLOWCONN-001).

Pure-logic / fake-client tests — no network, no MSAL. A fake PPEnvClient feeds
canned user-connections payloads so each verdict branch (PASSED, FAILED,
NOT_CONFIGURED, SKIPPED, never-raise WARNING) is exercised deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from flightcheck.checks import servicenow_flow_binding as sfb
from flightcheck.runner import Status


SN_CONNECTOR = "/providers/Microsoft.PowerApps/apis/shared_service-now"
SCHEMA = "msdyn_copilotforemployeeselfservicehr"
FLOW_ID = "a1f4c28d-6b7c-49b9-a32e-55d8f19c7a03"
CONFIG = {"agents": [{"slug": "ess", "schemaName": SCHEMA}], "activeAgent": "ess"}


@dataclass
class _Runner:
    config: Any = field(default_factory=lambda: CONFIG)
    env_id: str = "env-guid"
    tenant_id: str = "tenant"
    env_url: str = "https://org.crm.dynamics.com"


class _FakeClient:
    def __init__(self, *, token="tok", user_connections=None, raises=False):
        self._token = token
        self._uc = user_connections or {}
        self._raises = raises

    def authenticate(self, interactive=True):
        return self._token

    def get_user_connections(self, schema):
        if self._raises:
            raise RuntimeError("boom")
        return self._uc


def _uc(connection_id, status):
    return {
        "flowBindings": {
            FLOW_ID: {
                "connectors": [
                    {
                        "connectorId": SN_CONNECTOR,
                        "connectionId": connection_id,
                        "status": status,
                    }
                ]
            }
        }
    }


def _install(monkeypatch, client):
    monkeypatch.setattr(sfb, "PPEnvClient", lambda tenant, env_id: client)


def _only(results):
    assert len(results) == 1
    return results[0]


def test_passed_when_connected(monkeypatch):
    _install(monkeypatch, _FakeClient(user_connections=_uc("conn-1", "Connected")))
    r = _only(sfb.run_servicenow_flow_binding_checks(_Runner()))
    assert r.checkpoint_id == "SN-FLOWCONN-001"
    assert r.status == Status.PASSED.value
    assert r.roles  # roles= required


def test_failed_when_not_connected(monkeypatch):
    _install(monkeypatch, _FakeClient(user_connections=_uc(None, "NotConnected")))
    r = _only(sfb.run_servicenow_flow_binding_checks(_Runner()))
    assert r.status == Status.FAILED.value
    assert "Copilot Studio" in r.remediation
    assert FLOW_ID in r.result


def test_not_configured_when_no_sn_connector(monkeypatch):
    empty = {"flowBindings": {FLOW_ID: {"connectors": []}}}
    _install(monkeypatch, _FakeClient(user_connections=empty))
    r = _only(sfb.run_servicenow_flow_binding_checks(_Runner()))
    assert r.status == Status.NOT_CONFIGURED.value


def test_skipped_when_no_token(monkeypatch):
    _install(monkeypatch, _FakeClient(token=None))
    r = _only(sfb.run_servicenow_flow_binding_checks(_Runner()))
    assert r.status == Status.SKIPPED.value
    assert "Power Platform" in r.remediation


def test_skipped_when_no_env_id(monkeypatch):
    _install(monkeypatch, _FakeClient(user_connections=_uc("c", "Connected")))
    r = _only(sfb.run_servicenow_flow_binding_checks(_Runner(env_id=None)))
    assert r.status == Status.SKIPPED.value


def test_skipped_when_no_schema(monkeypatch):
    _install(monkeypatch, _FakeClient(user_connections=_uc("c", "Connected")))
    r = _only(sfb.run_servicenow_flow_binding_checks(_Runner(config={})))
    assert r.status == Status.SKIPPED.value


def test_never_raises_degrades_to_warning(monkeypatch):
    _install(monkeypatch, _FakeClient(raises=True))
    r = _only(sfb.run_servicenow_flow_binding_checks(_Runner()))
    assert r.status == Status.WARNING.value
    assert r.roles


def test_all_results_carry_roles(monkeypatch):
    _install(monkeypatch, _FakeClient(user_connections=_uc("conn-1", "Connected")))
    for runner in (_Runner(), _Runner(env_id=None), _Runner(config={})):
        for r in sfb.run_servicenow_flow_binding_checks(runner):
            assert r.roles, f"{r.checkpoint_id} missing roles"
