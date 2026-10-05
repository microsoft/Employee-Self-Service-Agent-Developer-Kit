# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import copy
import json
import subprocess
import sys

from pathlib import Path

import pytest

import connect_servicenow_da as snow


ENVIRONMENT_ID = "00000000-0000-4000-8000-000000001111"
AGENT_ID = "00000000-0000-4000-8000-000000002222"
CONNECTION_ID = "00000000-0000-4000-8000-000000003333"
APP_CLIENT_ID = "00000000-0000-4000-8000-000000006666"
AGENT_SLUG = "employee-self-service-hr"
_CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "solutions"
    / "ess-maker-skills"
    / "src"
    / "skills"
    / "connect"
    / snow.PROVIDER_KEY
    / "contract.json"
)
_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "solutions"
    / "ess-maker-skills"
    / "scripts"
    / "connect_servicenow_da.py"
)


def _context() -> dict:
    return {
        "agent": {
            "id": AGENT_ID,
            "schema_name": snow.HR_SCHEMA_NAME,
            "workspace_slug": AGENT_SLUG,
        },
        "active": {"slug": AGENT_SLUG},
        "environment": {
            "id": ENVIRONMENT_ID,
            "ring": "test",
        },
    }


def _lifecycle_path(root: Path) -> Path:
    return (
        root
        / ".local"
        / "connect"
        / snow.PROVIDER_KEY
        / "agents"
        / AGENT_SLUG
        / "lifecycle.json"
    )


def _phase_contract(phase_id: str) -> dict:
    contract = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
    return next(
        phase for phase in contract["phases"] if phase["id"] == phase_id
    )


def _seed_passing_test(
    root: Path,
    components: dict,
    *,
    publish: dict | None = None,
) -> dict:
    state = snow._state_base(_context(), components)
    normalized_connection_id = CONNECTION_ID.replace("-", "")
    state["evidence"]["credential"] = {
        "connectionId": normalized_connection_id,
    }
    state["evidence"]["agentConnection"] = {
        "kind": "maker-attestation",
        "status": "completed",
        "connectionId": normalized_connection_id,
        "physicalStatus": "Connected",
        "makerAttested": True,
        "recordedAt": "2026-10-01T00:00:00Z",
        "binding": {
            "draftSemanticHash": snow._draft_semantic_hash(components),
        },
    }
    connection_binding_hash = snow._connection_binding_hash(
        _context(),
        state,
        components,
    )
    state["connectionBindingHash"] = connection_binding_hash
    state["evidence"]["test"] = {
        "kind": "maker-attestation",
        "status": "completed",
        "promptCategory": "list-my-open-hr-cases",
        "result": "pass",
        "failureCategory": None,
        "recordedAt": "2026-10-01T00:01:00Z",
        "binding": {
            "provider": snow.PROVIDER_KEY,
            "profile": snow.PROFILE_KEY,
            "agentSlug": AGENT_SLUG,
            "agentId": AGENT_ID,
            "environmentId": ENVIRONMENT_ID,
            "connectionId": normalized_connection_id,
            "draftSemanticHash": snow._draft_semantic_hash(components),
            "connectionBindingHash": connection_binding_hash,
        },
    }
    if publish is not None:
        state["evidence"]["publish"] = publish
    state_path = _lifecycle_path(root)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    return state


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
                                "token:ResourceUri": {"value": APP_CLIENT_ID},
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


def _portal_components() -> dict:
    components = _components()
    components["botComponentChanges"].insert(
        1,
        {
            "$kind": "BotComponentInsert",
            "component": {
                "$kind": "DialogComponent",
                "id": "00000000-0000-4000-8000-000000005556",
                "version": 3,
                "displayName": "ServiceNow HRSD Setup Configurations",
                "schemaName": (
                    f"{snow.HR_SCHEMA_NAME}.topic."
                    "ServiceNowHRSDSetupConfigurations"
                ),
                "state": "Active",
                "status": "Active",
                "dialog": {
                    "$kind": "TaskDialog",
                    "beginDialog": {
                        "actions": [
                            {
                                "$kind": "SetVariable",
                                "displayName": (
                                    "Set ServiceNow Portal BaseURI"
                                ),
                                "variable": (
                                    "Global.ServiceNowHRSDPortalBaseURI"
                                ),
                                "value": {
                                    "$kind": "Literal",
                                    "literalValue": (
                                        "https://dev123.service-now.com/"
                                        "employee"
                                    ),
                                },
                            }
                        ]
                    },
                },
            },
        },
    )
    return components


def _connection_record(
    connection_id: str = CONNECTION_ID,
    *,
    display_name: str = "ServiceNow",
    status: str = "Connected",
    auth_mode: str = snow.AUTH_MODE,
    instance_name: str = "dev123",
    resource_uri: str = APP_CLIENT_ID,
) -> dict:
    return {
        "name": connection_id.replace("-", ""),
        "properties": {
            "displayName": display_name,
            "apiId": snow.CONNECTOR_ID,
            "statuses": [{"target": "token", "status": status}],
            "connectionParametersSet": {
                "name": auth_mode,
                "values": {
                    "token:InstanceName": {"value": instance_name},
                    "token:ResourceUri": {"value": resource_uri},
                },
            },
        },
    }


def _seed_admin_credential_requirements(root: Path) -> None:
    state = snow._state_base(_context(), _components())
    setup = snow._admin_setup(state)
    setup["preflight"]["instanceName"] = "dev123"
    setup["phaseHandoffs"]["entra-registration"] = {
        "status": "completed",
        "evidence": {
            "kind": "structured-admin-attestation",
            "recordedAt": "2026-10-01T00:00:00Z",
            "clientId": APP_CLIENT_ID,
        },
    }
    snow._write_json_atomic(_lifecycle_path(root), state)


def _write_foundation_context(
    root: Path,
    *,
    components: dict | None = None,
) -> Path:
    setup_path = root / snow.SETUP_STATE
    config_path = root / snow.ACTIVE_CONFIG
    snapshot = Path(
        "workspace/agents/employee-self-service-hr/"
        ".agentbuilder/components.json"
    )
    setup_path.parent.mkdir(parents=True, exist_ok=True)
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
                            "workspace_slug": AGENT_SLUG,
                        },
                        "workspace": {
                            "folder": f"workspace/agents/{AGENT_SLUG}",
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
                "activeAgent": AGENT_SLUG,
                "agents": [
                    {
                        "slug": AGENT_SLUG,
                        "botId": AGENT_ID,
                        "agentBuilderChangeSetPath": snapshot.as_posix(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    if components is not None:
        snapshot_path = root / snapshot
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(json.dumps(components), encoding="utf-8")
    return snapshot


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
    assert result["reference"]["resourceUri"] == APP_CLIENT_ID


def test_summarize_components_requires_active_state_and_status() -> None:
    components = _components(CONNECTION_ID)
    topic = components["botComponentChanges"][0]["component"]
    topic["state"] = "Active"
    topic["status"] = "Inactive"

    result = snow.summarize_components(components)

    assert result["serviceNowTopicCount"] == 1
    assert result["activeServiceNowTopicCount"] == 0


def test_draft_semantic_hash_ignores_only_known_publish_metadata() -> None:
    components = _components(CONNECTION_ID)
    baseline = snow._draft_semantic_hash(components)
    metadata_only = copy.deepcopy(components)
    metadata_only["changeToken"] = "server-revision"
    topic = metadata_only["botComponentChanges"][0]["component"]
    topic["version"] = 99
    topic["auditInfo"] = {"modifiedAt": "2026-10-01T00:00:00Z"}

    assert snow._draft_semantic_hash(metadata_only) == baseline

    authored_edit = copy.deepcopy(metadata_only)
    authored_edit["botComponentChanges"][0]["component"]["displayName"] = (
        "Edited authored topic"
    )
    assert snow._draft_semantic_hash(authored_edit) != baseline

    connection_edit = copy.deepcopy(metadata_only)
    reference = connection_edit["connectionReferenceChanges"][0][
        "connectionReference"
    ]
    parameters = json.loads(reference["sharedConnectionParameters"])
    parameters["values"]["token:InstanceName"]["value"] = "dev456"
    reference["sharedConnectionParameters"] = json.dumps(parameters)
    assert snow._draft_semantic_hash(connection_edit) != baseline


def test_draft_semantic_hash_fails_closed_on_malformed_relevant_shape() -> None:
    components = _components(CONNECTION_ID)
    components["botComponentChanges"] = {"unexpected": True}

    with pytest.raises(snow.ServiceNowConnectError, match="topic collection"):
        snow._draft_semantic_hash(components)


def test_portal_url_payload_updates_only_exact_literal_node() -> None:
    components = _portal_components()
    before = copy.deepcopy(components)

    payload, preimage, postimage = snow.build_portal_url_update_payload(
        components,
        "https://dev123.service-now.com/hrportal",
        expected_instance_name="dev123",
    )

    assert payload["changeToken"] == "token"
    assert len(payload["botComponentChanges"]) == 1
    update = payload["botComponentChanges"][0]
    assert update["$kind"] == "BotComponentUpdate"
    assert update["component"] == postimage
    assert snow._portal_literal_value(preimage) == (
        "https://dev123.service-now.com/employee"
    )
    assert snow._portal_literal_value(postimage) == (
        "https://dev123.service-now.com/hrportal"
    )
    assert components == before
    restored = copy.deepcopy(postimage)
    snow._portal_value_node(restored)["value"]["literalValue"] = (
        snow._portal_literal_value(preimage)
    )
    assert snow._component_content_hash(restored) == (
        snow._component_content_hash(preimage)
    )


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("https://dev123.service-now.com", "portal path"),
        ("https://dev123.service-now.com/", "portal path"),
        ("https://other.service-now.com/sp", "confirmed ServiceNow instance"),
        ("http://dev123.service-now.com/sp", "plain HTTPS"),
        ("https://dev123.service-now.com/sp?x=1", "plain HTTPS"),
        ("https://dev123.service-now.com:8443/sp", "plain HTTPS"),
        ("https://dev123.service-now.com/hr portal", "plain HTTPS"),
    ],
)
def test_portal_url_validation_rejects_unsafe_or_inferred_values(
    value: str,
    message: str,
) -> None:
    with pytest.raises(snow.ServiceNowConnectError, match=message):
        snow.normalize_portal_url(
            value,
            expected_instance_name="dev123",
        )


def test_portal_payload_rejects_zero_or_multiple_target_nodes() -> None:
    components = _portal_components()
    setup_topic = components["botComponentChanges"][1]["component"]
    setup_topic["dialog"]["beginDialog"]["actions"] = []
    with pytest.raises(snow.ServiceNowConnectError, match="exactly one Set"):
        snow.build_portal_url_update_payload(
            components,
            "https://dev123.service-now.com/hrportal",
            expected_instance_name="dev123",
        )

    duplicate = copy.deepcopy(components)
    duplicate["botComponentChanges"][1]["component"]["dialog"][
        "beginDialog"
    ]["actions"] = [
        {
            "$kind": "SetVariable",
            "displayName": snow.PORTAL_NODE_DISPLAY_NAME,
            "variable": snow.PORTAL_VARIABLE_NAME,
            "value": {"$kind": "Literal", "literalValue": ""},
        },
        {
            "$kind": "SetVariable",
            "displayName": snow.PORTAL_NODE_DISPLAY_NAME,
            "variable": snow.PORTAL_VARIABLE_NAME,
            "value": {"$kind": "Literal", "literalValue": ""},
        },
    ]
    with pytest.raises(snow.ServiceNowConnectError, match="found 2"):
        snow.build_portal_url_update_payload(
            duplicate,
            "https://dev123.service-now.com/hrportal",
            expected_instance_name="dev123",
        )


def test_portal_summary_never_echoes_url_credentials() -> None:
    components = _portal_components()
    setup_topic = components["botComponentChanges"][1]["component"]
    snow._portal_value_node(setup_topic)["value"]["literalValue"] = (
        "https://user:password@dev123.service-now.com/employee"
    )

    summary = snow.portal_configuration_summary(
        components,
        expected_instance_name="dev123",
    )

    assert summary["valid"] is False
    assert summary["reason"] == "invalid-url"
    assert summary["origin"] == "https://dev123.service-now.com"
    assert "user" not in json.dumps(summary)
    assert "password" not in json.dumps(summary)


def test_portal_payload_rejects_zero_or_multiple_setup_topics() -> None:
    with pytest.raises(
        snow.ServiceNowConnectError,
        match="Setup Configurations topic; found 0",
    ):
        snow.build_portal_url_update_payload(
            _components(),
            "https://dev123.service-now.com/hrportal",
            expected_instance_name="dev123",
        )

    components = _portal_components()
    duplicate = copy.deepcopy(
        components["botComponentChanges"][1]
    )
    duplicate["component"]["id"] = (
        "00000000-0000-4000-8000-000000005557"
    )
    components["botComponentChanges"].append(duplicate)
    with pytest.raises(
        snow.ServiceNowConnectError,
        match="Setup Configurations topic; found 2",
    ):
        snow.build_portal_url_update_payload(
            components,
            "https://dev123.service-now.com/hrportal",
            expected_instance_name="dev123",
        )


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

    result = snow.record_keep_current_topic_choice(_context())

    assert result["customerChoice"] == "keep-current"
    assert result["changedTopics"] == []
    state = json.loads(_lifecycle_path(tmp_path).read_text(encoding="utf-8"))
    assert state["evidence"]["topics"]["customerChoice"] == "keep-current"
    assert state["evidence"]["topics"]["kind"] == "maker-attestation"
    assert state["evidence"]["topics"]["status"] == "recorded"
    assert state["provider"] == snow.PROVIDER_KEY


def test_enable_all_topics_fails_when_refetch_is_still_inactive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
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

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )

    with pytest.raises(
        snow.ServiceNowConnectError,
        match="before any topic mutation",
    ):
        snow.enable_all_servicenow_topics(_context(), confirmed=True)


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
                        "token:ResourceUri": {"value": APP_CLIENT_ID},
                        "password": {"value": "must-not-be-returned"},
                    },
                },
            },
        }
    )

    assert result["status"] == "Connected"
    assert result["statusTarget"] == "token"
    assert result["parameterValues"]["token:InstanceName"] == "dev123"
    assert result["parameterValues"]["token:ResourceUri"] == APP_CLIENT_ID
    assert "password" not in result["parameterValues"]


