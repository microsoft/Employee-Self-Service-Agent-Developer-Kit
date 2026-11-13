# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from dataclasses import replace
import os
from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError, Locator, sync_playwright

from daga_chat_driver import (
    DagaChatDriver, NewChatError, _Snapshot, validate_cdp_endpoint, validate_studio_url,
)
from drive_surface import Bubble, aggregate_turn
from native_topic_test import assess

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


@pytest.fixture
def isolated_dom_page():
    with sync_playwright() as playwright:
        options = {}
        if not Path(playwright.chromium.executable_path).is_file():
            edge = (
                Path(os.environ.get("PROGRAMFILES(X86)", ""))
                / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            )
            if not edge.is_file():
                pytest.skip("No existing Chromium/Edge binary for the isolated DOM fixture.")
            options["executable_path"] = str(edge)
        browser = playwright.chromium.launch(
            headless=True,
            args=["--disable-background-networking", "--disable-component-update",
                  "--disable-sync", "--no-first-run"],
            **options,
        )
        try:
            context = browser.new_context(service_workers="block")
            context.route("**/*", lambda route: route.abort())
            yield context.new_page()
        finally:
            browser.close()


@pytest.mark.parametrize("with_text", [False, True])
def test_dom_capture_preserves_text_empty_cards_before_assertions(isolated_dom_page, with_text):
    answer = "Approved test response."
    text_bubble = (
        f'<div class="fai-CopilotMessage__content">{answer}</div>' if with_text else ""
    )
    isolated_dom_page.set_content(f"""
        <div id="m365-chat-editor-target-element" role="textbox"
             aria-label="Message Copilot" contenteditable="true"></div>
        <div data-testid="m365-chat-llm-web-ui-chat-message" data-message-index="0" id="turn-0">
          <div data-testid="chatQuestion"><div data-testid="chatOutput">prompt</div></div>
          <div id="chatMessageResponse-current" data-testid="copilot-message-reply-div">
            <div class="fai-CopilotMessage__content"><div class="ac-adaptiveCard">
              <input aria-label="Card input">
            </div></div>
            {text_bubble}
          </div>
        </div>
    """)
    driver = DagaChatDriver(cdp="http://127.0.0.1:9222", expected_url=isolated_dom_page.url)
    driver._page = isolated_dom_page
    snapshot = driver._snapshot()
    assert snapshot.response_id == "chatMessageResponse-current"
    assert snapshot.bubbles == (
        (Bubble("", had_card=True), Bubble(answer)) if with_text
        else (Bubble("", had_card=True),)
    )
    result = assess(aggregate_turn(list(snapshot.bubbles)), answer, True)
    assert result["outcome"] == "unsupported_reply"
    assert result["checks"]["savedResponse"]["assessed"] is False


@pytest.mark.parametrize("control_count", [0, 1, 2])
def test_new_chat_uses_only_the_supported_chat_frame(isolated_dom_page, control_count):
    isolated_dom_page.set_content("""
        <button onclick="document.body.dataset.clicked = 'true'">New chat</button>
        <iframe title="Test"></iframe>
    """)
    frame = isolated_dom_page.frames[1]
    control = """
        <button onclick="document.body.dataset.clicks =
            Number(document.body.dataset.clicks || 0) + 1">New chat</button>
    """
    frame.set_content("""
        <div id="m365-chat-editor-target-element" role="textbox"
             aria-label="Message Copilot" contenteditable="true">Unsent draft</div>
        <button>Stop generating</button>
    """ + control * control_count)
    driver = DagaChatDriver(cdp="http://127.0.0.1:9222", expected_url=isolated_dom_page.url)
    driver._page = isolated_dom_page

    if control_count == 1:
        assert driver.newChat() is True
        assert frame.evaluate("document.body.dataset.clicks") == "1"
    else:
        with pytest.raises(NewChatError, match="Fresh browser loads or browser resets") as caught:
            driver.newChat()
        assert caught.value.evidence["newChatClickAttempted"] is False
        assert frame.evaluate("document.body.dataset.clicks") is None

    assert isolated_dom_page.evaluate("document.body.dataset.clicked") is None
    assert not isolated_dom_page.is_closed()


