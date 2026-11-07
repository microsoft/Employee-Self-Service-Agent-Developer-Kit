# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Contracts for selected-agent topic YAML authoring."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import minimalbot_evaluation as native
import topic_authoring as authoring


@pytest.fixture
def topic_cli(monkeypatch, tmp_path, fake_tenant_id):
    agent_folder = tmp_path / "workspace" / "agents" / "selected"
    topics = agent_folder / "topics"
    baseline = agent_folder / ".baseline" / "topics"
    topics.mkdir(parents=True)
    baseline.mkdir(parents=True)
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(
        json.dumps({"agent": {"folder": str(agent_folder)}}),
        encoding="utf-8",
    )
    (agent_folder / ".component-map.json").write_text("{}\n", encoding="utf-8")

    target = {
        "environment": {
            "id": "00000000-0000-0000-0000-000000005555",
            "tenantId": fake_tenant_id,
            "ring": "test",
            "powerPlatformApiEndpoint": "https://api.test.example",
        },
        "agent": {
            "id": "00000000-0000-0000-0000-000000004444",
            "schemaName": "contoso_agent",
            "realm": "dev",
        },
    }
    components: list[dict] = []
    client = SimpleNamespace(
        host=target["environment"]["powerPlatformApiEndpoint"],
        headers={"Authorization": "Bearer test-token"},
        session=object(),
        fetch_components=lambda _agent: {
            "botComponentChanges": [
                {"component": copy.deepcopy(component)} for component in components
            ]
        },
    )
    transport = Mock()
    transport.create_dialog_component.side_effect = lambda component: {
        "component": copy.deepcopy(component),
        "createdComponents": 1,
        "verifiedComponents": 1,
    }
    def update_components(updates, **_kwargs):
        return {
            "updatedComponents": len(updates),
            "verifiedComponents": len(updates),
            "verified": True,
            "writeAttempted": True,
            "blockingDiagnostics": [],
            "components": [
                {
                    **copy.deepcopy(next(
                        component for component in components
                        if component["id"] == update["componentId"]
                    )),
                    "dialog": copy.deepcopy(update["dialog"]),
                }
                for update in updates
            ],
        }

    transport.update_dialog_components.side_effect = update_components
    connect = Mock(return_value=(client, target))
    monkeypatch.setattr(authoring, "connect_selected_dev_workspace", connect)
    monkeypatch.setattr(
        authoring,
        "MinimalBotEvaluationClient",
        Mock(return_value=transport),
    )
    monkeypatch.setattr(
        authoring,
        "yaml_to_object_models",
        lambda items: [
            {
                "key": item["key"],
                "success": True,
                "elementType": "AdaptiveDialog",
                "objectModel": json.loads(item["yaml"]),
            }
            for item in items
        ],
    )
    monkeypatch.setattr(
        authoring,
        "object_models_to_yaml",
        lambda items: [
            {
                "key": item["key"],
                "success": True,
                "elementType": "AdaptiveDialog",
                "yaml": json.dumps(item["objectModel"]),
            }
            for item in items
        ],
    )
    monkeypatch.chdir(tmp_path)
    dialog = {
        "$kind": "AdaptiveDialog",
        "modelDescription": "Explain the approved answer.",
        "unknown": {"preserve": True},
        "beginDialog": {
            "$kind": "OnRecognizedIntent",
            "id": "existing-trigger",
            "intent": {"$kind": "Intent", "triggerQueries": ["approved answer"]},
            "actions": [
                {
                    "$kind": "SendActivity",
                    "id": "existing-send",
                    "activity": {
                        "$kind": "Message",
                        "text": [
                            {
                                "$kind": "TemplateLine",
                                "segments": [
                                    {"$kind": "TextSegment", "value": "Approved."},
                                    {
                                        "$kind": "ExpressionSegment",
                                        "expression": "System.User.DisplayName",
                                    },
                                ],
                            }
                        ],
                    },
                }
            ],
        },
    }
    draft = topics / "CaseSensitiveName.mcs.yml"
    draft.write_text(json.dumps(dialog), encoding="utf-8")
    return SimpleNamespace(
        root=tmp_path,
        agent_folder=agent_folder,
        draft=draft,
        dialog=dialog,
        target=target,
        client=client,
        transport=transport,
        connect=connect,
        components=components,
    )


def _map(topic_cli):
    return json.loads(
        (topic_cli.agent_folder / ".component-map.json").read_text(encoding="utf-8")
    )


