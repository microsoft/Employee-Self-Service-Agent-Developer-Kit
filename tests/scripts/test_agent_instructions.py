# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""AgentBuilder instruction YAML and concurrency contracts."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
import yaml

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
        desired_instructions=desired_instructions,
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
            desired_instructions=_desired(component),
        )

    request.assert_not_called()


def test_native_noop_is_verified_without_write(component, monkeypatch):
    client, request = _client(monkeypatch, [_payload(component)])

    result = client.update_agent_instructions(
        component,
        desired_instructions=component["metadata"]["instructions"],
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
            desired_instructions=_desired(component),
        )

    assert exc_info.value.evidence["httpStatus"] == status
    assert exc_info.value.evidence["requestId"] == "correlation-id"
    assert "do-not-emit" not in str(exc_info.value)
    assert client.read_components.call_count == 1
    request.assert_called_once()


@pytest.mark.parametrize("drift", ["metadata", "other-content", "other-deleted"])
def test_instruction_save_ignores_unrelated_readback_drift(component, monkeypatch, drift):
    current = copy.deepcopy(component)
    current["metadata"]["unknownSetting"] = {"newer": "preserve"}
    after = _payload(current)
    after["botComponentChanges"][0]["component"]["metadata"]["instructions"] = (
        _desired(component)
    )
    if drift == "metadata":
        after["botComponentChanges"][0]["component"]["metadata"]["unknownSetting"] = {}
    elif drift == "other-content":
        after["botComponentChanges"][1]["component"]["dialog"] = {"newer": True}
    else:
        after["botComponentChanges"].pop()
    client, request = _client(monkeypatch, [_payload(current), after])

    result = client.update_agent_instructions(
        component, desired_instructions=_desired(component),
    )

    submitted = request.call_args.kwargs["body"]["botComponentChanges"][0]["component"]
    assert submitted["metadata"]["unknownSetting"] == {"newer": "preserve"}
    assert result["verified"] is True
    assert result["component"] == after["botComponentChanges"][0]["component"]


@pytest.mark.parametrize("problem", ["instructions", "read-failed"])
def test_accepted_instruction_write_retains_failed_verification(
    component, monkeypatch, problem,
):
    after = (
        _payload(component)
        if problem == "instructions"
        else native.MinimalBotEvaluationError("readback unavailable")
    )
    client, request = _client(monkeypatch, [_payload(component), after])

    with pytest.raises(native.AgentInstructionEditError) as error:
        client.update_agent_instructions(
            component, desired_instructions=_desired(component),
        )

    assert error.value.evidence["writeAccepted"] is True
    assert error.value.evidence["verified"] is False
    assert error.value.__cause__ is not None
    request.assert_called_once()


def test_instruction_transport_uncertainty_preserves_cause(component, monkeypatch):
    client, request = _client(monkeypatch, [_payload(component)])
    cause = requests.ConnectionError("Connection lost after request submission")
    request.side_effect = native.MinimalBotEvaluationError("transport unavailable")
    request.side_effect.__cause__ = cause

    with pytest.raises(native.AgentInstructionEditError) as error:
        client.update_agent_instructions(
            component, desired_instructions=_desired(component),
        )

    assert error.value.evidence["writeAttempted"] is True
    assert error.value.evidence["verified"] is False
    assert error.value.__cause__.__cause__ is cause
    request.assert_called_once()


def test_instruction_ack_preserves_other_baseline_fields_and_later_edits(tmp_path):
    baseline = tmp_path / ".baseline" / "agent.mcs.yml"
    baseline.parent.mkdir()
    original = {
        "displayName": "Original name", "unknownMetadata": {"keep": [1, 2]},
        "instructions": "old",
    }
    submitted = {
        "displayName": "Unsubmitted name",
        "instructions": ["Approved text", {"kind": "ExpressionSegment", "value": "=System.User"}],
    }
    baseline.write_text(yaml.safe_dump(original), encoding="utf-8")
    working = tmp_path / "agent.mcs.yml"
    working.write_text("instructions: Later local edit\n", encoding="utf-8")

    cli.acknowledge_instruction_baseline(tmp_path, yaml.safe_dump(submitted))

    assert yaml.safe_load(baseline.read_text(encoding="utf-8")) == {
        **original, "instructions": submitted["instructions"],
    }
    assert working.read_text(encoding="utf-8") == "instructions: Later local edit\n"