def test_load_context_requires_matching_schema_v4_hr_agent(
    tmp_path: Path,
) -> None:
    snapshot = _write_foundation_context(tmp_path)

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
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: type(
            "FakeAgentBuilder",
            (),
            {"fetch_components": lambda self, _agent_id: _components()},
        )(),
    )

    result = snow.record_agent_connection_attestation(
        _context(),
        CONNECTION_ID,
    )

    assert result["connectionId"] == CONNECTION_ID.replace("-", "")
    assert result["status"] == "completed"
    assert result["binding"]["connectionId"] == result["connectionId"]
    assert result["physicalStatus"] == "Connected"
    assert result["makerAttested"] is True
    state = json.loads(_lifecycle_path(tmp_path).read_text(encoding="utf-8"))
    assert state["evidence"]["agentConnection"]["makerAttested"] is True
    assert (
        state["evidence"]["agentConnection"]["binding"]["connectionId"]
        == state["evidence"]["agentConnection"]["connectionId"]
    )
    assert state["migration"]["legacySourcePath"].endswith("state.json")


def test_publish_receipt_uses_post_publish_component_revision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    before = _components(CONNECTION_ID)
    after = copy.deepcopy(before)
    after["changeToken"] = "published-token"

    class FakeAgentBuilder:
        def __init__(self) -> None:
            self.fetch_count = 0

        def fetch_components(self, _agent_id: str) -> dict:
            self.fetch_count += 1
            return before if self.fetch_count == 1 else after

        def publish_agent(self, _agent_id: str) -> dict:
            return {"ValidationPending": False}

    client = FakeAgentBuilder()
    monkeypatch.chdir(tmp_path)
    _seed_passing_test(tmp_path, before)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: client,
    )

    result = snow.publish(_context(), confirmed=True)
    receipt = result["evidence"]["publish"]

    assert receipt["requestedComponentHash"] == snow._component_hash(before)
    assert receipt["kind"] == "maker-attestation"
    assert receipt["publishedComponentHash"] == snow._component_hash(after)
    assert receipt["componentHash"] == snow._component_hash(after)
    assert receipt["recordedAt"] == receipt["completedAt"]
    assert receipt["status"] == "completed"
    state = json.loads(_lifecycle_path(tmp_path).read_text(encoding="utf-8"))
    assert state["componentHash"] == snow._component_hash(after)


def test_publish_rejects_missing_test_before_remote_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _components(CONNECTION_ID)
    state = _seed_passing_test(tmp_path, components)
    state["evidence"].pop("test")
    _lifecycle_path(tmp_path).write_text(json.dumps(state), encoding="utf-8")

    class FakeAgentBuilder:
        def __init__(self) -> None:
            self.publish_count = 0

        def fetch_components(self, _agent_id: str) -> dict:
            return components

        def publish_agent(self, _agent_id: str) -> dict:
            self.publish_count += 1
            return {"validationPending": False}

    client = FakeAgentBuilder()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: client,
    )

    with pytest.raises(
        snow.ServiceNowConnectError,
        match="Test this exact draft before publishing",
    ):
        snow.publish(_context(), confirmed=True)

    assert client.publish_count == 0


def test_validation_pending_publish_receipt_matches_current_manual_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    before = _components(CONNECTION_ID)
    after = copy.deepcopy(before)
    after["changeToken"] = "published-token"

    class FakeAgentBuilder:
        def __init__(self) -> None:
            self.fetch_count = 0

        def fetch_components(self, _agent_id: str) -> dict:
            self.fetch_count += 1
            return before if self.fetch_count == 1 else after

        def publish_agent(self, _agent_id: str) -> dict:
            return {"validationPending": True}

    monkeypatch.chdir(tmp_path)
    _seed_passing_test(tmp_path, before)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )

    result = snow.publish(_context(), confirmed=True)
    receipt = result["evidence"]["publish"]

    assert receipt["kind"] == "maker-attestation"
    assert receipt["status"] == "confirmation-required"
    assert receipt["recordedAt"] == receipt["completedAt"]
    assert receipt["publishedComponentHash"] == result["componentHash"]
    acknowledgement = _phase_contract("publish")[
        "manualAcknowledgementEvidence"
    ]
    assert receipt["status"] in acknowledgement["acceptedRecordStatuses"]
    assert receipt["kind"] == acknowledgement["requiredEvidenceKind"]
    assert receipt["publishedComponentHash"] == result["componentHash"]


def test_publish_refetch_failure_requires_reconciliation_without_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    before = _components(CONNECTION_ID)

    class FakeAgentBuilder:
        def __init__(self) -> None:
            self.fetch_count = 0
            self.publish_count = 0

        def fetch_components(self, _agent_id: str) -> dict:
            self.fetch_count += 1
            if self.fetch_count == 1:
                return before
            raise RuntimeError("post-publish read unavailable")

        def publish_agent(self, _agent_id: str) -> dict:
            self.publish_count += 1
            return {"validationPending": False}

    client = FakeAgentBuilder()
    monkeypatch.chdir(tmp_path)
    _seed_passing_test(tmp_path, before)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: client,
    )

    with pytest.raises(
        snow.ServiceNowConnectError,
        match="Do not republish blindly",
    ):
        snow.publish(_context(), confirmed=True)

    state = json.loads(_lifecycle_path(tmp_path).read_text(encoding="utf-8"))
    receipt = state["evidence"]["publish"]
    assert receipt["status"] == "needs_remediation"
    assert receipt["requestedComponentHash"] == snow._component_hash(before)
    assert receipt["response"]["validationPending"] is False
    assert client.publish_count == 1


def test_publish_semantic_drift_after_mutation_requires_retest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    before = _components(CONNECTION_ID)
    after = copy.deepcopy(before)
    after["botComponentChanges"][0]["component"]["displayName"] = (
        "Server-returned authored drift"
    )

    class FakeAgentBuilder:
        def __init__(self) -> None:
            self.fetch_count = 0
            self.publish_count = 0

        def fetch_components(self, _agent_id: str) -> dict:
            self.fetch_count += 1
            return before if self.fetch_count == 1 else after

        def publish_agent(self, _agent_id: str) -> dict:
            self.publish_count += 1
            return {"validationPending": False}

    client = FakeAgentBuilder()
    monkeypatch.chdir(tmp_path)
    _seed_passing_test(tmp_path, before)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: client,
    )

    with pytest.raises(
        snow.ServiceNowConnectError,
        match="changed authored semantic content",
    ):
        snow.publish(_context(), confirmed=True)

    state = json.loads(_lifecycle_path(tmp_path).read_text(encoding="utf-8"))
    assert state["evidence"]["publish"]["status"] == "needs_remediation"
    assert client.publish_count == 1


def test_publish_rejects_conflicting_validation_pending_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _components(CONNECTION_ID)

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            return components

        def publish_agent(self, _agent_id: str) -> dict:
            return {
                "ValidationPending": False,
                "validationPending": True,
            }

    monkeypatch.chdir(tmp_path)
    _seed_passing_test(tmp_path, components)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )

    with pytest.raises(
        snow.ServiceNowConnectError,
        match="conflicting ValidationPending",
    ):
        snow.publish(_context(), confirmed=True)


