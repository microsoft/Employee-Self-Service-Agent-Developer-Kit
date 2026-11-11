# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import argparse
import builtins
from copy import deepcopy
import json
from pathlib import Path

import pytest

import daga_chat_driver
from drive_surface import Bubble, aggregate_turn
import native_topic_test as native
from minimalbot_evaluation import MinimalBotEvaluationClient, MinimalBotEvaluationError


AGENT_ID = "00000000-0000-4000-8000-000000002222"
COMPONENT_ID = "00000000-0000-4000-8000-000000004444"
PROMPT = "show the saved test answer"
ANSWER = "Approved test response."
TARGET = {
    "environment": {
        "id": "00000000-0000-4000-8000-000000001111",
        "tenantId": "00000000-0000-4000-8000-000000009999",
        "ring": "test",
        "powerPlatformApiEndpoint": "https://example.test",
        "apiVersion": "2024-10-01",
    },
    "agent": {"id": AGENT_ID, "schemaName": "gptagent_test", "realm": "dev"},
}
URL = (
    "https://copilotstudio.test.microsoft.com/environments/"
    f"{TARGET['environment']['id']}/copilots/{AGENT_ID}/details?agentBackend=cosmos"
)


@pytest.fixture(autouse=True)
def no_operation_capability_events(monkeypatch):
    def emit(event, _data, **_kwargs):
        assert event != "adk.capability.use", "Testing passes belong to the skill."
        return {}

    monkeypatch.setattr("adk_telemetry._emit", emit)


@pytest.fixture
def component():
    # Expanded native literal shape verified by the live Maker-topic inspection.
    return {
        "$kind": "DialogComponent", "id": COMPONENT_ID, "version": 3,
        "state": "Active", "status": "Active",
        "dialog": {
            "$kind": "AdaptiveDialog",
            "beginDialog": {
                "$kind": "OnRecognizedIntent",
                "intent": {"$kind": "Intent", "triggerQueries": [PROMPT]},
                "actions": [
                    {
                        "$kind": "SendActivity",
                        "activity": {
                            "$kind": "Message",
                            "text": [{
                                "$kind": "TemplateLine",
                                "segments": [{"$kind": "TextSegment", "value": ANSWER}],
                            }],
                        },
                    },
                    {"$kind": "EndDialog"},
                ],
            },
        },
    }


@pytest.mark.parametrize("unsupported", ["expression", "extra-action", "malformed"])
def test_literal_response_rejects_nonliteral_shapes(component, unsupported):
    assert native.literal_response(component) == (ANSWER, [PROMPT])
    actions = component["dialog"]["beginDialog"]["actions"]
    if unsupported == "expression":
        actions[0]["activity"]["text"][0]["segments"][0] = {
            "$kind": "ExpressionSegment", "expression": "Global.answer",
        }
    elif unsupported == "extra-action":
        actions.insert(1, {"$kind": "BeginDialog", "dialog": "another-topic"})
    else:
        component["dialog"]["beginDialog"]["actions"] = ["not-an-action"]
    with pytest.raises(ValueError, match="Unsupported"):
        native.literal_response(component)


@pytest.mark.parametrize(
    "capture",
    [
        None,
        aggregate_turn([Bubble(ANSWER)], timed_out=True),
        aggregate_turn([]),
        aggregate_turn([Bubble(ANSWER, had_card=True)]),
        aggregate_turn([Bubble("", had_card=True)]),
    ],
)
def test_nonreplies_and_cards_never_pass_exact_response(capture):
    result = native.assess(capture, ANSWER, True)
    assert result["checks"]["savedResponse"]["assessed"] is False
    assert result["checks"]["savedResponse"]["met"] is None
    assert result["outcome"] != "passed"


def test_exact_response_requires_case_sensitive_match_and_native_integrity():
    capture = aggregate_turn([Bubble(ANSWER)])
    assert native.assess(capture, ANSWER, True)["outcome"] == "passed"
    assert native.assess(capture, ANSWER.lower(), True)["outcome"] == "failed"
    assert native.assess(capture, ANSWER, None)["outcome"] == "incomplete"
    assert native.assess(capture, ANSWER, False)["outcome"] == "failed"


def test_exact_complete_noncard_response_can_contain_advisory_consent_text():
    answer = "Open connection manager to verify your credentials."
    result = native.assess(aggregate_turn([Bubble(answer)]), answer, True)
    assert result["signal"] == "consent_gate"
    assert result["checks"]["savedResponse"]["met"] is True
    assert result["outcome"] == "passed"
    assert native.assess(
        aggregate_turn([Bubble(answer)]), ANSWER, True,
    )["outcome"] != "passed"
    assert native.assess(
        aggregate_turn([Bubble(answer)], timed_out=True), answer, True,
    )["outcome"] == "timeout"
    assert native.assess(
        aggregate_turn([Bubble(answer, had_card=True)]), answer, True,
    )["outcome"] == "unsupported_reply"


@pytest.fixture
def exercise(tmp_path, component, monkeypatch):
    evidence = tmp_path / ".local" / "topic-tests"
    evidence.mkdir(parents=True)
    inspection = evidence / "inspection.json"
    native._write(inspection, {
        "schemaVersion": 1, "operation": "inspect",
        "target": TARGET, "component": deepcopy(component),
    })
    args = argparse.Namespace(
        operation="run", inspection=inspection, prompt=PROMPT,
        cdp="http://127.0.0.1:9222", url=URL,
        output=evidence / "attempt", timeout=1,
        require_empty_conversation=False,
    )
    calls = []

    class Client:
        def fetch_components(self, agent_id):
            assert agent_id == AGENT_ID
            return {"botComponentChanges": [{"component": deepcopy(component)}]}

    class Driver:
        def __init__(self, *, cdp, expected_url):
            assert cdp == args.cdp and expected_url == URL

        def start(self):
            calls.append("start")

        def reset(self):
            calls.append("reset")
            return True

        def prepare(self):
            return {
                "pageTargetId": "owned-page", "expectedTurnIndex": 0,
                "chatDocumentTimeOrigin": 1000,
            }

        def send(self, text, timeout_s):
            calls.append(("send", text))
            return [Bubble(ANSWER)], True

        def observe(self, text, boundary, timeout_s):
            calls.append(("observe", text, boundary))
            return aggregate_turn([Bubble(ANSWER)])

        def observation(self):
            return {"turnElementId": "current-turn", "responseId": "current-response"}

        def screenshot(self, path):
            calls.append("screenshot")
            path.write_bytes(b"test screenshot")

        def close(self):
            calls.append("close")

    monkeypatch.setattr(daga_chat_driver, "DagaChatDriver", Driver)
    return args, Client(), calls


