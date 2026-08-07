# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for the DriveSurface contract (automated drive + capture).

TDD, contract-first: these define the observable end-user contract — a driver
sends a turn and returns the topic's full reply as aggregated text — before any
browser code exists. Assertions are on the text contract only (aggregated reply,
explicit timeout, empty == "" not an exception), never on selectors/frames/CDP.
The real driver is validated live; here it is a scripted in-memory FakeDriver.

The output must be exactly what reply_signal.classify_reply_signal already
accepts, so the diagnostic tools consume it unchanged.
"""
from __future__ import annotations

import pytest

from drive_surface import (
    Bubble,
    DriveResult,
    DriveSurface,
    aggregate_turn,
    turn_complete,
)
from reply_signal import ReplySignal, classify_reply_signal


# --------------------------------------------------------------------------- #
# aggregate_turn — the all-bubble join
# --------------------------------------------------------------------------- #

def test_aggregate_joins_all_bubbles_in_order():
    # card + interim text + a separate DBG bubble = ONE reply. A single-bubble
    # capture would drop the DBG bubble — the exact failure this guards.
    bubbles = [
        Bubble(text="Here are your open cases:", had_card=False),
        Bubble(text="<card>", had_card=True),
        Bubble(text="DBG count=3", had_card=False),
    ]
    result = aggregate_turn(bubbles)
    assert result.reply_text == "Here are your open cases:\n<card>\nDBG count=3"
    assert result.bubble_count == 3
    assert result.had_card is True


def test_aggregate_empty_is_empty_string_not_raise():
    result = aggregate_turn([])
    assert result.reply_text == ""
    assert result.bubble_count == 0
    assert result.had_card is False
    assert result.timed_out is False


def test_aggregate_carries_timeout_flag():
    result = aggregate_turn([Bubble(text="partial", had_card=False)], timed_out=True)
    assert result.timed_out is True
    assert result.reply_text == "partial"  # partial text may still be present


# --------------------------------------------------------------------------- #
# per-bubble granularity — the aggregate MUST also preserve the individual
# bubbles so a caller can distinguish a submitted card from a deterministic
# topic confirmation from a later generative follow-up. Only the
# turn-level had_card flag is not enough.
# --------------------------------------------------------------------------- #

def test_aggregate_preserves_individual_bubbles():
    bubbles = [
        Bubble(text="<card>", had_card=True),
        Bubble(text="Got it — creating your ticket.", had_card=False),
        Bubble(text="Your ticket INC0012345 is ready.", had_card=False),
    ]
    result = aggregate_turn(bubbles)
    assert len(result.bubbles) == 3
    assert result.bubbles[0].had_card is True
    assert result.bubbles[0].text == "<card>"
    assert [b.text for b in result.bubbles] == [b.text for b in bubbles]


def test_card_and_text_bubble_partitions():
    result = aggregate_turn([
        Bubble("<card>", True),
        Bubble("confirmation text", False),
        Bubble("<second card>", True),
    ])
    assert [b.text for b in result.card_bubbles] == ["<card>", "<second card>"]
    assert [b.text for b in result.text_bubbles] == ["confirmation text"]


def test_trailing_text_after_card_detected():
    # A card followed by a separate generated text bubble is the exact shape that
    # reads as "plain text" under the aggregate flag.
    with_followup = aggregate_turn([Bubble("<card>", True), Bubble("done", False)])
    assert with_followup.had_card is True
    assert with_followup.has_text_after_card is True

    card_only = aggregate_turn([Bubble("<card>", True)])
    assert card_only.has_text_after_card is False

    text_only = aggregate_turn([Bubble("hello", False)])
    assert text_only.has_text_after_card is False


def test_surface_drive_exposes_per_bubble():
    driver = FakeDriver([([Bubble("<card>", True), Bubble("follow-up", False)], False)])
    surface = DriveSurface(driver)
    surface.start()
    result = surface.drive("x", timeout_s=30)
    assert len(result.bubbles) == 2
    assert result.has_text_after_card is True


# --------------------------------------------------------------------------- #
# composition with reply_signal — the integration assertion (no browser)
# --------------------------------------------------------------------------- #

def test_result_composes_to_ok_signal():
    result = aggregate_turn([Bubble(text="You have 3 open HR cases.", had_card=False)])
    assert classify_reply_signal(result.reply_text, timed_out=result.timed_out) is ReplySignal.OK


def test_result_composes_to_consent_gate():
    result = aggregate_turn([Bubble(text="Connect to continue\nServiceNow", had_card=True)])
    sig = classify_reply_signal(result.reply_text, timed_out=result.timed_out)
    assert sig is ReplySignal.CONSENT_GATE


def test_result_composes_to_empty():
    result = aggregate_turn([])
    assert classify_reply_signal(result.reply_text, timed_out=result.timed_out) is ReplySignal.EMPTY


def test_result_composes_to_timeout_over_text():
    # timed_out wins even when partial text was captured.
    result = aggregate_turn([Bubble(text="Connect to continue", had_card=True)], timed_out=True)
    assert classify_reply_signal(result.reply_text, timed_out=result.timed_out) is ReplySignal.TIMEOUT


# --------------------------------------------------------------------------- #
# turn_complete — the turn-completion decision as a pure state function
# --------------------------------------------------------------------------- #

def test_turn_incomplete_until_a_request_is_seen():
    # No turn request seen yet -> not complete, regardless of quiet time.
    assert turn_complete(seen_any=False, in_flight=0, quiet_elapsed=99.0, quiet_s=1.5) is False


def test_turn_incomplete_while_request_in_flight():
    assert turn_complete(seen_any=True, in_flight=1, quiet_elapsed=99.0, quiet_s=1.5) is False


def test_turn_incomplete_until_quiet_period_elapses():
    assert turn_complete(seen_any=True, in_flight=0, quiet_elapsed=0.5, quiet_s=1.5) is False


def test_turn_complete_when_seen_settled_and_quiet():
    assert turn_complete(seen_any=True, in_flight=0, quiet_elapsed=1.6, quiet_s=1.5) is True


# --------------------------------------------------------------------------- #
# DriveSurface orchestration against a FakeDriver (no browser)
# --------------------------------------------------------------------------- #

class FakeDriver:
    """In-memory driver: scripts the bubbles each drive() returns. Records the
    call order so the surface's lifecycle contract can be asserted."""

    def __init__(self, scripted):
        # scripted: list of (bubbles, timed_out) per drive call
        self._scripted = list(scripted)
        self._i = 0
        self.calls = []
        self.started = 0
        self.closed = 0
        self.resets = 0

    def start(self):
        self.started += 1
        self.calls.append("start")

    def send(self, text, timeout_s):
        self.calls.append(("send", text, timeout_s))
        bubbles, timed_out = self._scripted[self._i]
        self._i += 1
        return bubbles, timed_out

    def reset(self):
        self.resets += 1
        self.calls.append("reset")
        return True

    def close(self):
        self.closed += 1
        self.calls.append("close")


