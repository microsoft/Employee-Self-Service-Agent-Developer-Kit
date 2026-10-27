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
        aggregate_turn([Bubble("Connect to continue")]),
        aggregate_turn([Bubble(ANSWER, had_card=True)]),
    ],
)
def test_nonreplies_and_cards_never_pass_exact_response(capture):
    result = native.assess(capture, ANSWER, {"added": [], "removed": [], "changed": []})
    assert result["checks"]["savedResponse"]["assessed"] is False
    assert result["checks"]["savedResponse"]["met"] is None
    assert result["outcome"] != "passed"


def test_exact_response_requires_case_sensitive_match_and_native_integrity():
    capture = aggregate_turn([Bubble(ANSWER)])
    clean = {"added": [], "removed": [], "changed": []}
    assert native.assess(capture, ANSWER, clean)["outcome"] == "passed"
    assert native.assess(capture, ANSWER.lower(), clean)["outcome"] == "failed"
    assert native.assess(capture, ANSWER, None)["outcome"] == "incomplete"
    assert native.assess(capture, ANSWER, {**clean, "changed": [COMPONENT_ID]})[
        "outcome"
    ] == "failed"


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
        component["version"] += 1
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
    assert result["checks"]["nativeComponentsUnchanged"]["met"] is True
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
