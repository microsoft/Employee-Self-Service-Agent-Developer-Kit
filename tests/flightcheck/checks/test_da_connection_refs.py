# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Contract tests for the canonical Declarative Agent connection-reference
reader (``checks/_da_connection_refs.py``), the single shared module that
``DV-CONN-001`` (active agent), ``ENV-004`` (environment-wide, de-duped) and the
Workday shared-parameter checks all read through.

These are pure-logic tests: a duck-typed fake AgentBuilder client returns
minimalBots components payloads built from
``tests.mocks.agentbuilder_connectivity`` (``MOCK_STATUS == "validated"``), so
no network replay or cassette is needed (same inline-fake approach as
``test_agent_handoff.py``). Every component shape traces to the validated
``components()`` builder or its documented ``sharedConnectionParameters``
variant; none is invented here.
"""

from __future__ import annotations

from typing import Any

import pytest

from flightcheck.checks import _da_connection_refs as reader
from tests.mocks import agentbuilder_connectivity as ab


class _FakeClient:
    """AgentBuilder stand-in: ``fetch_components(bot_id)`` returns the payload
    registered for that bot id (empty ``{}`` when none is registered)."""

    def __init__(self, payload_by_bot: dict[str, dict[str, Any]]):
        self._payload_by_bot = payload_by_bot

    def fetch_components(self, bot_id: str) -> dict[str, Any]:
        return self._payload_by_bot.get(bot_id, {})


class _FakeRunner:
    def __init__(self, client: _FakeClient | None, config: dict[str, Any]):
        self.agentbuilder = client
        self.config = config


# --------------------------------------------------------------------------
# agent_bot_ids
# --------------------------------------------------------------------------

def test_agent_bot_ids_unions_multi_and_single_and_dedups_casefold():
    config = {
        "agents": [{"botId": "Agent-A"}, {"botId": "Agent-B"}, {"botId": "agent-a"}],
        "agent": {"botId": "Agent-B"},
    }
    # agent-a folds onto Agent-A (dup); single Agent-B folds onto Agent-B (dup).
    assert reader.agent_bot_ids(config) == ["Agent-A", "Agent-B"]


def test_agent_bot_ids_single_only():
    assert reader.agent_bot_ids({"agent": {"botId": "SOLO"}}) == ["SOLO"]


def test_agent_bot_ids_ignores_blank_and_non_string():
    config = {"agents": [{"botId": ""}, {"botId": None}, {"botId": "  X  "}]}
    assert reader.agent_bot_ids(config) == ["X"]


def test_active_agent_bot_id_resolves_the_selected_multi_agent_entry():
    config = {
        "activeAgent": "ess-hr",
        "agent": {"slug": "stale-agent", "botId": "STALE-BOT"},
        "agents": [
            {"slug": "ess-it", "botId": "IT-BOT"},
            {"slug": "ess-hr", "botId": "HR-BOT"},
        ],
    }
    assert reader.active_agent_bot_id(config) == "HR-BOT"


# --------------------------------------------------------------------------
# read_active_agent_connection_references (DV-CONN-001 surface)
# --------------------------------------------------------------------------

def test_read_active_none_when_no_client():
    runner = _FakeRunner(None, {"agent": {"botId": "BOT"}})
    assert reader.read_active_agent_connection_references(runner) is None


def test_read_active_none_when_no_active_bot_id():
    # Only multi-agent config; no config["agent"].botId -> active read SKIPs.
    runner = _FakeRunner(_FakeClient({}), {"agents": [{"botId": "BOT"}]})
    assert reader.read_active_agent_connection_references(runner) is None


def test_read_active_uses_active_agent_in_multi_agent_config():
    payload = ab.components_with_references(
        references=[ab.workday_connection_reference(connection_id="wd-conn-1")]
    )
    runner = _FakeRunner(
        _FakeClient({"HR-BOT": payload}),
        {
            "activeAgent": "ess-hr",
            "agents": [
                {"slug": "ess-it", "botId": "IT-BOT"},
                {"slug": "ess-hr", "botId": "HR-BOT"},
            ],
        },
    )

    rows = reader.read_active_agent_connection_references(runner)

    assert len(rows) == 1
    assert rows[0]["botid"] == "HR-BOT"


def test_read_active_normalizes_workday_row():
    payload = ab.components_with_references(
        references=[ab.workday_connection_reference(connection_id="wd-conn-1")]
    )
    runner = _FakeRunner(_FakeClient({"BOT": payload}), {"agent": {"botId": "BOT"}})
    rows = reader.read_active_agent_connection_references(runner)
    assert len(rows) == 1
    row = rows[0]
    assert row["botid"] == "BOT"
    assert row["connectorid"].endswith("/apis/shared_workdaysoap")
    assert row["connectionid"] == "wd-conn-1"


def test_read_active_missing_change_set_is_empty_not_none():
    runner = _FakeRunner(_FakeClient({"BOT": {}}), {"agent": {"botId": "BOT"}})
    assert reader.read_active_agent_connection_references(runner) == []


def test_read_active_malformed_change_set_raises():
    runner = _FakeRunner(
        _FakeClient({"BOT": {"connectionReferenceChanges": "not-a-list"}}),
        {"agent": {"botId": "BOT"}},
    )
    with pytest.raises(ValueError):
        reader.read_active_agent_connection_references(runner)


# --------------------------------------------------------------------------
# read_all_agents_connection_references (ENV-004 surface: env-wide, de-duped)
# --------------------------------------------------------------------------

def test_read_all_none_when_no_client():
    runner = _FakeRunner(None, {"agents": [{"botId": "A"}]})
    assert reader.read_all_agents_connection_references(runner) is None


def test_read_all_dedups_by_logical_name_first_wins():
    ref_a = ab.workday_connection_reference(
        connection_id="c1", logical_name="ns.shared_workdaysoap"
    )
    ref_b = ab.workday_connection_reference(
        connection_id="c2", logical_name="ns.shared_workdaysoap"
    )
    client = _FakeClient(
        {
            "A": ab.components_with_references(references=[ref_a]),
            "B": ab.components_with_references(references=[ref_b]),
        }
    )
    runner = _FakeRunner(client, {"agents": [{"botId": "A"}, {"botId": "B"}]})
    rows = reader.read_all_agents_connection_references(runner)
    assert len(rows) == 1
    assert rows[0]["connectionid"] == "c1"


# --------------------------------------------------------------------------
# shared_connection_parameter_values
# --------------------------------------------------------------------------

def test_scp_values_parsed_from_json_string():
    ref = {
        "sharedconnectionparameters": ab.shared_connection_parameters_json_string(
            rest_base_uri="https://wd.example.com/ccx/api"
        )
    }
    values = reader.shared_connection_parameter_values(ref)
    assert values["restBaseUri"] == "https://wd.example.com/ccx/api"


def test_scp_values_parsed_from_nested_object():
    ref = {"sharedconnectionparameters": ab.shared_connection_parameters(tenant_name="mocktenant")}
    values = reader.shared_connection_parameter_values(ref)
    assert values["tenantName"] == "mocktenant"


def test_scp_values_missing_is_empty_map():
    assert reader.shared_connection_parameter_values({}) == {}


def test_scp_values_malformed_json_string_raises():
    ref = {"sharedconnectionparameters": "{not valid json"}
    with pytest.raises(ValueError):
        reader.shared_connection_parameter_values(ref)


# --------------------------------------------------------------------------
# workday_shared_connection_parameters (WD-ENV-001 / WD-REST-001 surface)
# --------------------------------------------------------------------------

def test_wscp_found_with_values():
    ref = ab.workday_connection_reference(
        shared_connection_parameters=ab.shared_connection_parameters_json_string()
    )
    payload = ab.components_with_references(references=[ref])
    runner = _FakeRunner(_FakeClient({"BOT": payload}), {"agent": {"botId": "BOT"}})
    values, message = reader.workday_shared_connection_parameters(runner)
    assert message == ""
    assert values["tenantName"] == "mocktenant"


def test_wscp_found_but_missing_values():
    ref = ab.workday_connection_reference(shared_connection_parameters=None)
    payload = ab.components_with_references(references=[ref])
    runner = _FakeRunner(_FakeClient({"BOT": payload}), {"agent": {"botId": "BOT"}})
    values, message = reader.workday_shared_connection_parameters(runner)
    assert values == {}
    assert "missing" in message.lower()


def test_wscp_workday_reference_not_found():
    # components() carries only the ServiceNow reference, no Workday one.
    runner = _FakeRunner(
        _FakeClient({"BOT": ab.components()}), {"agent": {"botId": "BOT"}}
    )
    values, message = reader.workday_shared_connection_parameters(runner)
    assert values == {}
    assert "not found" in message.lower()


def test_wscp_none_when_client_unavailable():
    runner = _FakeRunner(None, {"agent": {"botId": "BOT"}})
    values, message = reader.workday_shared_connection_parameters(runner)
    assert values is None
    assert message
