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
                    "schemaName": (
                        f"{snow.HR_SCHEMA_NAME}.topic."
                        "ServiceNowHRSDSystemCommonOrchestrator"
                    ),
                    "state": "Active",
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
    assert result["serviceNowInvokeConnectorActionCount"] == 1
    assert result["serviceNowInvokeFlowActionCount"] == 0
    assert result["invokeFlowActionCount"] == 1
    assert result["cloudFlowDefinitionCount"] == 0
    assert result["reference"]["instanceName"] == "dev123"
    assert result["reference"]["resourceUri"] == "resource-id"


def test_reference_update_is_minimal_and_preserves_reference_metadata() -> None:
    components = _components()

    payload = snow.build_reference_update_payload(
        components,
        CONNECTION_ID,
    )

    assert set(payload) == {"changeToken", "connectionReferenceChanges"}
    assert payload["changeToken"] == "token"
    change = payload["connectionReferenceChanges"][0]
    assert change["$kind"] == "ConnectionReferenceUpdate"
    assert change["connectionReference"]["connectionId"] == (
        CONNECTION_ID.replace("-", "")
    )
    assert change["connectionReference"]["version"] == 4
    assert (
        components["connectionReferenceChanges"][0]["connectionReference"][
            "connectionId"
        ]
        is None
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


def test_load_context_requires_matching_schema_v3_hr_agent(
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
                "schema_version": 3,
                "intent": "DA foundation setup",
                "connect_ready": True,
                "environment": {
                    "id": ENVIRONMENT_ID,
                    "tenant_id": "00000000-0000-4000-8000-000000009999",
                    "ring": "test",
                    "api_version": "2024-10-01",
                    "power_platform_api_endpoint": (
                        "https://example.environment.api.test.powerplatform.com"
                    ),
                },
                "agent": {
                    "id": AGENT_ID,
                    "schema_name": snow.HR_SCHEMA_NAME,
                    "realm": "dev",
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


def test_bind_requires_confirmation() -> None:
    with pytest.raises(snow.ServiceNowConnectError, match="confirmation"):
        snow.bind_reference({}, CONNECTION_ID, confirmed=False)


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
