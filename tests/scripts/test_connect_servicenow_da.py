# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import json

from pathlib import Path

import pytest

import connect_servicenow_da as snow


ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
AGENT_ID = "00000000-0000-4000-8000-000000002222"
CONNECTION_ID = "00000000-0000-4000-8000-000000003333"


def _components(connection_id: str | None = None) -> dict:
    return {
        "changeToken": "token",
        "botComponentChanges": [
            {
                "$kind": "BotComponentInsert",
                "component": {
                    "$kind": "DialogComponent",
                    "id": "00000000-0000-4000-8000-000000005555",
                    "version": 7,
                    "displayName": "ServiceNow HRSD Common Orchestrator",
                    "schemaName": (
                        f"{snow.HR_SCHEMA_NAME}.topic."
                        "ServiceNowHRSDSystemCommonOrchestrator"
                    ),
                    "state": "Active",
                    "status": "Active",
                    "dialog": {
                        "$kind": "TaskDialog",
                        "action": {
                            "$kind": "InvokeConnectorAction",
                            "connectionReference": "servicenow-ref",
                        },
                    },
                },
            },
            {
                "$kind": "BotComponentInsert",
                "component": {
                    "$kind": "DialogComponent",
                    "schemaName": f"{snow.HR_SCHEMA_NAME}.topic.WorkdayRuntime",
                    "state": "Active",
                    "dialog": {
                        "$kind": "TaskDialog",
                        "action": {
                            "$kind": "InvokeFlowAction",
                            "flowId": "flow-1",
                        },
                    },
                },
            },
        ],
        "connectionReferenceChanges": [
            {
                "$kind": "ConnectionReferenceInsert",
                "connectionReference": {
                    "$kind": "ConnectionReference",
                    "version": 4,
                    "id": "00000000-0000-4000-8000-000000004444",
                    "connectionId": connection_id,
                    "connectorId": snow.CONNECTOR_ID,
                    "connectionReferenceLogicalName": "servicenow-ref",
                    "displayName": "ServiceNow",
                    "sharedConnectionParameters": json.dumps(
                        {
                            "name": "entraIDUserLogin",
                            "values": {
                                "token:ResourceUri": {"value": "resource-id"},
                                "token:InstanceName": {"value": "dev123"},
                            },
                        }
                    ),
                },
            }
        ],
        "connectorDefinitionChanges": [
            {"$kind": "ConnectorDefinitionInsert"}
        ],
    }


def test_summarize_components_separates_servicenow_from_workday_flows() -> None:
    result = snow.summarize_components(_components(CONNECTION_ID))

    assert result["serviceNowTopicCount"] == 1
    assert result["activeServiceNowTopicCount"] == 1
    assert result["serviceNowTopics"][0]["displayName"] == (
        "ServiceNow HRSD Common Orchestrator"
    )
    assert result["serviceNowInvokeConnectorActionCount"] == 1
    assert result["serviceNowInvokeFlowActionCount"] == 0
    assert result["invokeFlowActionCount"] == 1
    assert result["cloudFlowDefinitionCount"] == 0
    assert result["reference"]["instanceName"] == "dev123"
    assert result["reference"]["resourceUri"] == "resource-id"


def test_topic_state_update_replays_full_dialog_component() -> None:
    components = _components()
    topic = components["botComponentChanges"][0]["component"]

    payload = snow.build_topic_state_update_payload(
        components,
        topic["id"],
        "Inactive",
    )

    assert set(payload) == {"changeToken", "botComponentChanges"}
    assert payload["changeToken"] == "token"
    change = payload["botComponentChanges"][0]
    assert change["$kind"] == "BotComponentUpdate"
    updated = change["component"]
    assert updated["id"] == topic["id"]
    assert updated["version"] == 7
    assert updated["schemaName"] == topic["schemaName"]
    assert updated["dialog"] == topic["dialog"]
    assert updated["state"] == "Inactive"
    assert updated["status"] == "Inactive"
    assert topic["state"] == "Active"
    assert topic["status"] == "Active"


