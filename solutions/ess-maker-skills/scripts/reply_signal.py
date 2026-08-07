"""Drive-outcome signalling: classify a captured bot reply into a ReplySignal.

When you drive a turn against an agent's test pane, the surface returns text —
but before you assert against that text you need to know whether it is a REAL
reply or a gate/non-reply that would make the assertion vacuous. The canonical
failure this prevents: a connector "Connect to continue" consent card (or a
connection-manager prompt) passing an absence/notContains check because the
backend call never actually ran.

This module is the pure, browser-free core. ``classify_reply_signal`` maps the
reply text (plus a timeout flag the caller sets when the turn did not complete)
to a ``ReplySignal`` the caller can branch on. A live driver can layer a
DOM-level consent check on top for the case where a consent card renders without
recognizable text; this module pins the text-level contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# Text markers of an unauthorized-connection gate. Two shapes seen in practice:
#  - the adaptive "Connect to continue" consent card (first connector call per
#    conversation)
#  - the "Open connection manager to verify your credentials" prompt (a stale or
#    repeat connection)
_CONSENT_MARKERS: tuple[str, ...] = (
    "connect to continue",
    "connect and to get the information",
    "open connection manager",
    "get you connected first",
    "verify your credentials",
)

# Text markers of an error-shaped reply. These do NOT change the ReplySignal (an
# error reply is still a real turn — OK); they drive a separate advisory so a
# 400/runtime failure that reads like a normal turn is flagged, not silently
# passed. Kept tight to avoid false positives on ordinary content.
_ERROR_MARKERS: tuple[str, ...] = (
    "error code:",
    "something went wrong",
    "unexpected error",
    "an error occurred",
    "failed to complete",
    "couldn't complete your request",
    "could not complete your request",
)


class ReplySignal(Enum):
    """Outcome of a drive turn, from the caller's point of view."""

    OK = "ok"                       # a real bot reply — assert against it
    CONSENT_GATE = "consent_gate"   # connector consent / connection-manager gate
    TIMEOUT = "timeout"             # the turn did not complete in time
    EMPTY = "empty"                 # no reply text captured

    @property
    def is_reply(self) -> bool:
        """True only when the text is a real reply safe to assert against."""
        return self is ReplySignal.OK

    @property
    def needs_consent(self) -> bool:
        """True when the block is recoverable by authorizing the connection
        (a manual/inline consent click), as opposed to a timeout/empty."""
        return self is ReplySignal.CONSENT_GATE


def _is_consent_text(reply: str) -> bool:
    low = reply.lower()
    return any(m in low for m in _CONSENT_MARKERS)


def looks_like_error(reply: str | None) -> bool:
    """True when the reply is error-shaped (a connector error code or a generic
    runtime failure). Advisory only — this never changes the ReplySignal, since
    an error reply is a real turn (OK). Use it to flag a 400/runtime failure that
    would otherwise read as an ordinary reply, and to decide whether to re-drive
    or dig into the flow run."""
    low = (reply or "").lower()
    return any(m in low for m in _ERROR_MARKERS)


@dataclass(frozen=True)
class AssertResult:
    """Outcome of a deterministic expected/rejected-text check over a reply."""
    passed: bool
    reason: str


def check_expectations(reply: str | None, *, expect=None, reject=None) -> AssertResult:
    """Grade a reply against expected/rejected substrings (case-insensitive).

    This is the deterministic axis on top of ``classify_reply_signal``: the
    signal says the turn is real (OK), and this says whether the real reply is
    the *right* reply. It is what distinguishes an error turn from a success turn
    when both are OK — assert what the reply must contain (``expect``) and must
    not contain (``reject``). With neither, it passes vacuously (nothing to grade).
    """
    text = reply or ""
    low = text.lower()
    for needle in (expect or ()):
        if needle.lower() not in low:
            return AssertResult(False, f"expected text not found: {needle!r}")
    for needle in (reject or ()):
        if needle.lower() in low:
            return AssertResult(False, f"rejected text present: {needle!r}")
    return AssertResult(True, "all expectations met")


def classify_reply_signal(reply: str | None, *, timed_out: bool = False) -> ReplySignal:
    """Classify a captured reply.

    Precedence: TIMEOUT (the turn did not complete, so any scraped text is
    partial/stale) > CONSENT_GATE (a recognizable gate) > EMPTY (nothing) > OK.
    A genuine backend error reply (e.g. "Error code: 400 ...") is OK — the error
    path is a real turn and any assertion must run against it.
    """
    if timed_out:
        return ReplySignal.TIMEOUT
    text = (reply or "").strip()
    if not text:
        return ReplySignal.EMPTY
    if _is_consent_text(text):
        return ReplySignal.CONSENT_GATE
    return ReplySignal.OK


_REMEDIATION = {
    ReplySignal.OK: "Real reply — safe to assert against; continue diagnosis.",
    ReplySignal.CONSENT_GATE: (
        "Authorize the connection (inline consent card or the maker portal's "
        "connection manager), then re-drive the turn."
    ),
    ReplySignal.TIMEOUT: (
        "The turn did not complete — re-drive (a hibernating backend may need a "
        "warm-up call first)."
    ),
    ReplySignal.EMPTY: (
        "No reply captured — confirm the topic actually triggered, then re-drive."
    ),
}


def main(argv=None) -> int:
    """CLI: classify a captured reply so a driver knows whether to trust it.

    Prints the signal (ok / consent_gate / timeout / empty) and a one-line
    remediation. When the reply is error-shaped, prints an advisory (the turn is
    still real, but it failed). With ``--expect``/``--reject``, also grades the
    reply deterministically and returns exit code 1 on a failed assertion.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Classify a captured bot reply into a drive-outcome signal.")
    parser.add_argument("reply", nargs="?", default="",
                        help="the captured reply text (quote it)")
    parser.add_argument("--timed-out", action="store_true",
                        help="the drive reported a timeout (the turn did not complete)")
    parser.add_argument("--expect", action="append", default=None, metavar="TEXT",
                        help="assert the reply CONTAINS this text (repeatable)")
    parser.add_argument("--reject", action="append", default=None, metavar="TEXT",
                        help="assert the reply does NOT contain this text (repeatable)")
    args = parser.parse_args(argv)

    signal = classify_reply_signal(args.reply, timed_out=args.timed_out)
    print(signal.value)
    print(_REMEDIATION[signal])

    if signal is ReplySignal.OK and looks_like_error(args.reply):
        print("advisory: reply is error-shaped (a real turn, but it failed) — "
              "inspect the flow run or re-drive.")

    if args.expect or args.reject:
        result = check_expectations(args.reply, expect=args.expect, reject=args.reject)
        print(f"assert: {'pass' if result.passed else 'fail'} ({result.reason})")
        if not result.passed:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
