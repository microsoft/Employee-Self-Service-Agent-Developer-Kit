# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Bounded embedded M365 chat operations on an operator-confirmed Studio page.

The DOM boundaries adapt Microsoft ESS bot-test primitives. Authentication,
navigation, publication, conversation resets and send replay are not operations
of this driver.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from playwright.sync_api import Error as PlaywrightError, sync_playwright
import requests

from drive_surface import Bubble, DriveResult, aggregate_turn
from setup_existing_da import STUDIO_RING_BY_HOST


_COMPOSER = (
    '#m365-chat-editor-target-element[role="textbox"]'
    '[aria-label="Message Copilot"]'
)
_TURN = '[data-testid="m365-chat-llm-web-ui-chat-message"]'
_USER = '[data-testid="chatQuestion"] [data-testid="chatOutput"]'
_REPLY = '[data-testid="copilot-message-reply-div"] .fai-CopilotMessage__content'


def validate_cdp_endpoint(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or parsed.port is None
        or not 1 <= parsed.port <= 65535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query or parsed.fragment
    ):
        raise ValueError("CDP must be an explicit HTTP numeric-loopback endpoint and port.")
    return value.rstrip("/")


def validate_studio_url(value: str, target: dict[str, Any]) -> str:
    parsed = urlsplit(value)
    expected_path = (
        f"/environments/{target['environment']['id']}"
        f"/copilots/{target['agent']['id']}/details"
    )
    if (
        parsed.scheme != "https"
        or STUDIO_RING_BY_HOST.get(parsed.hostname) != target["environment"]["ring"]
        or parsed.port not in {None, 443}
        or parsed.username is not None or parsed.password is not None
        or parsed.path != expected_path
        or parse_qsl(parsed.query, keep_blank_values=True) not in (
            [], [("agentBackend", "cosmos")],
        )
        or parsed.fragment
    ):
        raise ValueError(
            "Use the selected agent's full trusted HTTPS Studio details URL. "
            "Only the optional agentBackend=cosmos query is supported."
        )
    return value


@dataclass(frozen=True)
class _Snapshot:
    index: int | None
    element_id: str | None
    rendered_turns: int
    prompt: str
    bubbles: tuple[Bubble, ...]
    generating: bool
    response_id: str | None = None