@pytest.mark.parametrize("state", ["direct", "fresh", "expanded", "obstructed"])
def test_new_chat_prefers_direct_button_and_falls_back_to_navigation(
    isolated_dom_page, monkeypatch, state,
):
    isolated_dom_page.set_content("""
        <div id="m365-chat-editor-target-element" role="textbox"
             aria-label="Message Copilot" contenteditable="true"></div>
        <button id="direct" aria-label="New chat" aria-describedby="tooltip"
                onclick="document.body.dataset.selected = 'direct'">+</button>
        <div id="tooltip" role="tooltip" hidden>Start a new chat</div>
        <button aria-label="Expand navigation" aria-expanded="false"
                onclick="document.body.dataset.expansions =
                    Number(document.body.dataset.expansions || 0) + 1;
                    setTimeout(() => document.querySelector('nav').hidden = false, 30)"></button>
        <nav hidden><a href="#new" aria-label="New chat"
                onclick="event.preventDefault();
                    document.body.dataset.selected = 'navigation'">New chat</a></nav>
    """)
    if state in {"fresh", "expanded"}:
        isolated_dom_page.locator("#direct").evaluate("(el) => el.remove()")
    if state in {"direct", "expanded"}:
        isolated_dom_page.locator("nav").evaluate("(el) => el.hidden = false")
    click = Locator.click
    clicks = []

    def tracked_click(locator, **kwargs):
        clicks.append((locator.get_attribute("aria-label"), kwargs.get("trial", False)))
        if state == "obstructed" and locator.get_attribute("id") == "direct":
            assert kwargs.get("trial") is True
            raise PlaywrightError("Another element intercepts pointer events")
        return click(locator, **kwargs)

    monkeypatch.setattr(Locator, "click", tracked_click)
    driver = DagaChatDriver(cdp="http://127.0.0.1:9222", expected_url=isolated_dom_page.url)
    driver._page = isolated_dom_page
    driver._boundary = {"expectedTurnIndex": 3}
    driver._identity_transitions = [{"previous": "old"}]

    assert driver.newChat() is True
    assert isolated_dom_page.evaluate("document.body.dataset.selected") == (
        "direct" if state == "direct" else "navigation"
    )
    assert isolated_dom_page.evaluate("document.body.dataset.expansions") == (
        "1" if state in {"fresh", "obstructed"} else None
    )
    assert clicks.count(("New chat", False)) == 1
    assert driver._boundary is None and driver._identity_transitions == []


def test_new_chat_retains_missing_controls_and_expansion_evidence(isolated_dom_page):
    isolated_dom_page.set_content("""
        <div id="m365-chat-editor-target-element" role="textbox"
             aria-label="Message Copilot" contenteditable="true"></div>
        <button aria-label="Expand navigation"
                onclick="document.body.dataset.expanded = 'true'"></button>
    """)
    driver = DagaChatDriver(cdp="http://127.0.0.1:9222", expected_url=isolated_dom_page.url)
    driver._page = isolated_dom_page
    with pytest.raises(NewChatError, match="absence alone does not prove") as caught:
        driver.newChat()
    assert caught.value.evidence == {
        "phase": "navigation",
        "navigationExpansionAttempted": True,
        "navigationExpansionCompleted": True,
        "newChatClickAttempted": False,
    }
    assert isinstance(caught.value.__cause__, PlaywrightError)
    assert "New chat" in str(caught.value.__cause__)
    assert isolated_dom_page.evaluate("document.body.dataset.expanded") == "true"


def test_new_chat_does_not_fallback_after_uncertain_click(isolated_dom_page, monkeypatch):
    isolated_dom_page.set_content("""
        <div id="m365-chat-editor-target-element" role="textbox"
             aria-label="Message Copilot" contenteditable="true"></div>
        <button aria-label="New chat"
                onclick="document.body.dataset.clicks =
                    Number(document.body.dataset.clicks || 0) + 1"></button>
        <button aria-label="Expand navigation"
                onclick="document.body.dataset.expanded = 'true'"></button>
    """)
    click = Locator.click

    def lost_acknowledgement(locator, **kwargs):
        click(locator, **kwargs)
        if not kwargs.get("trial"):
            raise PlaywrightError("Acknowledgement lost after dispatch")

    monkeypatch.setattr(Locator, "click", lost_acknowledgement)
    driver = DagaChatDriver(cdp="http://127.0.0.1:9222", expected_url=isolated_dom_page.url)
    driver._page = isolated_dom_page
    driver._boundary = {"expectedTurnIndex": 3}
    with pytest.raises(NewChatError, match="inspect without replaying") as caught:
        driver.newChat()
    assert caught.value.evidence["newChatClickAttempted"] is True
    assert caught.value.evidence["navigationExpansionAttempted"] is False
    assert "Acknowledgement lost after dispatch" in str(caught.value.__cause__)
    assert isolated_dom_page.evaluate("document.body.dataset.clicks") == "1"
    assert isolated_dom_page.evaluate("document.body.dataset.expanded") is None
    assert driver._boundary == {"expectedTurnIndex": 3}
