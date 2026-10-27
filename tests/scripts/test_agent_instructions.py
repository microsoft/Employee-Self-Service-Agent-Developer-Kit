# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Native instruction text editing, based on the observed TemplateLine contract."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

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
        "version": 2,
        "state": "Active",
        "status": "Active",
        "auditInfo": {"modifiedOn": "before"},
        "unknownComponentField": {"keep": True},
        "metadata": {
            "unknownSetting": {"keep": [1, 2]},
            "instructions": {
                "$kind": "TemplateLine",
                "unknownInstructionField": "keep",
                "segments": [
                    {
                        "$kind": "TextSegment",
                        "value": "Old route. Other rule.",
                        "keep": True,
                    },
                    {
                        "$kind": "ExpressionSegment",
                        "expression": {
                            "$kind": "ValueExpression",
                            "variableReference": "System.User.DisplayName",
                        },
                    },
                    {"$kind": "TextSegment", "value": "End of instructions."},
                ],
            },
        },
    }


def _edits():
    return [{"segmentIndex": 0, "oldText": "Old route", "newText": "New route"}]


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
                status_code=status, headers={"x-ms-request-id": "correlation-id"}
            ),
            body if body is not None else {"nativeExtension": {"preserved": True}},
        )
    )
    monkeypatch.setattr(client, "_request", request)
    return client, request


def test_text_replacements_preserve_native_structure_and_use_original_offsets(
    component,
):
    before = copy.deepcopy(component)
    edits = [
        {"segmentIndex": 0, "oldText": "Old route", "newText": "Other rule"},
        {"segmentIndex": 0, "oldText": "Other rule", "newText": ""},
        {"segmentIndex": 2, "oldText": "End", "newText": "Approved end"},
    ]
    desired = native.build_agent_instruction_update(component, edits)
    assert component == before
    expected = copy.deepcopy(before)
    expected["metadata"]["instructions"]["segments"][0]["value"] = "Other rule. ."
    expected["metadata"]["instructions"]["segments"][2]["value"] = (
        "Approved end of instructions."
    )
    assert desired == expected


@pytest.mark.parametrize(
    "problem",
    [
        "expression",
        "ambiguous",
        "self-overlap",
        "overlap",
        "boolean-index",
        "extra-field",
    ],
)
def test_unsupported_text_edits_fail_without_mutation(component, problem):
    edits = _edits()
    if problem == "expression":
        edits[0]["segmentIndex"] = 1
    elif problem == "ambiguous":
        component["metadata"]["instructions"]["segments"][0]["value"] += " Old route."
    elif problem == "self-overlap":
        component["metadata"]["instructions"]["segments"][0]["value"] = "ababa"
        edits[0]["oldText"] = "aba"
    elif problem == "overlap":
        edits.append({"segmentIndex": 0, "oldText": "route", "newText": "answer"})
    elif problem == "boolean-index":
        edits[0]["segmentIndex"] = False
    else:
        edits[0]["expression"] = "unexpected"
    before = copy.deepcopy(component)
    with pytest.raises(native.MinimalBotEvaluationError):
        native.build_agent_instruction_update(component, edits)
    assert component == before


@pytest.mark.parametrize(
    "problem", ["missing", "duplicate", "wrong-bot", "wrong-parent", "missing-token"]
)
def test_native_read_requires_one_current_gpt_for_the_selected_agent(
    component, monkeypatch, problem
):
    payload = _payload(component)
    if problem == "missing":
        payload["botComponentChanges"].pop(0)
    elif problem == "duplicate":
        duplicate = copy.deepcopy(component)
        duplicate["id"] = "another-gpt"
        payload["botComponentChanges"].append({"component": duplicate})
    elif problem == "wrong-bot":
        payload["bot"]["cdsBotId"] = "another-agent"
    elif problem == "wrong-parent":
        payload["botComponentChanges"][0]["component"]["parentBotId"] = "another-agent"
    else:
        payload.pop("changeToken")
    client, request = _client(monkeypatch, [payload])
    with pytest.raises(native.MinimalBotEvaluationError):
        client.read_agent_instructions()
    request.assert_not_called()


def test_native_update_uses_fresh_token_one_gpt_and_authoritative_readback(
    component, monkeypatch
):
    desired = native.build_agent_instruction_update(component, _edits())
    after = _payload(desired)
    after["changeToken"] = "saved-token"
    after["botComponentChanges"][0]["component"]["version"] += 1
    after["botComponentChanges"][0]["component"]["auditInfo"]["modifiedOn"] = "after"
    after["botComponentChanges"][1]["component"]["version"] += 1
    client, request = _client(monkeypatch, [_payload(component), after])
    result = client.update_agent_instructions(component, _edits())
    request.assert_called_once()
    assert request.call_args.args == ("PUT", client._components_url)
    payload = request.call_args.kwargs["body"]
    assert payload["changeToken"] == "current-token"
    assert payload["botComponentChanges"] == [
        {"$kind": "BotComponentUpdate", "component": desired},
    ]
    assert "bot" not in payload
    assert all(
        value == []
        for key, value in payload.items()
        if key.endswith("Changes") and key != "botComponentChanges"
    )
    assert result["component"] == after["botComponentChanges"][0]["component"]
    assert result["updatedComponents"] == result["verifiedComponents"] == 1
    assert result["unchangedOtherComponents"] == 1
    assert result["requestId"] == "correlation-id"
    assert result["response"]["nativeExtension"] == {"preserved": True}


