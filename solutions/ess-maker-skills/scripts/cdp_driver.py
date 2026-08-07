# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""CdpDriver — a CDP-attach browser Driver for the Copilot Studio test pane.

Implements the ``drive_surface.Driver`` seam by attaching (over the Chrome
DevTools Protocol) to an Edge/Chromium the operator already launched InPrivate
and signed into, then driving the agent test pane and capturing the turn's reply
as bubbles. The surface above it (``DriveSurface`` / ``aggregate_turn``) turns
those into the browser-agnostic ``DriveResult`` the diagnostic tools consume.

Attribution: the DOM interaction logic (test-pane selectors, article-based
bubble capture, the pvaruntime turn-completion signal, consent/reset handling)
is adapted from an internal Microsoft ESS bot-test harness and duplicated here
so this kit stays self-contained. The pure re-typing/aggregation and the
completion *decision* live in ``drive_surface`` and are reused, not re-copied.

Launch (operator, once): Edge InPrivate with a dedicated user-data-dir and the
debug port — InPrivate disables Windows SSO so a test account signs in cleanly:

    msedge --inprivate --remote-debugging-port=9222 \\
        --user-data-dir=<fresh dir> --no-first-run --no-default-browser-check <url>

Then this driver attaches to ``http://localhost:9222`` and does not launch or
authenticate.
"""
from __future__ import annotations

import os
import sys
import time

from drive_surface import Bubble, turn_complete
from reply_signal import _CONSENT_MARKERS

CDP_ENDPOINT = "http://localhost:9222"
_DEFAULT_DEBUG_PORT = 9222

_DEBUG = bool(os.environ.get("DRIVE_DEBUG"))

# Common Edge install locations (x86 first — the usual layout on corp images).
_EDGE_PATHS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)

# Candidate selectors for the test-pane message input (first visible wins).
INPUT_CANDIDATES = [
    'textarea[placeholder*="Ask" i]',
    'textarea[aria-label*="message" i]',
    '[contenteditable="true"][aria-label*="message" i]',
    'input[placeholder*="Ask" i]',
    'textarea[data-testid*="webchat" i]',
    '[data-testid="chat-input"] textarea',
]

# Article a11y role prefixes: card reply, text reply, the user's own echo.
_ARTICLE_ROLES = (
    ("Bot attached:", "bot", True),
    ("Bot said:", "bot", False),
    ("You said:", "user", False),
)

_RESET_BUTTON_NAMES = (
    "Refresh", "Start new test session", "New test session", "New chat", "Restart",
)

_TEST_PANE_READY_TIMEOUT_MS = 120_000
_TEST_PANE_OPEN_GRACE_MS = 5_000
_TEST_PANE_POLL_MS = 500


# --------------------------------------------------------------------------- #
# Pure helpers (no browser) — unit-tested.
# --------------------------------------------------------------------------- #

def _strip_bubble_chrome(txt: str) -> str:
    """Drop the trailing reaction/timestamp chrome the CS test pane appends to a
    bubble ('Like'/'Dislike' reactions, 'Sent at <time>'). Handles both the
    space-joined and newline-joined a11y renderings."""
    for marker in ("Sent at", "Like\nDislike", "Like Dislike", "\nLike", "\nDislike"):
        i = txt.find(marker)
        if i != -1:
            txt = txt[:i]
    return txt.strip()


def _classify_article(raw_text: str) -> tuple[str, bool, str]:
    """Split an article's raw inner_text into (role, had_card, body) by its a11y
    prefix, stripping the prefix and trailing chrome. Unknown prefix -> role
    'unknown', kept verbatim."""
    t = (raw_text or "").strip()
    for prefix, role, had_card in _ARTICLE_ROLES:
        if t.startswith(prefix):
            return role, had_card, _strip_bubble_chrome(t[len(prefix):].strip())
    return "unknown", False, _strip_bubble_chrome(t)


# --------------------------------------------------------------------------- #
# Launch / attach helpers — bring up a signed-in-able browser to attach to.
# --------------------------------------------------------------------------- #

def build_launch_args(*, debug_port: int, user_data_dir: str, start_url: str,
                      inprivate: bool = True) -> list[str]:
    """Build the Edge argument list for a CDP-attachable browser (pure).

    InPrivate + a DEDICATED user-data-dir + the debug port are all mandatory
    together: InPrivate disables Windows SSO so a test account signs in cleanly
    (not the corp account); a dedicated user-data-dir is required or a second
    msedge invocation just opens a tab in the existing process and silently
    ignores --remote-debugging-port. First-run/default-browser prompts are
    suppressed.
    """
    args = [
        f"--remote-debugging-port={debug_port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if inprivate:
        args.append("--inprivate")
    args.append(start_url)
    return args


def _find_edge() -> str:
    for p in _EDGE_PATHS:
        if os.path.exists(p):
            return p
    raise RuntimeError(
        "msedge.exe not found in the standard locations: " + ", ".join(_EDGE_PATHS))


def is_cdp_up(cdp_endpoint: str = CDP_ENDPOINT) -> bool:
    """True if a CDP endpoint is already answering (a browser to attach to)."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"{cdp_endpoint}/json/version", timeout=2) as r:  # noqa: S310 — localhost
            return r.status == 200
    except Exception:
        return False