@pytest.mark.parametrize(("original_section", "submitted_section"), [
    ("instructions: |-\n  Original instruction.\n", "instructions: 'Approved literal'\n"),
    (
        "instructions: |-\n  Original instruction.\n",
        "instructions: |-\n  Approved line one.  \n  Approved line two.\n",
    ),
    (
        "instructions:\n  - Original text\n  - kind: ExpressionSegment\n    expression: System.User.Name\n",
        "instructions: 'Approved literal'\n",
    ),
])
def test_instruction_ack_preserves_unrelated_yaml_text(tmp_path, original_section, submitted_section):
    baseline = tmp_path / ".baseline" / "agent.mcs.yml"
    baseline.parent.mkdir()
    prefix = "# Keep this comment\nkind: GptComponentMetadata\ndisplayName: 'Original name'\n"
    suffix = (
        "# Preserve ordering and indentation\n"
        "conversationStarters:\n"
        "  - title: 'Help'\n"
        "    text: Ask a question\n"
        "gptCapabilities: {} # Keep this inline comment\n"
    )
    baseline.write_text(prefix + original_section + suffix, encoding="utf-8")
    submitted = "kind: GptComponentMetadata\n" + submitted_section + "displayName: Not approved\n"

    cli.acknowledge_instruction_baseline(tmp_path, submitted)

    assert baseline.read_text(encoding="utf-8") == prefix + submitted_section + suffix