class DagaChatDriver:
    """Attach-only Driver for one supported embedded text-chat surface."""

    def __init__(self, *, cdp: str, expected_url: str):
        self._cdp = validate_cdp_endpoint(cdp)
        self._expected_url = expected_url
        self._pw = self._page = None
        self._page_target_id: str | None = None
        self._document_time_origin: float | None = None
        self._boundary: dict[str, Any] | None = None
        self._confirmed: _Snapshot | None = None
        self._last_observed: _Snapshot | None = None
        self._identity_transitions: list[dict[str, Any]] = []

    def start(self) -> None:
        self._pw = sync_playwright().start()
        try:
            with requests.Session() as session:
                session.trust_env = False
                response = session.get(
                    self._cdp + "/json/version", timeout=5, allow_redirects=False,
                )
                if response.status_code != 200:
                    raise RuntimeError("The confirmed CDP endpoint did not return browser metadata.")
                websocket = response.json()["webSocketDebuggerUrl"]
            endpoint, ws = urlsplit(self._cdp), urlsplit(websocket)
            if (
                ws.scheme != "ws" or ws.hostname != endpoint.hostname
                or ws.port != endpoint.port
                or ws.username is not None or ws.password is not None
                or not ws.path.startswith("/devtools/browser/")
                or ws.query or ws.fragment
            ):
                raise RuntimeError("CDP advertised an unexpected browser endpoint.")
            browser = self._pw.chromium.connect_over_cdp(websocket, timeout=10_000)
            pages = [
                page for context in browser.contexts for page in context.pages
                if page.url == self._expected_url
            ]
            if len(pages) != 1:
                raise RuntimeError(
                    f"Expected one page at the exact confirmed URL; found {len(pages)}. "
                    "Restore browser sign-in and readiness without replaying a send."
                )
            self._page = pages[0]
            self._page.set_default_timeout(5_000)
            cdp = self._page.context.new_cdp_session(self._page)
            try:
                self._page_target_id = cdp.send("Target.getTargetInfo")["targetInfo"]["targetId"]
            finally:
                cdp.detach()
            self._composer()
            self._document_time_origin = self._root().evaluate("performance.timeOrigin")
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _visible(locator):
        return [
            locator.nth(index) for index in range(locator.count())
            if locator.nth(index).is_visible()
        ]

    def _unique(self, locator, label: str):
        matches = self._visible(locator)
        if len(matches) != 1:
            raise RuntimeError(f"Expected one visible {label}; found {len(matches)}.")
        return matches[0]

    def _root(self):
        if self._page is None or self._page.url != self._expected_url:
            raise RuntimeError("The confirmed Studio page is no longer available.")
        frames = [frame for frame in self._page.frames if self._visible(frame.locator(_COMPOSER))]
        if len(frames) != 1:
            raise RuntimeError(
                f"Expected one supported embedded chat frame; found {len(frames)}. "
                "Open the Test pane and confirm readiness."
            )
        root = frames[0]
        if (
            self._document_time_origin is not None
            and root.evaluate("performance.timeOrigin") != self._document_time_origin
        ):
            raise RuntimeError("The original chat document changed; refusing another conversation.")
        return root

    def _composer(self):
        return self._unique(self._root().locator(_COMPOSER), "message composer")

    def _snapshot(self) -> _Snapshot:
        root = self._root()
        turns = root.locator(_TURN)
        count = turns.count()
        generating = bool(self._visible(
            root.get_by_role("button", name="Stop generating", exact=True),
        ))
        if not count:
            return _Snapshot(None, None, 0, "", (), generating)
        indices = turns.evaluate_all(
            "(nodes) => nodes.map(n => n.getAttribute('data-message-index'))",
        )
        if (
            any(value is None or not value.isdecimal() for value in indices)
            or len(set(indices)) != len(indices)
            or [int(value) for value in indices] != sorted(int(value) for value in indices)
        ):
            raise RuntimeError("The embedded chat has an unsupported turn-identity boundary.")
        latest = turns.nth(count - 1)
        element_id = latest.get_attribute("id")
        if not element_id:
            raise RuntimeError("The current embedded turn has no stable element identity.")
        user = self._unique(latest.locator(_USER), "current user message")
        responses = latest.locator('[id^="chatMessageResponse-"]')
        if responses.count() > 1:
            raise RuntimeError("The current turn has ambiguous response identities.")
        response_id = responses.first.get_attribute("id") if responses.count() else None
        bubbles = tuple(
            Bubble(body, bool(reply.locator(".ac-adaptiveCard").count()))
            for reply in self._visible(latest.locator(_REPLY))
            if (body := reply.inner_text().strip())
        )
        return _Snapshot(
            int(indices[-1]), element_id, count, user.inner_text().strip(),
            bubbles, generating, response_id,
        )

    def prepare(self) -> dict[str, Any]:
        before = self._snapshot()
        composer = self._composer()
        if before.generating or not composer.is_editable():
            raise RuntimeError("The chat is busy or not ready; no message was sent.")
        if composer.inner_text().strip("\u200b\u200c \t\r\n"):
            raise RuntimeError("The composer contains a draft; clear it before testing.")
        self._boundary = {
            "pageTargetId": self._page_target_id,
            "chatDocumentTimeOrigin": self._document_time_origin,
            "beforeTurnIndex": before.index,
            "beforeTurnElementId": before.element_id,
            "renderedTurnsBefore": before.rendered_turns,
            "expectedTurnIndex": 0 if before.index is None else before.index + 1,
        }
        return dict(self._boundary)

    def _matching(self, current: _Snapshot, prompt: str) -> bool:
        assert self._boundary is not None
        expected_index = self._boundary["expectedTurnIndex"]
        if current.index is None or current.index < expected_index:
            return False
        if (
            current.index != expected_index
            or " ".join(current.prompt.split()) != " ".join(prompt.split())
            or (
                self._boundary.get("expectedResponseId") is not None
                and current.response_id != self._boundary["expectedResponseId"]
            )
            or (
                self._confirmed is not None
                and self._confirmed.response_id is not None
                and current.response_id != self._confirmed.response_id
            )
        ):
            raise RuntimeError(
                "The conversation changed or the current user turn does not match. "
                "Refusing stale capture or send replay."
            )
        self._confirmed = current
        return True

    def _wait(self, prompt: str, deadline: float) -> tuple[list[Bubble], bool]:
        previous = None
        stable_since = time.monotonic()
        while time.monotonic() < deadline:
            current = self._snapshot()
            self._last_observed = current
            identity = {
                "turnIndex": current.index, "turnElementId": current.element_id,
                "responseId": current.response_id, "userText": current.prompt,
            }
            if not self._identity_transitions or self._identity_transitions[-1] != identity:
                self._identity_transitions.append(identity)
            matched = self._matching(current, prompt)
            if current != previous or current.generating:
                previous = current
                stable_since = time.monotonic()
            if (
                matched and current.response_id is not None
                and current.bubbles and not current.generating
                and time.monotonic() - stable_since >= 4
                and self._composer().is_editable()
            ):
                return list(current.bubbles), False
            self._page.wait_for_timeout(250)
        if self._confirmed is None:
            raise RuntimeError(
                "No matching new user turn was confirmed. Submission is ambiguous; "
                "do not resend. Observe this attempt or restore readiness with the maker."
            )
        return list(self._confirmed.bubbles), True

    def send(self, text: str, timeout_s: int) -> tuple[list[Bubble], bool]:
        if self._boundary is None:
            raise RuntimeError("Prepare and record the turn boundary before sending.")
        current = self._snapshot()
        if (
            current.index != self._boundary["beforeTurnIndex"]
            or current.element_id != self._boundary["beforeTurnElementId"]
            or current.generating
        ):
            raise RuntimeError("The prepared conversation changed; no message was sent.")
        deadline = time.monotonic() + timeout_s
        composer = self._composer()
        if composer.inner_text().strip("\u200b\u200c \t\r\n"):
            raise RuntimeError("The composer contains a draft; no message was sent.")
        composer.fill(text, timeout=5_000)
        if self._composer().inner_text().removesuffix("\u200b\u200c") != text:
            raise RuntimeError("The composer changed before submission; no message was sent.")
        send = self._unique(self._root().get_by_role("button", name="Send", exact=True), "Send control")
        try:
            send.click(timeout=5_000)
        except PlaywrightError as error:
            raise RuntimeError(
                "Send returned an error and its outcome is ambiguous. "
                "Observe this attempt without replaying the message."
            ) from error
        return self._wait(text, deadline)

    def observe(self, prompt: str, boundary: dict[str, Any], timeout_s: int) -> DriveResult:
        if boundary["pageTargetId"] != self._page_target_id:
            raise RuntimeError("The original browser page changed; refusing a different conversation.")
        if (
            boundary.get("chatDocumentTimeOrigin") is None
            or boundary["chatDocumentTimeOrigin"] != self._document_time_origin
        ):
            raise RuntimeError(
                "The original chat document is unverified or changed; "
                "refusing a different conversation."
            )
        self._boundary = dict(boundary)
        bubbles, timed_out = self._wait(prompt, time.monotonic() + timeout_s)
        return aggregate_turn(bubbles, timed_out=timed_out)

    def observation(self) -> dict[str, Any]:
        current = self._confirmed
        latest = self._last_observed
        return {
            "pageTargetId": self._page_target_id,
            "chatDocumentTimeOrigin": self._document_time_origin,
            "turnIndex": current.index if current else None,
            "turnElementId": current.element_id if current else None,
            "responseId": current.response_id if current else None,
            "renderedTurns": current.rendered_turns if current else None,
            "generating": current.generating if current else None,
            "lastObservedTurn": {
                "turnIndex": latest.index,
                "turnElementId": latest.element_id,
                "responseId": latest.response_id,
                "userText": latest.prompt,
                "generating": latest.generating,
            } if latest is not None else None,
            "turnIdentityTransitions": list(self._identity_transitions),
        }

    def screenshot(self, path) -> None:
        current = self._snapshot()
        if self._confirmed is None or current != self._confirmed:
            raise RuntimeError("The current turn changed before its screenshot.")
        turns = self._root().locator(_TURN)
        turns.nth(turns.count() - 1).screenshot(path=str(path), timeout=5_000)

    def reset(self) -> bool:
        raise NotImplementedError("Conversation resets are not supported by this driver.")

    def close(self) -> None:
        if self._pw is not None:
            try:
                self._pw.stop()
            finally:
                self._pw = self._page = None