def launch_browser(*, start_url: str, debug_port: int = _DEFAULT_DEBUG_PORT,
                   user_data_dir: str | None = None, wait_ready_s: float = 10.0):
    """Launch Edge InPrivate with a fresh profile + the CDP debug port, pointed at
    ``start_url``. Returns the Popen. The operator signs in ONCE in that window;
    the driver then attaches. A fresh temp user-data-dir is created if none given.
    """
    import subprocess
    import tempfile
    import time

    exe = _find_edge()
    if user_data_dir is None:
        user_data_dir = tempfile.mkdtemp(prefix="adk-drive-edge-")
    args = build_launch_args(debug_port=debug_port, user_data_dir=user_data_dir,
                             start_url=start_url)
    proc = subprocess.Popen([exe, *args])  # noqa: S603 — trusted exe + fixed flags
    endpoint = f"http://localhost:{debug_port}"
    deadline = time.monotonic() + wait_ready_s
    while time.monotonic() < deadline:
        if is_cdp_up(endpoint):
            break
        time.sleep(0.5)
    return proc


# --------------------------------------------------------------------------- #
# DOM helpers (browser) — live-validated, not unit-tested.
# --------------------------------------------------------------------------- #

def _all_frames(page):
    return [page.main_frame, *[f for f in page.frames if f != page.main_frame]]


def _first_visible(page, selectors):
    for f in _all_frames(page):
        for sel in selectors:
            try:
                loc = f.locator(sel).first
                if loc.is_visible(timeout=500):
                    return f, sel
            except Exception:
                continue
    return None, None


def _find_input(page):
    frame, sel = _first_visible(page, INPUT_CANDIDATES)
    if frame is None:
        return None, None
    return frame.locator(sel).first, sel


