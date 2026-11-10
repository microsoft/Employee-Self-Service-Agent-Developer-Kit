# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read-only adapter contracts; synthetic state pairs are not live evidence."""

from copy import deepcopy
import json
from unittest.mock import Mock

import pytest
import requests
import responses

from agentbuilder import AgentBuilderClient, AgentBuilderError
from tests.conftest import require_validated_mock
from tests.mocks import agentbuilder_connectivity as native
from topic_actions_components import ComponentReadError, normalize_state, read_component_states


AGENT_ID = native.MOCK_AGENT_ID
COMPONENT_ID = "00000000-0000-0000-0000-00000000aaaa"
OTHER_ID = "00000000-0000-0000-0000-00000000bbbb"


@pytest.mark.parametrize(("state", "status", "expected"), [
    ("Active", "Active", ("On", "verified_pair")),
    ("Inactive", "Inactive", ("Off", "verified_pair")),
    ("Active", "Inactive", ("Unknown", "contradictory_state")),
    ("Inactive", "Active", ("Unknown", "contradictory_state")),
    (None, None, ("Unknown", "missing_state_and_status")),
    (None, "Active", ("Unknown", "missing_state")),
    ("Inactive", None, ("Unknown", "missing_status")),
    ("mc", "Active", ("Unknown", "unknown_state")),
    ("Active", "future-value", ("Unknown", "unknown_status")),
    ([], "Active", ("Unknown", "unknown_state")),
    ("Active", True, ("Unknown", "unknown_status")),
    ("active", "Active", ("Unknown", "unknown_state")),
])
def test_state_pairs_are_conservative(state, status, expected):
    assert normalize_state(state, status) == expected


@pytest.fixture
def snapshot():
    return {
        "bot": {"cdsBotId": AGENT_ID},
        "changeToken": "private-change-token",
        "botComponentChanges": [{
            "$kind": "BotComponentInsert",
            "component": {
                "$kind": "DialogComponent", "id": COMPONENT_ID,
                "schemaName": "synthetic.topic.DoNotInferMembership",
                "parentBotId": AGENT_ID,
                "state": "Active", "status": "Active",
                "dialog": {"private-content": "must-not-emit"},
            },
        }],
    }


@responses.activate
def test_native_read_uses_post_empty_body_and_keeps_captured_unknown_state_private(capsys):
    require_validated_mock(native)
    # Captured native record shape/state, not an invented live On/Off response.
    change = native.dialog_component_change(schema_name="synthetic.topic.Example")
    payload = {"botComponentChanges": [change], "changeToken": "private-change-token"}
    response = native.get_components(payload=payload)
    responses.add(**response)
    client = AgentBuilderClient(
        native.MOCK_AGENTBUILDER_BASE, "private-auth-token", ring="test",
        tenant_id=native.MOCK_ENV_ID,
    )
    try:
        adapter = client.session.get_adapter("https://")
        retries = adapter.max_retries
        result = read_component_states(client, AGENT_ID, [change["component"]["id"]])
        assert client.session.get_adapter("https://") is adapter
        assert adapter.max_retries is retries
    finally:
        client.session.close()
    assert len(responses.calls) == 1
    request = responses.calls[0].request
    assert request.method == "POST"
    assert f"/minimalBots/api/{AGENT_ID}/components?" in request.url
    assert request.url.startswith(native.MOCK_AGENTBUILDER_BASE)
    assert json.loads(request.body) == {}
    assert result.components[0].state == "Unknown"
    assert result.components[0].reason == "unknown_state"
    assert result._change_token == "private-change-token"
    assert result.public_result()["changeTokenAvailable"] is True
    safe = repr(result) + json.dumps(result.public_result()) + capsys.readouterr().out
    assert "private-change-token" not in safe
    assert "private-auth-token" not in safe
    assert "AdaptiveDialog" not in safe


def test_exact_id_lookup_missing_duplicate_and_fresh_reads(snapshot):
    original = deepcopy(snapshot)
    client = Mock(spec=AgentBuilderClient)
    client.fetch_components.return_value = snapshot
    first = read_component_states(client, AGENT_ID, [OTHER_ID, COMPONENT_ID.upper()])
    assert first.public_result()["components"] == [
        {"componentId": OTHER_ID, "state": "Unknown", "reason": "missing_component"},
        {"componentId": COMPONENT_ID, "state": "On", "reason": "verified_pair"},
    ]
    assert snapshot == original
    assert "must-not-emit" not in repr(first) + json.dumps(first.public_result())
    snapshot["botComponentChanges"].append(deepcopy(snapshot["botComponentChanges"][0]))
    second = read_component_states(client, AGENT_ID, [COMPONENT_ID])
    assert second.components[0].reason == "ambiguous_identity"
    assert second.components[0].state == "Unknown"
    assert first.components[1].state == "On"
    assert client.fetch_components.call_args_list == [((AGENT_ID,),), ((AGENT_ID,),)]