def test_reconcile_legacy_publish_receipt_requires_stable_double_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _components(CONNECTION_ID)
    component_hash = snow._component_hash(components)
    last_published_at = "2026-09-30T20:22:44.5041453Z"
    _seed_passing_test(
        tmp_path,
        components,
        publish={
            "requestedAt": "2026-09-30T20:22:44.806391Z",
            "completedAt": "2026-09-30T20:22:54.575668Z",
            "status": "confirmation-required",
            "componentHash": "a" * 64,
            "response": {"validationPending": None},
        },
    )

    class FakeAgentBuilder:
        def get_agent(self, _agent_id: str) -> dict:
            return {"lastPublishedAt": last_published_at}

        def fetch_components(self, _agent_id: str) -> dict:
            return components

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )

    inspected = snow.inspect_publish_state(_context())
    reconciled = snow.reconcile_publish_receipt(
        _context(),
        expected_component_hash=inspected["componentHash"],
        expected_last_published_at=inspected["serverLastPublishedAt"],
        confirmed=True,
    )

    assert inspected["reconciliationEligible"] is True
    assert reconciled["status"] == "confirmation-required"
    assert reconciled["publishedComponentHash"] == component_hash
    assert reconciled["componentHash"] == component_hash
    assert reconciled["verifiedBy"] == "maker-attested-current-revision"
    assert reconciled["recordedAt"] == reconciled["reconciledAt"]
    assert reconciled["completedAt"] == "2026-09-30T20:22:54.575668Z"
    assert reconciled["legacyReceipt"]["componentHash"] == "a" * 64

    test_record = snow.record_test_attestation(
        _context(),
        prompt_category="list-my-open-hr-cases",
        result="pass",
        failure_category=None,
    )
    assert test_record["binding"]["draftSemanticHash"] == (
        reconciled["publishedSemanticHash"]
    )
    assert test_record["binding"]["connectionBindingHash"] == (
        reconciled["connectionBindingHash"]
    )
    acknowledgement = _phase_contract("test")[
        "manualAcknowledgementEvidence"
    ]
    assert test_record["status"] in acknowledgement[
        "acceptedRecordStatuses"
    ]
    assert test_record["kind"] == acknowledgement["requiredEvidenceKind"]
    assert test_record["result"] == acknowledgement["requiredValues"]["result"]


def test_reconcile_legacy_publish_receipt_uses_server_time_when_completion_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _components(CONNECTION_ID)
    component_hash = snow._component_hash(components)
    last_published_at = "2026-09-30T20:22:44.5041453Z"
    _seed_passing_test(
        tmp_path,
        components,
        publish={
            "requestedAt": "2026-09-30T20:22:44.806391Z",
            "status": "needs_remediation",
            "componentHash": "a" * 64,
        },
    )

    class FakeAgentBuilder:
        def get_agent(self, _agent_id: str) -> dict:
            return {"lastPublishedAt": last_published_at}

        def fetch_components(self, _agent_id: str) -> dict:
            return components

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )

    reconciled = snow.reconcile_publish_receipt(
        _context(),
        expected_component_hash=component_hash,
        expected_last_published_at=last_published_at,
        confirmed=True,
    )

    assert reconciled["completedAt"] == last_published_at
    assert reconciled["recordedAt"]


def test_reconcile_publish_receipt_rejects_revision_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _components(CONNECTION_ID)
    state_path = _lifecycle_path(tmp_path)
    _seed_passing_test(
        tmp_path,
        components,
        publish={
            "requestedAt": "2026-09-30T20:22:44.806391Z",
            "status": "confirmation-required",
            "componentHash": "a" * 64,
        },
    )

    class FakeAgentBuilder:
        def get_agent(self, _agent_id: str) -> dict:
            return {"lastPublishedAt": "2026-09-30T20:22:44.5041453Z"}

        def fetch_components(self, _agent_id: str) -> dict:
            changed = copy.deepcopy(components)
            changed["changeToken"] = "changed-after-confirmation"
            return changed

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )

    with pytest.raises(
        snow.ServiceNowConnectError,
        match="component revision changed",
    ):
        snow.reconcile_publish_receipt(
            _context(),
            expected_component_hash=snow._component_hash(components),
            expected_last_published_at="2026-09-30T20:22:44.5041453Z",
            confirmed=True,
        )

    unchanged = json.loads(state_path.read_text(encoding="utf-8"))
    assert unchanged["evidence"]["publish"]["componentHash"] == "a" * 64


def test_record_agent_connection_rejects_unsupported_auth_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeConnectivity:
        def get_connection(self, _connection_id: str) -> dict:
            return {
                "name": CONNECTION_ID.replace("-", ""),
                "properties": {
                    "displayName": "ServiceNow",
                    "statuses": [{"target": "token", "status": "Connected"}],
                    "connectionParametersSet": {"name": "oauth2"},
                },
            }

    monkeypatch.setattr(
        snow,
        "_connectivity_client",
        lambda _context: FakeConnectivity(),
    )

    with pytest.raises(
        snow.ServiceNowConnectError,
        match="Microsoft Entra ID User Login",
    ):
        snow.record_agent_connection_attestation(
            {
                "agent": {"id": AGENT_ID},
                "environment": {"id": ENVIRONMENT_ID},
            },
            CONNECTION_ID,
        )


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

    context = _context()
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
    assert result["progress"]["publish"]["status"] == "pending"
    assert (
        result["progress"]["agentConnection"]["status"]
        == "confirmation-required"
    )
    assert "parameterSharing" not in result["progress"]
    assert result["progress"]["test"]["status"] == "pending"
    state = json.loads(_lifecycle_path(tmp_path).read_text(encoding="utf-8"))
    assert state["evidence"]["agentConnection"]["reconfirmRequired"] is True
    assert state["evidence"]["parameterSharing"]["reconfirmRequired"] is True
    assert state["evidence"]["test"]["reconfirmRequired"] is True


def test_inspect_reopens_topics_after_later_deactivation(
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
                "topicEnablement": {"customerChoice": "enable-all"},
                "steps": {"topics": "done"},
            }
        ),
        encoding="utf-8",
    )
    components = _components(CONNECTION_ID)
    components["botComponentChanges"][0]["component"]["state"] = "Inactive"
    components["botComponentChanges"][0]["component"]["status"] = "Inactive"

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            return components

    class FakeConnectivity:
        def get_connector(self) -> dict:
            return {"properties": {}}

        def list_connections(self) -> list[dict]:
            return []

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

    result = snow.inspect(
        {
            "agent": {
                "id": AGENT_ID,
                "schema_name": snow.HR_SCHEMA_NAME,
            },
            "environment": {"id": ENVIRONMENT_ID, "ring": "test"},
        }
    )

    assert result["progress"]["topics"]["status"] == "pending"


def test_inspect_preserves_explicit_keep_current_topic_choice(
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
                "topicEnablement": {"customerChoice": "keep-current"},
                "steps": {"topics": "done"},
            }
        ),
        encoding="utf-8",
    )
    components = _components(CONNECTION_ID)
    components["botComponentChanges"][0]["component"]["state"] = "Inactive"
    components["botComponentChanges"][0]["component"]["status"] = "Inactive"

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            return components

    class FakeConnectivity:
        def get_connector(self) -> dict:
            return {"properties": {}}

        def list_connections(self) -> list[dict]:
            return []

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

    result = snow.inspect(
        {
            "agent": {
                "id": AGENT_ID,
                "schema_name": snow.HR_SCHEMA_NAME,
            },
            "environment": {"id": ENVIRONMENT_ID, "ring": "test"},
        }
    )

    assert result["progress"]["topics"]["status"] == "pending"


def test_parameter_sharing_has_no_active_cli_surface() -> None:
    help_text = snow.build_parser().format_help()
    phase_help = snow.build_parser()._subparsers._group_actions[0].choices[
        "record-admin-phase"
    ].format_help()

    assert "record-parameter-sharing" not in help_text
    assert not hasattr(snow, "record_parameter_sharing")
    assert "--claim" not in phase_help
    assert "--user-field" not in phase_help


def test_connectivity_scopes_are_read_only() -> None:
    scopes = snow.connectivity_scopes("test")

    assert (
        "https://api.test.powerplatform.com/Connectivity.Connections.Read"
        in scopes
    )
    assert not any(scope.endswith(".Write") for scope in scopes)


def test_set_portal_url_commits_with_fresh_readback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _portal_components()
    updates: list[dict] = []

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            return copy.deepcopy(components)

        def update_components(self, _agent_id: str, payload: dict) -> dict:
            updates.append(copy.deepcopy(payload))
            updated = payload["botComponentChanges"][0]["component"]
            components["botComponentChanges"][1]["component"] = copy.deepcopy(
                updated
            )
            components["botComponentChanges"][1]["component"]["version"] += 1
            components["changeToken"] = "token-2"
            return {"changeToken": "token-2"}

    monkeypatch.chdir(tmp_path)
    _seed_admin_credential_requirements(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )

    result = snow.set_portal_url(
        _context(),
        "https://dev123.service-now.com/hrportal",
        confirmed=True,
    )

    assert result["status"] == "committed"
    assert result["readbackVerified"] is True
    assert len(updates) == 1
    assert snow._portal_literal_value(
        components["botComponentChanges"][1]["component"]
    ) == "https://dev123.service-now.com/hrportal"
    state = json.loads(_lifecycle_path(tmp_path).read_text(encoding="utf-8"))
    transaction = state["transactions"]["portal"][result["operationId"]]
    assert transaction["status"] == "committed"


def test_set_portal_url_skips_update_when_already_configured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _portal_components()

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            return copy.deepcopy(components)

        def update_components(self, _agent_id: str, _payload: dict) -> dict:
            raise AssertionError("already configured value must not be updated")

    monkeypatch.chdir(tmp_path)
    _seed_admin_credential_requirements(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )

    result = snow.set_portal_url(
        _context(),
        "https://dev123.service-now.com/employee",
        confirmed=True,
    )

    assert result["status"] == "already-configured"
    assert result["readbackVerified"] is True