@pytest.mark.parametrize("failure", [None, "target", "click"])
def test_new_conversation_cli_clicks_without_capture_or_component_changes(
    exercise, tmp_path, monkeypatch, capsys, failure,
):
    args, client, calls = exercise
    monkeypatch.setattr(
        native, "connect_selected_dev_workspace", lambda *_args: (client, TARGET),
    )

    def unexpected_components(*_args):
        pytest.fail("Starting a new conversation must not read or change topic components.")

    monkeypatch.setattr(client, "fetch_components", unexpected_components)
    if failure == "click":
        def failed_click(_self):
            calls.append("reset")
            raise RuntimeError("New chat click failed")

        monkeypatch.setattr(daga_chat_driver.DagaChatDriver, "reset", failed_click)
    url = URL.replace(AGENT_ID, COMPONENT_ID) if failure == "target" else URL
    code = native.main([
        "new-conversation", "--kit-root", str(tmp_path), "--cdp", args.cdp, "--url", url,
    ])
    output = capsys.readouterr()

    if failure:
        assert code == 2
        error = json.loads(output.err)["error"]
        assert error["type"] == ("ValueError" if failure == "target" else "RuntimeError")
        assert ("selected agent" if failure == "target" else "New chat click failed") in error["message"]
    else:
        assert code == 0
        result = json.loads(output.out)
        assert result["operation"] == "new-conversation"
        assert result["outcome"] == "clicked"
        assert result["target"] == TARGET
    assert calls == ([] if failure == "target" else ["start", "reset", "close"])
    assert not args.output.exists()


@pytest.mark.parametrize("failure", ["changed", "inactive", "target", "phrase"])
def test_native_gates_block_before_browser_start(exercise, component, failure, tmp_path):
    args, client, calls = exercise
    if failure == "changed":
        component["dialog"]["beginDialog"]["intent"]["triggerQueries"].append("another phrase")
    elif failure == "inactive":
        component["state"] = "Inactive"
        inspected = native._read(args.inspection)
        inspected["component"] = component
        args.inspection.write_text(json.dumps(inspected), encoding="utf-8")
    elif failure == "target":
        inspected = native._read(args.inspection)
        inspected["target"]["agent"]["id"] = COMPONENT_ID
        args.inspection.write_text(json.dumps(inspected), encoding="utf-8")
    else:
        args.prompt = "an invented phrase"
    with pytest.raises(ValueError):
        native._exercise(args, tmp_path, client, TARGET)
    assert not calls
    assert not args.output.exists()


def test_timeout_then_observe_preserves_original_and_does_not_send(exercise, tmp_path):
    args, client, calls = exercise
    original, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == 1 and original["outcome"] == "timeout"
    original_result = (args.output / "result.json").read_bytes()
    original_execution = (args.output / "execution.json").read_bytes()
    args.operation = "observe"
    args.previous = args.output
    args.output = None
    result, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == 0 and result["outcome"] == "passed"
    assert [call for call in calls if isinstance(call, tuple) and call[0] == "send"] == [
        ("send", PROMPT)
    ]
    observed = [call for call in calls if isinstance(call, tuple) and call[0] == "observe"]
    assert observed == [(
        "observe", PROMPT,
        {"pageTargetId": "owned-page", "expectedTurnIndex": 0,
         "chatDocumentTimeOrigin": 1000, "expectedResponseId": "current-response"},
    )]
    assert (args.previous / "result.json").read_bytes() == original_result
    assert (args.previous / "execution.json").read_bytes() == original_execution
    with pytest.raises(FileExistsError):
        args.operation = "run"
        args.output = args.previous
        native._exercise(args, tmp_path, client, TARGET)


def test_error_facts_preserve_cause():
    try:
        try:
            raise RuntimeError("Send control stayed disabled")
        except RuntimeError as cause:
            raise RuntimeError("Submission not confirmed") from cause
    except RuntimeError as error:
        facts = native._error_facts(error)
    assert facts["cause"] == {
        "type": "RuntimeError", "message": "Send control stayed disabled",
    }


def test_cleanup_failure_is_reported_without_losing_native_readback(exercise, tmp_path, monkeypatch):
    args, client, calls = exercise

    def failed_close(_self):
        raise RuntimeError("Browser disconnect failed")

    monkeypatch.setattr(daga_chat_driver.DagaChatDriver, "close", failed_close)
    result, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == 2 and result["outcome"] == "incomplete"
    assert result["checks"]["selectedTopicUnchanged"]["met"] is True
    assert result["error"]["cleanupError"]["message"] == "Browser disconnect failed"
    assert calls.count(("send", PROMPT)) == 1


def test_observe_retains_confirmed_response_identity_after_capture_error(
    exercise, tmp_path, monkeypatch,
):
    args, client, calls = exercise

    def failed_capture(_self, text, timeout_s):
        calls.append(("send", text))
        raise RuntimeError("Capture interrupted after confirming the user turn")

    monkeypatch.setattr(daga_chat_driver.DagaChatDriver, "send", failed_capture)
    original, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == 2 and original["observation"]["responseId"] == "current-response"
    args.operation, args.previous, args.output = "observe", args.output, None
    result, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == 0 and result["outcome"] == "passed"
    observed = [call for call in calls if isinstance(call, tuple) and call[0] == "observe"]
    assert observed[0][2]["expectedResponseId"] == "current-response"
    assert calls.count(("send", PROMPT)) == 1


@pytest.fixture
def completed_exercise(exercise, monkeypatch):
    args, client, calls = exercise

    def completed_send(_self, text, timeout_s):
        calls.append(("send", text))
        return [Bubble(ANSWER)], False

    monkeypatch.setattr(daga_chat_driver.DagaChatDriver, "send", completed_send)
    return args, client, calls


def test_inspection_allows_unrelated_selected_component_metadata_changes(
    completed_exercise, component, tmp_path,
):
    args, client, calls = completed_exercise
    component["version"] += 1
    component["displayName"] = "Updated label"
    result, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == 0 and result["outcome"] == "passed"
    assert calls.count(("send", PROMPT)) == 1