def _wait_for_input(page, timeout_ms=_TEST_PANE_READY_TIMEOUT_MS,
                    poll_ms=_TEST_PANE_POLL_MS):
    """Wait for the test-pane input and return it once interactive."""
    attempts = max(1, (timeout_ms + poll_ms - 1) // poll_ms)
    for attempt in range(attempts):
        box, selector = _find_input(page)
        if box is not None:
            return box, selector
        if attempt < attempts - 1:
            page.wait_for_timeout(poll_ms)
    return None, None


def _find_test_button(page):
    for frame in _all_frames(page):
        try:
            button = frame.get_by_role("button", name="Test", exact=True)
            if button.is_visible(timeout=500):
                return button
        except Exception:
            continue
    return None


def _ensure_test_pane_ready(page, timeout_ms=_TEST_PANE_READY_TIMEOUT_MS,
                            open_grace_ms=_TEST_PANE_OPEN_GRACE_MS):
    """Reuse an open test pane, or open it once and wait for hydration."""
    box, selector = _wait_for_input(page, timeout_ms=open_grace_ms)
    if box is not None:
        return box, selector

    attempts = max(1, (timeout_ms + _TEST_PANE_POLL_MS - 1)
                   // _TEST_PANE_POLL_MS)
    opened = False
    for attempt in range(attempts):
        box, selector = _find_input(page)
        if box is not None:
            return box, selector
        if not opened:
            button = _find_test_button(page)
            if button is not None:
                button.click()
                opened = True
        if attempt < attempts - 1:
            page.wait_for_timeout(_TEST_PANE_POLL_MS)
    return None, None


def _chat_frame(page):
    """The frame holding the transcript — the one with the most <article> bubbles."""
    best, best_n = None, 0
    for f in _all_frames(page):
        try:
            n = f.locator("article").count()
        except Exception:
            continue
        if n > best_n:
            best, best_n = f, n
    return best


def _card_text(scope) -> str:
    """Concatenate rendered Adaptive Card text (.ac-textBlock) within ``scope``."""
    parts = []
    try:
        blocks = scope.locator(".ac-textBlock")
        for i in range(min(blocks.count(), 40)):
            try:
                t = blocks.nth(i).inner_text(timeout=500).strip()
            except Exception:
                continue
            if t:
                parts.append(t)
    except Exception:
        return ""
    deduped = []
    for p in parts:
        if not deduped or deduped[-1] != p:
            deduped.append(p)
    return "\n".join(deduped)


class _Article:
    __slots__ = ("role", "text", "had_card")

    def __init__(self, role, text, had_card):
        self.role = role
        self.text = text
        self.had_card = had_card


def _articles(page) -> list[_Article]:
    """All transcript bubbles in DOM order (article-based), role-attributed."""
    frame = _chat_frame(page)
    if frame is None:
        return []
    articles = frame.locator("article")
    out: list[_Article] = []
    for i in range(articles.count()):
        art = articles.nth(i)
        try:
            raw = art.inner_text(timeout=1000)
        except Exception:
            continue
        role, had_card, body = _classify_article(raw)
        if role == "bot" and (had_card or not body):
            card = _card_text(art)
            if card:
                body, had_card = card, True
        out.append(_Article(role, body, had_card))
    return out


def _turn_bot_bubbles(page) -> list[Bubble]:
    """Bot bubbles produced since the last user turn — the current turn's reply.
    Mapped to the driver-agnostic ``drive_surface.Bubble`` (text + had_card)."""
    articles = _articles(page)
    last_user = max((i for i, a in enumerate(articles) if a.role == "user"), default=-1)
    return [Bubble(text=a.text, had_card=a.had_card)
            for a in articles[last_user + 1:] if a.role == "bot" and a.text]


def _dismiss_consent(page):
    for f in _all_frames(page):
        try:
            btn = f.get_by_role("button", name="Confirm")
            if btn.is_visible(timeout=800):
                btn.click()
                time.sleep(1)
        except Exception:
            pass


def consent_card_present(page) -> bool:
    """True when an unauthorized-connection consent card is rendered (backend
    replies are unreachable until the connection is authorized manually)."""
    for f in _all_frames(page):
        try:
            blocks = f.locator(".ac-textBlock")
            for i in range(min(blocks.count(), 30)):
                txt = blocks.nth(i).inner_text(timeout=500)
                if any(m.lower() in txt.lower() for m in _CONSENT_MARKERS):
                    return True
        except Exception:
            continue
    return False


def _reset_conversation(page, settle_ms=2500) -> bool:
    for f in _all_frames(page):
        for name in _RESET_BUTTON_NAMES:
            try:
                btn = f.get_by_role("button", name=name)
                if btn.is_visible(timeout=800):
                    btn.click()
                    page.wait_for_timeout(settle_ms)
                    box, _selector = _wait_for_input(page)
                    return box is not None
            except Exception:
                continue
    return False


def _is_turn_request(url, method) -> bool:
    """True for the pvaruntime POST that streams one bot turn — the deterministic
    completion signal on this surface."""
    if (method or "").upper() != "POST":
        return False
    u = (url or "").lower()
    return "pvaruntime" in u and "/test/conversations/" in u


def _drive_turn(page, text, timeout_s, *, arm_window_s=10, quiet_s=1.5, poll_ms=250):
    """Send ``text`` into the input, wait for the turn to finish via the
    pvaruntime stream-close signal (reusing ``turn_complete``), and return
    ``(bubbles, timed_out)``. ``timed_out`` is True only when the wait hit the
    deadline without a completion signal."""
    box, _sel = _ensure_test_pane_ready(page)
    if box is None:
        raise RuntimeError(
            "test pane did not become ready; confirm the browser is on the "
            "agent overview and signed in")

    client = page.context.new_cdp_session(page)
    client.send("Network.enable")
    state = {"seen": False, "in_flight": set(), "last_event": time.time()}

    def _on_req(params):
        req = params.get("request", {}) or {}
        if _is_turn_request(req.get("url", ""), req.get("method", "")):
            state["in_flight"].add(params.get("requestId"))
            state["seen"] = True
            state["last_event"] = time.time()

    def _on_done(params):
        rid = params.get("requestId")
        if rid in state["in_flight"]:
            state["in_flight"].discard(rid)
            state["last_event"] = time.time()

    client.on("Network.requestWillBeSent", _on_req)
    client.on("Network.loadingFinished", _on_done)
    client.on("Network.loadingFailed", _on_done)

    box.click()
    box.fill(text)
    box.press("Enter")
    if _DEBUG:
        print(f"  [drive] {text!r}", file=sys.stderr)

    deadline = time.time() + timeout_s
    arm_deadline = time.time() + arm_window_s
    completed = False
    while time.time() < deadline:
        page.wait_for_timeout(poll_ms)
        if not state["seen"] and time.time() > arm_deadline:
            # No network turn request observed — treat as a settle and read what
            # is on the DOM (a cached/no-op turn). Not a hard timeout.
            # KNOWN LIMITATION (needs live validation to fix safely): if the send
            # never registered, or the turn-request URL pattern changed, the DOM
            # may still hold the PREVIOUS turn's bubbles, which would be returned
            # as this turn's reply. A robust fix baselines the transcript before
            # send and requires a new bubble past the baseline.
            completed = True
            break
        if turn_complete(
            seen_any=state["seen"], in_flight=len(state["in_flight"]),
            quiet_elapsed=time.time() - state["last_event"], quiet_s=quiet_s,
        ):
            completed = True
            break

    try:
        client.detach()
    except Exception:
        pass

    if completed:
        # Stream closed but the final bubble may paint a beat later.
        paint_deadline = time.time() + 8
        while time.time() < paint_deadline:
            bubbles = _turn_bot_bubbles(page)
            if bubbles:
                return bubbles, False
            page.wait_for_timeout(poll_ms)
        return _turn_bot_bubbles(page), False

    return _turn_bot_bubbles(page), True  # hit the deadline


# --------------------------------------------------------------------------- #
# The Driver.
# --------------------------------------------------------------------------- #

class CdpDriver:
    """A ``drive_surface.Driver`` backed by a CDP-attached test-pane browser.

    Attaches (does not launch): the operator opens Edge InPrivate on the debug
    port and signs in; ``start`` connects, ``send`` drives one turn and returns
    ``(bubbles, timed_out)``, ``reset`` starts a fresh test session, ``close``
    detaches (leaving the browser running).
    """

    def __init__(self, cdp_endpoint: str = CDP_ENDPOINT, *, expected_match: str | None = None):
        self._cdp = cdp_endpoint
        self._expected_match = expected_match
        self._pw = None
        self._browser = None
        self._page = None

    def start(self) -> None:
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.connect_over_cdp(self._cdp)
            if not self._browser.contexts:
                raise RuntimeError("no browser context on the CDP endpoint")
            page = self._pick_page(self._browser, self._expected_match)
            if page is None:
                hint = (f" matching {self._expected_match!r}"
                        if self._expected_match else "")
                raise RuntimeError(
                    f"no open Copilot Studio page{hint} on the CDP endpoint")
            self._page = page
        except Exception:
            self._pw.stop()
            self._pw = self._browser = self._page = None
            raise
        _dismiss_consent(self._page)
        box, _selector = _ensure_test_pane_ready(self._page)
        if box is None:
            self.close()
            raise RuntimeError("test pane did not become ready after attach")

    @staticmethod
    def _pick_page(browser, expected_match=None):
        """Pick the Copilot Studio page to drive.

        When ``expected_match`` is given (an env or bot id from the requested
        test-pane URL), restrict to pages whose URL contains it, so a drive
        attaches to THIS agent's pane and never another agent's tab left open by
        a concurrent session. Among the eligible pages, prefer the most
        *drivable* one (has an input, has a Test button, is the overview /
        adaptive pane) so a hydrated test pane wins over a stale tab.
        """
        candidates = []
        for ctx in browser.contexts:
            for page in ctx.pages:
                if "copilotstudio" in (page.url or ""):
                    candidates.append(page)
        if expected_match:
            candidates = [p for p in candidates
                          if expected_match in (p.url or "")]
        if not candidates:
            return None

        def drive_score(page):
            has_input = False
            has_test_button = False
            try:
                has_input = _find_input(page)[0] is not None
            except Exception:
                pass
            try:
                has_test_button = _find_test_button(page) is not None
            except Exception:
                pass
            url = page.url or ""
            return (
                has_input,
                has_test_button,
                "/overview" in url,
                "/adaptive/" in url,
                "/actions-adaptive/" not in url,
            )

        return max(
            candidates,
            key=drive_score,
        )

    def send(self, text: str, timeout_s: int) -> tuple[list[Bubble], bool]:
        if self._page is None:
            raise RuntimeError("driver not started; call start() first")
        return _drive_turn(self._page, text, timeout_s)

    def reset(self) -> bool:
        if self._page is None:
            raise RuntimeError("driver not started; call start() first")
        return _reset_conversation(self._page)

    def close(self) -> None:
        if self._pw is not None:
            try:
                self._pw.stop()
            finally:
                self._pw = self._browser = self._page = None