def test_schema_name_is_not_a_component_id(snapshot):
    client = Mock(spec=AgentBuilderClient)
    client.fetch_components.return_value = snapshot
    result = read_component_states(
        client, AGENT_ID, ["synthetic.topic.DoNotInferMembership"],
    )
    assert result.components[0].reason == "missing_component"


@pytest.mark.parametrize("body", [
    {}, {"botComponentChanges": None}, {"botComponentChanges": {}},
    {"botComponentChanges": [None]},
    {"botComponentChanges": [{"$kind": "BotComponentDelete", "component": {"id": COMPONENT_ID}}]},
    {"botComponentChanges": [{"$kind": "BotComponentInsert", "component": {}}]},
    {"botComponentChanges": [], "changeToken": []},
    {"botComponentChanges": [], "changeToken": ""},
])
def test_malformed_reads_fail_instead_of_becoming_empty_evidence(body):
    client = Mock(spec=AgentBuilderClient)
    client.fetch_components.return_value = body
    with pytest.raises(ComponentReadError) as error:
        read_component_states(client, AGENT_ID, [COMPONENT_ID])
    assert error.value.reason == "invalid_response"


def test_empty_collection_and_missing_token_are_explicit():
    client = Mock(spec=AgentBuilderClient)
    client.fetch_components.return_value = {"botComponentChanges": []}
    result = read_component_states(client, AGENT_ID, [COMPONENT_ID])
    assert result.components[0].state == "Unknown"
    assert result.components[0].reason == "missing_component"
    assert result.public_result()["changeTokenAvailable"] is False


@pytest.mark.parametrize("location", ["bot", "component"])
def test_foreign_agent_evidence_blocks_the_entire_snapshot(snapshot, location):
    if location == "bot":
        snapshot["bot"]["cdsBotId"] = OTHER_ID
    else:
        snapshot["botComponentChanges"][0]["component"]["parentBotId"] = OTHER_ID
    client = Mock(spec=AgentBuilderClient)
    client.fetch_components.return_value = snapshot
    with pytest.raises(ComponentReadError) as error:
        read_component_states(client, AGENT_ID, [COMPONENT_ID])
    assert error.value.reason == "target_mismatch"


@pytest.mark.parametrize(("agent_id", "ids"), [
    ("not-an-agent-id", [COMPONENT_ID]), (None, [COMPONENT_ID]),
    (AGENT_ID, []), (AGENT_ID, "not-a-list"),
    (AGENT_ID, [COMPONENT_ID, COMPONENT_ID.upper()]),
    (AGENT_ID, [" unsafe "]), (AGENT_ID, ["unsafe\n"]), (AGENT_ID, [None]),
])
def test_invalid_target_or_selection_stops_before_read(agent_id, ids):
    client = Mock(spec=AgentBuilderClient)
    with pytest.raises(ComponentReadError) as error:
        read_component_states(client, agent_id, ids)
    assert error.value.reason == "invalid_request"
    client.fetch_components.assert_not_called()


@responses.activate
@pytest.mark.parametrize(("status", "reason"), [
    (401, "authentication_failed"), (403, "access_denied"),
    (404, "target_not_found"), (429, "read_throttled"), (500, "read_failed"),
])
def test_native_read_failures_are_safe_and_not_retried(status, reason, capsys):
    response = native.get_components(payload={"error": {"message": "private-service-body"}})
    response["status"] = status
    responses.add(**response)
    client = AgentBuilderClient(
        native.MOCK_AGENTBUILDER_BASE, "private-auth-token", ring="test",
        tenant_id=native.MOCK_ENV_ID,
    )
    try:
        with pytest.raises(ComponentReadError) as error:
            read_component_states(client, AGENT_ID, [COMPONENT_ID])
    finally:
        client.session.close()
    assert error.value.reason == reason
    assert error.value.__suppress_context__
    assert "private-service-body" not in str(error.value) + capsys.readouterr().out
    assert len(responses.calls) == 1
    assert responses.calls[0].request.method == "POST"


@pytest.mark.parametrize(("failure", "reason"), [
    (requests.Timeout("private-timeout"), "read_timeout"),
    (requests.ConnectionError("private-network"), "read_failed"),
    (AgentBuilderError("private-response"), "read_failed"),
])
def test_transport_errors_never_return_cached_evidence(failure, reason):
    client = Mock(spec=AgentBuilderClient)
    client.fetch_components.side_effect = failure
    with pytest.raises(ComponentReadError) as error:
        read_component_states(client, AGENT_ID, [COMPONENT_ID])
    assert error.value.reason == reason
    assert "private-" not in str(error.value)
    client.fetch_components.assert_called_once_with(AGENT_ID)