def _register_existing(topic_cli):
    component = {
        "$kind": "DialogComponent",
        "id": "00000000-0000-0000-0000-000000003333",
        "schemaName": "contoso_agent.topic.CaseSensitiveName",
        "displayName": "Approved answer",
        "parentBotId": topic_cli.target["agent"]["id"],
        "state": "Active",
        "status": "Active",
        "dialog": copy.deepcopy(topic_cli.dialog),
        "extensionData": {"unknown": "preserve"},
    }
    topic_cli.components.append(component)
    mapping = {
        "topics/CaseSensitiveName.mcs.yml": {
            "componentKind": "DialogComponent",
            "componentId": component["id"],
            "schemaName": component["schemaName"],
            "displayName": component["displayName"],
            "version": 7,
        }
    }
    (topic_cli.agent_folder / ".component-map.json").write_text(
        json.dumps(mapping),
        encoding="utf-8",
    )
    (topic_cli.agent_folder / ".baseline" / "topics" / topic_cli.draft.name).write_text(
        json.dumps(topic_cli.dialog),
        encoding="utf-8",
    )
    return component


@pytest.mark.parametrize("status", [403, 409, 412, 503])
def test_scoped_update_returns_service_evidence_without_conflict_replay(
    topic_cli, monkeypatch, status,
):
    component = _register_existing(topic_cli)
    component["managedProperties"] = {"isManaged": True, "isCustomizable": False}
    client = native.MinimalBotEvaluationClient(
        topic_cli.target["environment"]["id"], topic_cli.target["agent"]["id"],
        topic_cli.target["environment"]["tenantId"],
    )
    read = Mock(return_value={
        "changeToken": "fresh-token", "botComponentChanges": [{"component": component}],
    })
    body = {
        "error": {"code": "service-permission-or-conflict", "unfamiliar": {"keep": True}},
        "access_token": "must-not-emit",
    }
    request = Mock(return_value=(
        SimpleNamespace(status_code=status, headers={"x-ms-request-id": "write-id"}), body,
    ))
    monkeypatch.setattr(client, "read_components", read)
    monkeypatch.setattr(client, "_request", request)
    desired = {**component["dialog"], "modelDescription": "Explicit approved edit"}

    with pytest.raises(native.ComponentEditError) as error:
        client.update_dialog_components([{
            "componentId": component["id"], "schemaName": component["schemaName"],
            "expectedDialog": component["dialog"], "dialog": desired,
        }], _retry_on_conflict=False)

    assert error.value.evidence["httpStatus"] == status
    assert error.value.evidence["requestId"] == "write-id"
    assert error.value.evidence["response"]["error"] == body["error"]
    assert "must-not-emit" not in json.dumps(error.value.evidence)
    request.assert_called_once()
    read.assert_called_once()


def test_accepted_create_readback_failure_preserves_cause_and_never_recreates(
    topic_cli, monkeypatch,
):
    component = _register_existing(topic_cli)
    component["state"] = component["status"] = "Inactive"
    client = native.MinimalBotEvaluationClient(
        topic_cli.target["environment"]["id"], topic_cli.target["agent"]["id"],
        topic_cli.target["environment"]["tenantId"],
    )
    cause = RuntimeError("Unexpected readback failure")
    client.read_components = Mock(side_effect=[{
        "bot": {"cdsBotId": client.bot_id,
                "schemaName": topic_cli.target["agent"]["schemaName"]},
        "changeToken": "fresh-token", "botComponentChanges": [],
    }, cause])
    request = Mock(return_value=(
        SimpleNamespace(status_code=200), {"unknownCreateEvidence": ["preserved"]},
    ))
    monkeypatch.setattr(client, "_request", request)

    with pytest.raises(native.ComponentEditError) as error:
        client.create_dialog_component(component)

    assert error.value.evidence["writeAccepted"] is True
    assert error.value.evidence["verified"] is False
    assert error.value.evidence["response"] == {"unknownCreateEvidence": ["preserved"]}
    assert error.value.__cause__ is cause
    request.assert_called_once()