def test_topic_state_update_requires_change_token() -> None:
    components = _components()
    del components["changeToken"]
    topic_id = components["botComponentChanges"][0]["component"]["id"]

    with pytest.raises(snow.ServiceNowConnectError, match="change token"):
        snow.build_topic_state_update_payload(
            components,
            topic_id,
            "Inactive",
        )


def test_topic_state_mutation_requires_confirmation() -> None:
    with pytest.raises(snow.ServiceNowConnectError, match="confirmation"):
        snow.set_topic_state(
            {},
            "00000000-0000-4000-8000-000000005555",
            "Inactive",
            confirmed=False,
        )


def test_enable_all_topics_payload_contains_only_inactive_servicenow_topics() -> None:
    components = _components()
    topic = components["botComponentChanges"][0]["component"]
    topic["state"] = "Inactive"
    topic["status"] = "Inactive"

    payload = snow.build_enable_all_topics_payload(components)

    assert payload["changeToken"] == "token"
    assert len(payload["botComponentChanges"]) == 1
    change = payload["botComponentChanges"][0]
    assert change["$kind"] == "BotComponentUpdate"
    assert change["component"]["id"] == topic["id"]
    assert change["component"]["state"] == "Active"
    assert change["component"]["status"] == "Active"


def test_enable_all_topics_refetches_and_verifies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _components()
    topic = components["botComponentChanges"][0]["component"]
    topic["state"] = "Inactive"
    topic["status"] = "Inactive"

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            return json.loads(json.dumps(components))

        def update_components(
            self,
            _agent_id: str,
            payload: dict,
        ) -> dict:
            update = payload["botComponentChanges"][0]["component"]
            components["botComponentChanges"][0]["component"] = update
            components["changeToken"] = "token-2"
            return {}

    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )
    monkeypatch.chdir(tmp_path)

    result = snow.enable_all_servicenow_topics(
        {
            "agent": {
                "id": AGENT_ID,
                "schema_name": snow.HR_SCHEMA_NAME,
            },
            "environment": {
                "id": ENVIRONMENT_ID,
                "ring": "test",
            },
        },
        confirmed=True,
    )

    assert result["customerChoice"] == "enable-all"
    assert result["before"] == {"total": 1, "active": 0, "inactive": 1}
    assert result["after"] == {"total": 1, "active": 1, "inactive": 0}
    assert result["changedTopics"][0]["id"] == topic["id"]
    assert result["published"] is False


def test_enable_all_topics_requires_confirmation() -> None:
    with pytest.raises(snow.ServiceNowConnectError, match="confirmation"):
        snow.enable_all_servicenow_topics({}, confirmed=False)


def test_enable_all_topics_is_noop_when_all_are_active(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _components()

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            return components

        def update_components(self, _agent_id: str, payload: dict) -> dict:
            raise AssertionError(f"Unexpected update: {payload}")

    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )
    monkeypatch.chdir(tmp_path)

    result = snow.enable_all_servicenow_topics(
        {
            "agent": {
                "id": AGENT_ID,
                "schema_name": snow.HR_SCHEMA_NAME,
            },
            "environment": {
                "id": ENVIRONMENT_ID,
                "ring": "test",
            },
        },
        confirmed=True,
    )

    assert result["status"] == "already-active"
    assert result["changedTopics"] == []
    assert result["published"] is False


def test_keep_current_topic_choice_records_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _components()

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            return components

        def update_components(self, _agent_id: str, payload: dict) -> dict:
            raise AssertionError(f"Unexpected update: {payload}")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )

    result = snow.record_keep_current_topic_choice(
        {
            "agent": {
                "id": AGENT_ID,
                "schema_name": snow.HR_SCHEMA_NAME,
            },
            "environment": {
                "id": ENVIRONMENT_ID,
                "ring": "test",
            },
        }
    )

    assert result["customerChoice"] == "keep-current"
    assert result["changedTopics"] == []
    state = json.loads(
        (
            tmp_path
            / ".local"
            / "connect"
            / "servicenow"
            / "agents"
            / AGENT_ID
            / "state.json"
        ).read_text(encoding="utf-8")
    )
    assert state["topicEnablement"]["customerChoice"] == "keep-current"