def test_stale_native_baseline_is_rejected_before_write(component, monkeypatch):
    stale = copy.deepcopy(component)
    stale["version"] -= 1
    client, request = _client(monkeypatch, [_payload(component)])
    with pytest.raises(native.MinimalBotEvaluationError, match="changed since"):
        client.update_agent_instructions(stale, _edits())
    request.assert_not_called()


def test_native_noop_is_a_read_not_a_write(component, monkeypatch):
    edits = _edits()
    edits[0]["newText"] = edits[0]["oldText"]
    client, request = _client(monkeypatch, [_payload(component)])
    result = client.update_agent_instructions(component, edits)
    assert result["updatedComponents"] == 0
    assert result["component"] == component
    request.assert_not_called()


@pytest.mark.parametrize("status", [400, 409, 500])
def test_service_failure_retains_causal_details_and_does_not_reconcile(
    component, monkeypatch, status
):
    body = {
        "error": {"code": "native-code", "unknownDetails": {"reason": "preserve"}},
        "access_token": "do-not-emit",
    }
    client, request = _client(
        monkeypatch, [_payload(component)], status=status, body=body
    )
    with pytest.raises(native.AgentInstructionEditError) as error:
        client.update_agent_instructions(component, _edits())
    assert error.value.evidence["httpStatus"] == status
    assert error.value.evidence["requestId"] == "correlation-id"
    assert error.value.evidence["response"]["error"] == body["error"]
    assert error.value.evidence["writeAttempted"] is True
    assert error.value.evidence["verified"] is False
    assert "do-not-emit" not in str(error.value)
    request.assert_called_once()
    assert client.read_components.call_count == 1


def test_transport_uncertainty_keeps_the_original_cause(component, monkeypatch):
    client, request = _client(monkeypatch, [_payload(component)])
    cause = requests.ReadTimeout("response was lost")
    transport_error = native.MinimalBotEvaluationError("instruction transport failed")
    transport_error.__cause__ = cause
    request.side_effect = transport_error
    with pytest.raises(
        native.AgentInstructionEditError, match="outcome is unknown"
    ) as error:
        client.update_agent_instructions(component, _edits())
    assert error.value.__cause__ is transport_error
    assert error.value.__cause__.__cause__ is cause
    assert "httpStatus" not in error.value.evidence
    assert error.value.evidence["verified"] is False
    request.assert_called_once()


@pytest.mark.parametrize(
    "problem",
    ["instructions", "metadata", "other-content", "other-deleted", "read-failed"],
)
def test_accepted_write_does_not_claim_success_when_verification_fails(
    component, monkeypatch, problem
):
    desired = native.build_agent_instruction_update(component, _edits())
    after = _payload(desired)
    if problem == "instructions":
        after = _payload(component)
    elif problem == "metadata":
        after["botComponentChanges"][0]["component"]["metadata"]["unknownSetting"] = {}
    elif problem == "other-content":
        after["botComponentChanges"][1]["component"]["dialog"]["unknownField"] = (
            "changed"
        )
    elif problem == "other-deleted":
        after["botComponentChanges"].pop()
    else:
        after = native.MinimalBotEvaluationError("readback unavailable")
    client, request = _client(monkeypatch, [_payload(component), after])
    with pytest.raises(
        native.AgentInstructionEditError, match="verification failed"
    ) as error:
        client.update_agent_instructions(component, _edits())
    assert error.value.evidence["httpStatus"] == 200
    assert error.value.evidence["verified"] is False
    assert isinstance(error.value.__cause__, native.MinimalBotEvaluationError)
    request.assert_called_once()


def test_unexpected_failure_is_not_swallowed(component, monkeypatch):
    client, request = _client(monkeypatch, [_payload(component)])
    failure = RuntimeError("unexpected failure")
    request.side_effect = failure
    with pytest.raises(RuntimeError) as error:
        client.update_agent_instructions(component, _edits())
    assert error.value is failure