def test_session_component_writes_reuse_selected_transport_without_status_retry(
    topic_cli,
):
    from agentbuilder import AgentBuilderClient
    import responses

    builder = AgentBuilderClient(
        native._environment_host(topic_cli.target["environment"]["id"], "test"),
        "offline-token",
        ring="test", tenant_id=topic_cli.target["environment"]["tenantId"],
    )
    client = native.MinimalBotEvaluationClient(
        topic_cli.target["environment"]["id"], topic_cli.target["agent"]["id"],
        topic_cli.target["environment"]["tenantId"],
        host=builder.host, access_token="offline-token", session=builder.session,
    )
    assert client._session is builder.session
    with responses.RequestsMock() as recorded:
        recorded.post(client._components_url, json={}, status=503)
        recorded.put(client._components_url, json={"serviceHint": "inspect"}, status=503)
        response, _ = client._request("POST", client._components_url, body={})
        assert response.status_code == 503
        response, body = client._request("PUT", client._components_url, body={})
        assert response.status_code == 503 and body == {"serviceHint": "inspect"}
        assert [call.request.method for call in recorded.calls] == ["POST", "PUT"]


def test_create_uses_exact_filename_schema_and_registers_verified_identity(topic_cli):
    assert authoring.main(
        [
            "create",
            "--draft",
            str(topic_cli.draft),
            "--display-name",
            "Approved answer",
            "--yes",
        ]
    ) == 0

    component = topic_cli.transport.create_dialog_component.call_args.args[0]
    assert component["schemaName"] == "contoso_agent.topic.CaseSensitiveName"
    assert component["state"] == component["status"] == "Inactive"
    assert component["extensionData"] == {"UseProvidedBotComponentId": True}
    assert component["dialog"] == topic_cli.dialog
    entry = _map(topic_cli)["topics/CaseSensitiveName.mcs.yml"]
    assert entry["componentId"] == component["id"]
    assert entry["schemaName"] == component["schemaName"]
    assert (
        topic_cli.agent_folder
        / ".baseline"
        / "topics"
        / "CaseSensitiveName.mcs.yml"
    ).read_text(encoding="utf-8") == json.dumps(topic_cli.dialog)
    topic_cli.connect.assert_called_with(topic_cli.root.resolve(), None)


def test_create_reports_same_name_as_advisory_and_still_sends(topic_cli, capsys):
    topic_cli.components.append(
        {
            "$kind": "DialogComponent",
            "id": "existing",
            "schemaName": "contoso_agent.topic.Other",
            "displayName": " APPROVED ANSWER ",
        }
    )

    authoring.main(
        [
            "create",
            "--draft",
            str(topic_cli.draft),
            "--display-name",
            "Approved answer",
            "--yes",
        ]
    )

    result = json.loads(capsys.readouterr().out)
    assert result["advisories"] == [
        {
            "kind": "same-name",
            "componentId": "existing",
            "schemaName": "contoso_agent.topic.Other",
            "displayName": " APPROVED ANSWER ",
        }
    ]
    topic_cli.transport.create_dialog_component.assert_called_once()


def test_read_uses_component_map_identity_and_can_project_yaml(topic_cli):
    component = _register_existing(topic_cli)
    projection = topic_cli.root / "projection.mcs.yml"

    authoring.main(
        [
            "read",
            "--topic",
            str(topic_cli.draft),
            "--yaml-output",
            str(projection),
        ]
    )

    assert json.loads(projection.read_text(encoding="utf-8")) == component["dialog"]


def test_update_sends_captured_yaml_with_fresh_read_baseline(topic_cli):
    component = _register_existing(topic_cli)
    before = topic_cli.root / "before.json"
    authoring.main(
        ["read", "--topic", str(topic_cli.draft), "--output", str(before)]
    )
    desired = copy.deepcopy(topic_cli.dialog)
    desired["beginDialog"]["actions"][0]["activity"]["text"][0]["segments"][0][
        "value"
    ] = "Updated."
    topic_cli.draft.write_text(json.dumps(desired), encoding="utf-8")

    authoring.main(
        [
            "update",
            "--draft",
            str(topic_cli.draft),
            "--expected",
            str(before),
            "--yes",
        ]
    )

    topic_cli.transport.update_dialog_components.assert_called_once_with(
        [
            {
                "componentId": component["id"],
                "schemaName": component["schemaName"],
                "expectedDialog": component["dialog"],
                "dialog": desired,
                "requireCleanDiagnostics": True,
            }
        ],
        _retry_on_conflict=False,
    )
    acknowledged = (
        topic_cli.agent_folder
        / ".baseline"
        / "topics"
        / topic_cli.draft.name
    )
    assert json.loads(acknowledged.read_text(encoding="utf-8")) == desired