@pytest.mark.parametrize(
    "change,unchanged",
    [("other-added", True), ("other-removed", True), ("other-changed", True),
     ("metadata", True), ("dialog", False), ("inactive", False),
     ("identity", False), ("removed", False)],
)
def test_integrity_is_scoped_to_selected_topic_with_all_drift_retained(
    completed_exercise, component, tmp_path, monkeypatch, change, unchanged,
):
    args, client, _calls = completed_exercise
    other_id = "00000000-0000-4000-8000-000000005555"
    reads = 0

    def fetch(_agent_id):
        nonlocal reads
        reads += 1
        selected = deepcopy(component)
        other = {"id": other_id, "$kind": "GptComponent", "version": reads}
        components = [selected]
        if change != "other-added" or reads > 1:
            components.append(other)
        if reads > 1:
            if change == "other-removed":
                components.remove(other)
            elif change == "metadata":
                selected["version"] += 1
            elif change == "dialog":
                selected["dialog"]["modelDescription"] = "Changed routing intent"
            elif change == "inactive":
                selected["status"] = "Inactive"
            elif change == "identity":
                selected["schemaName"] = "another.topic"
            elif change == "removed":
                components.remove(selected)
        return {"botComponentChanges": [{"component": value} for value in components]}

    monkeypatch.setattr(client, "fetch_components", fetch)
    result, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == (0 if unchanged else 1)
    assert result["checks"]["selectedTopicUnchanged"]["met"] is unchanged
    assert result["checks"]["savedResponse"]["met"] is True
    assert any(result["componentDrift"].values())
    assert native._read(args.output / "native-after.json") == result["nativeReadback"]


def test_screenshot_failure_is_diagnostic_with_its_original_cause(
    completed_exercise, tmp_path, monkeypatch,
):
    args, client, _calls = completed_exercise

    def failed_screenshot(_self, _path):
        try:
            raise OSError("Screenshot file is unavailable")
        except OSError as cause:
            raise RuntimeError("Current-turn screenshot failed") from cause

    monkeypatch.setattr(daga_chat_driver.DagaChatDriver, "screenshot", failed_screenshot)
    result, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == 0 and result["outcome"] == "passed"
    assert result["diagnostics"]["screenshotError"]["cause"] == {
        "type": "OSError", "message": "Screenshot file is unavailable",
    }
    assert result["capture"]["replyText"] == ANSWER
    assert result["checks"]["selectedTopicUnchanged"]["met"] is True


@pytest.mark.parametrize("filename", ["capture.json", "native-after.json", "result.json"])
def test_output_failure_preserves_known_capture_and_readback(
    completed_exercise, tmp_path, monkeypatch, filename,
):
    args, client, calls = completed_exercise
    write = native._write

    def failed_write(path, value):
        if path.name == filename:
            raise OSError(f"Cannot write {filename}")
        write(path, value)

    monkeypatch.setattr(native, "_write", failed_write)
    result, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == 2 and result["outcome"] == "incomplete"
    assert result["assessmentOutcome"] == "passed"
    assert result["capture"]["replyText"] == ANSWER
    assert result["nativeReadback"]["component"]["id"] == COMPONENT_ID
    assert result["checks"]["savedResponse"]["met"] is True
    assert result["checks"]["selectedTopicUnchanged"]["met"] is True
    assert result["observation"]["responseId"] == "current-response"
    assert result["submissionMayHaveOccurred"] is True
    assert result["evidenceWriteErrors"] == [{
        "file": filename, "error": {"type": "OSError", "message": f"Cannot write {filename}"},
    }]
    assert calls.count(("send", PROMPT)) == 1


def test_required_execution_recording_failure_blocks_send(
    completed_exercise, tmp_path, monkeypatch,
):
    args, client, calls = completed_exercise
    write = native._write

    def failed_write(path, value):
        if path.name == "execution.json":
            raise OSError("Cannot record the pre-send boundary")
        write(path, value)

    monkeypatch.setattr(native, "_write", failed_write)
    result, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == 2 and result["outcome"] == "blocked"
    assert result["submissionMayHaveOccurred"] is False
    assert result["capture"] is None
    assert result["error"]["captureError"]["message"] == "Cannot record the pre-send boundary"
    assert result["checks"]["selectedTopicUnchanged"]["met"] is True
    assert not any(isinstance(call, tuple) and call[0] == "send" for call in calls)


def test_readback_failure_survives_later_result_write_failure(
    completed_exercise, tmp_path, monkeypatch,
):
    args, client, _calls = completed_exercise
    fetch = client.fetch_components
    write = native._write
    reads = 0

    def failed_readback(agent_id):
        nonlocal reads
        reads += 1
        if reads > 1:
            raise native.requests.ConnectionError("Authoritative readback unavailable")
        return fetch(agent_id)

    def failed_write(path, value):
        if path.name == "result.json":
            raise OSError("Result directory became read-only")
        write(path, value)

    monkeypatch.setattr(client, "fetch_components", failed_readback)
    monkeypatch.setattr(native, "_write", failed_write)
    result, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == 2 and result["outcome"] == "incomplete"
    assert result["capture"]["replyText"] == ANSWER
    assert result["checks"]["selectedTopicUnchanged"]["assessed"] is False
    assert result["error"]["nativeReadbackError"]["message"] == "Authoritative readback unavailable"
    assert result["evidenceWriteErrors"][0]["error"]["message"] == "Result directory became read-only"


def test_result_output_failure_returns_known_facts_through_cli(
    completed_exercise, tmp_path, monkeypatch, capsys,
):
    args, client, calls = completed_exercise
    write = native._write

    def failed_write(path, value):
        if path.name == "result.json":
            raise OSError("Result file unavailable")
        write(path, value)

    monkeypatch.setattr(native, "_write", failed_write)
    monkeypatch.setattr(native, "connect_selected_dev_workspace", lambda *_args: (client, TARGET))
    code = native.main([
        "run", "--kit-root", str(tmp_path), "--inspection", str(args.inspection),
        "--prompt", PROMPT, "--cdp", args.cdp, "--url", URL, "--output", str(args.output),
    ])
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert code == 2 and not output.err
    assert result["outcome"] == "incomplete" and result["assessmentOutcome"] == "passed"
    assert result["capture"]["replyText"] == ANSWER
    assert result["nativeReadback"]["component"]["id"] == COMPONENT_ID
    assert result["evidenceWriteErrors"][0]["error"]["message"] == "Result file unavailable"
    assert calls.count(("send", PROMPT)) == 1


def test_later_observation_keeps_original_snapshot_and_expectation(
    exercise, tmp_path, monkeypatch,
):
    args, client, calls = exercise
    _result, _code = native._exercise(args, tmp_path, client, TARGET)
    original_snapshot = native._read(args.output / "native-before.json")
    other_id = "00000000-0000-4000-8000-000000005555"
    fetch = client.fetch_components

    def changed_inventory(agent_id):
        result = fetch(agent_id)
        result["botComponentChanges"].append({"component": {"id": other_id, "$kind": "GptComponent"}})
        return result

    monkeypatch.setattr(client, "fetch_components", changed_inventory)
    args.operation, args.previous, args.output = "observe", args.output, None
    result, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == 0 and result["outcome"] == "passed"
    assert result["componentDrift"]["added"] == [other_id]
    assert native._read(args.previous / "native-before.json") == original_snapshot
    assert calls.count(("send", PROMPT)) == 1

    execution_path = args.previous / "execution.json"
    execution = native._read(execution_path)
    execution["expectation"]["text"] = "A replacement expectation"
    execution_path.write_text(json.dumps(execution), encoding="utf-8")
    calls.clear()
    with pytest.raises(ValueError, match="original response"):
        native._exercise(args, tmp_path, client, TARGET)
    assert not calls