@pytest.fixture
def instruction_cli(component, monkeypatch, tmp_path, fake_token, fake_tenant_id):
    target = {
        "environment": {
            "id": ENV_ID,
            "tenantId": fake_tenant_id,
            "ring": "test",
            "powerPlatformApiEndpoint": native._environment_host(ENV_ID, "test"),
        },
        "agent": {"id": BOT_ID, "schemaName": "contoso_agent", "realm": "dev"},
    }
    connection = SimpleNamespace(
        host=target["environment"]["powerPlatformApiEndpoint"],
        headers={"Authorization": f"Bearer {fake_token}"},
        session=object(),
    )
    transport = Mock()
    snapshot = {
        "component": component,
        "changeToken": "current-token",
        "componentCount": 2,
    }
    transport.read_agent_instructions.side_effect = lambda: copy.deepcopy(snapshot)
    transport.update_agent_instructions.side_effect = lambda expected, edits: {
        "component": native.build_agent_instruction_update(expected, edits),
        "updatedComponents": 1,
        "verifiedComponents": 1,
        "changeToken": "saved-token",
        "unchangedOtherComponents": 1,
    }
    monkeypatch.setattr(cli, "connect", Mock(return_value=(connection, target)))
    monkeypatch.setattr(cli, "MinimalBotEvaluationClient", Mock(return_value=transport))
    monkeypatch.chdir(tmp_path)
    baseline = tmp_path / "baseline.json"
    cli.main(["read", "--output", str(baseline)])
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"edits": _edits()}), encoding="utf-8")
    return SimpleNamespace(
        root=tmp_path,
        target=target,
        snapshot=snapshot,
        transport=transport,
        baseline=baseline,
        request=request,
        preview=tmp_path / "preview.json",
    )


def _preview(fixture):
    return cli.main(
        [
            "update",
            "--request",
            str(fixture.request),
            "--expected",
            str(fixture.baseline),
            "--output",
            str(fixture.preview),
        ]
    )


def test_cli_read_and_preview_compose_without_writes_then_explicit_save(
    instruction_cli,
):
    fixture = instruction_cli
    assert _preview(fixture) == 0
    preview = json.loads(fixture.preview.read_text(encoding="utf-8"))
    assert preview["component"] == fixture.snapshot["component"]
    assert preview["desiredComponent"]["metadata"]["instructions"]["segments"][0][
        "value"
    ] == ("New route. Other rule.")
    assert preview["saved"] is False and preview["changed"] is True
    fixture.transport.update_agent_instructions.assert_not_called()
    result = fixture.root / "result.json"
    assert (
        cli.main(
            [
                "update",
                "--request",
                str(fixture.request),
                "--expected",
                str(fixture.preview),
                "--yes",
                "--output",
                str(result),
            ]
        )
        == 0
    )
    fixture.transport.update_agent_instructions.assert_called_once_with(
        fixture.snapshot["component"],
        _edits(),
    )
    saved = json.loads(result.read_text(encoding="utf-8"))
    assert saved["saved"] is True
    assert saved["published"] is False and saved["conversationVerified"] is False


@pytest.mark.parametrize("drift", ["request", "target", "native", "read-not-preview"])
def test_cli_save_requires_the_same_preview_request_target_and_baseline(
    instruction_cli, drift
):
    fixture = instruction_cli
    _preview(fixture)
    expected = fixture.preview
    if drift == "request":
        edits = _edits()
        edits[0]["newText"] = "Unapproved change"
        fixture.request.write_text(json.dumps({"edits": edits}), encoding="utf-8")
    elif drift == "target":
        fixture.target["environment"]["ring"] = "prod"
    elif drift == "native":
        fixture.snapshot["component"]["version"] += 1
    else:
        expected = fixture.baseline
    with pytest.raises(
        ValueError, match="different target|changed since|approved preview"
    ):
        cli.main(
            [
                "update",
                "--request",
                str(fixture.request),
                "--expected",
                str(expected),
                "--yes",
            ]
        )
    fixture.transport.update_agent_instructions.assert_not_called()


def test_cli_does_not_overwrite_existing_evidence(instruction_cli):
    fixture = instruction_cli
    with pytest.raises(FileExistsError):
        cli.main(
            [
                "update",
                "--request",
                str(fixture.request),
                "--expected",
                str(fixture.baseline),
                "--yes",
                "--output",
                str(fixture.baseline),
            ]
        )
    fixture.transport.update_agent_instructions.assert_not_called()


def test_cli_output_failure_does_not_hide_an_observed_native_save(
    instruction_cli,
    monkeypatch,
    capsys,
):
    fixture = instruction_cli
    _preview(fixture)
    original_open = cli.Path.open
    result = fixture.root / "result.json"

    def fail_result_open(path, mode="r", *args, **kwargs):
        if path == result and mode == "x":
            raise PermissionError("result output is unavailable")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(cli.Path, "open", fail_result_open)
    capsys.readouterr()
    with pytest.raises(PermissionError, match="result output is unavailable"):
        cli.main(
            [
                "update",
                "--request",
                str(fixture.request),
                "--expected",
                str(fixture.preview),
                "--yes",
                "--output",
                str(result),
            ]
        )
    observed = json.loads(capsys.readouterr().out)
    assert observed["saved"] is True and observed["verifiedComponents"] == 1
    fixture.transport.update_agent_instructions.assert_called_once()