def test_update_acknowledges_capture_not_later_disk_edit(topic_cli):
    component = _register_existing(topic_cli)
    before = topic_cli.root / "before.json"
    authoring.main(
        ["read", "--topic", str(topic_cli.draft), "--output", str(before)]
    )
    submitted = {**topic_cli.dialog, "modelDescription": "Submitted description"}
    later = {**topic_cli.dialog, "modelDescription": "Later disk edit"}
    topic_cli.draft.write_text(json.dumps(submitted), encoding="utf-8")

    def update(*_args, **_kwargs):
        topic_cli.draft.write_text(json.dumps(later), encoding="utf-8")
        return {
            "updatedComponents": 1,
            "verifiedComponents": 1,
            "blockingDiagnostics": [],
            "components": [{**component, "dialog": submitted}],
        }

    topic_cli.transport.update_dialog_components.side_effect = update
    authoring.main(
        [
            "update",
            "--draft",
            str(topic_cli.draft),
            "--expected",
            str(before),
            "--yes",
        ]
    )

    acknowledged = (
        topic_cli.agent_folder
        / ".baseline"
        / "topics"
        / topic_cli.draft.name
    )
    assert json.loads(acknowledged.read_text(encoding="utf-8")) == submitted
    assert json.loads(topic_cli.draft.read_text(encoding="utf-8")) == later


@pytest.mark.parametrize("operation", ["update", "workspace"])
@pytest.mark.parametrize("later_edit", [False, True])
def test_merged_save_acknowledges_readback_and_preserves_later_draft(
    topic_cli, monkeypatch, capsys, operation, later_edit,
):
    topic_cli.dialog["beginDialog"]["actions"].append({
        "$kind": "SendActivity", "id": "unrelated-action", "activity": "Helpful note.",
    })
    topic_cli.draft.write_text(json.dumps(topic_cli.dialog), encoding="utf-8")
    component = _register_existing(topic_cli)
    before = topic_cli.root / "before.json"
    authoring.main(["read", "--topic", str(topic_cli.draft), "--output", str(before)])
    capsys.readouterr()

    desired = copy.deepcopy(component["dialog"])
    desired["modelDescription"] = "Approved description."
    submitted = json.dumps(desired)
    topic_cli.draft.write_text(submitted, encoding="utf-8")
    remote = copy.deepcopy(component)
    remote["dialog"]["beginDialog"]["actions"].pop()
    saved = copy.deepcopy(remote)
    saved["dialog"]["modelDescription"] = desired["modelDescription"]
    later = {**desired, "modelDescription": "Later pending description."}

    client = native.MinimalBotEvaluationClient(
        topic_cli.target["environment"]["id"], topic_cli.target["agent"]["id"],
        topic_cli.target["environment"]["tenantId"],
    )
    client.read_components = Mock(side_effect=[
        {"changeToken": "before", "botComponentChanges": [{"component": remote}]},
        {"changeToken": "after", "botComponentChanges": [{"component": saved}]},
    ])

    def request(*_args, **_kwargs):
        if later_edit:
            topic_cli.draft.write_text(json.dumps(later), encoding="utf-8")
        return SimpleNamespace(status_code=200, headers={}), {}

    client._request = Mock(side_effect=request)
    if operation == "update":
        monkeypatch.setattr(authoring, "_native_client", lambda *_args: client)
        authoring.main([
            "update", "--draft", str(topic_cli.draft), "--expected", str(before), "--yes",
        ])
        result = json.loads(capsys.readouterr().out)
    else:
        result = authoring.save_workspace_topic_updates(
            client, topic_cli.agent_folder, [{
                "path": "topics/CaseSensitiveName.mcs.yml",
                "componentId": component["id"], "schemaName": component["schemaName"],
                "expectedDialog": component["dialog"], "dialog": desired,
                "submittedYaml": submitted,
            }],
            retry_on_conflict=False,
        )

    baseline = topic_cli.agent_folder / ".baseline" / "topics" / topic_cli.draft.name
    assert json.loads(baseline.read_text(encoding="utf-8")) == saved["dialog"]
    assert json.loads(topic_cli.draft.read_text(encoding="utf-8")) == (
        later if later_edit else saved["dialog"]
    )
    assert result["reconciledComponents"] == 1
    assert result["writeAttempted"] is True
    assert result["components"] == [saved]
    client._request.assert_called_once()