@pytest.fixture
def ordinary_dialog(component):
    # Existing expanded native Object Model fields; literal extraction cannot
    # grade a topic that continues into another dialog.
    component["dialog"]["beginDialog"]["actions"].insert(
        0, {"$kind": "BeginDialog", "dialog": "another-topic"},
    )
    return component


@pytest.mark.parametrize("literal", [False, True])
def test_inspect_returns_authoritative_topic_without_requiring_exact_mode(
    exercise, component, tmp_path, monkeypatch, capsys, literal,
):
    args, client, calls = exercise
    if not literal:
        component["dialog"]["beginDialog"]["actions"].append({"$kind": "BeginDialog"})
    monkeypatch.setattr(native, "connect_selected_dev_workspace", lambda *_args: (client, TARGET))
    assert native.main([
        "inspect", "--kit-root", str(tmp_path), "--component-id", COMPONENT_ID,
        "--output", str(args.output),
    ]) == 0
    result = json.loads(capsys.readouterr().out)
    inspection = native._read(args.output / "inspection.json")
    assert inspection["component"] == result["component"] == component
    assert inspection["triggers"] == [PROMPT]
    assert inspection["response"] == (ANSWER if literal else None)
    assert inspection["exactMode"]["supported"] is literal
    assert result["inspectionEvidence"]["componentHash"] == native._hash(component)
    assert result["state"] == result["status"] == "Active"
    assert not calls


def test_general_inspection_preserves_trigger_configuration_without_assuming_phrases(component):
    component["dialog"]["beginDialog"]["$kind"] = "OnConversationStart"
    component["dialog"]["beginDialog"].pop("intent")
    result = native._inspection(component, TARGET)
    assert result["triggers"] is None
    assert result["inspectionEvidence"]["triggerKind"] == "OnConversationStart"
    assert result["exactMode"]["supported"] is False
    assert result["component"] == component


@pytest.fixture
def general_exercise(completed_exercise, ordinary_dialog):
    args, client, calls = completed_exercise
    inspection = native._read(args.inspection)
    inspection["component"] = deepcopy(ordinary_dialog)
    args.inspection.write_text(json.dumps(inspection), encoding="utf-8")
    args.operation = "capture"
    args.prompt = "An approved paraphrase, not one of the saved triggers"
    return args, client, calls


@pytest.mark.parametrize("timed_out", [False, True])
def test_capture_preserves_arbitrary_prompt_cards_and_partial_facts_without_grading(
    general_exercise, tmp_path, monkeypatch, timed_out,
):
    args, client, calls = general_exercise

    def card_send(_self, text, timeout_s):
        calls.append(("send", text))
        return [Bubble("", had_card=True), Bubble("An interim or follow-up reply")], timed_out

    monkeypatch.setattr(daga_chat_driver.DagaChatDriver, "send", card_send)
    result, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == (1 if timed_out else 0)
    assert result["outcome"] == ("timeout" if timed_out else "captured")
    assert result["mode"] == "capture" and result["graded"] is False
    assert "checks" not in result and "assessmentOutcome" not in result
    assert result["capture"]["hadCard"] is True
    assert result["capture"]["bubbles"] == [
        {"text": "", "hadCard": True}, {"text": "An interim or follow-up reply", "hadCard": False},
    ]
    assert result["capture"]["partial"] is timed_out
    assert result["capture"]["completionObserved"] is not timed_out
    assert result["selectedTopicUnchanged"] is True
    assert result["nativeReadback"]["component"]["id"] == COMPONENT_ID
    assert calls.count(("send", args.prompt)) == 1
    assert native._read(args.output / "execution.json")["expectation"] is None
    assert native._read(args.output / "native-before.json")["component"]["id"] == COMPONENT_ID
    assert any("card interactions" in limitation for limitation in result["limitations"])


def test_capture_allows_repeated_explicit_known_completed_turns(general_exercise, tmp_path):
    args, client, calls = general_exercise
    first, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == 0 and first["capture"]["completionObserved"] is True
    args.output = args.output.with_name("next-explicit-attempt")
    second, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == 0 and second["graded"] is False
    assert calls.count(("send", args.prompt)) == 2


@pytest.mark.parametrize(
    ("text", "timed_out", "signal", "error_shaped"),
    [
        ("A completed answer", False, "ok", False),
        ("Error code: 400", False, "ok", True),
        ("Connect to continue", False, "consent_gate", False),
        ("", False, "empty", False),
        ("A partial answer", True, "timeout", False),
    ],
)
def test_capture_classifies_replies_without_grading_or_replaying(
    general_exercise, tmp_path, monkeypatch, text, timed_out, signal, error_shaped,
):
    args, client, calls = general_exercise

    def send(_self, prompt, timeout_s):
        calls.append(("send", prompt))
        return [Bubble(text)] if text else [], timed_out

    monkeypatch.setattr(daga_chat_driver.DagaChatDriver, "send", send)
    result, code = native._exercise(args, tmp_path, client, TARGET)
    assert result["signal"] == signal and result["errorShaped"] is error_shaped
    assert result["graded"] is False
    assert result["outcome"] == ("timeout" if timed_out else "captured")
    assert code == (1 if timed_out else 0)
    assert calls.count(("send", args.prompt)) == 1


@pytest.mark.parametrize(
    "boundary",
    [
        {},
        {"renderedTurnsBefore": 1, "expectedTurnIndex": 1},
        {"renderedTurnsBefore": False, "expectedTurnIndex": 0},
        {"renderedTurnsBefore": 0, "expectedTurnIndex": 1},
        {"renderedTurnsBefore": 0, "expectedTurnIndex": 0, "beforeTurnIndex": 0},
        {"renderedTurnsBefore": 0, "expectedTurnIndex": 0, "beforeTurnElementId": "old-turn"},
    ],
)
def test_required_empty_conversation_blocks_nonempty_or_unknown_boundaries(
    general_exercise, tmp_path, monkeypatch, boundary,
):
    args, client, calls = general_exercise
    args.require_empty_conversation = True
    monkeypatch.setattr(daga_chat_driver.DagaChatDriver, "prepare", lambda _self: boundary)
    result, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == 2 and result["outcome"] == "blocked"
    assert result["submissionMayHaveOccurred"] is False and result["capture"] is None
    assert result["diagnostics"]["conversationBoundary"] == boundary
    assert "No message was sent" in result["error"]["captureError"]["message"]
    assert not (args.output / "execution.json").exists()
    assert not any(isinstance(call, tuple) for call in calls)
    assert calls == ["start", "close"]


