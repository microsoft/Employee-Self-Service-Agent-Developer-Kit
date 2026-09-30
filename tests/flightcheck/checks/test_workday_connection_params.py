# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for selected-agent Workday flow-to-connection resolution."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from flightcheck.checks import _workday_connection_params as mod
from flightcheck.checks._agent_connection_refs import ActiveConnectionBinding
from tests.conftest import require_validated_mock
from tests.mocks import pp_admin as pp

require_validated_mock(pp)


_REQUIRED_VALUES = {
    "tenantName": "mocktenant",
    "token:ResourceUri": "https://wd.example.com",
    "token:WorkdayTokenUri": (
        "https://wd.example.com/ccx/oauth2/mocktenant/token"
    ),
    "token:WorkdayClientId": "mock-client-id",
    "baseUri": "https://wd.example.com/ccx/service",
    "restBaseUri": "https://wd.example.com/ccx/api/mocktenant",
}


class _FakePP:
    def __init__(self, connections):
        self.connections = connections
        self.calls: list[str] = []

    def get_connections(self, env_id):
        self.calls.append(env_id)
        return self.connections


def _runner(connections):
    return SimpleNamespace(
        env_id=pp.MOCK_ENV_ID,
        pp_admin=_FakePP(connections),
    )


def _binding(
    *,
    connector="shared_workdaysoap",
    connection_name="workday-oauth-1",
    logical_name="new_sharedworkdaysoap_ff0df",
):
    return ActiveConnectionBinding(
        logical_name=logical_name,
        connector=connector,
        connection_name=connection_name,
    )


def test_resolver_joins_flow_binding_to_oauth_connection(monkeypatch):
    monkeypatch.setattr(
        mod,
        "build_active_agent_connection_bindings",
        lambda runner: (_binding(),),
    )
    runner = _runner([
        pp.workday_connection(
            connection_name="workday-oauth-1",
            display_name="Workday OAuth",
            parameter_set_name="oauth",
            parameter_values=_REQUIRED_VALUES,
        )
    ])

    result = mod.resolve_active_workday_oauth_connections(runner)

    assert result is not None
    assert result.has_workday_binding is True
    assert len(result.connections) == 1
    assert result.connections[0].display_name == "Workday OAuth"
    assert result.connections[0].values == _REQUIRED_VALUES
    assert result.unresolved_bindings == ()
    assert runner.pp_admin.calls == [pp.MOCK_ENV_ID]


def test_resolver_ignores_non_workday_flow_bindings(monkeypatch):
    monkeypatch.setattr(
        mod,
        "build_active_agent_connection_bindings",
        lambda runner: (_binding(connector="shared_office365"),),
    )
    runner = _runner([])

    result = mod.resolve_active_workday_oauth_connections(runner)

    assert result is not None
    assert result.has_workday_binding is False
    assert result.connections == ()
    assert runner.pp_admin.calls == []


def test_resolver_tracks_missing_physical_connection(monkeypatch):
    monkeypatch.setattr(
        mod,
        "build_active_agent_connection_bindings",
        lambda runner: (_binding(connection_name="missing-connection"),),
    )
    runner = _runner([])

    result = mod.resolve_active_workday_oauth_connections(runner)

    assert result is not None
    assert result.connections == ()
    assert result.unresolved_bindings == ("missing-connection",)


def test_resolver_ignores_named_non_oauth_parameter_set(monkeypatch):
    monkeypatch.setattr(
        mod,
        "build_active_agent_connection_bindings",
        lambda runner: (_binding(),),
    )
    runner = _runner([
        pp.workday_connection(
            connection_name="workday-oauth-1",
            parameter_set_name="basic",
            parameter_values={"username": "isu"},
        )
    ])

    result = mod.resolve_active_workday_oauth_connections(runner)

    assert result is not None
    assert result.connections == ()
    assert result.ignored_non_oauth_bindings == (
        "workday-oauth-1 (basic)",
    )


def test_resolver_treats_unknown_parameter_set_as_unresolved(monkeypatch):
    monkeypatch.setattr(
        mod,
        "build_active_agent_connection_bindings",
        lambda runner: (_binding(),),
    )
    runner = _runner([
        pp.workday_connection(
            connection_name="workday-oauth-1",
            parameter_values=_REQUIRED_VALUES,
        )
    ])

    result = mod.resolve_active_workday_oauth_connections(runner)

    assert result is not None
    assert result.connections == ()
    assert result.unresolved_bindings == ("workday-oauth-1",)


def test_resolver_rejects_wrong_connector_inventory_record(monkeypatch):
    monkeypatch.setattr(
        mod,
        "build_active_agent_connection_bindings",
        lambda runner: (_binding(),),
    )
    runner = _runner([
        pp.connection(
            name="workday-oauth-1",
            api_name="shared_office365",
            extra_properties={
                "connectionParametersSet": {
                    "name": "oauth",
                    "values": {},
                }
            },
        )
    ])

    result = mod.resolve_active_workday_oauth_connections(runner)

    assert result is not None
    assert result.connections == ()
    assert result.unresolved_bindings == ("workday-oauth-1",)


def test_resolver_deduplicates_same_physical_connection(monkeypatch):
    monkeypatch.setattr(
        mod,
        "build_active_agent_connection_bindings",
        lambda runner: (
            _binding(logical_name="ref-a"),
            _binding(logical_name="ref-b"),
        ),
    )
    runner = _runner([
        pp.workday_connection(
            connection_name="workday-oauth-1",
            parameter_set_name="oauth",
            parameter_values=_REQUIRED_VALUES,
        )
    ])

    first = mod.resolve_active_workday_oauth_connections(runner)
    second = mod.resolve_active_workday_oauth_connections(runner)

    assert first is second
    assert first is not None
    assert len(first.connections) == 1
    assert runner.pp_admin.calls == [pp.MOCK_ENV_ID]


def test_resolver_surfaces_connection_inventory_error(monkeypatch):
    monkeypatch.setattr(
        mod,
        "build_active_agent_connection_bindings",
        lambda runner: (_binding(),),
    )
    runner = _runner({"_error": "403 Forbidden", "_status": 403})

    with pytest.raises(RuntimeError, match="403 Forbidden"):
        mod.resolve_active_workday_oauth_connections(runner)
