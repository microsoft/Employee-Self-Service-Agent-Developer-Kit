# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for drive_topic's pure/orchestration logic (no browser).

Covers the test-pane URL, the drive-resolution decisions (attach vs launch vs
warn), and the warn-and-fall-back behavior when no browser can be reached — the
paths the user must be able to trust without a live browser.
"""
from __future__ import annotations

import drive_topic
from reply_signal import ReplySignal


def test_test_pane_url_uses_dashed_guids():
    url = drive_topic.test_pane_url("11111111-1111-1111-1111-111111111111",
                                    "22222222-2222-2222-2222-222222222222")
    assert url == (
        "https://copilotstudio.preview.microsoft.com/environments/"
        "11111111-1111-1111-1111-111111111111/bots/"
        "22222222-2222-2222-2222-222222222222/overview"
    )


def test_connect_no_launch_and_no_browser_raises_actionable(monkeypatch):
    monkeypatch.setattr(drive_topic, "is_cdp_up", lambda ep: False)
    try:
        drive_topic._connect(env_id="e", bot_id="b", allow_launch=False,
                             cdp_endpoint="http://localhost:9222")
        raised = None
    except RuntimeError as exc:
        raised = str(exc)
    assert raised is not None
    assert "--no-launch" in raised  # tells the operator exactly what to do


def test_connect_launch_without_env_bot_raises(monkeypatch):
    monkeypatch.setattr(drive_topic, "is_cdp_up", lambda ep: False)
    try:
        drive_topic._connect(env_id=None, bot_id=None, allow_launch=True,
                             cdp_endpoint="http://localhost:9222")
        raised = None
    except RuntimeError as exc:
        raised = str(exc)
    assert raised is not None
    assert "--env" in raised and "--bot" in raised


def test_connect_attaches_when_cdp_already_up(monkeypatch):
    # CDP already up -> no launch, straight to attach (a stub surface).
    monkeypatch.setattr(drive_topic, "is_cdp_up", lambda ep: True)
    started = {"n": 0}

    class StubSurface:
        def __init__(self, driver):
            pass

        def start(self):
            started["n"] += 1

    monkeypatch.setattr(drive_topic, "DriveSurface", StubSurface)
    monkeypatch.setattr(drive_topic, "CdpDriver", lambda ep, **kw: object())
    surface = drive_topic._connect(env_id="e", bot_id="b", allow_launch=True,
                                   cdp_endpoint="http://localhost:9222")
    assert started["n"] == 1
    assert isinstance(surface, StubSurface)


def test_debug_port_defaults_to_9222_when_absent():
    assert drive_topic._debug_port("http://localhost") == 9222


def test_debug_port_reads_explicit_port():
    assert drive_topic._debug_port("http://localhost:9224") == 9224


def test_debug_port_falls_back_on_garbage():
    assert drive_topic._debug_port("not a url") == 9222


def test_connect_launch_uses_the_cdp_port_not_the_default(monkeypatch):
    # Regression: --cdp on a non-default port must LAUNCH on that same port,
    # otherwise launch (9222) and attach (9224) disagree and attach finds nothing.
    monkeypatch.setattr(drive_topic, "is_cdp_up", lambda ep: False)
    captured = {}

    def _fake_launch(*, start_url, debug_port):
        captured["port"] = debug_port

    monkeypatch.setattr(drive_topic, "launch_browser", _fake_launch)
    monkeypatch.setattr(drive_topic, "input", lambda: "", raising=False)
    monkeypatch.setattr(drive_topic.sys.stdin, "isatty", lambda: True)

    class StubSurface:
        def __init__(self, driver):
            pass

        def start(self):
            pass

    monkeypatch.setattr(drive_topic, "DriveSurface", StubSurface)
    monkeypatch.setattr(drive_topic, "CdpDriver", lambda ep, **kw: object())
    drive_topic._connect(env_id="e", bot_id="b", allow_launch=True,
                         cdp_endpoint="http://localhost:9224")
    assert captured["port"] == 9224


def test_format_attached_renders_pages_only():
    targets = [
        {"type": "page", "title": "My Agent | Copilot Studio",
         "url": "https://copilotstudio.microsoft.com/x"},
        {"type": "service_worker", "title": "sw", "url": "https://x/sw.js"},
        {"type": "page", "title": "", "url": "devtools://devtools/bundled/x"},
    ]
    out = drive_topic._format_attached(targets)
    assert "My Agent | Copilot Studio" in out
    assert "https://copilotstudio.microsoft.com/x" in out
    assert "sw" not in out           # non-page filtered
    assert "devtools://" not in out  # devtools page filtered


def test_format_attached_empty_is_blank():
    assert drive_topic._format_attached([]) == ""
    assert drive_topic._format_attached(None) == ""


def test_main_warns_and_returns_2_when_cannot_connect(monkeypatch, capsys):
    def _raise(**kw):
        raise RuntimeError("no signed-in Copilot Studio page")

    monkeypatch.setattr(drive_topic, "_connect", _raise)
    monkeypatch.setattr(drive_topic, "_load_env_bot", lambda e, b: (e, b))
    rc = drive_topic.main(["--prompt", "hi", "--env", "e", "--bot", "b"])
    out = capsys.readouterr().out
    assert rc == 2
    assert "Cannot drive automatically" in out
    assert "Drive manually" in out  # offers the fallback, does not silently die


def test_main_drives_and_classifies(monkeypatch, capsys):
    from drive_surface import DriveResult

    class StubSurface:
        def drive(self, prompt, timeout_s):
            return DriveResult(reply_text="You have 2 open HR cases.",
                               timed_out=False, bubble_count=1, had_card=False)

        def close(self):
            pass

    monkeypatch.setattr(drive_topic, "_connect", lambda **kw: StubSurface())
    monkeypatch.setattr(drive_topic, "_load_env_bot", lambda e, b: ("e", "b"))
    rc = drive_topic.main(["--prompt", "show cases", "--env", "e", "--bot", "b"])
    out = capsys.readouterr().out
    assert rc == 0
    assert f"signal: {ReplySignal.OK.value}" in out
    assert "You have 2 open HR cases." in out


def test_main_non_ok_reply_returns_nonzero_even_if_expect_would_match(monkeypatch):
    # A consent-gate reply is a phantom turn: it must fail (rc 2), NOT pass just
    # because the gate text happens to contain an --expect substring.
    from drive_surface import DriveResult

    class StubSurface:
        def drive(self, prompt, timeout_s):
            return DriveResult(reply_text="Please connect to continue to proceed.",
                               timed_out=False, bubble_count=1, had_card=False)

        def close(self):
            pass

    monkeypatch.setattr(drive_topic, "_connect", lambda **kw: StubSurface())
    monkeypatch.setattr(drive_topic, "_load_env_bot", lambda e, b: ("e", "b"))
    rc = drive_topic.main(
        ["--prompt", "x", "--env", "e", "--bot", "b", "--expect", "connect"])
    assert rc == 2  # non-ok signal wins over a would-be-passing assertion


class _RecordingSurface:
    """A stub surface that records whether reset() was called before drive()."""

    def __init__(self):
        from drive_surface import DriveResult
        self.reset_calls = 0
        self.reset_before_drive = None
        self._result = DriveResult(reply_text="ok reply", timed_out=False,
                                   bubble_count=1, had_card=False)

    def reset(self):
        self.reset_calls += 1
        return True

    def drive(self, prompt, timeout_s):
        self.reset_before_drive = self.reset_calls
        return self._result

    def close(self):
        pass


def test_main_new_session_resets_before_driving(monkeypatch):
    surface = _RecordingSurface()
    monkeypatch.setattr(drive_topic, "_connect", lambda **kw: surface)
    monkeypatch.setattr(drive_topic, "_load_env_bot", lambda e, b: ("e", "b"))
    rc = drive_topic.main(
        ["--prompt", "show cases", "--env", "e", "--bot", "b", "--new-session"])
    assert rc == 0
    assert surface.reset_calls == 1
    assert surface.reset_before_drive == 1  # reset happened before the turn


def test_main_without_new_session_does_not_reset(monkeypatch):
    surface = _RecordingSurface()
    monkeypatch.setattr(drive_topic, "_connect", lambda **kw: surface)
    monkeypatch.setattr(drive_topic, "_load_env_bot", lambda e, b: ("e", "b"))
    rc = drive_topic.main(["--prompt", "show cases", "--env", "e", "--bot", "b"])
    assert rc == 0
    assert surface.reset_calls == 0


class _ReplySurface:
    """A stub surface that returns a fixed reply text."""

    def __init__(self, reply):
        from drive_surface import DriveResult
        self._result = DriveResult(reply_text=reply, timed_out=False,
                                   bubble_count=1, had_card=False)

    def drive(self, prompt, timeout_s):
        return self._result

    def close(self):
        pass


def test_main_expect_pass_returns_0(monkeypatch, capsys):
    monkeypatch.setattr(drive_topic, "_connect",
                        lambda **kw: _ReplySurface("You have 2 open HR cases."))
    monkeypatch.setattr(drive_topic, "_load_env_bot", lambda e, b: ("e", "b"))
    rc = drive_topic.main(["--prompt", "show cases", "--env", "e", "--bot", "b",
                           "--expect", "open HR cases"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "assert: pass" in out


def test_main_expect_fail_returns_1(monkeypatch, capsys):
    # An error turn is OK (real turn) but must FAIL the expected-text assertion —
    # this is the axis that separates a 400 from a real success.
    monkeypatch.setattr(drive_topic, "_connect",
                        lambda **kw: _ReplySurface("Error code: 400 Bad Request"))
    monkeypatch.setattr(drive_topic, "_load_env_bot", lambda e, b: ("e", "b"))
    rc = drive_topic.main(["--prompt", "show cases", "--env", "e", "--bot", "b",
                           "--expect", "open HR cases"])
    out = capsys.readouterr().out
    assert rc == 1
    assert f"signal: {ReplySignal.OK.value}" in out  # signal is still OK
    assert "assert: fail" in out


def test_main_reject_fail_returns_1(monkeypatch, capsys):
    monkeypatch.setattr(drive_topic, "_connect",
                        lambda **kw: _ReplySurface("Error code: 400 Bad Request"))
    monkeypatch.setattr(drive_topic, "_load_env_bot", lambda e, b: ("e", "b"))
    rc = drive_topic.main(["--prompt", "show cases", "--env", "e", "--bot", "b",
                           "--reject", "Error code"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "assert: fail" in out


def test_main_error_reply_advisory_without_assertions(monkeypatch, capsys):
    monkeypatch.setattr(drive_topic, "_connect",
                        lambda **kw: _ReplySurface("Sorry, something went wrong."))
    monkeypatch.setattr(drive_topic, "_load_env_bot", lambda e, b: ("e", "b"))
    rc = drive_topic.main(["--prompt", "show cases", "--env", "e", "--bot", "b"])
    out = capsys.readouterr().out
    assert rc == 0  # no assertions -> a real turn still "drove" successfully
    assert "error-shaped" in out.lower()


class _BubbleSurface:
    """A stub surface returning a fixed list of bubbles as one turn."""

    def __init__(self, bubbles):
        from drive_surface import aggregate_turn
        self._result = aggregate_turn(bubbles)

    def drive(self, prompt, timeout_s):
        return self._result

    def close(self):
        pass


def test_main_prints_per_bubble_breakdown(monkeypatch, capsys):
    from drive_surface import Bubble
    surface = _BubbleSurface([Bubble("<card>", True), Bubble("Ticket created.", False)])
    monkeypatch.setattr(drive_topic, "_connect", lambda **kw: surface)
    monkeypatch.setattr(drive_topic, "_load_env_bot", lambda e, b: ("e", "b"))
    rc = drive_topic.main(["--prompt", "make a ticket", "--env", "e", "--bot", "b"])
    out = capsys.readouterr().out
    assert rc == 0
    # A card followed by a text bubble is surfaced per-bubble, not just aggregate.
    assert "card" in out.lower()
    assert "Ticket created." in out
    # The card+follow-up shape is called out so it isn't read as plain text.
    assert "follow-up" in out.lower() or "after card" in out.lower()


def test_main_single_bubble_no_breakdown_noise(monkeypatch, capsys):
    from drive_surface import Bubble
    surface = _BubbleSurface([Bubble("You have 3 open HR cases.", False)])
    monkeypatch.setattr(drive_topic, "_connect", lambda **kw: surface)
    monkeypatch.setattr(drive_topic, "_load_env_bot", lambda e, b: ("e", "b"))
    rc = drive_topic.main(["--prompt", "show cases", "--env", "e", "--bot", "b"])
    out = capsys.readouterr().out
    assert rc == 0
    # A single plain text bubble should not print a per-bubble breakdown block.
    assert "[1]" not in out