def test_set_portal_url_reports_failed_unchanged_for_unsupported_update(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _portal_components()

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            return copy.deepcopy(components)

        def update_components(self, _agent_id: str, _payload: dict) -> dict:
            raise PermissionError("unsupported")

    monkeypatch.chdir(tmp_path)
    _seed_admin_credential_requirements(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )

    with pytest.raises(
        snow.ServiceNowConnectError,
        match="did not apply the Portal BaseURI change",
    ) as raised:
        snow.set_portal_url(
            _context(),
            "https://dev123.service-now.com/hrportal",
            confirmed=True,
        )

    transaction = raised.value.details["transaction"]
    assert transaction["status"] == "failed-unchanged"
    assert transaction["rollbackVerified"] is True


def test_set_portal_url_can_verify_and_roll_back(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _portal_components()
    original = snow._portal_literal_value(
        components["botComponentChanges"][1]["component"]
    )
    updates: list[dict] = []

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            return copy.deepcopy(components)

        def update_components(self, _agent_id: str, payload: dict) -> dict:
            updates.append(copy.deepcopy(payload))
            updated = payload["botComponentChanges"][0]["component"]
            components["botComponentChanges"][1]["component"] = copy.deepcopy(
                updated
            )
            components["botComponentChanges"][1]["component"]["version"] += 1
            components["changeToken"] = f"token-{len(updates) + 1}"
            return {"changeToken": components["changeToken"]}

    monkeypatch.chdir(tmp_path)
    _seed_admin_credential_requirements(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )

    result = snow.set_portal_url(
        _context(),
        "https://dev123.service-now.com/hrportal",
        confirmed=True,
        rollback_after_verify=True,
    )

    assert result["status"] == "verified-and-rolled-back"
    assert result["rollbackVerified"] is True
    assert len(updates) == 2
    assert snow._portal_literal_value(
        components["botComponentChanges"][1]["component"]
    ) == original


def test_set_portal_url_reports_rollback_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _portal_components()
    update_count = 0

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            return copy.deepcopy(components)

        def update_components(self, _agent_id: str, payload: dict) -> dict:
            nonlocal update_count
            update_count += 1
            if update_count == 2:
                raise PermissionError("rollback rejected")
            updated = payload["botComponentChanges"][0]["component"]
            components["botComponentChanges"][1]["component"] = copy.deepcopy(
                updated
            )
            components["botComponentChanges"][1]["component"]["version"] += 1
            components["changeToken"] = "token-2"
            return {"changeToken": "token-2"}

    monkeypatch.chdir(tmp_path)
    _seed_admin_credential_requirements(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )

    with pytest.raises(
        snow.ServiceNowConnectError,
        match="Rollback did not restore",
    ) as raised:
        snow.set_portal_url(
            _context(),
            "https://dev123.service-now.com/hrportal",
            confirmed=True,
            rollback_after_verify=True,
        )

    transaction = raised.value.details["transaction"]
    assert transaction["status"] == "rollback-incomplete"
    assert transaction["rollbackVerified"] is False
    assert transaction["rollbackError"] == "PermissionError"


def test_set_portal_url_preserves_concurrent_authored_edit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _portal_components()

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            return copy.deepcopy(components)

        def update_components(self, _agent_id: str, payload: dict) -> dict:
            updated = copy.deepcopy(
                payload["botComponentChanges"][0]["component"]
            )
            updated["externalConcurrentEdit"] = "must-survive"
            components["botComponentChanges"][1]["component"] = updated
            components["changeToken"] = "token-2"
            return {"changeToken": "token-2"}

    monkeypatch.chdir(tmp_path)
    _seed_admin_credential_requirements(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )

    with pytest.raises(
        snow.ServiceNowConnectError,
        match="changed unexpectedly",
    ):
        snow.set_portal_url(
            _context(),
            "https://dev123.service-now.com/hrportal",
            confirmed=True,
            rollback_after_verify=True,
        )

    assert (
        components["botComponentChanges"][1]["component"][
            "externalConcurrentEdit"
        ]
        == "must-survive"
    )
    state = json.loads(_lifecycle_path(tmp_path).read_text(encoding="utf-8"))
    transaction = next(iter(state["transactions"]["portal"].values()))
    assert transaction["status"] == "conflict"


def test_set_portal_url_reports_unverifiable_readback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _portal_components()
    fetch_count = 0

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            nonlocal fetch_count
            fetch_count += 1
            if fetch_count > 1:
                raise RuntimeError("readback unavailable")
            return copy.deepcopy(components)

        def update_components(self, _agent_id: str, payload: dict) -> dict:
            updated = payload["botComponentChanges"][0]["component"]
            components["botComponentChanges"][1]["component"] = copy.deepcopy(
                updated
            )
            return {}

    monkeypatch.chdir(tmp_path)
    _seed_admin_credential_requirements(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )

    with pytest.raises(
        snow.ServiceNowConnectError,
        match="readback failed",
    ) as raised:
        snow.set_portal_url(
            _context(),
            "https://dev123.service-now.com/hrportal",
            confirmed=True,
        )

    transaction = raised.value.details["transaction"]
    assert transaction["status"] == "reconciliation-required"
    assert transaction["reconciliationError"] == "RuntimeError"
    assert transaction["mutationMayHaveOccurred"] is True


def test_inspect_portal_url_offline_reports_sanitized_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    components = _portal_components()
    _write_foundation_context(tmp_path, components=components)
    _seed_admin_credential_requirements(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert snow.main(["inspect-portal-url", "--offline"]) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["status"] == "configured"
    assert result["mode"] == "offline"
    assert result["portal"]["origin"] == "https://dev123.service-now.com"
    assert result["portal"]["path"] == "/employee"
    assert result["input"] is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("dev123", "dev123"),
        ("https://dev123.service-now.com", "dev123"),
        ("https://DEV123.service-now.com/", "dev123"),
    ],
)
def test_normalize_instance_name(value: str, expected: str) -> None:
    assert snow.normalize_instance_name(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://dev123.service-now.com",
        "https://dev123.service-now.com/path",
        "https://example.com",
        "dev123.example.com",
    ],
)
def test_normalize_instance_name_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(snow.ServiceNowConnectError):
        snow.normalize_instance_name(value)


@pytest.mark.parametrize(
    ("ring", "power_automate", "power_apps", "copilot_studio"),
    [
        (
            "prod",
            "https://make.powerautomate.com",
            "https://make.powerapps.com",
            "https://copilotstudio.microsoft.com",
        ),
        (
            "preprod",
            "https://make.preprod.powerautomate.com",
            "https://make.preprod.powerapps.com",
            "https://copilotstudio.preprod.microsoft.com",
        ),
        (
            "test",
            "https://make.test.powerautomate.com",
            "https://make.test.powerapps.com",
            "https://copilotstudio.test.microsoft.com",
        ),
    ],
)
def test_maker_portal_links_are_ring_aware_and_identity_scoped(
    ring: str,
    power_automate: str,
    power_apps: str,
    copilot_studio: str,
) -> None:
    context = _context()
    context["environment"]["ring"] = ring

    links = snow.maker_portal_links(
        context,
        instance_name="dev123",
    )

    assert links["serviceNowInstance"] == {
        "label": "Open this ServiceNow instance",
        "url": "https://dev123.service-now.com/",
    }
    assert links["hrCorePlugin"] == {
        "label": "Open HR Service Delivery Core",
        "url": (
            "https://dev123.service-now.com/now/app-manager/home/plugin/"
            "id/com.sn_hr_core/details"
        ),
    }
    assert links["entra"]["url"] == "https://entra.microsoft.com/"
    assert links["powerAutomateConnections"]["url"] == (
        f"{power_automate}/environments/{ENVIRONMENT_ID}/connections"
    )
    assert links["powerApps"]["url"] == f"{power_apps}/"
    assert links["copilotStudioAgent"]["url"] == (
        f"{copilot_studio}/environments/{ENVIRONMENT_ID}/copilots/"
        f"{AGENT_ID}/details?agentBackend=cosmos"
    )
    template = "[Open Power Apps]({POWER_APPS_URL})"
    rendered = template.replace(
        "{POWER_APPS_URL}",
        links["powerApps"]["url"],
    )
    assert rendered == f"[Open Power Apps]({power_apps}/)"
    assert rendered.replace("https://", "").find("//") == -1


def test_maker_portal_links_reject_unknown_ring() -> None:
    context = _context()
    context["environment"]["ring"] = "unknown"

    with pytest.raises(
        snow.ServiceNowConnectError,
        match="Unsupported Power Platform ring",
    ):
        snow.maker_portal_links(context)


def test_plugin_requirements_are_scope_and_auth_dynamic() -> None:
    hrsd = snow.required_servicenow_prerequisites("hrsd")
    itsm = snow.required_servicenow_prerequisites("itsm")

    assert [item["id"] for item in hrsd] == ["hr-core"]
    assert itsm == []
    assert hrsd[0]["aliases"] == ["com.sn_hr_core", "sn_hr_core"]
    with pytest.raises(snow.ServiceNowConnectError):
        snow.required_servicenow_prerequisites("hrsd", "oauth2ServiceNow")


def test_preflight_derives_instance_without_customer_progress_question(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeConnectivity:
        def list_connections(self) -> list[dict]:
            return [
                {
                    "name": CONNECTION_ID.replace("-", ""),
                    "properties": {
                        "displayName": "Existing ServiceNow",
                        "statuses": [
                            {"target": "token", "status": "Connected"}
                        ],
                        "connectionParametersSet": {
                            "name": snow.AUTH_MODE,
                            "values": {
                                "token:InstanceName": {"value": "dev123"},
                                "token:ResourceUri": {
                                    "value": APP_CLIENT_ID
                                },
                            },
                        },
                    },
                }
            ]

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow,
        "_connectivity_client",
        lambda _context: FakeConnectivity(),
    )

    discovery = snow.inspect_admin_setup(_context())
    refreshed = snow.inspect_admin_setup(_context())
    snow.record_admin_phase(
        _context(),
        phase="entra-registration",
        status="completed",
        client_id=APP_CLIENT_ID,
    )
    with_client_id = snow.inspect_admin_setup(_context())

    assert discovery["connectionCandidates"][0]["status"] == "Connected"
    assert "fingerprint" not in discovery
    assert "fingerprint" not in refreshed
    assert "fingerprint" not in with_client_id
    assert discovery["instanceName"] == "dev123"
    assert discovery["instanceInputRequired"] is False
    assert discovery["credentialResolution"]["healthyExactCount"] == 0
    assert with_client_id["credentialResolution"]["healthyExactCount"] == 1
    assert with_client_id["credentialResolution"]["unhealthyExactCount"] == 0
    assert discovery["links"]["serviceNowInstance"]["url"] == (
        "https://dev123.service-now.com/"
    )
    assert discovery["links"]["powerAutomateConnections"]["url"].startswith(
        "https://make.test.powerautomate.com/"
    )
    assert with_client_id["entraClientId"] == APP_CLIENT_ID
    state = json.loads(_lifecycle_path(tmp_path).read_text(encoding="utf-8"))
    assert "scenario" not in state["adminSetup"]["preflight"]
    assert "reuseDecision" not in state["adminSetup"]["preflight"]
    assert state["adminSetup"]["phaseHandoffs"]["preflight"] == {
        "status": "completed",
        "evidence": {
            "kind": "read-only-resource-discovery",
            "instanceName": "dev123",
            "observedAt": with_client_id["observedAt"],
        },
    }


def test_preflight_requests_only_missing_instance_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeConnectivity:
        def list_connections(self) -> list[dict]:
            return []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow,
        "_connectivity_client",
        lambda _context: FakeConnectivity(),
    )

    discovery = snow.inspect_admin_setup(_context())
    recorded = snow.record_preflight_instance(
        _context(),
        instance_url="https://dev123.service-now.com",
    )
    refreshed = snow.inspect_admin_setup(_context())

    assert discovery["instanceInputRequired"] is True
    assert recorded["instanceName"] == "dev123"
    assert refreshed["instanceInputRequired"] is False
    assert "scenario" not in recorded
    assert "--scenario" not in snow.build_parser().format_help()