def test_empty_conversation_gate_preserves_timeout_for_observation_without_reset(
    general_exercise, tmp_path, monkeypatch,
):
    args, client, calls = general_exercise
    args.require_empty_conversation = True
    boundary = {
        "pageTargetId": "owned-page", "chatDocumentTimeOrigin": 1000,
        "renderedTurnsBefore": 0, "beforeTurnIndex": None, "beforeTurnElementId": None,
        "expectedTurnIndex": 0,
    }
    monkeypatch.setattr(daga_chat_driver.DagaChatDriver, "prepare", lambda _self: boundary)

    def send(_self, prompt, timeout_s):
        calls.append(("send", prompt))
        return [Bubble("Partial answer")], True

    monkeypatch.setattr(daga_chat_driver.DagaChatDriver, "send", send)
    original, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == 1 and original["signal"] == "timeout"
    execution_path = args.output / "execution.json"
    original_execution = execution_path.read_bytes()
    execution = native._read(execution_path)
    assert execution["requireEmptyConversation"] is True
    assert execution["boundary"] == boundary
    assert "not established by DOM alone" in execution["isolation"]
    args.operation, args.previous, args.output = "observe", args.output, None
    result, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == 0 and result["requireEmptyConversation"] is True
    assert result["submissionMayHaveOccurred"] is False
    assert calls.count(("send", args.prompt)) == 1
    assert len([call for call in calls if isinstance(call, tuple) and call[0] == "observe"]) == 1
    assert execution_path.read_bytes() == original_execution


def test_empty_conversation_cli_gate_runs_before_send(
    general_exercise, tmp_path, monkeypatch, capsys,
):
    args, client, calls = general_exercise
    monkeypatch.setattr(native, "connect_selected_dev_workspace", lambda *_args: (client, TARGET))
    monkeypatch.setattr(daga_chat_driver.DagaChatDriver, "prepare", lambda _self: {
        "renderedTurnsBefore": 2, "expectedTurnIndex": 2,
    })
    code = native.main([
        "capture", "--kit-root", str(tmp_path), "--inspection", str(args.inspection),
        "--prompt", args.prompt, "--cdp", args.cdp, "--url", URL, "--output", str(args.output),
        "--require-empty-conversation",
    ])
    result = json.loads(capsys.readouterr().out)
    assert code == 2 and result["requireEmptyConversation"] is True
    assert result["submissionMayHaveOccurred"] is False
    assert calls == ["start", "close"]
    with pytest.raises(SystemExit) as exc:
        native.main(["observe", "--previous", str(args.output), "--require-empty-conversation"])
    assert exc.value.code == 2
    assert calls == ["start", "close"]


@pytest.mark.parametrize("interrupted", [False, True])
def test_observe_original_capture_never_sends_or_acquires_an_exact_grade(
    general_exercise, tmp_path, monkeypatch, interrupted,
):
    args, client, calls = general_exercise

    def uncertain_send(_self, text, timeout_s):
        calls.append(("send", text))
        if interrupted:
            raise RuntimeError("Send outcome is ambiguous; observe without replay")
        return [Bubble("Partial", had_card=True)], True

    monkeypatch.setattr(daga_chat_driver.DagaChatDriver, "send", uncertain_send)
    original, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == (2 if interrupted else 1)
    assert original["graded"] is False and original["submissionMayHaveOccurred"] is True
    original_result = (args.output / "result.json").read_bytes()
    args.operation, args.previous, args.output = "observe", args.output, None
    result, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == 0 and result["outcome"] == "captured"
    assert result["mode"] == "capture" and result["graded"] is False
    assert "checks" not in result and "assessmentOutcome" not in result
    assert result["submissionMayHaveOccurred"] is False
    assert native._read(Path(result["evidenceDirectory"]) / "execution.json")[
        "expectation"
    ] is None
    assert calls.count(("send", args.prompt)) == 1
    observed = [call for call in calls if isinstance(call, tuple) and call[0] == "observe"]
    assert len(observed) == 1 and observed[0][2]["expectedResponseId"] == "current-response"
    assert (args.previous / "result.json").read_bytes() == original_result


@pytest.mark.parametrize("failure", ["target", "dialog", "state", "parent", "empty-prompt"])
def test_capture_gates_stale_target_content_and_active_state_before_send(
    general_exercise, component, tmp_path, failure,
):
    args, client, calls = general_exercise
    if failure == "target":
        inspection = native._read(args.inspection)
        inspection["target"]["environment"]["id"] = COMPONENT_ID
        args.inspection.write_text(json.dumps(inspection), encoding="utf-8")
    elif failure == "dialog":
        component["dialog"]["modelDescription"] = "Changed approved behavior"
    elif failure == "parent":
        component["parentBotId"] = COMPONENT_ID
    elif failure == "state":
        component["state"] = component["status"] = "Inactive"
        inspection = native._read(args.inspection)
        inspection["component"] = deepcopy(component)
        args.inspection.write_text(json.dumps(inspection), encoding="utf-8")
    else:
        args.prompt = " "
    with pytest.raises(ValueError):
        native._exercise(args, tmp_path, client, TARGET)
    assert not calls and not args.output.exists()


def test_capture_output_failure_does_not_replace_known_facts_with_a_grade(
    general_exercise, tmp_path, monkeypatch,
):
    args, client, _calls = general_exercise
    write = native._write

    def failed_write(path, value):
        if path.name == "result.json":
            raise OSError("Captured evidence directory is unavailable")
        write(path, value)

    monkeypatch.setattr(native, "_write", failed_write)
    result, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == 2 and result["outcome"] == "incomplete"
    assert result["graded"] is False and result["capture"]["completionObserved"] is True
    assert result["nativeReadback"]["component"]["id"] == COMPONENT_ID
    assert "assessmentOutcome" not in result


def test_capture_cli_returns_observations_without_counting_a_pass(
    general_exercise, tmp_path, monkeypatch, capsys,
):
    args, client, calls = general_exercise
    monkeypatch.setattr(native, "connect_selected_dev_workspace", lambda *_args: (client, TARGET))
    code = native.main([
        "capture", "--kit-root", str(tmp_path), "--inspection", str(args.inspection),
        "--prompt", args.prompt, "--cdp", args.cdp, "--url", URL, "--output", str(args.output),
    ])
    result = json.loads(capsys.readouterr().out)
    assert code == 0 and result["graded"] is False
    assert calls.count(("send", args.prompt)) == 1


