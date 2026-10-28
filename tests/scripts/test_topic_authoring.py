# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure-logic contracts for bounded native topic authoring."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import minimalbot_evaluation as native
import topic_authoring as authoring


@pytest.fixture
def topic_cli(monkeypatch, tmp_path, fake_config, fake_token, fake_tenant_id):
    values = {
        "name": "Approved answer",
        "intent": "Return the approved answer.",
        "triggers": ["show the approved answer"],
        "response": "The approved response.",
    }
    monkeypatch.setattr(
        authoring, "object_models_to_yaml",
        lambda models: [{
            "success": True, "yaml": json.dumps(models[0]["objectModel"]),
        }],
    )
    monkeypatch.setattr(
        authoring, "yaml_to_object_models",
        lambda models: [{
            "success": True, "elementType": "AdaptiveDialog",
            "objectModel": json.loads(models[0]["yaml"]),
        }],
    )
    environment_id = "00000000-0000-0000-0000-000000005555"
    endpoint = native._environment_host(environment_id, "test")
    target = {
        "environment": {
            "id": environment_id, "tenantId": fake_tenant_id,
            "ring": "test", "powerPlatformApiEndpoint": endpoint,
        },
        "agent": {
            "id": fake_config["agent"]["botId"],
            "schemaName": fake_config["agent"]["schemaName"], "realm": "dev",
        },
    }
    components = []
    client = SimpleNamespace(
        tenant_id=fake_tenant_id, ring="test", host=endpoint, session=object(),
        headers={"Authorization": f"Bearer {fake_token}"},
        fetch_components=lambda _agent: {
            "botComponentChanges": [
                {"component": copy.deepcopy(component)} for component in components
            ],
        },
    )
    transport = Mock()
    transport.create_dialog_component.side_effect = lambda component: {
        "component": copy.deepcopy(component), "createdComponents": 1,
        "verifiedComponents": 1,
    }

    def update(updates, *, _retry_on_conflict):
        for change in updates:
            component = next(c for c in components if c["id"] == change["componentId"])
            component["dialog"] = copy.deepcopy(change["dialog"])
        return {
            "verifiedComponents": len(updates), "components": copy.deepcopy(components),
        }

    transport.update_dialog_components.side_effect = update
    monkeypatch.setattr(authoring, "connect_selected_dev_workspace", lambda _root, _account: (client, target))
    monkeypatch.setattr(authoring, "MinimalBotEvaluationClient", Mock(return_value=transport))
    monkeypatch.chdir(tmp_path)
    request = tmp_path / "request.json"
    request.write_text(json.dumps(values), encoding="utf-8")
    component = {
        "$kind": "DialogComponent",
        "id": "00000000-0000-0000-0000-000000004444",
        "schemaName": target["agent"]["schemaName"] + ".topic.ApprovedAnswer",
        "parentBotId": target["agent"]["id"],
        "displayName": values["name"], "description": values["intent"],
        "state": "Inactive", "status": "Inactive",
        "extensionData": {
            "UseProvidedBotComponentId": True, authoring.PATTERN_KEY: True,
        },
        "dialog": authoring.build_dialog(values),
    }
    component["dialog"]["beginDialog"]["id"] = "existing-trigger"
    component["dialog"]["beginDialog"]["actions"][0]["id"] = "existing-send"
    component["dialog"]["beginDialog"]["actions"][1]["id"] = "existing-end"
    before = tmp_path / "before.json"
    before.write_text(json.dumps({"target": target, "component": component}), encoding="utf-8")
    return SimpleNamespace(
        root=tmp_path, values=values, request=request, target=target,
        component=component, components=components, transport=transport, before=before,
    )


