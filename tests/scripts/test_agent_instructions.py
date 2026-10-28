# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Native instruction YAML and concurrency contracts."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import agent_instructions as cli
import minimalbot_evaluation as native


ENV_ID = "00000000-0000-0000-0000-000000005555"
BOT_ID = "00000000-0000-0000-0000-000000004444"


@pytest.fixture
def component():
    return {
        "$kind": "GptComponent",
        "id": "native-gpt",
        "parentBotId": BOT_ID,
        "schemaName": "contoso_agent.gpt.default",
        "displayName": "Contoso agent",
        "version": 2,
        "auditInfo": {"modifiedOn": "before"},
        "unknownComponentField": {"keep": True},
        "metadata": {
            "$kind": "GptComponentMetadata",
            "unknownSetting": {"keep": [1, 2]},
            "instructions": {
                "$kind": "TemplateLine",
                "unknownInstructionField": "keep",
                "segments": [
                    {"$kind": "TextSegment", "value": "Old route.", "keep": True},
                    {
                        "$kind": "ExpressionSegment",
                        "expression": {
                            "$kind": "ValueExpression",
                            "variableReference": "System.User.DisplayName",
                        },
                    },
                ],
            },
        },
    }


def _payload(component):
    return {
        "bot": {"cdsBotId": BOT_ID, "schemaName": "contoso_agent"},
        "changeToken": "current-token",
        "botComponentChanges": [
            {"component": copy.deepcopy(component)},
            {
                "component": {
                    "$kind": "DialogComponent",
                    "id": "unrelated-topic",
                    "dialog": {"unknownField": "preserve"},
                    "version": 3,
                }
            },
        ],
    }


def _client(monkeypatch, payloads, *, status=200, body=None):
    client = native.MinimalBotEvaluationClient(ENV_ID, BOT_ID, "test-tenant")
    client.read_components = Mock(side_effect=payloads)
    request = Mock(
        return_value=(
            SimpleNamespace(
                status_code=status,
                headers={"x-ms-request-id": "correlation-id"},
            ),
            body if body is not None else {"nativeExtension": {"preserved": True}},
        )
    )
    monkeypatch.setattr(client, "_request", request)
    return client, request


def _desired(component):
    instructions = copy.deepcopy(component["metadata"]["instructions"])
    instructions["segments"][0]["value"] = "New route."
    return instructions


def test_native_update_preserves_fresh_unrelated_gpt_fields(component, monkeypatch):
    fresh = copy.deepcopy(component)
    fresh["unknownComponentField"]["concurrent"] = "preserve"
    desired_instructions = _desired(component)
    saved = copy.deepcopy(fresh)
    saved["metadata"]["instructions"] = desired_instructions
    saved["version"] += 1
    saved["auditInfo"]["modifiedOn"] = "after"
    after = _payload(saved)
    client, request = _client(monkeypatch, [_payload(fresh), after])

    result = client.update_agent_instructions(
        component,
        component["metadata"]["instructions"],
        desired_instructions,
    )

    payload = request.call_args.kwargs["body"]
    updated = payload["botComponentChanges"][0]["component"]
    assert updated["unknownComponentField"]["concurrent"] == "preserve"
    assert updated["metadata"]["unknownSetting"] == {"keep": [1, 2]}
    assert updated["metadata"]["instructions"] == desired_instructions
    assert result["component"]["metadata"]["instructions"] == desired_instructions


def test_native_update_rejects_instruction_drift_but_not_other_gpt_drift(
    component,
    monkeypatch,
):
    drifted = copy.deepcopy(component)
    drifted["metadata"]["instructions"]["segments"][0]["value"] = "Concurrent route."
    client, request = _client(monkeypatch, [_payload(drifted)])

    with pytest.raises(native.MinimalBotEvaluationError, match="instructions changed"):
        client.update_agent_instructions(
            component,
            component["metadata"]["instructions"],
            _desired(component),
        )

    request.assert_not_called()


def test_native_noop_is_verified_without_write(component, monkeypatch):
    client, request = _client(monkeypatch, [_payload(component)])

    result = client.update_agent_instructions(
        component,
        component["metadata"]["instructions"],
        component["metadata"]["instructions"],
    )

    assert result["updatedComponents"] == 0
    assert result["verifiedComponents"] == 1
    request.assert_not_called()


