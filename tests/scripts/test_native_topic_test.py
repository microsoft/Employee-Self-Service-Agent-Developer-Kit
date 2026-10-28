# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from __future__ import annotations

import argparse
from copy import deepcopy
import json

import pytest

import daga_chat_driver
from drive_surface import Bubble, aggregate_turn
import native_topic_test as native


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
