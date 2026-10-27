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
        return {"verifiedComponents": len(updates)}

    transport.update_dialog_components.side_effect = update
    monkeypatch.setattr(authoring, "connect", lambda _root, _account: (client, target))
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


def test_create_prevents_same_name_even_for_an_unmarked_topic(topic_cli):
    topic_cli.components.append({
        "$kind": "DialogComponent", "id": "another-topic",
        "displayName": f" {topic_cli.values['name'].upper()} ",
    })
    with pytest.raises(ValueError, match="name already exists"):
        authoring.main(["create", "--request", str(topic_cli.request)])
    topic_cli.transport.create_dialog_component.assert_not_called()


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


@pytest.mark.parametrize("boundary", ["unmarked", "managed"])
def test_update_rechecks_the_current_supported_topic_boundary(topic_cli, boundary):
    component = copy.deepcopy(topic_cli.component)
    if boundary == "unmarked":
        component["extensionData"].clear()
    else:
        component["managedProperties"] = {"isManaged": True}
    topic_cli.components.append(component)
    with pytest.raises(ValueError, match="not an editable crafted-response topic"):
        authoring.main([
            "update", "--request", str(topic_cli.request),
            "--expected", str(topic_cli.before), "--yes",
        ])
    topic_cli.transport.update_dialog_components.assert_not_called()


@pytest.mark.parametrize("mismatch", ["account", "tenant"])
def test_connect_checks_the_actual_authenticated_identity(
    monkeypatch, tmp_path, fake_config, fake_tenant_id, fake_token, mismatch,
):
    local = tmp_path / ".local"
    (local / "setup").mkdir(parents=True)
    fake_config["ring"] = "test"
    (local / "config.json").write_text(json.dumps(fake_config), encoding="utf-8")
    (local / "setup" / "config.json").write_text(json.dumps({
        "schema_version": 4, "environment": {"tenant_id": fake_tenant_id},
        "agents": {"selected": {
            "agent": {
                "workspace_slug": fake_config["activeAgent"],
                "id": fake_config["agent"]["botId"], "realm": "dev",
            },
            "connect_ready": True,
        }},
    }), encoding="utf-8")
    monkeypatch.setattr(authoring, "cached_account_names", lambda _cache: ["maker@contoso.com"])
    monkeypatch.setattr(
        authoring, "_acquire_token",
        lambda **_kwargs: (
            fake_token, "another@contoso.com" if mismatch == "account" else "maker@contoso.com",
        ),
    )
    monkeypatch.setattr(
        authoring, "tenant_id_from_access_token",
        lambda _token: "another-tenant" if mismatch == "tenant" else fake_tenant_id,
    )
    client = Mock()
    monkeypatch.setattr(authoring, "AgentBuilderClient", client)
    message = "different account" if mismatch == "account" else "tenant does not match"
    with pytest.raises(ValueError, match=message):
        authoring.connect(tmp_path, None)
    client.assert_not_called()


def test_native_insert_sends_one_inactive_component_and_verifies_readback(topic_cli, monkeypatch):
    component = topic_cli.component
    before = {
        "bot": {
            "cdsBotId": topic_cli.target["agent"]["id"],
            "schemaName": topic_cli.target["agent"]["schemaName"],
        },
        "changeToken": "fresh-token", "botComponentChanges": [],
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


def test_native_insert_rechecks_same_name_before_sending(topic_cli, monkeypatch):
    client = native.MinimalBotEvaluationClient(
        topic_cli.target["environment"]["id"], topic_cli.target["agent"]["id"],
        topic_cli.target["environment"]["tenantId"],
    )
    monkeypatch.setattr(client, "read_components", lambda: {
        "bot": {
            "cdsBotId": topic_cli.target["agent"]["id"],
            "schemaName": topic_cli.target["agent"]["schemaName"],
        },
        "changeToken": "fresh-token",
        "botComponentChanges": [{"component": {
            "$kind": "DialogComponent", "id": "another-topic",
            "displayName": topic_cli.component["displayName"].upper(),
        }}],
    })
    request = Mock()
    monkeypatch.setattr(client, "_request", request)
    with pytest.raises(native.MinimalBotEvaluationError, match="name already exists"):
        client.create_dialog_component(topic_cli.component)
    request.assert_not_called()
