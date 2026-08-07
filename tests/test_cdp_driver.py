# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for CdpDriver's pure helpers (no browser).

The browser-touching code (attach, drive, capture) is validated live, not in CI.
These cover the pure article-classification and chrome-stripping — the parts that
decide role/card/body from a bubble's raw text.
"""
from __future__ import annotations

from cdp_driver import _classify_article, _strip_bubble_chrome


def test_strip_removes_reaction_and_timestamp_chrome():
    assert _strip_bubble_chrome("Your cases:\nLike\nDislike") == "Your cases:"
    assert _strip_bubble_chrome("Done Sent at 3:04 PM") == "Done"
    assert _strip_bubble_chrome("Plain text") == "Plain text"


def test_classify_bot_text_reply():
    role, had_card, body = _classify_article("Bot said: You have 3 open HR cases.")
    assert role == "bot"
    assert had_card is False
    assert body == "You have 3 open HR cases."


def test_classify_bot_card_reply():
    role, had_card, body = _classify_article("Bot attached: <card>")
    assert role == "bot"
    assert had_card is True
    assert body == "<card>"


def test_classify_user_echo():
    role, had_card, body = _classify_article("You said: show my cases")
    assert role == "user"
    assert had_card is False
    assert body == "show my cases"


def test_classify_unknown_prefix_kept_verbatim():
    role, had_card, body = _classify_article("System notice")
    assert role == "unknown"
    assert had_card is False
    assert body == "System notice"


def test_classify_strips_chrome_from_body():
    role, _had_card, body = _classify_article("Bot said: Here you go\nLike\nDislike")
    assert role == "bot"
    assert body == "Here you go"


def test_build_launch_args_has_mandatory_flags():
    from cdp_driver import build_launch_args
    args = build_launch_args(debug_port=9222, user_data_dir="C:/tmp/x",
                             start_url="https://example/pane")
    assert "--remote-debugging-port=9222" in args
    assert "--user-data-dir=C:/tmp/x" in args
    assert "--inprivate" in args           # test-account isolation is mandatory
    assert "--no-first-run" in args
    assert args[-1] == "https://example/pane"  # url is last


def test_build_launch_args_can_disable_inprivate():
    from cdp_driver import build_launch_args
    args = build_launch_args(debug_port=9222, user_data_dir="d", start_url="u",
                             inprivate=False)
    assert "--inprivate" not in args


class _FakePage:
    def __init__(self, url):
        self.url = url


class _FakeBrowser:
    def __init__(self, urls):
        self.contexts = [type("Ctx", (), {"pages": [_FakePage(u) for u in urls]})()]


def test_pick_page_without_match_returns_first_copilotstudio_page():
    from cdp_driver import CdpDriver
    browser = _FakeBrowser(["https://other.com/x",
                            "https://copilotstudio.microsoft.com/a"])
    assert CdpDriver._pick_page(browser).url == "https://copilotstudio.microsoft.com/a"


def test_pick_page_with_match_requires_the_token_in_url():
    from cdp_driver import CdpDriver
    bot = "2731c539"
    browser = _FakeBrowser([
        "https://copilotstudio.microsoft.com/environments/e/bots/OTHER/overview",
        f"https://copilotstudio.microsoft.com/environments/e/bots/{bot}/overview",
    ])
    page = CdpDriver._pick_page(browser, bot)
    assert bot in page.url  # attaches to THIS bot's pane, not the other tab


def test_pick_page_with_match_returns_none_when_no_page_matches():
    from cdp_driver import CdpDriver
    browser = _FakeBrowser(["https://copilotstudio.microsoft.com/bots/OTHER/overview"])
    assert CdpDriver._pick_page(browser, "2731c539") is None


def test_ensure_test_pane_ready_returns_input_when_already_present(monkeypatch):
    # Fast path: the input is already interactive, so no Test-button click.
    import cdp_driver
    monkeypatch.setattr(cdp_driver, "_find_input", lambda page: ("box", "sel"))
    box, sel = cdp_driver._ensure_test_pane_ready(object())
    assert box == "box" and sel == "sel"


def test_ensure_test_pane_ready_opens_pane_then_finds_input(monkeypatch):
    # The pane isn't hydrated yet: the first look finds nothing, so the helper
    # clicks the Test button, then the input appears on a later poll.
    import cdp_driver
    calls = {"find": 0, "clicked": 0}

    def fake_find(page):
        calls["find"] += 1
        return (("box", "sel") if calls["find"] >= 3 else (None, None))

    class _Btn:
        def click(self):
            calls["clicked"] += 1

    monkeypatch.setattr(cdp_driver, "_find_input", fake_find)
    monkeypatch.setattr(cdp_driver, "_find_test_button", lambda page: _Btn())

    class _Page:
        def wait_for_timeout(self, ms):
            pass

    box, _sel = cdp_driver._ensure_test_pane_ready(
        _Page(), timeout_ms=5_000, open_grace_ms=0)
    assert box == "box"
    assert calls["clicked"] == 1  # opened the pane exactly once


def test_ensure_test_pane_ready_gives_up_when_never_ready(monkeypatch):
    import cdp_driver
    monkeypatch.setattr(cdp_driver, "_find_input", lambda page: (None, None))
    monkeypatch.setattr(cdp_driver, "_find_test_button", lambda page: None)

    class _Page:
        def wait_for_timeout(self, ms):
            pass

    box, sel = cdp_driver._ensure_test_pane_ready(
        _Page(), timeout_ms=1_000, open_grace_ms=0)
    assert box is None and sel is None