def test_resolve_credential_automatically_records_unique_healthy_exact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = _connection_record(display_name="Existing ServiceNow")

    class FakeConnectivity:
        def list_connections(self) -> list[dict]:
            return [record]

        def get_connection(self, connection_id: str) -> dict:
            assert connection_id == CONNECTION_ID.replace("-", "")
            return record

    monkeypatch.chdir(tmp_path)
    _seed_admin_credential_requirements(tmp_path)
    monkeypatch.setattr(
        snow,
        "_connectivity_client",
        lambda _context: FakeConnectivity(),
    )
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: type(
            "FakeAgentBuilder",
            (),
            {
                "fetch_components": lambda self, _agent_id: _components(
                    CONNECTION_ID
                )
            },
        )(),
    )

    result = snow.resolve_credential_completion(_context())

    assert result["status"] == "selected"
    assert result["selection"] == {"label": "Existing ServiceNow"}
    state = json.loads(_lifecycle_path(tmp_path).read_text(encoding="utf-8"))
    assert state["evidence"]["credential"]["connectionId"] == (
        CONNECTION_ID.replace("-", "")
    )
    assert state["adminSetup"]["phaseHandoffs"]["credential"]["status"] == (
        "completed"
    )


def test_resolve_credential_requires_bounded_choice_for_multiple_exact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first_id = "00000000-0000-4000-8000-000000003331"
    second_id = "00000000-0000-4000-8000-000000003332"
    records = [
        _connection_record(first_id, display_name="ServiceNow A"),
        _connection_record(second_id, display_name="ServiceNow B"),
    ]

    class FakeConnectivity:
        def list_connections(self) -> list[dict]:
            return records

        def get_connection(self, connection_id: str) -> dict:
            return next(
                record
                for record in records
                if record["name"] == connection_id
            )

    monkeypatch.chdir(tmp_path)
    _seed_admin_credential_requirements(tmp_path)
    monkeypatch.setattr(
        snow,
        "_connectivity_client",
        lambda _context: FakeConnectivity(),
    )
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: type(
            "FakeAgentBuilder",
            (),
            {
                "fetch_components": lambda self, _agent_id: _components(
                    first_id
                )
            },
        )(),
    )

    choice = snow.resolve_credential_completion(_context())

    assert choice["status"] == "choice-required"
    assert [candidate["label"] for candidate in choice["candidates"]] == [
        "ServiceNow A (Connected, option 1)",
        "ServiceNow B (Connected, option 2)",
    ]
    serialized = json.dumps(choice)
    assert first_id not in serialized
    assert first_id.replace("-", "") not in serialized
    assert second_id not in serialized
    pending_state = json.loads(
        _lifecycle_path(tmp_path).read_text(encoding="utf-8")
    )
    assert "credential" not in pending_state["evidence"]

    selected = snow.resolve_credential_completion(
        _context(),
        selection_key=choice["candidates"][1]["selectionKey"],
    )

    assert selected["status"] == "selected"
    assert selected["selection"] == {"label": "ServiceNow B"}
    state = json.loads(_lifecycle_path(tmp_path).read_text(encoding="utf-8"))
    assert state["evidence"]["credential"]["connectionId"] == (
        second_id.replace("-", "")
    )


@pytest.mark.parametrize(
    "record",
    [
        _connection_record(status="Disconnected"),
        _connection_record(auth_mode="oauth2"),
        _connection_record(instance_name="dev456"),
        _connection_record(
            resource_uri="00000000-0000-4000-8000-000000009999"
        ),
    ],
)
def test_resolve_credential_rejects_nonhealthy_or_nonexact_candidates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    record: dict,
) -> None:
    class FakeConnectivity:
        def list_connections(self) -> list[dict]:
            return [record]

    monkeypatch.chdir(tmp_path)
    _seed_admin_credential_requirements(tmp_path)
    monkeypatch.setattr(
        snow,
        "_connectivity_client",
        lambda _context: FakeConnectivity(),
    )

    result = snow.resolve_credential_completion(_context())

    assert result["status"] == "not-ready"
    assert "No exact healthy Connected" in result["remediation"]
    state = json.loads(_lifecycle_path(tmp_path).read_text(encoding="utf-8"))
    assert "credential" not in state["evidence"]


def test_resolve_credential_read_failure_is_explicit_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeConnectivity:
        def list_connections(self) -> list[dict]:
            raise snow.ServiceNowConnectError(
                "Connection inventory is unavailable."
            )

    monkeypatch.chdir(tmp_path)
    _seed_admin_credential_requirements(tmp_path)
    monkeypatch.setattr(snow, "load_context", lambda: _context())
    monkeypatch.setattr(
        snow,
        "_connectivity_client",
        lambda _context: FakeConnectivity(),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["connect_servicenow_da.py", "resolve-credential"],
    )

    assert snow.main() == 1
    assert json.loads(capsys.readouterr().out) == {
        "status": "error",
        "message": "Connection inventory is unavailable.",
    }


def test_resolve_credential_rejects_stale_selection_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    record = _connection_record()

    class FakeConnectivity:
        def list_connections(self) -> list[dict]:
            return [record]

    monkeypatch.chdir(tmp_path)
    _seed_admin_credential_requirements(tmp_path)
    monkeypatch.setattr(
        snow,
        "_connectivity_client",
        lambda _context: FakeConnectivity(),
    )

    with pytest.raises(
        snow.ServiceNowConnectError,
        match="no longer an exact healthy candidate",
    ):
        snow.resolve_credential_completion(
            _context(),
            selection_key="connection-stale",
        )

    state = json.loads(_lifecycle_path(tmp_path).read_text(encoding="utf-8"))
    assert "credential" not in state["evidence"]


def test_phase_local_reuse_does_not_require_global_preflight_choice(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    record = snow.record_admin_phase(
        _context(),
        phase="plugin-prerequisites",
        status="reused",
    )

    assert record["status"] == "reused"
    assert "record-reuse-decision" not in snow.build_parser().format_help()


def test_admin_operation_records_only_non_secret_identity_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    app = snow.record_admin_phase(
        _context(),
        phase="entra-registration",
        status="completed",
        client_id=APP_CLIENT_ID,
    )
    mapping = snow.record_admin_phase(
        _context(),
        phase="servicenow-oidc",
        status="completed",
    )

    assert app["evidence"]["clientId"] == APP_CLIENT_ID
    assert mapping["evidence"]["oidcCapabilityConfirmed"] is True
    assert mapping["evidence"]["runbookCompleted"] is True
    assert mapping["evidence"]["mappingDetailsCollected"] is False
    assert "claim" not in mapping["evidence"]
    assert "userField" not in mapping["evidence"]
    serialized = _lifecycle_path(tmp_path).read_text(encoding="utf-8")
    assert "secret" not in serialized.casefold()
    assert "password" not in serialized.casefold()
    assert "token" not in serialized.casefold()


def test_v2_lifecycle_migrates_to_v6_without_obsolete_preflight_gates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    state_path = _lifecycle_path(tmp_path)
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "provider": snow.PROVIDER_KEY,
                "profile": "hrsd",
                "agentSlug": AGENT_SLUG,
                "agentId": AGENT_ID,
                "environmentId": ENVIRONMENT_ID,
                "attested": True,
                "phases": {
                    phase_id: {
                        "status": "done",
                        "actionApplied": True,
                        "checkpointResults": {"old": "Passed"},
                    }
                    for phase_id in (
                        "topics",
                        "credential",
                        "agent-connection",
                        "parameter-sharing",
                        "publish",
                        "test",
                    )
                },
                "evidence": {
                    "credential": {"connectionId": CONNECTION_ID},
                    "custom": {"mustSurvive": True},
                },
                "transactions": {
                    "topics": {"operation": {"status": "committed"}}
                },
                "migration": {},
            }
        ),
        encoding="utf-8",
    )

    state = snow._load_lifecycle_state(_context())
    snow._write_lifecycle_state(_context(), state)
    first_bytes = state_path.read_bytes()
    state_again = snow._load_lifecycle_state(_context())
    snow._write_lifecycle_state(_context(), state_again)

    assert state["schemaVersion"] == 6
    assert state["acceptedContractRevision"] == 1
    assert "reuseDecision" not in state["adminSetup"]["preflight"]
    assert set(state["adminSetup"]["phaseHandoffs"]) == {
        "preflight",
        "plugin-prerequisites",
        "entra-registration",
        "servicenow-oidc",
        "credential",
    }
    assert "operations" not in state["adminSetup"]
    assert state["phases"]["preflight"]["status"] == "in-progress"
    assert state["phases"]["credential"]["status"] == "in-progress"
    assert "actionApplied" not in state["phases"]["credential"]
    for phase_id in (
        "topics",
        "agent-connection",
        "publish",
        "test",
    ):
        assert state["phases"][phase_id]["status"] == "pending"
    assert "parameter-sharing" not in state["phases"]
    assert state["retiredPhases"]["parameter-sharing"]["status"] == "pending"
    assert state["evidence"]["custom"]["mustSurvive"] is True
    assert state["transactions"]["topics"]["operation"]["status"] == "committed"
    assert state["migration"]["schemaV3"]["reuseApprovalInferred"] is False
    assert state["migration"]["schemaV4"][
        "removedGlobalReuseDecision"
    ] is True
    assert state["migration"]["schemaV4"][
        "retainedCompletedPreflight"
    ] is False
    assert state["migration"]["schemaV5"]["removedScenarioGate"] is True
    assert first_bytes == state_path.read_bytes()


def test_v5_migration_retires_parameter_phase_without_fabricating_draft_test(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    components = _components(CONNECTION_ID)
    component_hash = snow._component_hash(components)
    state_path = _lifecycle_path(tmp_path)
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schemaVersion": 5,
                "provider": snow.PROVIDER_KEY,
                "profile": snow.PROFILE_KEY,
                "agentSlug": AGENT_SLUG,
                "agentId": AGENT_ID,
                "environmentId": ENVIRONMENT_ID,
                "phases": {
                    "parameter-sharing": {
                        "status": "done",
                        "checkpointResults": {
                            "SN-DA-HRSD-PARAMETER-SHARING-001": "Manual"
                        },
                    }
                },
                "evidence": {
                    "credential": {"connectionId": CONNECTION_ID},
                    "parameterSharing": {
                        "status": "not-exposed",
                        "makerAttested": True,
                    },
                    "publish": {
                        "status": "completed",
                        "componentHash": component_hash,
                        "publishedComponentHash": component_hash,
                    },
                    "test": {
                        "status": "completed",
                        "result": "pass",
                        "binding": {
                            "publishedComponentHash": component_hash,
                        },
                    },
                },
                "transactions": {"topics": {}},
                "migration": {},
            }
        ),
        encoding="utf-8",
    )

    migrated = snow._load_lifecycle_state(_context(), components)
    snow._write_lifecycle_state(_context(), migrated)
    first_bytes = state_path.read_bytes()
    migrated_again = snow._load_lifecycle_state(_context(), components)
    snow._write_lifecycle_state(_context(), migrated_again)

    assert "parameter-sharing" not in migrated["phases"]
    assert migrated["retiredPhases"]["parameter-sharing"]["status"] == "done"
    assert migrated["evidence"]["parameterSharing"]["status"] == "not-exposed"
    assert "draftSemanticHash" not in migrated["evidence"]["test"]["binding"]
    assert "testedDraftSemanticHash" not in migrated["evidence"]["publish"]
    assert first_bytes == state_path.read_bytes()