@pytest.mark.parametrize("drift", ["response", "ring", "agent"])
def test_create_preview_does_not_write_and_rejects_changed_approval(topic_cli, drift):
    preview = topic_cli.root / "preview.json"
    authoring.main(["create", "--request", str(topic_cli.request), "--output", str(preview)])
    assert json.loads(preview.read_text())["saved"] is False
    topic_cli.transport.create_dialog_component.assert_not_called()
    if drift == "response":
        changed = {**topic_cli.values, "response": "A different response."}
        topic_cli.request.write_text(json.dumps(changed), encoding="utf-8")
        message = "differs from its approved preview"
    else:
        changed = json.loads(preview.read_text())
        if drift == "ring":
            changed["target"]["environment"]["ring"] = "prod"
        else:
            changed["target"]["agent"]["id"] = "another-agent"
        preview.write_text(json.dumps(changed), encoding="utf-8")
        message = "different target"
    with pytest.raises(ValueError, match=message):
        authoring.main([
            "create", "--request", str(topic_cli.request),
            "--expected", str(preview), "--yes",
        ])
    topic_cli.transport.create_dialog_component.assert_not_called()


def test_create_requires_a_preview_before_writing(topic_cli):
    with pytest.raises(SystemExit) as exc:
        authoring.main(["create", "--request", str(topic_cli.request), "--yes"])
    assert exc.value.code == 2
    topic_cli.transport.create_dialog_component.assert_not_called()


def test_create_saves_one_marked_inactive_component_after_approval(topic_cli):
    preview = topic_cli.root / "preview.json"
    saved = topic_cli.root / "saved.json"
    authoring.main(["create", "--request", str(topic_cli.request), "--output", str(preview)])
    authoring.main([
        "create", "--request", str(topic_cli.request), "--expected", str(preview),
        "--yes", "--output", str(saved),
    ])
    topic_cli.transport.create_dialog_component.assert_called_once()
    component = topic_cli.transport.create_dialog_component.call_args.args[0]
    assert component["parentBotId"] == topic_cli.target["agent"]["id"]
    assert component["state"] == component["status"] == "Inactive"
    assert component["extensionData"] == {
        "UseProvidedBotComponentId": True, authoring.PATTERN_KEY: True,
    }
    result = json.loads(saved.read_text())
    assert result["saved"] is True and result["published"] is False
    assert result["component"]["id"] == component["id"]


def test_deliberate_creation_does_not_retarget_an_existing_same_name(topic_cli):
    topic_cli.components.append({
        "$kind": "DialogComponent", "id": "another-topic",
        "displayName": f" {topic_cli.values['name'].upper()} ",
    })
    preview = topic_cli.root / "preview.json"
    authoring.main([
        "create", "--request", str(topic_cli.request), "--output", str(preview),
    ])
    authoring.main([
        "create", "--request", str(topic_cli.request),
        "--expected", str(preview), "--yes",
    ])
    inserted = topic_cli.transport.create_dialog_component.call_args.args[0]
    assert inserted["id"] != "another-topic"
    topic_cli.transport.update_dialog_components.assert_not_called()


def test_update_keeps_native_identity_and_saved_node_ids(topic_cli):
    topic_cli.components.append(copy.deepcopy(topic_cli.component))
    changed = {**topic_cli.values, "response": "The approved revised response."}
    topic_cli.request.write_text(json.dumps(changed), encoding="utf-8")
    preview = topic_cli.root / "preview.json"
    arguments = [
        "update", "--request", str(topic_cli.request),
        "--expected", str(topic_cli.before),
    ]
    authoring.main([*arguments, "--output", str(preview)])
    topic_cli.transport.update_dialog_components.assert_not_called()
    saved = topic_cli.root / "saved.json"
    authoring.main([*arguments, "--yes", "--output", str(saved)])
    desired = copy.deepcopy(topic_cli.component["dialog"])
    desired["beginDialog"]["actions"][0]["activity"] = authoring.build_dialog(changed)[
        "beginDialog"
    ]["actions"][0]["activity"]
    topic_cli.transport.update_dialog_components.assert_called_once_with([{
        "componentId": topic_cli.component["id"],
        "schemaName": topic_cli.component["schemaName"],
        "expectedDialog": topic_cli.component["dialog"],
        "dialog": desired, "requireCleanDiagnostics": True,
    }], _retry_on_conflict=False)
    result = json.loads(saved.read_text())
    assert result["saved"] is True and result["published"] is False
    assert result["component"]["id"] == topic_cli.component["id"]
    topic_cli.transport.create_dialog_component.assert_not_called()