def test_basic_only_browser_testing_is_explicitly_unsupported(
    general_exercise, tmp_path, monkeypatch, capsys,
):
    args, client, calls = general_exercise
    monkeypatch.setattr(native, "connect_selected_dev_workspace", lambda *_args: (client, TARGET))
    import_module = builtins.__import__

    def missing_driver(name, *import_args, **kwargs):
        if name == "daga_chat_driver":
            raise ModuleNotFoundError("No module named 'playwright'")
        return import_module(name, *import_args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_driver)
    code = native.main([
        "capture", "--kit-root", str(tmp_path), "--inspection", str(args.inspection),
        "--prompt", args.prompt, "--cdp", args.cdp, "--url", URL, "--output", str(args.output),
    ])
    output = capsys.readouterr()
    result = json.loads(output.err)
    assert code == 2 and not output.out
    assert result["outcome"] == "blocked"
    assert "Basic-only installations do not support browser testing" in result["error"]["message"]
    assert result["error"]["cause"]["message"] == "No module named 'playwright'"
    assert not calls and not args.output.exists()


@pytest.mark.parametrize("failure", ["changed", "readback"])
def test_capture_native_integrity_failure_preserves_non_graded_reply(
    general_exercise, component, tmp_path, monkeypatch, failure,
):
    args, client, calls = general_exercise
    fetch = client.fetch_components
    reads = 0

    def native_read(agent_id):
        nonlocal reads
        reads += 1
        if reads > 1:
            if failure == "readback":
                raise native.requests.ConnectionError("Native readback unavailable")
            component["status"] = "Inactive"
        return fetch(agent_id)

    monkeypatch.setattr(client, "fetch_components", native_read)
    result, code = native._exercise(args, tmp_path, client, TARGET)
    assert code == (2 if failure == "readback" else 1)
    assert result["outcome"] == "incomplete" and result["graded"] is False
    assert result["selectedTopicUnchanged"] is (None if failure == "readback" else False)
    assert result["capture"]["replyText"] == ANSWER
    assert "checks" not in result and calls.count(("send", args.prompt)) == 1


@pytest.fixture
def activation(exercise, component, monkeypatch):
    args, client, calls = exercise
    component.update({
        "state": "Inactive", "status": "Inactive",
        "schemaName": "gptagent_test.topic.Selected",
        "parentBotId": AGENT_ID,
        "extensionData": {"UseProvidedBotComponentId": True},
    })
    args.inspection.write_text(json.dumps(native._inspection(component, TARGET)), encoding="utf-8")
    args.operation, args.yes = "activate", False
    # Exercise the existing native components transport contract locally. Its
    # BotComponentUpdate, changeToken and state/status fields are sourced from
    # MinimalBotEvaluationClient.update_dialog_components, not a guessed API.
    runtime = MinimalBotEvaluationClient(
        TARGET["environment"]["id"], AGENT_ID, TARGET["environment"]["tenantId"],
        host="https://example.test", access_token="local-test-token",
        session=native.requests.Session(),
    )
    writes = []

    def request(method, url, *, body=None, operation="request", params=None):
        response = native.requests.Response()
        response.status_code = 200
        response.headers["x-ms-request-id"] = "local-request"
        if method == "POST":
            return response, {**client.fetch_components(AGENT_ID), "changeToken": "local-token"}
        assert method == "PUT" and body["changeToken"] == "local-token"
        writes.append(deepcopy(body))
        assert len(body["botComponentChanges"]) == 1
        change = body["botComponentChanges"][0]
        assert change["$kind"] == "BotComponentUpdate"
        component.clear()
        component.update(deepcopy(change["component"]))
        return response, {}

    monkeypatch.setattr(runtime, "_request", request)
    monkeypatch.setattr(native, "_native_client", lambda *_args: runtime)
    return args, client, calls, runtime, writes


def test_activation_preview_is_readonly_and_confirmation_changes_only_selected_state(
    activation, component, tmp_path,
):
    args, client, calls, _runtime, writes = activation
    inspected = deepcopy(component)
    preview, code = native._activate(args, tmp_path, client, TARGET)
    assert code == 0 and preview["outcome"] == "preview"
    assert preview["writeAttempted"] is False and preview["verified"] is False
    assert not writes and not calls and component == inspected
    args.output, args.yes = args.output.with_name("confirmed-activation"), True
    result, code = native._activate(args, tmp_path, client, TARGET)
    assert code == 0 and result["outcome"] == "activated"
    assert result["writeAttempted"] is result["writeAccepted"] is result["verified"] is True
    assert result["published"] is False and result["stateMatchesRequest"] is True
    assert len(writes) == 1
    desired = {**inspected, "state": "Active", "status": "Active"}
    assert writes[0]["botComponentChanges"][0]["component"] == desired
    assert result["nativeReadback"]["component"] == desired
    assert all(value == [] for key, value in writes[0].items() if key.endswith("Changes")
               and key != "botComponentChanges")


@pytest.mark.parametrize("change", ["target", "dialog", "schema", "parent", "state"])
def test_activation_rejects_stale_inspection_without_write(
    activation, component, tmp_path, change,
):
    args, client, _calls, _runtime, writes = activation
    args.yes = True
    if change == "target":
        inspection = native._read(args.inspection)
        inspection["target"]["agent"]["id"] = COMPONENT_ID
        args.inspection.write_text(json.dumps(inspection), encoding="utf-8")
    elif change == "dialog":
        component["dialog"]["modelDescription"] = "Fresh content requires fresh consent"
    else:
        component[{"schema": "schemaName", "parent": "parentBotId", "state": "state"}[change]] = "changed"
    with pytest.raises(ValueError):
        native._activate(args, tmp_path, client, TARGET)
    assert not writes and not args.output.exists()


def test_activation_guards_second_native_read_without_reconciling_new_content(
    activation, component, tmp_path, monkeypatch,
):
    args, client, _calls, runtime, writes = activation
    args.yes = True
    request = runtime._request

    def concurrent_request(method, *request_args, **kwargs):
        if method == "POST":
            component["dialog"]["modelDescription"] = "Concurrent edit after initial gate"
        return request(method, *request_args, **kwargs)

    monkeypatch.setattr(runtime, "_request", concurrent_request)
    result, code = native._activate(args, tmp_path, client, TARGET)
    assert code == 2 and result["writeAttempted"] is False
    assert "Inspect and approve" in result["error"]["activationError"]["message"]
    assert not writes