@pytest.mark.parametrize("status", [400, 409, 412, 500])
def test_native_service_failure_retains_status_and_request_evidence(
    component,
    monkeypatch,
    status,
):
    body = {
        "error": {"code": "native-code", "unknownDetails": {"reason": "preserve"}},
        "access_token": "do-not-emit",
    }
    client, request = _client(
        monkeypatch,
        [_payload(component)],
        status=status,
        body=body,
    )

    with pytest.raises(native.AgentInstructionEditError) as exc_info:
        client.update_agent_instructions(
            component,
            component["metadata"]["instructions"],
            _desired(component),
        )

    assert exc_info.value.evidence["httpStatus"] == status
    assert exc_info.value.evidence["requestId"] == "correlation-id"
    assert "do-not-emit" not in str(exc_info.value)
    assert client.read_components.call_count == 1
    request.assert_called_once()


@pytest.fixture
def instruction_cli(component, monkeypatch, tmp_path, fake_tenant_id):
    agent_folder = tmp_path / "workspace" / "agents" / "selected"
    baseline_folder = agent_folder / ".baseline"
    baseline_folder.mkdir(parents=True)
    local = tmp_path / ".local"
    local.mkdir()
    (local / "config.json").write_text(
        json.dumps({"agent": {"folder": str(agent_folder)}}),
        encoding="utf-8",
    )
    metadata = {
        **copy.deepcopy(component["metadata"]),
        "displayName": component["displayName"],
    }
    agent_file = agent_folder / "agent.mcs.yml"
    agent_file.write_text(json.dumps(metadata), encoding="utf-8")
    (baseline_folder / "agent.mcs.yml").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )
    target = {
        "environment": {
            "id": ENV_ID,
            "tenantId": fake_tenant_id,
            "ring": "test",
            "powerPlatformApiEndpoint": "https://api.test.example",
        },
        "agent": {"id": BOT_ID, "schemaName": "contoso_agent", "realm": "dev"},
    }
    connection = SimpleNamespace(
        host=target["environment"]["powerPlatformApiEndpoint"],
        headers={"Authorization": "Bearer test-token"},
        session=object(),
    )
    snapshot = {
        "component": component,
        "changeToken": "current-token",
        "componentCount": 2,
    }
    transport = Mock()
    transport.read_agent_instructions.side_effect = lambda: copy.deepcopy(snapshot)
    transport.update_agent_instructions.side_effect = (
        lambda expected_component, _expected_instructions, desired_instructions: {
            "component": {
                **copy.deepcopy(expected_component),
                "metadata": {
                    **copy.deepcopy(expected_component["metadata"]),
                    "instructions": copy.deepcopy(desired_instructions),
                },
            },
            "updatedComponents": 1,
            "verifiedComponents": 1,
            "changeToken": "saved-token",
            "unchangedOtherComponents": 1,
        }
    )
    connect = Mock(return_value=(connection, target))
    monkeypatch.setattr(cli, "connect_selected_dev_workspace", connect)
    monkeypatch.setattr(cli, "MinimalBotEvaluationClient", Mock(return_value=transport))
    monkeypatch.setattr(
        cli,
        "yaml_to_object_models",
        lambda items: [
            {
                "key": item["key"],
                "success": True,
                "elementType": "GptComponentMetadata",
                "objectModel": json.loads(item["yaml"]),
            }
            for item in items
        ],
    )
    monkeypatch.setattr(
        cli,
        "object_models_to_yaml",
        lambda items: [
            {
                "key": item["key"],
                "success": True,
                "elementType": "GptComponentMetadata",
                "yaml": json.dumps(item["objectModel"]),
            }
            for item in items
        ],
    )
    monkeypatch.chdir(tmp_path)
    expected = tmp_path / "expected.json"
    cli.main(["read", "--output", str(expected)])
    return SimpleNamespace(
        root=tmp_path,
        agent_folder=agent_folder,
        agent_file=agent_file,
        expected=expected,
        component=component,
        metadata=metadata,
        target=target,
        transport=transport,
        connect=connect,
    )