def test_update_rechecks_the_current_supported_topic_boundary(topic_cli):
    component = copy.deepcopy(topic_cli.component)
    component["extensionData"].clear()
    topic_cli.components.append(component)
    with pytest.raises(ValueError, match="not an editable crafted-response topic"):
        authoring.main([
            "update", "--request", str(topic_cli.request),
            "--expected", str(topic_cli.before), "--yes",
        ])
    topic_cli.transport.update_dialog_components.assert_not_called()


def test_managed_property_hints_do_not_override_service_permissions(topic_cli):
    component = copy.deepcopy(topic_cli.component)
    component["managedProperties"] = {"isManaged": True, "isCustomizable": False}
    topic_cli.components.append(component)
    authoring.main([
        "update", "--request", str(topic_cli.request),
        "--expected", str(topic_cli.before), "--yes",
    ])
    topic_cli.transport.update_dialog_components.assert_called_once()




def test_native_insert_sends_one_inactive_component_and_verifies_readback(topic_cli, monkeypatch):
    component = topic_cli.component
    before = {
        "bot": {
            "cdsBotId": topic_cli.target["agent"]["id"],
            "schemaName": topic_cli.target["agent"]["schemaName"],
        },
        "changeToken": "fresh-token", "botComponentChanges": [{"component": {
            "$kind": "DialogComponent", "id": "same-name",
            "displayName": component["displayName"].upper(),
        }}],
    }
    after = {
        **before, "changeToken": "saved-token",
        "botComponentChanges": [{"component": component}],
    }
    client = native.MinimalBotEvaluationClient(
        topic_cli.target["environment"]["id"], topic_cli.target["agent"]["id"],
        topic_cli.target["environment"]["tenantId"],
    )
    reads = iter((before, after))
    monkeypatch.setattr(client, "read_components", lambda: next(reads))
    request = Mock(return_value=(SimpleNamespace(status_code=200), {}))
    monkeypatch.setattr(client, "_request", request)
    result = client.create_dialog_component(component)
    assert result["createdComponents"] == 1 and result["verifiedComponents"] == 1
    assert result["component"] == component
    assert request.call_args.args[0] == "PUT"
    body = request.call_args.kwargs["body"]
    assert "bot" not in body
    assert body["changeToken"] == "fresh-token"
    assert body["botComponentChanges"] == [{
        "$kind": "BotComponentInsert", "component": component,
    }]
    assert all(value == [] for key, value in body.items() if key.endswith("Changes")
               and key != "botComponentChanges")


@pytest.mark.parametrize("status", [403, 409, 412, 503])
def test_scoped_update_returns_service_evidence_without_conflict_replay(
    topic_cli, monkeypatch, status,
):
    component = copy.deepcopy(topic_cli.component)
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
    component = topic_cli.component
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
        topic_cli.target["environment"]["powerPlatformApiEndpoint"], "offline-token",
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


def test_output_failure_preserves_a_known_topic_save(topic_cli, monkeypatch, capsys):
    preview = topic_cli.root / "preview.json"
    authoring.main([
        "create", "--request", str(topic_cli.request), "--output", str(preview),
    ])
    output = topic_cli.root / "saved.json"
    original_write = authoring.Path.write_text
    cause = PermissionError("Output directory is unavailable")

    def fail_output(path, *args, **kwargs):
        if path == output:
            raise cause
        return original_write(path, *args, **kwargs)

    monkeypatch.setattr(authoring.Path, "write_text", fail_output)
    capsys.readouterr()
    with pytest.raises(native.ComponentEditError) as error:
        authoring.main([
            "create", "--request", str(topic_cli.request), "--expected", str(preview),
            "--yes", "--output", str(output),
        ])
    assert error.value.__cause__ is cause
    assert error.value.evidence["operationResult"]["createdComponents"] == 1
    observed = json.loads(capsys.readouterr().out)
    assert observed["saved"] is True and observed["verifiedComponents"] == 1
    topic_cli.transport.create_dialog_component.assert_called_once()