def test_v4_migration_removes_obsolete_gates_and_keeps_completed_discovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    state_path = _lifecycle_path(tmp_path)
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schemaVersion": 4,
                "provider": snow.PROVIDER_KEY,
                "profile": "hrsd",
                "agentSlug": AGENT_SLUG,
                "agentId": AGENT_ID,
                "environmentId": ENVIRONMENT_ID,
                "phases": {
                    "preflight": {
                        "status": "done",
                        "actionApplied": True,
                        "checkpointResults": {
                            "SN-DA-HRSD-ADMIN-PREFLIGHT-001": "Passed"
                        },
                    }
                },
                "adminSetup": {
                    "schemaVersion": 2,
                    "scope": "hrsd",
                    "authMode": snow.AUTH_MODE,
                    "preflight": {
                        "scenario": "connected",
                        "instanceName": "dev123",
                        "reuseDecision": {
                            "decision": "configure-missing",
                            "discoveryFingerprint": "old",
                        },
                        "discovery": {
                            "source": "connectivity-readonly",
                            "observedAt": "2026-09-29T00:00:00Z",
                            "requiredPlugins": [],
                            "connectionCandidates": [],
                            "fingerprint": "old",
                        },
                    },
                    "phaseHandoffs": {
                        "preflight": {
                            "status": "completed",
                            "evidence": {
                                "kind": "maker-reuse-decision",
                                "decision": "configure-missing",
                                "discoveryFingerprint": "old",
                            },
                        },
                        "servicenow-oidc": {
                            "status": "completed",
                            "evidence": {
                                "kind": "structured-admin-attestation",
                                "recordedAt": "2026-09-29T00:00:00Z",
                                "claim": "upn",
                                "userField": "user_name",
                            },
                        },
                    },
                },
                "evidence": {"mustSurvive": True},
                "transactions": {"topics": {"operation": {"status": "committed"}}},
                "migration": {},
            }
        ),
        encoding="utf-8",
    )

    state = snow._load_lifecycle_state(_context())

    assert state["schemaVersion"] == 6
    assert state["adminSetup"]["schemaVersion"] == 4
    assert "scenario" not in state["adminSetup"]["preflight"]
    assert "reuseDecision" not in state["adminSetup"]["preflight"]
    assert "fingerprint" not in state["adminSetup"]["preflight"]["discovery"]
    assert state["adminSetup"]["phaseHandoffs"]["preflight"]["status"] == (
        "completed"
    )
    evidence = state["adminSetup"]["phaseHandoffs"]["preflight"]["evidence"]
    assert evidence["kind"] == "read-only-resource-discovery"
    assert "decision" not in evidence
    assert "discoveryFingerprint" not in evidence
    assert state["phases"]["preflight"]["status"] == "done"
    assert state["evidence"]["mustSurvive"] is True
    assert state["transactions"]["topics"]["operation"]["status"] == "committed"
    assert state["migration"]["schemaV5"][
        "retainedCompletedPreflight"
    ] is True
    oidc_evidence = state["adminSetup"]["phaseHandoffs"][
        "servicenow-oidc"
    ]["evidence"]
    assert oidc_evidence["oidcCapabilityConfirmed"] is True
    assert oidc_evidence["runbookCompleted"] is True
    assert oidc_evidence["mappingDetailsCollected"] is False
    assert "claim" not in oidc_evidence
    assert "userField" not in oidc_evidence
    assert state["migration"]["schemaV5"][
        "inferredOidcCapabilityFromCompletedHandoff"
    ] is True


@pytest.mark.parametrize(
    "evidence_update",
    [
        {"kind": "unrelated"},
        {"kind": None},
        {"recordedAt": ""},
        {"recordedAt": None},
        {"claim": ""},
        {"userField": ""},
    ],
)
def test_v4_migration_does_not_infer_oidc_capability_from_invalid_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    evidence_update: dict,
) -> None:
    monkeypatch.chdir(tmp_path)
    state_path = _lifecycle_path(tmp_path)
    state_path.parent.mkdir(parents=True)
    evidence = {
        "kind": "structured-admin-attestation",
        "recordedAt": "2026-09-29T00:00:00Z",
        "claim": "upn",
        "userField": "user_name",
        **evidence_update,
    }
    state_path.write_text(
        json.dumps(
            {
                "schemaVersion": 4,
                "provider": snow.PROVIDER_KEY,
                "profile": "hrsd",
                "agentSlug": AGENT_SLUG,
                "agentId": AGENT_ID,
                "environmentId": ENVIRONMENT_ID,
                "phases": {},
                "adminSetup": {
                    "schemaVersion": 2,
                    "scope": "hrsd",
                    "authMode": snow.AUTH_MODE,
                    "preflight": {"discovery": {}},
                    "phaseHandoffs": {
                        "servicenow-oidc": {
                            "status": "completed",
                            "evidence": evidence,
                        }
                    },
                },
                "evidence": {},
                "transactions": {"topics": {}},
                "migration": {},
            }
        ),
        encoding="utf-8",
    )

    state = snow._load_lifecycle_state(_context())
    migrated = state["adminSetup"]["phaseHandoffs"]["servicenow-oidc"]

    assert migrated == {"status": "pending"}
    assert state["migration"]["retiredOidcMappingEvidence"][
        "qualifiedCompletion"
    ] is False
    assert state["migration"]["schemaV5"][
        "inferredOidcCapabilityFromCompletedHandoff"
    ] is False


def test_v4_migration_does_not_infer_oidc_capability_from_pending_handoff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    state_path = _lifecycle_path(tmp_path)
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schemaVersion": 4,
                "provider": snow.PROVIDER_KEY,
                "profile": "hrsd",
                "agentSlug": AGENT_SLUG,
                "agentId": AGENT_ID,
                "environmentId": ENVIRONMENT_ID,
                "phases": {},
                "adminSetup": {
                    "schemaVersion": 2,
                    "scope": "hrsd",
                    "authMode": snow.AUTH_MODE,
                    "preflight": {"discovery": {}},
                    "phaseHandoffs": {
                        "servicenow-oidc": {
                            "status": "pending",
                            "evidence": {
                                "kind": "structured-admin-attestation",
                                "recordedAt": "2026-09-29T00:00:00Z",
                                "claim": "upn",
                                "userField": "user_name",
                            },
                        }
                    },
                },
                "evidence": {},
                "transactions": {"topics": {}},
                "migration": {},
            }
        ),
        encoding="utf-8",
    )

    state = snow._load_lifecycle_state(_context())

    assert state["adminSetup"]["phaseHandoffs"]["servicenow-oidc"] == {
        "status": "pending"
    }


def test_v4_migration_removes_scenario_and_resets_incomplete_preflight_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    state_path = _lifecycle_path(tmp_path)
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schemaVersion": 4,
                "provider": snow.PROVIDER_KEY,
                "profile": "hrsd",
                "agentSlug": AGENT_SLUG,
                "agentId": AGENT_ID,
                "environmentId": ENVIRONMENT_ID,
                "phases": {
                    "preflight": {
                        "status": "done",
                        "actionApplied": True,
                        "lastActionAt": "2026-09-29T00:00:00Z",
                        "checkpointResults": {"old": "Passed"},
                    },
                    "plugin-prerequisites": {
                        "status": "done",
                        "checkpointResults": {"keep": "Manual"},
                    },
                },
                "adminSetup": {
                    "schemaVersion": 2,
                    "scope": "hrsd",
                    "authMode": snow.AUTH_MODE,
                    "preflight": {
                        "scenario": "connected",
                        "reuseDecision": {"decision": "reuse-discovered"},
                        "discovery": {},
                    },
                    "phaseHandoffs": {},
                },
                "evidence": {},
                "transactions": {"topics": {}},
                "migration": {},
            }
        ),
        encoding="utf-8",
    )

    state = snow._load_lifecycle_state(_context())

    assert state["phases"]["preflight"]["status"] == "in-progress"
    assert state["phases"]["preflight"]["checkpointResults"] == {}
    assert "actionApplied" not in state["phases"]["preflight"]
    assert "lastActionAt" not in state["phases"]["preflight"]
    assert state["phases"]["plugin-prerequisites"]["status"] == "done"
    assert "scenario" not in state["adminSetup"]["preflight"]
    assert state["migration"]["schemaV5"][
        "retainedCompletedPreflight"
    ] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider", "workday"),
        ("profile", "itsm"),
        ("agentSlug", "other-agent"),
        ("provider", None),
    ],
)
def test_v2_migration_rejects_canonical_identity_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    value: str | None,
) -> None:
    monkeypatch.chdir(tmp_path)
    state_path = _lifecycle_path(tmp_path)
    state_path.parent.mkdir(parents=True)
    state = {
        "schemaVersion": 2,
        "provider": snow.PROVIDER_KEY,
        "profile": "hrsd",
        "agentSlug": AGENT_SLUG,
        "agentId": AGENT_ID,
        "environmentId": ENVIRONMENT_ID,
        "phases": {},
        "evidence": {"mustSurvive": True},
        "transactions": {"topics": {}},
        "migration": {},
    }
    if value is None:
        state.pop(field)
    else:
        state[field] = value
    original = json.dumps(state)
    state_path.write_text(original, encoding="utf-8")

    with pytest.raises(snow.ServiceNowConnectError, match=field):
        snow._load_lifecycle_state(_context())

    assert state_path.read_text(encoding="utf-8") == original


def test_future_lifecycle_schema_fails_without_rewrite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    state_path = _lifecycle_path(tmp_path)
    state_path.parent.mkdir(parents=True)
    original = json.dumps(
        {
            "schemaVersion": snow.LIFECYCLE_SCHEMA_VERSION + 1,
            "provider": snow.PROVIDER_KEY,
            "agentSlug": AGENT_SLUG,
            "agentId": AGENT_ID,
            "environmentId": ENVIRONMENT_ID,
        }
    )
    state_path.write_text(original, encoding="utf-8")

    with pytest.raises(snow.ServiceNowConnectError, match="newer kit"):
        snow._load_lifecycle_state(_context())

    assert state_path.read_text(encoding="utf-8") == original


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
    assert result["connection"]["resourceUri"] == APP_CLIENT_ID
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
    assert not _lifecycle_path(tmp_path).exists()