def test_cli_uses_agent_yaml_and_acknowledges_only_instruction_section(
    instruction_cli,
):
    fixture = instruction_cli
    desired_metadata = copy.deepcopy(fixture.metadata)
    desired_metadata["instructions"]["segments"][0]["value"] = "New route."
    desired_metadata["unknownSetting"] = {"draft-only": True}
    fixture.agent_file.write_text(json.dumps(desired_metadata), encoding="utf-8")

    cli.main(
        [
            "update",
            "--draft",
            str(fixture.agent_file),
            "--expected",
            str(fixture.expected),
            "--yes",
        ]
    )

    fixture.transport.update_agent_instructions.assert_called_once_with(
        fixture.component,
        fixture.component["metadata"]["instructions"],
        desired_metadata["instructions"],
    )
    baseline = json.loads(
        (fixture.agent_folder / ".baseline" / "agent.mcs.yml").read_text(
            encoding="utf-8"
        )
    )
    assert baseline["instructions"] == desired_metadata["instructions"]
    assert baseline["unknownSetting"] == fixture.metadata["unknownSetting"]


def test_cli_acknowledges_capture_not_later_instruction_edit(instruction_cli):
    fixture = instruction_cli
    submitted = copy.deepcopy(fixture.metadata)
    submitted["instructions"]["segments"][0]["value"] = "Submitted route."
    later = copy.deepcopy(submitted)
    later["instructions"]["segments"][0]["value"] = "Later route."
    fixture.agent_file.write_text(json.dumps(submitted), encoding="utf-8")

    def update(*args):
        fixture.agent_file.write_text(json.dumps(later), encoding="utf-8")
        expected_component, _, desired_instructions = args
        return {
            "component": {
                **copy.deepcopy(expected_component),
                "metadata": {
                    **copy.deepcopy(expected_component["metadata"]),
                    "instructions": copy.deepcopy(desired_instructions),
                },
            },
            "updatedComponents": 1,
            "verifiedComponents": 1,
        }

    fixture.transport.update_agent_instructions.side_effect = update
    cli.main(
        [
            "update",
            "--draft",
            str(fixture.agent_file),
            "--expected",
            str(fixture.expected),
            "--yes",
        ]
    )

    baseline = json.loads(
        (fixture.agent_folder / ".baseline" / "agent.mcs.yml").read_text(
            encoding="utf-8"
        )
    )
    assert baseline["instructions"] == submitted["instructions"]
    assert json.loads(fixture.agent_file.read_text())["instructions"] == later[
        "instructions"
    ]


def test_cli_verified_noop_is_saved_and_acknowledged(instruction_cli, capsys):
    fixture = instruction_cli

    fixture.transport.update_agent_instructions.return_value = {
        "component": fixture.component,
        "updatedComponents": 0,
        "verifiedComponents": 1,
    }
    cli.main(
        [
            "update",
            "--draft",
            str(fixture.agent_file),
            "--expected",
            str(fixture.expected),
            "--yes",
        ]
    )

    result = json.loads(capsys.readouterr().out)
    assert result["changed"] is False
    assert result["saved"] is True
    assert result["bookkeepingComplete"] is True


def test_cli_bookkeeping_failure_retains_verified_remote_result(
    instruction_cli,
    monkeypatch,
):
    fixture = instruction_cli
    desired = copy.deepcopy(fixture.metadata)
    desired["instructions"]["segments"][0]["value"] = "New route."
    fixture.agent_file.write_text(json.dumps(desired), encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "_acknowledge_instructions",
        Mock(side_effect=PermissionError("baseline unavailable")),
    )

    with pytest.raises(cli.InstructionBookkeepingError) as exc_info:
        cli.main(
            [
                "update",
                "--draft",
                str(fixture.agent_file),
                "--expected",
                str(fixture.expected),
                "--yes",
            ]
        )

    remote = exc_info.value.evidence["remoteResult"]
    assert remote["saved"] is True
    assert remote["verifiedComponents"] == 1
    assert remote["bookkeepingComplete"] is False


def test_cli_output_failure_retains_verified_remote_result(
    instruction_cli,
    monkeypatch,
):
    fixture = instruction_cli
    monkeypatch.setattr(
        cli,
        "_emit_result",
        Mock(side_effect=PermissionError("output unavailable")),
    )

    with pytest.raises(cli.InstructionBookkeepingError) as exc_info:
        cli.main(
            [
                "update",
                "--draft",
                str(fixture.agent_file),
                "--expected",
                str(fixture.expected),
                "--yes",
            ]
        )

    remote = exc_info.value.evidence["remoteResult"]
    assert remote["saved"] is True
    assert remote["verifiedComponents"] == 1
    assert remote["bookkeepingComplete"] is True
    assert remote["outputComplete"] is False