def test_already_active_confirmed_topic_is_verified_without_a_write(
    activation, component, tmp_path,
):
    args, client, _calls, _runtime, writes = activation
    component["state"] = component["status"] = "Active"
    args.inspection.write_text(json.dumps(native._inspection(component, TARGET)), encoding="utf-8")
    args.yes = True
    result, code = native._activate(args, tmp_path, client, TARGET)
    assert code == 0 and result["outcome"] == "unchanged"
    assert result["writeAttempted"] is False and result["writeAccepted"] is None
    assert result["verified"] is True and result["stateMatchesRequest"] is True
    assert not writes


@pytest.mark.parametrize("failure", ["uncertain", "conflict", "readback"])
def test_activation_retains_uncertain_or_accepted_write_evidence_and_never_retries(
    activation, tmp_path, monkeypatch, failure,
):
    args, client, _calls, runtime, writes = activation
    args.yes = True
    request = runtime._request
    attempts = 0

    def failing_request(method, *request_args, **kwargs):
        nonlocal attempts
        if method == "PUT":
            attempts += 1
            if failure == "uncertain":
                try:
                    raise native.requests.ConnectionError("Connection lost after request")
                except native.requests.ConnectionError as cause:
                    raise MinimalBotEvaluationError("Native write transport failed") from cause
            if failure == "conflict":
                response = native.requests.Response()
                response.status_code = 409
                return response, {}
        elif failure == "readback" and attempts:
            raise MinimalBotEvaluationError("Native verification read unavailable")
        return request(method, *request_args, **kwargs)

    monkeypatch.setattr(runtime, "_request", failing_request)
    result, code = native._activate(args, tmp_path, client, TARGET)
    assert code == 2 and result["outcome"] == "incomplete"
    assert result["writeAttempted"] is True and result["verified"] is False
    assert result["writeAccepted"] == {
        "uncertain": None, "conflict": False, "readback": True,
    }[failure]
    assert result["activationOutcome"] == "incomplete" and attempts == 1
    facts = result["error"]["activationError"]
    assert facts["evidence"]["writeAttempted"] is True
    if failure == "uncertain":
        assert facts["cause"]["cause"]["message"] == "Connection lost after request"
    if failure == "readback":
        assert result["stateMatchesRequest"] is True
        assert len(writes) == 1


@pytest.mark.parametrize("filename", ["native-after.json", "result.json"])
def test_activation_keeps_verified_success_when_local_evidence_writing_fails(
    activation, tmp_path, monkeypatch, filename,
):
    args, client, _calls, _runtime, writes = activation
    args.yes = True
    write = native._write

    def failing_write(path, value):
        if path.name == filename:
            raise OSError("Local evidence unavailable")
        write(path, value)

    monkeypatch.setattr(native, "_write", failing_write)
    result, code = native._activate(args, tmp_path, client, TARGET)
    assert code == 2 and result["outcome"] == "incomplete"
    assert result["activationOutcome"] == "activated"
    assert result["writeAccepted"] is result["verified"] is True
    assert result["nativeReadback"]["component"]["state"] == "Active"
    assert result["evidenceWriteErrors"][0]["file"] == filename
    assert len(writes) == 1


def test_activation_preserves_verified_write_when_later_native_readback_fails(
    activation, component, tmp_path, monkeypatch,
):
    args, client, _calls, runtime, writes = activation
    args.yes = True
    fetch = client.fetch_components

    def failed_fetch(agent_id):
        if writes:
            raise native.requests.ConnectionError("Later inventory unavailable")
        return fetch(agent_id)

    # Keep adapter verification available, but fail the helper's later inventory.
    def read_components():
        return {
            "botComponentChanges": [{"component": deepcopy(component)}],
            "changeToken": "local-token",
        }

    monkeypatch.setattr(runtime, "read_components", read_components)
    monkeypatch.setattr(client, "fetch_components", failed_fetch)
    result, code = native._activate(args, tmp_path, client, TARGET)
    assert code == 2 and result["activationOutcome"] == "activated"
    assert result["verified"] is result["writeAccepted"] is True
    assert "Later inventory unavailable" in result["error"]["nativeReadbackError"]["message"]
    assert len(writes) == 1


def test_activation_must_record_intent_before_any_write(activation, tmp_path, monkeypatch):
    args, client, _calls, _runtime, writes = activation
    args.yes = True
    write = native._write

    def failed_write(path, value):
        if path.name == "execution.json":
            raise OSError("Cannot persist activation intent")
        write(path, value)

    monkeypatch.setattr(native, "_write", failed_write)
    with pytest.raises(OSError, match="activation intent"):
        native._activate(args, tmp_path, client, TARGET)
    assert not writes


@pytest.mark.parametrize("confirmed", [False, True])
def test_activation_cli_confirmation_without_counting_a_pass(activation, tmp_path, monkeypatch, capsys, confirmed):
    args, client, _calls, _runtime, writes = activation
    monkeypatch.setattr(native, "connect_selected_dev_workspace", lambda *_args: (client, TARGET))
    code = native.main([
        "activate", "--kit-root", str(tmp_path), "--inspection", str(args.inspection),
        "--output", str(args.output), *(["--yes"] if confirmed else []),
    ])
    result = json.loads(capsys.readouterr().out)
    assert code == 0 and result["outcome"] == ("activated" if confirmed else "preview")
    assert len(writes) == (1 if confirmed else 0)


def test_activation_cli_keeps_known_remote_success_when_result_file_fails(
    activation, tmp_path, monkeypatch, capsys,
):
    args, client, _calls, _runtime, writes = activation
    monkeypatch.setattr(native, "connect_selected_dev_workspace", lambda *_args: (client, TARGET))
    write = native._write

    def failed_write(path, value):
        if path.name == "result.json":
            raise OSError("Activation result file unavailable")
        write(path, value)

    monkeypatch.setattr(native, "_write", failed_write)
    code = native.main([
        "activate", "--kit-root", str(tmp_path), "--inspection", str(args.inspection),
        "--output", str(args.output), "--yes",
    ])
    output = capsys.readouterr()
    result = json.loads(output.out)
    assert code == 2 and not output.err
    assert result["outcome"] == "incomplete" and result["activationOutcome"] == "activated"
    assert result["writeAccepted"] is result["verified"] is True
    assert result["evidenceWriteErrors"][0]["error"]["message"] == "Activation result file unavailable"
    assert len(writes) == 1