def test_enable_all_topics_fails_when_refetch_is_still_inactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    components = _components()
    topic = components["botComponentChanges"][0]["component"]
    topic["state"] = "Inactive"
    topic["status"] = "Inactive"

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            return components

        def update_components(self, _agent_id: str, payload: dict) -> dict:
            return {}

    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )

    with pytest.raises(
        snow.ServiceNowConnectError,
        match="remained inactive",
    ):
        snow.enable_all_servicenow_topics(
            {"agent": {"id": AGENT_ID}},
            confirmed=True,
        )


def test_connection_summary_prefers_token_status() -> None:
    result = snow.connection_summary(
        {
            "name": CONNECTION_ID.replace("-", ""),
            "properties": {
                "displayName": "ServiceNow",
                "statuses": [
                    {"target": "connector", "status": "Ready"},
                    {"target": "token", "status": "Connected"},
                ],
                "connectionParametersSet": {
                    "name": "entraIDUserLogin",
                    "values": {
                        "token:InstanceName": {"value": "dev123"},
                        "token:ResourceUri": {"value": "resource-id"},
                        "password": {"value": "must-not-be-returned"},
                    },
                },
            },
        }
    )

    assert result["status"] == "Connected"
    assert result["statusTarget"] == "token"
    assert result["parameterValues"]["token:InstanceName"] == "dev123"
    assert result["parameterValues"]["token:ResourceUri"] == "resource-id"
    assert "password" not in result["parameterValues"]


