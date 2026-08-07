# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Drive a topic turn and classify the reply — automated, with launch + fallback.

The automated front of the L4 debug loop: send a scenario to a deployed topic's
test pane, capture the full reply, and classify it (ok / consent_gate / timeout /
empty) — no human at the input/output edge.

Drive resolution (in order):
  1. If a CDP browser is already up on the debug port, ATTACH to it.
  2. Otherwise LAUNCH Edge InPrivate on the test-pane URL, prompt the operator to
     sign in ONCE, wait for the pane, then attach.
  3. If attach still fails (no signed-in Copilot Studio page), WARN and offer to
     relaunch; only then does the maker fall back to the manual test pane.

InPrivate is deliberate — it disables Windows SSO so a *test* account signs in
cleanly rather than the ambient corp account. This tool launches and drives; it
never captures or stores credentials.

Usage:
    python scripts/drive_topic.py --prompt "Show me my open HR cases"
    python scripts/drive_topic.py --prompt "..." --env <env-guid> --bot <bot-guid>
    python scripts/drive_topic.py --prompt "..." --no-launch   # attach only
    python scripts/drive_topic.py --prompt "..." --new-session # fresh test session
"""
from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from cdp_driver import (
    CDP_ENDPOINT,
    CdpDriver,
    _DEFAULT_DEBUG_PORT,
    is_cdp_up,
    launch_browser,
)
from drive_surface import DriveSurface
from reply_signal import (
    ReplySignal,
    check_expectations,
    classify_reply_signal,
    looks_like_error,
)

_TEST_PANE_HOST = "https://copilotstudio.preview.microsoft.com"

_REMEDIATION = {
    ReplySignal.OK: "Real reply — safe to assert against; continue diagnosis.",
    ReplySignal.CONSENT_GATE: (
        "Authorize the connection in the test pane (the 'Connect to continue' "
        "card), then re-drive."
    ),
    ReplySignal.TIMEOUT: "The turn did not complete — re-drive (a hibernating backend may need a warm-up).",
    ReplySignal.EMPTY: "No reply captured — confirm the topic triggered, then re-drive.",
}


def test_pane_url(env_id: str, bot_id: str) -> str:
    """Agent-overview URL where the test pane is docked (dashed GUIDs, verbatim)."""
    return f"{_TEST_PANE_HOST}/environments/{env_id}/bots/{bot_id}/overview"


def _load_env_bot(explicit_env, explicit_bot):
    """Resolve (env_id, bot_id): explicit args win, else the active agent from
    .local/config.json (dataverseEndpoint's env + agent.botId)."""
    if explicit_env and explicit_bot:
        return explicit_env, explicit_bot
    try:
        from auth import load_config
        cfg = load_config()
        env = explicit_env or cfg.get("environmentId") or cfg["agent"].get("environmentId")
        bot = explicit_bot or cfg["agent"]["botId"]
        return env, bot
    except Exception:
        return explicit_env, explicit_bot


def _debug_port(cdp_endpoint: str) -> int:
    """The TCP port from a CDP endpoint URL, defaulting to 9222 if absent/unparsable.

    Pure. Used to launch the browser on the SAME port the caller will attach to —
    otherwise ``--cdp http://localhost:9224`` would launch on 9222 and attach to
    9224 (nothing there).
    """
    try:
        return urlsplit(cdp_endpoint).port or _DEFAULT_DEBUG_PORT
    except (ValueError, TypeError):
        return _DEFAULT_DEBUG_PORT


def _format_attached(targets) -> str:
    """One-line-per-page summary of the CDP targets we're about to attach to.

    Pure. ``targets`` is the decoded ``/json`` list; keeps only real pages and
    renders ``title — url`` so a wrong-attach (another session's agent) is visible
    instead of silent. Returns "" when there is nothing page-like to show.
    """
    lines = []
    for t in targets or []:
        if not isinstance(t, dict) or t.get("type") != "page":
            continue
        url = (t.get("url") or "").strip()
        if not url or url.startswith("devtools://"):
            continue
        title = (t.get("title") or "").strip() or "(untitled)"
        lines.append(f"    - {title} — {url}")
    return "\n".join(lines)


def _attached_targets(cdp_endpoint: str, timeout_s: float = 2.0):
    """Best-effort GET of ``<endpoint>/json`` (the CDP target list). [] on any error."""
    try:
        base = cdp_endpoint.rstrip("/")
        with urllib.request.urlopen(f"{base}/json", timeout=timeout_s) as resp:
            import json
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return []


def _connect(*, env_id, bot_id, allow_launch, cdp_endpoint):
    """Return a started DriveSurface, launching + waiting for sign-in if needed.

    Returns (surface, launched_proc). Raises RuntimeError with an actionable
    message if no signed-in test-pane page can be reached.
    """
    if not is_cdp_up(cdp_endpoint):
        if not allow_launch:
            raise RuntimeError(
                f"no CDP browser on {cdp_endpoint} and --no-launch set. Launch Edge "
                "InPrivate with --remote-debugging-port, sign in, and retry.")
        if not (env_id and bot_id):
            raise RuntimeError(
                "no CDP browser to attach to, and no env/bot to launch a test pane. "
                "Pass --env and --bot (or run from an agent workspace).")
        url = test_pane_url(env_id, bot_id)
        port = _debug_port(cdp_endpoint)
        print(f"Launching Edge InPrivate on the test pane (CDP port {port}):\n  {url}")
        launch_browser(start_url=url, debug_port=port)
        print("\n>>> Sign in as your TEST account in the InPrivate window, open the "
              "agent's Test pane, then press Enter here. <<<")
        if not sys.stdin.isatty():
            raise RuntimeError(
                "launch requires an interactive sign-in, but stdin is not a TTY. "
                "Launch the browser and sign in out-of-band, then re-run with "
                "--no-launch --cdp http://localhost:<port>.")
        input()
    else:
        # Attaching to a browser that was already up — it may belong to another
        # debug session on this port. Show what we're attaching to so a
        # wrong-attach (a different agent's pane) is visible, not silent.
        summary = _format_attached(_attached_targets(cdp_endpoint))
        print(f"Attaching to the existing CDP browser on {cdp_endpoint} — "
              "verify this is YOUR agent's Test pane, not another session's.")
        if summary:
            print(summary)
        print("(To run a second, isolated session, pass "
              "--cdp http://localhost:<other-port>.)")

    surface = DriveSurface(CdpDriver(cdp_endpoint, expected_match=bot_id))
    try:
        surface.start()  # raises if no signed-in Copilot Studio page is present
    except RuntimeError:
        raise
    except Exception as exc:  # noqa: BLE001 — normalize CDP/Playwright errors
        raise RuntimeError(
            f"could not attach to a signed-in test pane on {cdp_endpoint}: {exc}"
        ) from exc
    return surface


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Drive a topic turn on the test pane and classify the reply.")
    parser.add_argument("--prompt", required=True, help="the scenario input to send")
    parser.add_argument("--env", default=None, help="environment id (GUID)")
    parser.add_argument("--bot", default=None, help="bot/agent id (GUID)")
    parser.add_argument("--timeout", type=int, default=90, help="turn timeout seconds")
    parser.add_argument("--no-launch", action="store_true",
                        help="attach only; do not launch a browser")
    parser.add_argument("--new-session", action="store_true",
                        help="start a fresh test conversation before driving "
                             "(clears stale routing after a publish)")
    parser.add_argument("--expect", action="append", default=None, metavar="TEXT",
                        help="assert the reply CONTAINS this text (repeatable); "
                             "a failed assertion returns exit code 1")
    parser.add_argument("--reject", action="append", default=None, metavar="TEXT",
                        help="assert the reply does NOT contain this text (repeatable)")
    parser.add_argument("--cdp", default=CDP_ENDPOINT, help="CDP endpoint to attach")
    args = parser.parse_args(argv)

    env_id, bot_id = _load_env_bot(args.env, args.bot)

    try:
        surface = _connect(env_id=env_id, bot_id=bot_id,
                           allow_launch=not args.no_launch, cdp_endpoint=args.cdp)
    except RuntimeError as exc:
        # WARN + offer the recovery path rather than silently falling back.
        print(f"\nCannot drive automatically: {exc}\n")
        print("Options:")
        print("  - Fix the above (launch/sign-in) and re-run this command, or")
        print("  - Drive manually: send the prompt in the Test pane, copy the full "
              "reply, and run:  python scripts/reply_signal.py \"<pasted reply>\"")
        return 2

    try:
        if args.new_session:
            if surface.reset():
                print("Started a fresh test session.")
            else:
                print("Could not start a fresh session (no reset control found); "
                      "driving in the current session.")
        result = surface.drive(args.prompt, timeout_s=args.timeout)
    finally:
        surface.close()

    signal = classify_reply_signal(result.reply_text, timed_out=result.timed_out)
    print(f"signal: {signal.value}")
    print(f"remediation: {_REMEDIATION[signal]}")
    print(f"bubbles: {result.bubble_count} | had_card: {result.had_card} | "
          f"timed_out: {result.timed_out}")

    if signal is ReplySignal.OK and looks_like_error(result.reply_text):
        print("advisory: reply is error-shaped (a real turn, but it failed) — "
              "inspect the flow run (flow_run_inspect.py) or re-drive.")

    # Per-bubble breakdown when the turn is more than a single plain-text bubble
    # (a card, or a card followed by a generative/confirmation follow-up). The
    # aggregate had_card flag alone hides this — surfacing each bubble keeps a
    # card submission from reading as plain text.
    if result.bubble_count > 1 or result.had_card:
        print("--- bubbles ---")
        for i, b in enumerate(result.bubbles, 1):
            kind = "card" if b.had_card else "text"
            print(f"  [{i}] {kind}: {b.text}")
        if result.has_text_after_card:
            print("note: a text bubble follows a card (a generative/confirmation "
                  "follow-up) — do not treat this turn as plain text.")

    print("--- reply ---")
    print(result.reply_text)

    # A non-OK signal is a phantom reply — a consent gate, a timeout, or an empty
    # non-reply. Assertions against it are vacuous and success is meaningless, so
    # the exit code must reflect the signal, not the text. Only an OK turn earns a
    # content check and a 0 exit.
    if signal is not ReplySignal.OK:
        print(f"result: non-ok signal ({signal.value}) — not a drivable reply; "
              "resolve the remediation above and re-drive.")
        return 2

    if args.expect or args.reject:
        assertion = check_expectations(result.reply_text,
                                       expect=args.expect, reject=args.reject)
        print(f"assert: {'pass' if assertion.passed else 'fail'} "
              f"({assertion.reason})")
        if not assertion.passed:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
