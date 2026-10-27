# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from dataclasses import replace

import pytest

from daga_chat_driver import DagaChatDriver, _Snapshot, validate_cdp_endpoint, validate_studio_url
from drive_surface import Bubble

TARGET = {
    "environment": {"id": "00000000-0000-4000-8000-000000001111", "ring": "test"},
    "agent": {"id": "00000000-0000-4000-8000-000000002222"},
}
URL = (
    "https://copilotstudio.test.microsoft.com/environments/"
    f"{TARGET['environment']['id']}/copilots/{TARGET['agent']['id']}/details?agentBackend=cosmos"
)


@pytest.mark.parametrize(
    "endpoint",
    ["http://localhost:9222", "https://127.0.0.1:9222", "http://127.0.0.1",
     "http://127.0.0.1:9222/redirect", "http://user@127.0.0.1:9222",
     "http://127.0.0.1:9222?other=1"],
)
def test_rejects_unconfirmed_cdp_endpoints(endpoint):
    with pytest.raises(ValueError):
        validate_cdp_endpoint(endpoint)


@pytest.mark.parametrize(
    "url",
    [URL.replace("https:", "http:"),
     URL.replace("copilotstudio.test.microsoft.com", "copilotstudio.microsoft.com"),
     URL.replace(TARGET["agent"]["id"], TARGET["environment"]["id"]),
     URL + "&redirect=other", URL + "#different"],
)
def test_rejects_studio_target_or_route_drift(url):
    with pytest.raises(ValueError):
        validate_studio_url(url, TARGET)


def test_current_turn_correlation_survives_rendered_history_eviction():
    driver = DagaChatDriver(cdp="http://127.0.0.1:9222", expected_url=URL)
    driver._boundary = {"expectedTurnIndex": 4}
    previous = _Snapshot(3, "old-turn", 4, "same prompt", (Bubble("stale"),), False)
    assert not driver._matching(previous, "same prompt")
    current = replace(previous, index=4, element_id="new-turn", bubbles=(Bubble("new"),))
    assert driver._matching(current, "same prompt")
    assert driver._confirmed.bubbles == (Bubble("new"),)
    with pytest.raises(RuntimeError, match="conversation changed"):
        driver._matching(replace(current, index=5), "same prompt")


def test_response_identity_survives_react_container_remount():
    driver = DagaChatDriver(cdp="http://127.0.0.1:9222", expected_url=URL)
    driver._boundary = {"expectedTurnIndex": 0}
    original = _Snapshot(0, "react-original", 1, "prompt", (), True, "chatMessageResponse-abc")
    assert driver._matching(original, "prompt")
    remounted = replace(
        original, element_id="react-remounted", bubbles=(Bubble("answer"),), generating=False,
    )
    assert driver._matching(remounted, "prompt")
    assert driver._confirmed == remounted
    with pytest.raises(RuntimeError, match="conversation changed"):
        driver._matching(replace(remounted, response_id="chatMessageResponse-other"), "prompt")


def test_observation_rejects_changed_turn_or_page():
    driver = DagaChatDriver(cdp="http://127.0.0.1:9222", expected_url=URL)
    driver._page_target_id = "original-page"
    with pytest.raises(RuntimeError, match="original browser page changed"):
        driver.observe("prompt", {"pageTargetId": "another-page"}, 1)
    driver._document_time_origin = 1000
    with pytest.raises(RuntimeError, match="original chat document"):
        driver.observe("prompt", {
            "pageTargetId": "original-page", "chatDocumentTimeOrigin": 2000,
        }, 1)
    driver._boundary = {"expectedTurnIndex": 0, "expectedResponseId": "original-response"}
    wrong_turn = _Snapshot(
        0, "replacement-turn", 1, "prompt", (Bubble("answer"),), False, "another-response",
    )
    with pytest.raises(RuntimeError, match="conversation changed"):
        driver._matching(wrong_turn, "prompt")


def test_mismatching_echo_retains_diagnostic_without_accepting_reply():
    driver = DagaChatDriver(cdp="http://127.0.0.1:9222", expected_url=URL)
    driver._boundary = {"expectedTurnIndex": 0}
    current = _Snapshot(0, "current-turn", 1, "different prompt", (), True)
    driver._last_observed = current
    with pytest.raises(RuntimeError, match="current user turn does not match"):
        driver._matching(current, "expected prompt")
    facts = driver.observation()
    assert facts["turnElementId"] is None
    assert facts["lastObservedTurn"]["userText"] == "different prompt"
