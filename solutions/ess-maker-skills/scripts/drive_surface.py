# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""DriveSurface — the automated drive+capture contract for topic debugging.

Sends a turn to a deployed topic and returns its full reply as aggregated text,
so the diagnostic tools (reply_signal / flow_run_inspect / plant_debug) run
without a human pasting the reply. The contract is deliberately browser-agnostic:
a caller depends only on ``DriveResult`` text, never on how the reply was driven.

Layers:
  * ``Bubble`` / ``DriveResult`` / ``aggregate_turn`` — pure value + the
    all-bubble join (so a card + interim text + a separate DBG bubble is one
    reply, not a dropped bubble).
  * ``turn_complete`` — the turn-completion decision as a pure state function.
  * ``DriveSurface`` — orchestrates a ``Driver`` (the browser seam) into
    ``DriveResult``s. The concrete browser ``Driver`` is a separate adapter,
    validated live; this module is fully unit-testable with a fake driver.

The chosen driver is Python launch + CDP-attach; the contract here keeps that
decision swappable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Bubble:
    """One rendered bot bubble in a turn: its text and whether it was a card."""
    text: str
    had_card: bool = False


@dataclass(frozen=True)
class DriveResult:
    """The end-user contract of a driven turn.

    ``reply_text`` is the turn's bot bubbles joined by newlines — the exact
    surface ``reply_signal.classify_reply_signal`` consumes. ``timed_out`` is
    explicit (never inferred from empty text); an empty turn is ``reply_text=""``,
    not an exception. ``bubbles`` preserves the individual bubbles (in order, with
    per-bubble ``had_card``) so a caller can distinguish a submitted card from a
    deterministic topic confirmation from a later generative follow-up — the
    turn-level ``had_card`` aggregate alone loses that.
    """
    reply_text: str
    timed_out: bool
    bubble_count: int
    had_card: bool
    bubbles: tuple[Bubble, ...] = ()

    @property
    def card_bubbles(self) -> tuple[Bubble, ...]:
        """The card/attachment bubbles of the turn, in order."""
        return tuple(b for b in self.bubbles if b.had_card)

    @property
    def text_bubbles(self) -> tuple[Bubble, ...]:
        """The plain-text (non-card) bubbles of the turn, in order."""
        return tuple(b for b in self.bubbles if not b.had_card)

    @property
    def has_text_after_card(self) -> bool:
        """True when a plain-text bubble follows a card bubble — the shape that
        reads as 'plain text' under the aggregate flag and hides a card
        submission's later generative/confirmation follow-up."""
        seen_card = False
        for b in self.bubbles:
            if b.had_card:
                seen_card = True
            elif seen_card:
                return True
        return False


def aggregate_turn(bubbles: list[Bubble], *, timed_out: bool = False) -> DriveResult:
    """Join every bubble of a turn into one ``DriveResult``.

    The joined text includes every bubble in order so a separate-bubble plant (a
    DBG line, a card plus interim text) is never missed. The individual bubbles
    are preserved on ``DriveResult.bubbles`` (immutable) so per-bubble card/text
    identity survives the aggregation. An empty turn yields ``reply_text=""``.
    """
    texts = [b.text for b in bubbles]
    return DriveResult(
        reply_text="\n".join(texts),
        timed_out=timed_out,
        bubble_count=len(bubbles),
        had_card=any(b.had_card for b in bubbles),
        bubbles=tuple(bubbles),
    )


def turn_complete(*, seen_any: bool, in_flight: int, quiet_elapsed: float,
                  quiet_s: float) -> bool:
    """Decide whether a turn is complete, as a pure state function.

    Based on the network-completion signal: a turn is done once at least one turn
    request has been seen (``seen_any``), none remain in flight
    (``in_flight == 0``), and the transcript has been quiet for ``quiet_s``
    seconds (``quiet_elapsed >= quiet_s``). Keeping this pure lets the completion
    logic be tested without a live network stream.
    """
    return seen_any and in_flight == 0 and quiet_elapsed >= quiet_s


class Driver(Protocol):
    """The browser seam. A concrete driver (CDP-attach) implements this; the
    surface depends only on the Protocol, so the contract is fake-testable."""

    def start(self) -> None: ...
    def send(self, text: str, timeout_s: int) -> tuple[list[Bubble], bool]: ...
    def reset(self) -> bool: ...
    def close(self) -> None: ...


class DriveSurface:
    """Orchestrates a ``Driver`` into ``DriveResult``s.

    Lifecycle: ``start`` (idempotent) -> ``drive`` (one turn -> aggregated
    result) -> optional ``reset`` -> ``close``. ``drive`` before ``start`` is a
    programming error (raises); ``close`` before ``start`` is a safe no-op.
    """

    def __init__(self, driver: Driver):
        self._driver = driver
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._driver.start()
        self._started = True

    def drive(self, text: str, timeout_s: int = 90) -> DriveResult:
        if not self._started:
            raise RuntimeError("DriveSurface not started; call start() first")
        bubbles, timed_out = self._driver.send(text, timeout_s)
        return aggregate_turn(bubbles, timed_out=timed_out)

    def reset(self) -> bool:
        if not self._started:
            raise RuntimeError("DriveSurface not started; call start() first")
        return self._driver.reset()

    def close(self) -> None:
        if not self._started:
            return
        self._driver.close()
        self._started = False