@pytest.mark.parametrize("operation", ["update", "workspace"])
def test_merged_projection_failure_preserves_remote_result_and_local_files(
    topic_cli, monkeypatch, operation,
):
    component = _register_existing(topic_cli)
    before = topic_cli.root / "before.json"
    authoring.main(["read", "--topic", str(topic_cli.draft), "--output", str(before)])
    saved = {**component, "dialog": {**component["dialog"], "remoteField": "preserved"}}
    known = {
        "updatedComponents": 1, "verifiedComponents": 1, "verified": True,
        "writeAttempted": True, "components": [saved],
    }
    topic_cli.transport.update_dialog_components.side_effect = None
    topic_cli.transport.update_dialog_components.return_value = known
    cause = authoring.ObjectModelConverterError("Projection failed after verified save")
    monkeypatch.setattr(authoring, "_project_topic", Mock(side_effect=cause))
    baseline = topic_cli.agent_folder / ".baseline" / "topics" / topic_cli.draft.name
    original = (topic_cli.draft.read_bytes(), baseline.read_bytes())

    with pytest.raises(authoring.ComponentEditError) as error:
        if operation == "update":
            authoring.main([
                "update", "--draft", str(topic_cli.draft),
                "--expected", str(before), "--yes",
            ])
        else:
            authoring.save_workspace_topic_updates(
                topic_cli.transport, topic_cli.agent_folder, [{
                    "path": "topics/CaseSensitiveName.mcs.yml",
                    "componentId": component["id"], "schemaName": component["schemaName"],
                    "dialog": topic_cli.dialog,
                    "submittedYaml": topic_cli.draft.read_text(encoding="utf-8"),
                }],
            )

    assert error.value.__cause__ is cause
    assert error.value.evidence["remoteResult"]["components"] == [saved]
    assert error.value.evidence["remoteResult"]["writeAttempted"] is True
    assert (topic_cli.draft.read_bytes(), baseline.read_bytes()) == original
    topic_cli.transport.update_dialog_components.assert_called_once()


def test_bookkeeping_failure_retains_verified_remote_result(topic_cli, monkeypatch):
    monkeypatch.setattr(
        authoring,
        "_register_created_topic",
        Mock(side_effect=PermissionError("map unavailable")),
    )

    with pytest.raises(authoring.TopicBookkeepingError) as exc_info:
        authoring.main(
            [
                "create",
                "--draft",
                str(topic_cli.draft),
                "--display-name",
                "Approved answer",
                "--yes",
            ]
        )

    remote = exc_info.value.evidence["remoteResult"]
    assert remote["saved"] is True
    assert remote["verifiedComponents"] == 1
    assert remote["bookkeepingComplete"] is False


def test_output_failure_retains_verified_remote_result(topic_cli, monkeypatch):
    monkeypatch.setattr(
        authoring,
        "_emit_result",
        Mock(side_effect=PermissionError("output unavailable")),
    )

    with pytest.raises(authoring.TopicBookkeepingError) as exc_info:
        authoring.main(
            [
                "create",
                "--draft",
                str(topic_cli.draft),
                "--display-name",
                "Case sensitive",
                "--yes",
            ]
        )

    remote = exc_info.value.evidence["remoteResult"]
    assert remote["saved"] is True
    assert remote["verifiedComponents"] == 1
    assert remote["bookkeepingComplete"] is True
    assert remote["outputComplete"] is False


def test_native_create_allows_same_name_and_verifies_readback(topic_cli, monkeypatch):
    component = {
        "$kind": "DialogComponent",
        "id": "new-topic",
        "schemaName": "contoso_agent.topic.NewTopic",
        "displayName": "Duplicate display name",
        "parentBotId": topic_cli.target["agent"]["id"],
        "state": "Inactive",
        "status": "Inactive",
        "dialog": topic_cli.dialog,
    }
    before = {
        "bot": {
            "cdsBotId": topic_cli.target["agent"]["id"],
            "schemaName": topic_cli.target["agent"]["schemaName"],
        },
        "changeToken": "fresh",
        "botComponentChanges": [
            {
                "component": {
                    "$kind": "DialogComponent",
                    "id": "existing",
                    "displayName": component["displayName"],
                }
            }
        ],
    }
    after = {
        **before,
        "changeToken": "saved",
        "botComponentChanges": [
            *before["botComponentChanges"],
            {"component": component},
        ],
    }
    from minimalbot_evaluation import MinimalBotEvaluationClient

    native = MinimalBotEvaluationClient(
        topic_cli.target["environment"]["id"],
        topic_cli.target["agent"]["id"],
        topic_cli.target["environment"]["tenantId"],
    )
    native.read_components = Mock(side_effect=[before, after])
    request = Mock(return_value=(SimpleNamespace(status_code=200, headers={}), {}))
    monkeypatch.setattr(native, "_request", request)

    result = native.create_dialog_component(component)

    assert result["component"] == component
    request.assert_called_once()