def test_surface_drive_returns_aggregated_result():
    driver = FakeDriver([([Bubble("A", False), Bubble("B", True)], False)])
    surface = DriveSurface(driver)
    surface.start()
    result = surface.drive("show my cases", timeout_s=30)
    assert isinstance(result, DriveResult)
    assert result.reply_text == "A\nB"
    assert result.bubble_count == 2
    assert result.had_card is True
    assert result.timed_out is False


def test_surface_start_is_idempotent():
    driver = FakeDriver([])
    surface = DriveSurface(driver)
    surface.start()
    surface.start()
    assert driver.started == 1  # second start is a no-op


def test_surface_drive_requires_start():
    driver = FakeDriver([([Bubble("A", False)], False)])
    surface = DriveSurface(driver)
    with pytest.raises(RuntimeError):
        surface.drive("x", timeout_s=30)


def test_surface_close_is_safe_without_start():
    driver = FakeDriver([])
    surface = DriveSurface(driver)
    surface.close()  # must not raise
    assert driver.closed == 0  # nothing to close if never started


def test_surface_drive_carries_timeout_through():
    driver = FakeDriver([([Bubble("partial", False)], True)])
    surface = DriveSurface(driver)
    surface.start()
    result = surface.drive("x", timeout_s=1)
    assert result.timed_out is True
    assert classify_reply_signal(result.reply_text, timed_out=result.timed_out) is ReplySignal.TIMEOUT
