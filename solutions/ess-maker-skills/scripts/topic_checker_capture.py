# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Capture Copilot Studio Topic checker errors over CDP (read-only).

VS Code diagnostics can report a topic clean while Copilot Studio's authoring
canvas Topic checker shows real failures — unrecognized identifiers, incompatible
types, wrong assignment types (surfaced as ``PowerFxError`` and detailed
type errors). Those live only in the authoring UI's Topic checker panel; the
local YAML diagnostics never see them. This tool opens that panel over a
CDP-attached browser and captures the visible errors so they can gate a push
(complements the local static diagnostics and the runtime debug loop — a defect
can pass local diagnostics yet fail the Topic checker, and separately pass the
Topic checker yet fail at runtime).

Read-only: it attaches to an already-signed-in browser (the operator launched
Edge InPrivate with a debug port — see cdp_driver's launch note), opens the
Topic checker panel if closed, and reads the error nodes. It never edits,
publishes, or navigates destructively.

Exit codes (so a pre-push gate can branch):
  0  the Topic checker ran and reported no errors
  1  the Topic checker ran and reported one or more errors
  2  the Topic checker could not be surfaced (tried the command bar and the
     'More' overflow menu) and no errors were visible — deliberately NOT
     conflated with "clean". The panel has additional rendering conditions that
     can't be fully automated, so the report advises surfacing it manually.

Trigger: run this after a runtime drive returns a GENERIC, unexplained error
(``looks_like_unexplained_error``) — "something went wrong" with no actionable
detail is often the surface of a publish-time authoring defect the Topic checker
would name. A specific error (a status code, a named table/field) points at the
flow run or connector instead, not the authoring canvas.

Usage:
    python scripts/topic_checker_capture.py [--topic-id <GUID>] [--json]

Known limitation: when Copilot Studio omits ``data-node-id`` on an
error node, the linked node/field ancestry is not fully recovered — the message
is captured but ``node`` may be empty.
"""
from __future__ import annotations

import argparse
import json

from cdp_driver import CDP_ENDPOINT

_ERROR_SELECTOR = '[data-testid="node-error"]'

# Accessible names for the overflow / "More" control that can reveal the Topic
# checker when it is not directly on the command bar. Tried in order.
_MORE_BUTTON_NAMES = ("More", "More commands", "More options", "…")

# Markers of a GENERIC, unexplained runtime error — the cue that a publish-time
# authoring defect (that the Topic checker would show) is the likely cause, as
# opposed to a specific, actionable error that points at the flow/connector.
_UNEXPLAINED_MARKERS = (
    "something went wrong",
    "unexpected error",
    "an error occurred",
    "an error has occurred",
)

# A specific error carrying real detail (a status code, a named field/table) is
# NOT "unexplained" — it points at the flow run or connector, not the canvas.
_EXPLAINED_MARKERS = (
    "error code:",
    "status code",
    "statuscode",
)


def looks_like_unexplained_error(reply: str | None) -> bool:
    """True when a runtime reply is a GENERIC, unexplained error — the trigger to
    run a Topic checker pass. A generic "something went wrong" with no actionable
    detail is often the surface of a publish-time authoring defect the Topic
    checker would name. An error carrying specific detail (a status code, a named
    table/field) is explained — it points at the flow run or connector, not the
    authoring canvas — so it does not trigger the checker pass."""
    low = (reply or "").lower()
    if not any(m in low for m in _UNEXPLAINED_MARKERS):
        return False
    if any(m in low for m in _EXPLAINED_MARKERS):
        return False
    return True


# --------------------------------------------------------------------------- #
# Pure logic (offline-testable): de-dupe, exit-code decision, report rendering.
# --------------------------------------------------------------------------- #

def dedupe_errors(errors: list[dict]) -> list[dict]:
    """Collapse identical (message, node) errors into one entry with a ``count``.

    Copilot Studio can render the same generic ``PowerFxError`` many times; a
    de-duplicated, counted list is what a reader (agentic or human) reasons about.
    First-seen order is preserved so the report reads top-to-bottom as authored.
    """
    order: list[tuple[str, str]] = []
    counts: dict[tuple[str, str], int] = {}
    for e in errors:
        key = (e.get("message", ""), e.get("node", ""))
        if key not in counts:
            counts[key] = 0
            order.append(key)
        counts[key] += 1
    return [{"message": msg, "node": node, "count": counts[(msg, node)]}
            for (msg, node) in order]


def decide_exit(errors: list[dict], *, checker_found: bool) -> int:
    """Map (errors, whether the checker ran) to an exit code.

    Errors present -> 1 (they demonstrably ran, even if the button lookup failed).
    No errors AND the checker never opened -> 2 (unknown, NOT clean). No errors
    with the checker open -> 0 (genuinely clean).
    """
    if errors:
        return 1
    return 0 if checker_found else 2


def render_report(url: str, errors: list[dict], *, checker_found: bool) -> str:
    """Human-readable report. Makes 'did not run' unmistakably distinct from
    'clean' so a false-clean can never read as a pass."""
    lines = [f"Topic checker @ {url}"]
    if not checker_found and not errors:
        lines.append(
            "WARNING: the Topic checker could not be surfaced (tried the command "
            "bar and the 'More' overflow menu). This is NOT a clean result — the "
            "panel has additional rendering conditions that can't be fully "
            "automated. There MAY be a Topic checker error you need to surface "
            "manually: open the topic's authoring canvas and open Topic checker "
            "(via 'More' if it isn't on the command bar), then re-run.")
        return "\n".join(lines)
    if not errors:
        lines.append("0 errors — the Topic checker reported no problems.")
        return "\n".join(lines)
    lines.append(f"{len(errors)} error(s):")
    for i, e in enumerate(errors, 1):
        node = f" [{e['node']}]" if e.get("node") else ""
        count = e.get("count", 1)
        rep = f" x{count}" if count > 1 else ""
        lines.append(f"  {i}. {e['message']}{node}{rep}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Browser I/O (live-only): page selection, panel open, error capture.
# --------------------------------------------------------------------------- #

def _article_count(page) -> int:
    frames = [page.main_frame, *[f for f in page.frames if f != page.main_frame]]
    return max((f.locator("article").count() for f in frames), default=0)


def _select_page(browser, topic_id: str | None):
    """Pick the authoring page. Prefer an adaptive/authoring canvas URL and the
    page with the most rendered articles; narrow to ``topic_id`` when given."""
    pages = [p for ctx in browser.contexts for p in ctx.pages
             if "copilotstudio" in (p.url or "")]
    if topic_id:
        matching = [p for p in pages if topic_id.lower() in (p.url or "").lower()]
        if not matching:
            # An explicit topic id that matches no open page must NOT silently
            # fall back to some other Copilot Studio tab — that would report the
            # wrong topic as clean/erroring.
            raise RuntimeError(
                f"no open Copilot Studio page matches topic id {topic_id!r}")
        pages = matching
    if not pages:
        raise RuntimeError("no open Copilot Studio page on the CDP endpoint")
    return max(pages, key=lambda p: (
        "/adaptive/" in (p.url or ""),
        _article_count(p),
    ))


def _try_topic_checker_button(page) -> bool:
    """Click the 'Topic checker' command if it's visible. Returns True if clicked."""
    button = page.get_by_role("button", name="Topic checker", exact=True)
    if button.count() and button.is_visible(timeout=1000):
        button.click()
        page.wait_for_timeout(1500)
        return True
    return False


def _open_checker(page) -> bool:
    """Surface the Topic checker panel via an escalation ladder. Returns True when
    the checker is demonstrably available; False when it could not be surfaced (so
    the caller warns the user to check manually rather than report a false-clean).

    Ladder:
      1. Click the 'Topic checker' command if it's on the command bar.
      2. Otherwise open the overflow 'More' menu, then click 'Topic checker'.
      3. If error nodes are already on the page, the checker has clearly run
         (panel already open) — treat as available.
      4. Otherwise give up (return False): the panel has additional rendering
         conditions we can't fully drive, so the caller advises manual surfacing.
    """
    # 1. Direct command.
    if _try_topic_checker_button(page):
        return True
    # 2. Overflow 'More' menu, then the command.
    for name in _MORE_BUTTON_NAMES:
        try:
            more = page.get_by_role("button", name=name, exact=True)
            if more.count() and more.first.is_visible(timeout=800):
                more.first.click()
                page.wait_for_timeout(800)
                if _try_topic_checker_button(page):
                    return True
        except Exception:
            continue
    # 3. Panel already open (error nodes present) => checker has run.
    try:
        return page.locator(_ERROR_SELECTOR).count() > 0
    except Exception:
        return False


def capture_errors(page) -> list[dict[str, str]]:
    """Capture the visible Topic checker error nodes as ``{message, node}``."""
    errors = page.locator(_ERROR_SELECTOR)
    captured = []
    for i in range(errors.count()):
        node = errors.nth(i)
        if not node.is_visible():
            continue
        captured.append({
            "message": node.inner_text().strip(),
            "node": node.get_attribute("data-node-id") or "",
        })
    return captured


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture visible Copilot Studio Topic checker errors (read-only).")
    parser.add_argument("--topic-id", help="topic component GUID to disambiguate the page")
    parser.add_argument("--cdp", default=CDP_ENDPOINT, help="CDP endpoint to attach")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args(argv)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(args.cdp)
        page = _select_page(browser, args.topic_id)
        checker_found = _open_checker(page)
        raw = capture_errors(page)
        # Read page.url INSIDE the context — the connection is gone after the
        # `with` block, so any attribute access would be stale/raise.
        url = page.url

    errors = dedupe_errors(raw)

    if args.json:
        print(json.dumps(
            {"url": url, "checkerRan": checker_found, "errors": errors}, indent=2))
    else:
        print(render_report(url, errors, checker_found=checker_found))

    return decide_exit(errors, checker_found=checker_found)


if __name__ == "__main__":
    raise SystemExit(main())