@pytest.fixture
def browser_preparation(tmp_path, monkeypatch):
    profile = tmp_path / "owned-browser-profile"
    profile.mkdir()
    monkeypatch.setattr(native, "_edge_executable", lambda: Path("msedge.exe"))
    monkeypatch.setattr(native.tempfile, "mkdtemp", lambda **_kwargs: str(profile))
    launches = []

    class Process:
        pid = 12345
        returncode = None

        def poll(self):
            return self.returncode

    process = Process()

    def launch(arguments, **kwargs):
        launches.append((arguments, kwargs))
        return process

    metadata = {
        "Browser": "Edg/test",
        "webSocketDebuggerUrl": "ws://127.0.0.1:23456/devtools/browser/test",
        "additionalBrowserFact": "retained",
    }
    monkeypatch.setattr(native.subprocess, "Popen", launch)
    monkeypatch.setattr(
        native, "_wait_for_browser",
        lambda *_args: ("http://127.0.0.1:23456", metadata),
    )
    args = argparse.Namespace(
        url=URL, output=Path(".local/topic-tests/browser"), timeout=1,
    )
    return args, process, launches, metadata


def test_browser_preparation_cli_returns_connection_without_human_readiness_or_send(
    browser_preparation, tmp_path, monkeypatch, capsys,
):
    args, process, launches, metadata = browser_preparation
    monkeypatch.setattr(native, "connect_selected_dev_workspace", lambda *_args: (object(), TARGET))
    code = native.main([
        "prepare-browser", "--kit-root", str(tmp_path), "--url", URL,
        "--output", str(args.output),
    ])
    result = json.loads(capsys.readouterr().out)
    assert code == 0 and result["outcome"] == "prepared"
    assert result["target"] == native._identity(TARGET)
    assert result["pid"] == process.pid and result["processExitCode"] is None
    assert result["cdp"] == "http://127.0.0.1:23456" and result["url"] == URL
    assert result["browserMetadata"] == metadata
    assert result["humanReadinessConfirmed"] is result["sendAttempted"] is False
    assert result["launchAttempted"] is True
    assert len(launches) == 1
    arguments, options = launches[0]
    assert "--inprivate" in arguments
    assert "--remote-debugging-port=0" in arguments
    assert "--remote-debugging-address=127.0.0.1" in arguments
    assert f"--user-data-dir={result['profile']}" in arguments
    assert arguments[-1] == URL
    assert options["stdin"] == options["stdout"] == options["stderr"] == native.subprocess.DEVNULL
    assert not Path(result["profile"]).is_relative_to(Path(result["output"]))
    intent = native._read(tmp_path / args.output / "launch-intent.json")
    assert intent["launchAttempted"] is False
    assert native._read(tmp_path / args.output / "result.json") == result


def test_browser_preparation_rejects_another_agent_before_launch(
    browser_preparation, tmp_path,
):
    args, _process, launches, _metadata = browser_preparation
    args.url = URL.replace(AGENT_ID, COMPONENT_ID)
    with pytest.raises(ValueError, match="selected agent"):
        native._prepare_browser(args, tmp_path, TARGET)
    assert not launches
    assert not (tmp_path / args.output).exists()


@pytest.mark.parametrize("stage", [
    "launch-intent.json", "browser-process.json", "result.json", "endpoint", "exited",
])
def test_browser_preparation_preserves_launch_facts_when_incomplete(
    browser_preparation, tmp_path, monkeypatch, stage,
):
    args, process, launches, _metadata = browser_preparation
    write = native._write

    def failed_write(path, value):
        if path.name == stage:
            raise OSError("Browser evidence unavailable")
        write(path, value)

    def failed_endpoint(*_args):
        raise TimeoutError("Browser endpoint unavailable") from ValueError("Original startup cause")

    monkeypatch.setattr(native, "_write", failed_write)
    if stage == "endpoint":
        monkeypatch.setattr(native, "_wait_for_browser", failed_endpoint)
    elif stage == "exited":
        process.returncode = 9
    result, code = native._prepare_browser(args, tmp_path, TARGET)
    assert code == 2
    assert result["outcome"] == ("blocked" if stage == "launch-intent.json" else "incomplete")
    assert len(launches) == (0 if stage == "launch-intent.json" else 1)
    assert result["sendAttempted"] is result["humanReadinessConfirmed"] is False
    if stage == "launch-intent.json":
        assert result["launchAttempted"] is False and "pid" not in result
    else:
        assert result["launchAttempted"] is True and result["pid"] == process.pid
    if stage == "endpoint":
        assert result["error"]["cause"]["message"] == "Original startup cause"
    elif stage in {"browser-process.json", "result.json"}:
        assert result["cdp"] == "http://127.0.0.1:23456"
        assert result["evidenceWriteErrors"][0]["error"]["message"] == "Browser evidence unavailable"
    elif stage == "exited":
        assert result["processExitCode"] == 9
        assert result["error"]["message"].endswith("code 9.")


@pytest.mark.parametrize("advertised_endpoint", [
    "ws://127.0.0.1:23456/devtools/browser/owned",
    "ws://127.0.0.1:23456/devtools/browser/another",
    "ws://example.test:23456/devtools/browser/owned",
])
def test_browser_endpoint_must_match_its_private_profile_descriptor(
    tmp_path, monkeypatch, advertised_endpoint,
):
    (tmp_path / "DevToolsActivePort").write_text(
        "23456\n/devtools/browser/owned\n", encoding="utf-8",
    )
    calls = []

    class Process:
        def poll(self):
            return None

    class Response:
        status_code = 200

        def json(self):
            return {"webSocketDebuggerUrl": advertised_endpoint, "browserFact": "retained"}

    class Session:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def get(self, url, **kwargs):
            calls.append((url, kwargs, self.trust_env))
            return Response()

    monkeypatch.setattr(native.requests, "Session", Session)
    if advertised_endpoint.endswith("/owned") and "example.test" not in advertised_endpoint:
        endpoint, metadata = native._wait_for_browser(Process(), tmp_path, 1)
        assert endpoint == "http://127.0.0.1:23456"
        assert metadata["browserFact"] == "retained"
    else:
        with pytest.raises(RuntimeError, match="does not match"):
            native._wait_for_browser(Process(), tmp_path, 1)
    assert calls == [(
        "http://127.0.0.1:23456/json/version",
        {"timeout": 2, "allow_redirects": False}, False,
    )]


def test_browser_preparation_does_not_wait_forever_for_a_debug_descriptor(
    tmp_path, monkeypatch,
):
    class Process:
        def poll(self):
            return None

    clock = iter([0, 2])
    monkeypatch.setattr(native.time, "monotonic", lambda: next(clock))
    with pytest.raises(TimeoutError, match="did not expose its endpoint"):
        native._wait_for_browser(Process(), tmp_path, 1)