def test_prepare_manual_connection_rejects_api_identifier_uri(
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

    with pytest.raises(snow.ServiceNowConnectError, match="not api://"):
        snow.prepare_manual_connection(
            _context(),
            instance_name="https://dev123.service-now.com",
            resource_uri=f"api://{APP_CLIENT_ID}",
            display_name=None,
        )


def test_record_test_attestation_persists_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    context = _context()
    components = _components(CONNECTION_ID)
    state_path = _lifecycle_path(tmp_path)
    state = _seed_passing_test(tmp_path, components)
    state["evidence"].pop("test")
    state_path.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: type(
            "FakeAgentBuilder",
            (),
            {"fetch_components": lambda self, _agent_id: components},
        )(),
    )

    result = snow.record_test_attestation(
        context,
        prompt_category="list-my-open-hr-cases",
        result="pass",
        failure_category=None,
    )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert result["result"] == "pass"
    assert result["status"] == "completed"
    assert state["evidence"]["test"]["promptCategory"] == (
        "list-my-open-hr-cases"
    )
    assert "prompt" not in state["evidence"]["test"]
    assert "details" not in state["evidence"]["test"]
    assert state["evidence"]["test"]["binding"]["draftSemanticHash"] == (
        snow._draft_semantic_hash(components)
    )
    assert state["evidence"]["test"]["binding"]["connectionBindingHash"]
    assert "publishedComponentHash" not in state["evidence"]["test"]["binding"]


def test_record_test_requires_current_agent_connection_attestation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _components(CONNECTION_ID)
    state = _seed_passing_test(tmp_path, components)
    state["evidence"].pop("test")
    state["evidence"].pop("agentConnection")
    _lifecycle_path(tmp_path).write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: type(
            "FakeAgentBuilder",
            (),
            {"fetch_components": lambda self, _agent_id: components},
        )(),
    )

    with pytest.raises(
        snow.ServiceNowConnectError,
        match="current Agent Connect observation",
    ):
        snow.record_test_attestation(
            _context(),
            prompt_category="list-my-open-hr-cases",
            result="pass",
            failure_category=None,
        )


def test_fresh_draft_test_bridges_trustworthy_existing_publish_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _components(CONNECTION_ID)
    component_hash = snow._component_hash(components)
    state = _seed_passing_test(
        tmp_path,
        components,
        publish={
            "kind": "maker-attestation",
            "status": "completed",
            "recordedAt": "2026-09-28T00:00:00Z",
            "completedAt": "2026-09-28T00:00:00Z",
            "componentHash": component_hash,
            "publishedComponentHash": component_hash,
        },
    )
    _lifecycle_path(tmp_path).write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    loaded = snow._load_lifecycle_state(_context(), components)
    receipt = loaded["evidence"]["publish"]

    assert receipt["testedDraftSemanticHash"] == loaded["draftSemanticHash"]
    assert receipt["publishedSemanticHash"] == loaded["draftSemanticHash"]
    assert receipt["connectionBindingHash"] == loaded["connectionBindingHash"]


@pytest.mark.parametrize(
    ("prompt_category", "result", "failure_category", "message"),
    [
        ("free-form-prompt", "pass", None, "privacy-safe"),
        (
            "list-my-open-hr-cases",
            "pass",
            "permission",
            "cannot have a failure category",
        ),
        (
            "list-my-open-hr-cases",
            "fail",
            None,
            "requires a bounded failure category",
        ),
    ],
)
def test_record_test_attestation_rejects_unbounded_or_inconsistent_evidence(
    prompt_category: str,
    result: str,
    failure_category: str | None,
    message: str,
) -> None:
    with pytest.raises(snow.ServiceNowConnectError, match=message):
        snow.record_test_attestation(
            _context(),
            prompt_category=prompt_category,
            result=result,
            failure_category=failure_category,
        )


def test_legacy_state_migration_is_idempotent_and_preserves_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    legacy_path = (
        tmp_path
        / ".local"
        / "connect"
        / "servicenow"
        / "agents"
        / AGENT_ID
        / "state.json"
    )
    legacy_path.parent.mkdir(parents=True)
    legacy = {
        "schemaVersion": 1,
        "agentId": AGENT_ID,
        "environmentId": ENVIRONMENT_ID,
        "topicEnablement": {
            "customerChoice": "keep-current",
            "before": {"total": 1, "active": 0, "inactive": 1},
        },
        "test": {
            "prompt": "Show my HR cases",
            "result": "pass",
        },
    }
    legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
    components = _components()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: type(
            "FakeAgentBuilder",
            (),
            {"fetch_components": lambda self, _agent_id: components},
        )(),
    )

    first = snow.migrate_state(_context())
    first_bytes = _lifecycle_path(tmp_path).read_bytes()
    second = snow.migrate_state(_context())
    second_bytes = _lifecycle_path(tmp_path).read_bytes()
    state = json.loads(first_bytes)

    assert first["status"] == "migrated"
    assert second["migration"]["legacySha256"] == first["migration"][
        "legacySha256"
    ]
    assert first_bytes == second_bytes
    assert json.loads(legacy_path.read_text(encoding="utf-8")) == legacy
    assert (
        state["evidence"]["topics"]["customerChoice"]
        == "keep-current"
    )
    assert state["evidence"]["test"]["reconfirmRequired"] is True


def test_first_run_initialize_then_migrate_and_inspect_offline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    components = _components(CONNECTION_ID)
    _write_foundation_context(tmp_path, components=components)
    contract = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
    contract_path = tmp_path / snow.CONTRACT_PATH
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert snow.main(
        [
            "initialize-state",
            "--contract-revision",
            str(contract["contractRevision"]),
        ]
    ) == 0
    initialized = json.loads(capsys.readouterr().out)
    state_path = _lifecycle_path(tmp_path)
    state = json.loads(state_path.read_text(encoding="utf-8"))

    assert initialized["status"] == "initialized"
    assert state["schemaVersion"] == snow.LIFECYCLE_SCHEMA_VERSION
    assert state["provider"] == snow.PROVIDER_KEY
    assert state["profile"] == snow.PROFILE_KEY
    assert state["agentSlug"] == AGENT_SLUG
    assert state["agentId"] == AGENT_ID
    assert state["environmentId"] == ENVIRONMENT_ID
    assert state["attested"] is True
    assert state["acceptedContractRevision"] == contract["contractRevision"]
    expected_phase_ids = [
        phase["id"] for phase in contract["phases"]
    ]
    assert initialized["phaseIds"] == expected_phase_ids
    assert set(state["phases"]) == set(expected_phase_ids)
    assert all(
        phase == {
            "status": "pending",
            "checkpointResults": {},
            "checkpointAcknowledgements": {},
        }
        for phase in state["phases"].values()
    )

    assert snow.main(["migrate-state"]) == 0
    migrated = json.loads(capsys.readouterr().out)
    assert migrated["status"] == "migrated"

    assert snow.main(["inspect", "--offline"]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["mode"] == "offline"
    assert inspected["agentId"] == AGENT_ID
    assert inspected["components"]["serviceNowTopicCount"] == 1


def test_initialize_state_never_replaces_existing_malformed_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_foundation_context(
        tmp_path,
        components=_components(CONNECTION_ID),
    )
    contract = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
    contract_path = tmp_path / snow.CONTRACT_PATH
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    state_path = _lifecycle_path(tmp_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    malformed = {
        "provider": snow.PROVIDER_KEY,
        "agentSlug": AGENT_SLUG,
    }
    state_path.write_text(json.dumps(malformed), encoding="utf-8")
    before = state_path.read_bytes()
    monkeypatch.chdir(tmp_path)

    assert snow.main(
        [
            "initialize-state",
            "--contract-revision",
            str(contract["contractRevision"]),
        ]
    ) == 1
    error = json.loads(capsys.readouterr().out)

    assert error["status"] == "error"
    assert "already exists" in error["message"]
    assert state_path.read_bytes() == before


def test_initialize_state_preserves_file_created_during_atomic_publish(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_foundation_context(
        tmp_path,
        components=_components(CONNECTION_ID),
    )
    contract = json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))
    contract_path = tmp_path / snow.CONTRACT_PATH
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    state_path = _lifecycle_path(tmp_path)
    sentinel = b'{"sentinel":"concurrent-state"}\n'
    original_link = snow.os.link

    def create_concurrent_state_then_link(
        source: str | bytes | Path,
        destination: str | bytes | Path,
        *args,
        **kwargs,
    ) -> None:
        Path(destination).write_bytes(sentinel)
        original_link(source, destination, *args, **kwargs)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow.os,
        "link",
        create_concurrent_state_then_link,
    )

    assert snow.main(
        [
            "initialize-state",
            "--contract-revision",
            str(contract["contractRevision"]),
        ]
    ) == 1
    error = json.loads(capsys.readouterr().out)

    assert error["status"] == "error"
    assert "appeared during initialization" in error["message"]
    assert state_path.read_bytes() == sentinel


def test_migrate_state_cli_returns_nonzero_for_malformed_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_foundation_context(tmp_path)
    state_path = _lifecycle_path(tmp_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "provider": snow.PROVIDER_KEY,
                "profile": snow.PROFILE_KEY,
                "agentSlug": AGENT_SLUG,
                "agentId": AGENT_ID,
                "environmentId": ENVIRONMENT_ID,
            }
        ),
        encoding="utf-8",
    )
    before = state_path.read_bytes()
    monkeypatch.chdir(tmp_path)

    assert snow.main(["migrate-state"]) == 1
    error = json.loads(capsys.readouterr().out)

    assert error == {
        "status": "error",
        "message": "ServiceNow lifecycle schemaVersion must be an integer.",
    }
    assert state_path.read_bytes() == before


def test_migrate_state_process_exits_nonzero_for_malformed_state(
    tmp_path: Path,
) -> None:
    _write_foundation_context(tmp_path)
    state_path = _lifecycle_path(tmp_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "provider": snow.PROVIDER_KEY,
                "profile": snow.PROFILE_KEY,
                "agentSlug": AGENT_SLUG,
                "agentId": AGENT_ID,
                "environmentId": ENVIRONMENT_ID,
            }
        ),
        encoding="utf-8",
    )
    before = state_path.read_bytes()

    completed = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), "migrate-state"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    error = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert completed.stderr == ""
    assert error == {
        "status": "error",
        "message": "ServiceNow lifecycle schemaVersion must be an integer.",
    }
    assert state_path.read_bytes() == before


def test_enable_all_topics_rolls_back_ambiguous_partial_mutation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _components()
    topic = components["botComponentChanges"][0]["component"]
    topic["state"] = "Inactive"
    topic["status"] = "Inactive"
    updates: list[dict] = []

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            return json.loads(json.dumps(components))

        def update_components(self, _agent_id: str, payload: dict) -> dict:
            updates.append(json.loads(json.dumps(payload)))
            update = payload["botComponentChanges"][0]["component"]
            topic.update(update)
            topic["version"] = int(topic["version"]) + 1
            components["changeToken"] = f"token-{len(updates) + 1}"
            if len(updates) == 1:
                raise RuntimeError("ambiguous network failure")
            return {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )

    with pytest.raises(
        snow.ServiceNowConnectError,
        match="rolled back safely",
    ):
        snow.enable_all_servicenow_topics(_context(), confirmed=True)

    assert len(updates) == 2
    assert topic["state"] == "Inactive"
    assert topic["status"] == "Inactive"
    state = json.loads(_lifecycle_path(tmp_path).read_text(encoding="utf-8"))
    transaction = next(iter(state["transactions"]["topics"].values()))
    assert transaction["status"] == "rolled-back"
    assert list(transaction["topics"].values()) == ["restored"]