def test_acknowledged_baseline_round_trips_through_real_object_model(tmp_path):
    from agentbuilder_object_model_packages import assembly_paths

    if not all(path.is_file() for path in assembly_paths()):
        pytest.skip("Install the Object Model packages to run the real-converter check.")
    instructions = {
        "$kind": "TemplateLine",
        "segments": [{"$kind": "TextSegment", "value": "Approved line one.  \nLine two."}],
    }
    metadata = {
        "$kind": "GptComponentMetadata",
        "displayName": "Original name",
        "instructions": {
            "$kind": "TemplateLine",
            "segments": [{"$kind": "TextSegment", "value": "Original instruction."}],
        },
        "conversationStarters": [{"$kind": "ConversationStarter", "title": "Help", "text": "Ask"}],
    }
    original = cli._project_metadata(metadata, "agent").replace("\r\n", "\n")
    submitted = cli._project_metadata(
        {**metadata, "displayName": "Unsubmitted name", "instructions": instructions}, "agent",
    )
    baseline = tmp_path / ".baseline" / "agent.mcs.yml"
    baseline.parent.mkdir()
    baseline.write_text(original, encoding="utf-8")

    cli.acknowledge_instruction_baseline(tmp_path, submitted)

    converted = cli._metadata_from_yaml(baseline.read_text(encoding="utf-8"), "agent:baseline")
    assert converted["instructions"] == instructions
    assert converted["displayName"] == metadata["displayName"]
    assert converted["conversationStarters"] == metadata["conversationStarters"]


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
        lambda expected_component, *, desired_instructions: {
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
    connect = Mock(return_value=(connection, target, _payload(component)))
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


@pytest.mark.parametrize("apply", [False, True])
def test_instruction_update_reports_baseline_drift_and_blocks_unacknowledged_save(
    instruction_cli, capsys, apply,
):
    fixture = instruction_cli
    fixture.component["metadata"]["instructions"]["segments"][0]["value"] = "Remote route."
    cli.main(["read", "--output", str(fixture.expected)])
    desired = copy.deepcopy(fixture.metadata)
    desired["instructions"]["segments"][0]["value"] = "Local route."
    fixture.agent_file.write_text(json.dumps(desired), encoding="utf-8")
    baseline = fixture.agent_folder / ".baseline" / "agent.mcs.yml"
    original = (baseline.read_bytes(), fixture.agent_file.read_bytes())
    capsys.readouterr()
    args = ["update", "--draft", str(fixture.agent_file), "--expected", str(fixture.expected)]

    if apply:
        with pytest.raises(native.ComponentEditError, match="changed since") as error:
            cli.main([*args, "--yes"])
        result = error.value.evidence
    else:
        assert cli.main(args) == 0
        result = json.loads(capsys.readouterr().out)

    assert result["saveBlocked"] is True
    assert result["writeAttempted"] is False
    assert result["baselineComparison"] == {
        "baseline": fixture.metadata["instructions"],
        "remote": fixture.component["metadata"]["instructions"],
        "draft": desired["instructions"],
    }
    fixture.transport.update_agent_instructions.assert_not_called()
    assert (baseline.read_bytes(), fixture.agent_file.read_bytes()) == original


@pytest.mark.parametrize("problem", ["missing", "invalid"])
@pytest.mark.parametrize("acknowledge", [False, True])
def test_instruction_update_requires_usable_baseline_even_with_acknowledgement(
    instruction_cli, problem, acknowledge,
):
    fixture = instruction_cli
    baseline = fixture.agent_folder / ".baseline" / "agent.mcs.yml"
    if problem == "missing":
        baseline.unlink()
    else:
        baseline.write_text("invalid YAML conversion", encoding="utf-8")
    draft_before = fixture.agent_file.read_bytes()
    args = [
        "update", "--draft", str(fixture.agent_file),
        "--expected", str(fixture.expected), "--yes",
    ]
    if acknowledge:
        args.append("--acknowledge-remote-changes")

    with pytest.raises(native.ComponentEditError, match="baseline") as error:
        cli.main(args)

    assert error.value.__cause__ is not None
    assert error.value.evidence["writeAttempted"] is False
    assert error.value.evidence["baselinePath"] == str(baseline)
    fixture.transport.update_agent_instructions.assert_not_called()
    assert fixture.agent_file.read_bytes() == draft_before
    assert baseline.exists() is (problem != "missing")


@pytest.mark.parametrize("drift_stage", ["none", "before-command", "before-write"])
def test_acknowledged_instruction_drift_pins_reviewed_snapshot(
    instruction_cli, monkeypatch, drift_stage,
):
    fixture = instruction_cli
    fixture.component["metadata"]["instructions"]["segments"][0]["value"] = "Reviewed route."
    cli.main(["read", "--output", str(fixture.expected)])
    desired = copy.deepcopy(fixture.metadata)
    desired["instructions"] = copy.deepcopy(fixture.component["metadata"]["instructions"])
    desired["instructions"]["segments"].append(
        {"$kind": "TextSegment", "value": "Approved addition."}
    )
    fixture.agent_file.write_text(json.dumps(desired), encoding="utf-8")
    baseline = fixture.agent_folder / ".baseline" / "agent.mcs.yml"
    original = (baseline.read_bytes(), fixture.agent_file.read_bytes())
    latest = copy.deepcopy(fixture.component)
    if drift_stage != "none":
        latest["metadata"]["instructions"]["segments"][0]["value"] = "Changed after review."
    saved = copy.deepcopy(latest)
    saved["metadata"]["instructions"] = desired["instructions"]
    initial = latest if drift_stage == "before-command" else fixture.component
    client, request = _client(monkeypatch, [
        _payload(initial), _payload(latest), _payload(saved),
    ])
    monkeypatch.setattr(cli, "_native_client", lambda *_args: client)
    args = [
        "update", "--draft", str(fixture.agent_file), "--expected", str(fixture.expected),
        "--acknowledge-remote-changes", "--yes",
    ]

    if drift_stage == "none":
        assert cli.main(args) == 0
        request.assert_called_once()
        submitted = request.call_args.kwargs["body"]["botComponentChanges"][0]
        assert submitted["component"]["metadata"]["instructions"] == desired["instructions"]
        assert yaml.safe_load(baseline.read_text())["instructions"] == desired["instructions"]
    else:
        with pytest.raises((ValueError, native.MinimalBotEvaluationError), match="changed"):
            cli.main(args)
        request.assert_not_called()
        assert (baseline.read_bytes(), fixture.agent_file.read_bytes()) == original


def test_instruction_already_current_allows_noop_with_older_baseline(
    instruction_cli, monkeypatch, capsys,
):
    fixture = instruction_cli
    fixture.component["metadata"]["instructions"]["segments"][0]["value"] = "Already saved."
    fixture.agent_file.write_text(
        json.dumps(fixture.component["metadata"], indent=4), encoding="utf-8",
    )
    fixture.component["metadata"]["unknownSetting"] = {"newer": "remote metadata"}
    cli.main(["read", "--output", str(fixture.expected)])
    capsys.readouterr()
    client, request = _client(
        monkeypatch, [_payload(fixture.component), _payload(fixture.component)],
    )
    monkeypatch.setattr(cli, "_native_client", lambda *_args: client)

    assert cli.main([
        "update", "--draft", str(fixture.agent_file),
        "--expected", str(fixture.expected), "--yes",
    ]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["saveBlocked"] is False
    assert result["writeAttempted"] is False
    request.assert_not_called()


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
        desired_instructions=desired_metadata["instructions"],
    )
    baseline = yaml.safe_load(
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

    def update(expected_component, *, desired_instructions):
        fixture.agent_file.write_text(json.dumps(later), encoding="utf-8")
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

    baseline = yaml.safe_load(
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

    fixture.transport.update_agent_instructions.side_effect = None
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
        "acknowledge_instruction_baseline",
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