def test_load_context_requires_matching_schema_v4_hr_agent(
    tmp_path: Path,
) -> None:
    setup_path = tmp_path / snow.SETUP_STATE
    config_path = tmp_path / snow.ACTIVE_CONFIG
    snapshot = Path(
        "workspace/agents/employee-self-service-hr/"
        ".agentbuilder/components.json"
    )
    setup_path.parent.mkdir(parents=True)
    setup_path.write_text(
        json.dumps(
            {
                "schema_version": 4,
                "intent": "DA foundation setup",
                "environment": {
                    "id": ENVIRONMENT_ID,
                    "tenant_id": "00000000-0000-4000-8000-000000009999",
                    "ring": "test",
                    "api_version": "2024-10-01",
                    "power_platform_api_endpoint": (
                        "https://example.environment.api.test.powerplatform.com"
                    ),
                },
                "agents": {
                    AGENT_ID: {
                        "authoring_ready": True,
                        "connect_ready": False,
                        "agent": {
                            "id": AGENT_ID,
                            "schema_name": snow.HR_SCHEMA_NAME,
                            "realm": "dev",
                            "workspace_slug": "employee-self-service-hr",
                        },
                        "workspace": {
                            "folder": "workspace/agents/employee-self-service-hr",
                            "agent_path": "agent.mcs.yml",
                        },
                        "steps": {
                            "SETUP-01": {"state": "done"},
                            "SETUP-02.1": {"state": "done"},
                            "SETUP-02.2": {"state": "blocked"},
                            "SETUP-03": {"state": "done"},
                            "SETUP-04": {"state": "done"},
                            "SETUP-05": {"state": "blocked"},
                            "SETUP-06": {"state": "done"},
                            "SETUP-07": {"state": "done"},
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    config_path.write_text(
        json.dumps(
            {
                "activeAgent": "employee-self-service-hr",
                "agents": [
                    {
                        "slug": "employee-self-service-hr",
                        "botId": AGENT_ID,
                        "agentBuilderChangeSetPath": snapshot.as_posix(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = snow.load_context(tmp_path)

    assert result["agent"]["id"] == AGENT_ID
    assert result["snapshotPath"] == tmp_path / snapshot


def test_load_context_rejects_incomplete_foundation_step(
    tmp_path: Path,
) -> None:
    test_load_context_requires_matching_schema_v4_hr_agent(tmp_path)
    setup_path = tmp_path / snow.SETUP_STATE
    setup = json.loads(setup_path.read_text(encoding="utf-8"))
    setup["agents"][AGENT_ID]["steps"]["SETUP-03"]["state"] = "blocked"
    setup["agents"][AGENT_ID]["authoring_ready"] = False
    setup_path.write_text(json.dumps(setup), encoding="utf-8")

    with pytest.raises(
        snow.ServiceNowConnectError,
        match="not ready for authoring",
    ):
        snow.load_context(tmp_path)


def test_record_agent_connection_validates_health_and_persists_attestation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = (
        tmp_path
        / ".local"
        / "connect"
        / "servicenow"
        / "agents"
        / AGENT_ID
        / "state.json"
    )
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "agentId": AGENT_ID,
                "environmentId": ENVIRONMENT_ID,
            }
        ),
        encoding="utf-8",
    )

    class FakeConnectivity:
        def get_connection(self, connection_id: str) -> dict:
            assert connection_id == CONNECTION_ID
            return {
                "name": CONNECTION_ID.replace("-", ""),
                "properties": {
                    "displayName": "ServiceNow",
                    "statuses": [{"target": "token", "status": "Connected"}],
                    "connectionParametersSet": {
                        "name": "entraIDUserLogin",
                    },
                },
            }

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow,
        "_connectivity_client",
        lambda _context: FakeConnectivity(),
    )

    result = snow.record_agent_connection_attestation(
        {
            "agent": {"id": AGENT_ID},
            "environment": {"id": ENVIRONMENT_ID},
        },
        CONNECTION_ID,
    )

    assert result["connectionId"] == CONNECTION_ID.replace("-", "")
    assert result["physicalStatus"] == "Connected"
    assert result["makerAttested"] is True
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["steps"]["agentConnection"] == "done"


def test_inspect_preserves_progress_and_reports_completed_steps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = (
        tmp_path
        / ".local"
        / "connect"
        / "servicenow"
        / "agents"
        / AGENT_ID
        / "state.json"
    )
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "agentId": AGENT_ID,
                "environmentId": ENVIRONMENT_ID,
                "agentConnection": {
                    "connectionId": CONNECTION_ID.replace("-", ""),
                    "makerAttested": True,
                },
                "parameterSharing": {"status": "not-exposed"},
                "publish": {"completedAt": "2026-09-24T00:00:00Z"},
                "test": {"result": "pass"},
                "steps": {
                    "topics": "done",
                    "agentConnection": "done",
                    "parameterSharing": "done",
                    "publish": "done",
                    "test": "done",
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            return _components(CONNECTION_ID)

    class FakeConnectivity:
        def get_connector(self) -> dict:
            return {
                "properties": {
                    "displayName": "ServiceNow",
                    "tier": "Premium",
                    "isCustomApi": False,
                }
            }

        def list_connections(self) -> list[dict]:
            return [
                {
                    "name": CONNECTION_ID.replace("-", ""),
                    "properties": {
                        "displayName": "maker@example.com",
                        "statuses": [
                            {"target": "token", "status": "Connected"}
                        ],
                        "connectionParametersSet": {
                            "name": "entraIDUserLogin",
                        },
                    },
                }
            ]

    context = {
        "agent": {
            "id": AGENT_ID,
            "schema_name": snow.HR_SCHEMA_NAME,
        },
        "environment": {
            "id": ENVIRONMENT_ID,
            "ring": "test",
        },
    }
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )
    monkeypatch.setattr(
        snow,
        "_connectivity_client",
        lambda _context: FakeConnectivity(),
    )

    result = snow.inspect(context)

    assert result["progress"]["topics"]["status"] == "done"
    assert result["progress"]["credential"]["status"] == "done"
    assert result["progress"]["publish"]["status"] == "done"
    assert (
        result["progress"]["agentConnection"]["status"]
        == "confirmation-required"
    )
    assert (
        result["progress"]["parameterSharing"]["status"]
        == "confirmation-required"
    )
    assert result["progress"]["test"]["status"] == "confirmation-required"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["agentConnection"]["makerAttested"] is True
    assert state["parameterSharing"]["status"] == "not-exposed"
    assert state["test"]["result"] == "pass"


def test_record_parameter_sharing_persists_maker_observation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = (
        tmp_path
        / ".local"
        / "connect"
        / "servicenow"
        / "agents"
        / AGENT_ID
        / "state.json"
    )
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "agentId": AGENT_ID,
                "environmentId": ENVIRONMENT_ID,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    result = snow.record_parameter_sharing(
        {
            "agent": {"id": AGENT_ID},
            "environment": {"id": ENVIRONMENT_ID},
        },
        "not-exposed",
    )

    assert result["status"] == "not-exposed"
    assert result["makerAttested"] is True
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["steps"]["parameterSharing"] == "done"


def test_connectivity_scopes_are_read_only() -> None:
    scopes = snow.connectivity_scopes("test")

    assert (
        "https://api.test.powerplatform.com/Connectivity.Connections.Read"
        in scopes
    )
    assert not any(scope.endswith(".Write") for scope in scopes)


def test_prepare_manual_connection_returns_exact_maker_guidance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            return _components()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )
    monkeypatch.setattr(
        snow,
        "_connectivity_client",
        lambda *_args, **_kwargs: pytest.fail(
            "manual preparation must not call Connectivity APIs"
        ),
    )

    result = snow.prepare_manual_connection(
        {
            "agent": {
                "id": AGENT_ID,
                "schema_name": snow.HR_SCHEMA_NAME,
            },
            "environment": {
                "id": ENVIRONMENT_ID,
                "ring": "test",
            },
        },
        instance_name=None,
        resource_uri=None,
        display_name=None,
    )

    assert result["creationMode"] == "manual"
    assert result["connection"]["instanceName"] == "dev123"
    assert result["connection"]["resourceUri"] == "resource-id"
    assert any(
        "Connection settings" in instruction
        for instruction in result["instructions"]
    )


def test_prepare_manual_connection_requests_missing_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _components()
    reference = components["connectionReferenceChanges"][0][
        "connectionReference"
    ]
    reference["connectionId"] = None
    reference["sharedConnectionParameters"] = json.dumps(
        {
            "name": "entraIDUserLogin",
            "values": {
                "token:ResourceUri": {"value": None},
                "token:InstanceName": {"value": None},
            },
        }
    )

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            return components

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )

    result = snow.prepare_manual_connection(
        {
            "agent": {
                "id": AGENT_ID,
                "schema_name": snow.HR_SCHEMA_NAME,
            },
            "environment": {
                "id": ENVIRONMENT_ID,
                "ring": "test",
            },
        },
        instance_name=None,
        resource_uri=None,
        display_name=None,
    )

    assert result["status"] == "input-required"
    assert result["missingFields"] == ["instanceName", "resourceUri"]
    assert not (
        tmp_path
        / ".local"
        / "connect"
        / "servicenow"
        / "agents"
        / AGENT_ID
        / "state.json"
    ).exists()


def test_record_test_attestation_persists_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    context = {
        "agent": {"id": AGENT_ID},
        "environment": {"id": ENVIRONMENT_ID},
    }

    result = snow.record_test_attestation(
        context,
        prompt="Show my HR cases",
        result="pass",
        details="Returned the case list.",
    )

    state = json.loads(
        (
            tmp_path
            / ".local"
            / "connect"
            / "servicenow"
            / "agents"
            / AGENT_ID
            / "state.json"
        ).read_text(encoding="utf-8")
    )
    assert result["result"] == "pass"
    assert state["test"]["prompt"] == "Show my HR cases"
    assert state["steps"]["test"] == "done"