def test_enable_all_topics_accepts_server_managed_audit_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _components()
    topic = components["botComponentChanges"][0]["component"]
    topic["state"] = "Inactive"
    topic["status"] = "Inactive"
    topic["auditInfo"] = {
        "modifiedAt": "2026-09-28T00:00:00Z",
        "modifiedBy": "before",
    }

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            return json.loads(json.dumps(components))

        def update_components(self, _agent_id: str, payload: dict) -> dict:
            updated = payload["botComponentChanges"][0]["component"]
            topic.update(updated)
            topic["version"] = int(topic["version"]) + 1
            topic["auditInfo"] = {
                "modifiedAt": "2026-09-28T00:01:00Z",
                "modifiedBy": "platform",
            }
            components["changeToken"] = "token-2"
            return {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )

    result = snow.enable_all_servicenow_topics(
        _context(),
        confirmed=True,
    )

    assert result["transactionStatus"] == "committed"
    assert result["after"] == {"total": 1, "active": 1, "inactive": 0}
    state = json.loads(_lifecycle_path(tmp_path).read_text(encoding="utf-8"))
    transaction = next(iter(state["transactions"]["topics"].values()))
    target = transaction["targets"][topic["id"]]
    assert target["ownershipStatus"] == "owned"
    assert target["changedByOperation"] is True


def test_topic_rollback_does_not_overwrite_concurrent_external_edit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _components()
    first = components["botComponentChanges"][0]["component"]
    first["state"] = "Inactive"
    first["status"] = "Inactive"
    second = copy.deepcopy(first)
    second["id"] = "00000000-0000-4000-8000-000000006666"
    second["displayName"] = "ServiceNow HRSD Get Cases"
    second["schemaName"] = (
        f"{snow.HR_SCHEMA_NAME}.topic.ServiceNowHRSDGetCases"
    )
    components["botComponentChanges"].append(
        {"$kind": "BotComponentInsert", "component": second}
    )
    updates: list[dict] = []

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            return json.loads(json.dumps(components))

        def update_components(self, _agent_id: str, payload: dict) -> dict:
            updates.append(json.loads(json.dumps(payload)))
            first_update = payload["botComponentChanges"][0]["component"]
            first.update(first_update)
            first["version"] = int(first["version"]) + 1
            first["externalConcurrentEdit"] = "must-survive"
            components["changeToken"] = "token-2"
            raise RuntimeError("ambiguous partial update")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )

    historical_operation_id = "00000000-0000-4000-8000-000000000001"
    initial_state = snow._state_base(_context(), components)
    initial_state["transactions"]["topics"][historical_operation_id] = {
        "operationId": historical_operation_id,
        "status": "rollback-incomplete",
    }
    state_path = _lifecycle_path(tmp_path)
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps(initial_state), encoding="utf-8")

    with pytest.raises(
        snow.ServiceNowConnectError,
        match="rollback is incomplete",
    ) as raised:
        snow.enable_all_servicenow_topics(_context(), confirmed=True)

    assert len(updates) == 1
    assert first["externalConcurrentEdit"] == "must-survive"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    current_operation_id = raised.value.details["operationId"]
    assert current_operation_id != historical_operation_id
    transaction = state["transactions"]["topics"][current_operation_id]
    assert transaction["status"] == "rollback-incomplete"
    assert transaction["topics"][first["id"]] == "conflict"
    assert raised.value.details["transactionStatus"] == "rollback-incomplete"
    assert raised.value.details["before"] == {
        "total": 2,
        "active": 0,
        "inactive": 2,
    }
    target = next(
        item
        for item in raised.value.details["targets"]
        if item["topicId"] == first["id"]
    )
    assert target["ownershipStatus"] == "conflict"
    assert target["rollbackStatus"] == "conflict"
    assert "component" not in json.dumps(raised.value.details)


def test_topic_rollback_treats_ambiguous_applied_restore_as_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _components()
    topic = components["botComponentChanges"][0]["component"]
    preimage = copy.deepcopy(topic)
    preimage["state"] = "Inactive"
    preimage["status"] = "Inactive"
    topic["state"] = "Active"
    topic["status"] = "Active"
    operation_id = "00000000-0000-4000-8000-000000007777"
    state_path = _lifecycle_path(tmp_path)
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "provider": snow.PROVIDER_KEY,
                "profile": "hrsd",
                "agentSlug": AGENT_SLUG,
                "agentId": AGENT_ID,
                "environmentId": ENVIRONMENT_ID,
                "phases": {},
                "evidence": {},
                "transactions": {
                    "topics": {
                        operation_id: {
                            "operationId": operation_id,
                            "status": "rollback-required",
                            "targets": {
                                topic["id"]: {
                                    "component": preimage,
                                    "changedByOperation": True,
                                    "ownershipStatus": "owned",
                                    "beforeContentHashExcludingVersion": (
                                        snow._component_content_hash(preimage)
                                    ),
                                    "expectedPostContentHashExcludingVersion": (
                                        snow._component_content_hash(topic)
                                    ),
                                }
                            },
                        }
                    }
                },
                "migration": {},
            }
        ),
        encoding="utf-8",
    )

    class FakeAgentBuilder:
        calls = 0

        def fetch_components(self, _agent_id: str) -> dict:
            return json.loads(json.dumps(components))

        def update_components(self, _agent_id: str, payload: dict) -> dict:
            self.calls += 1
            restored = payload["botComponentChanges"][0]["component"]
            topic.update(restored)
            topic["version"] = int(topic["version"]) + 1
            components["changeToken"] = f"token-{self.calls + 1}"
            if self.calls == 1:
                raise RuntimeError("ambiguous rollback response")
            return {}

    client = FakeAgentBuilder()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: client,
    )

    first = snow.rollback_topic_transaction(
        _context(),
        operation_id,
        confirmed=True,
    )
    second = snow.rollback_topic_transaction(
        _context(),
        operation_id,
        confirmed=True,
    )

    assert first["status"] == "rolled-back"
    assert second["status"] == "rolled-back"
    assert client.calls == 1
    assert topic["state"] == "Inactive"
    assert topic["status"] == "Inactive"


def test_failed_post_update_refetch_does_not_claim_rollback_ownership(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _components()
    topic = components["botComponentChanges"][0]["component"]
    topic["state"] = "Inactive"
    topic["status"] = "Inactive"
    fail_refetch = False
    update_calls = 0

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            nonlocal fail_refetch
            if fail_refetch:
                fail_refetch = False
                raise RuntimeError("post-update fetch failed")
            return json.loads(json.dumps(components))

        def update_components(self, _agent_id: str, payload: dict) -> dict:
            nonlocal fail_refetch, update_calls
            update_calls += 1
            update = payload["botComponentChanges"][0]["component"]
            topic.update(update)
            topic["version"] = int(topic["version"]) + 1
            components["changeToken"] = "token-2"
            fail_refetch = True
            return {}

    client = FakeAgentBuilder()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: client,
    )

    with pytest.raises(
        snow.ServiceNowConnectError,
        match="post-update refetch failed",
    ):
        snow.enable_all_servicenow_topics(_context(), confirmed=True)

    state = json.loads(_lifecycle_path(tmp_path).read_text(encoding="utf-8"))
    operation_id, transaction = next(
        iter(state["transactions"]["topics"].items())
    )
    assert transaction["status"] == "reconciliation-required"
    target = transaction["targets"][topic["id"]]
    assert "ownershipStatus" not in target

    topic["externalConcurrentEdit"] = "must-survive"
    result = snow.rollback_topic_transaction(
        _context(),
        operation_id,
        confirmed=True,
    )

    assert result["status"] == "rollback-incomplete"
    assert result["topics"][topic["id"]] == "conflict"
    assert topic["externalConcurrentEdit"] == "must-survive"
    assert update_calls == 1


def test_enable_all_topics_rejects_missing_transaction_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    components = _components()
    first = components["botComponentChanges"][0]["component"]
    first["state"] = "Inactive"
    first["status"] = "Inactive"
    second = copy.deepcopy(first)
    second["id"] = "00000000-0000-4000-8000-000000006666"
    second["displayName"] = "ServiceNow HRSD Get Cases"
    second["schemaName"] = (
        f"{snow.HR_SCHEMA_NAME}.topic.ServiceNowHRSDGetCases"
    )
    components["botComponentChanges"].append(
        {"$kind": "BotComponentInsert", "component": second}
    )

    class FakeAgentBuilder:
        def fetch_components(self, _agent_id: str) -> dict:
            return json.loads(json.dumps(components))

        def update_components(self, _agent_id: str, payload: dict) -> dict:
            second.update(payload["botComponentChanges"][1]["component"])
            second["version"] = int(second["version"]) + 1
            components["botComponentChanges"] = [
                change
                for change in components["botComponentChanges"]
                if change["component"].get("id") != first["id"]
            ]
            components["changeToken"] = "token-2"
            return {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        snow,
        "_agentbuilder_client",
        lambda _context: FakeAgentBuilder(),
    )

    with pytest.raises(
        snow.ServiceNowConnectError,
        match="rollback is incomplete",
    ) as raised:
        snow.enable_all_servicenow_topics(_context(), confirmed=True)

    state = json.loads(_lifecycle_path(tmp_path).read_text(encoding="utf-8"))
    operation_id = raised.value.details["operationId"]
    transaction = state["transactions"]["topics"][operation_id]
    assert transaction["status"] == "rollback-incomplete"
    assert transaction["topics"][first["id"]] == "missing"
    assert transaction["status"] != "committed"
    target = next(
        item
        for item in raised.value.details["targets"]
        if item["topicId"] == first["id"]
    )
    assert target["ownershipStatus"] == "missing"
    assert target["rollbackStatus"] == "missing"


def test_main_serializes_current_topic_transaction_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operation_id = "00000000-0000-4000-8000-000000009999"
    monkeypatch.setattr(snow, "load_context", lambda: _context())
    monkeypatch.setattr(
        snow,
        "enable_all_servicenow_topics",
        lambda _context, *, confirmed: (_ for _ in ()).throw(
            snow.ServiceNowConnectError(
                "topic update failed",
                details={
                    "operationId": operation_id,
                    "transactionStatus": "rollback-incomplete",
                    "targets": [],
                },
            )
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["connect_servicenow_da.py", "enable-all-topics", "--yes"],
    )

    assert snow.main() == 1
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "status": "error",
        "message": "topic update failed",
        "details": {
            "operationId": operation_id,
            "transactionStatus": "rollback-incomplete",
            "targets": [],
        },
    }
