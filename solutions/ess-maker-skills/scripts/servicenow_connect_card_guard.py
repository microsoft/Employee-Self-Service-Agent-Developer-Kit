# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""preToolUse hook: no question cards while ServiceNow Connect is running.

The ServiceNow Connect flow is plain chat text only. This hook denies the
card tools (ask_user and friends) while the Connect controller has marked a
ServiceNow lifecycle as active, so the agent sends the controller's chat text
as an ordinary message instead. Every other flow, including Setup and
Workday, is left alone.

The hook is deliberately fail-open: any problem reading the input or the
marker results in "no decision". A crash must never block unrelated tools.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

CARD_TOOLS = frozenset(
    {
        "ask_user",
        "vscode_askquestions",
        "askuserquestion",
        "askquestions",
    }
)
MARKER_RELATIVE = Path(".local") / "connect" / "servicenow-active.json"
MARKER_MAX_AGE_SECONDS = 4 * 60 * 60
DENY_REASON = (
    "ServiceNow Connect never uses question or input cards. Do not call "
    "ask_user. Send the controller's chatMessage as an ordinary plain text "
    "chat message. If endTurn is true, end your turn so the maker can reply "
    "in chat. If endTurn is false, run nextCommand in the same turn."
)


def _tool_name(payload: dict) -> str:
    for key in ("toolName", "tool_name", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _marker_roots(payload: dict) -> list[Path]:
    roots = [Path(__file__).resolve().parents[1]]
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        base = Path(cwd)
        roots.append(base)
        roots.append(base / "solutions" / "ess-maker-skills")
    return roots


def lifecycle_active(payload: dict, now: float | None = None) -> bool:
    current = time.time() if now is None else now
    for root in _marker_roots(payload):
        marker = root / MARKER_RELATIVE
        try:
            if not marker.is_file():
                continue
            data = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        updated = data.get("updatedAt") if isinstance(data, dict) else None
        if isinstance(updated, (int, float)) and (
            0 <= current - updated <= MARKER_MAX_AGE_SECONDS
        ):
            return True
    return False


def decide(payload: dict, now: float | None = None) -> dict:
    if _tool_name(payload).lower().replace("-", "_") not in CARD_TOOLS:
        return {}
    if not lifecycle_active(payload, now):
        return {}
    return {
        "permissionDecision": "deny",
        "permissionDecisionReason": DENY_REASON,
    }


def _trace(payload: dict, decision: dict) -> None:
    """Append one line proving the hook ran. Best effort; never raises."""
    try:
        root = Path(__file__).resolve().parents[1]
        log = root / ".local" / "connect" / "card-guard.log"
        if not log.parent.is_dir():
            return
        if log.is_file() and log.stat().st_size > 200_000:
            log.write_text("", encoding="utf-8")
        line = (
            f"{time.strftime('%Y-%m-%dT%H:%M:%S')} tool={_tool_name(payload) or '?'} "
            f"decision={'deny' if decision else 'none'}\n"
        )
        with log.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except Exception:  # noqa: BLE001 - tracing must never affect the hook
        return


def main() -> int:
    payload: dict = {}
    try:
        raw = sys.stdin.read()
        parsed = json.loads(raw) if raw.strip() else {}
        payload = parsed if isinstance(parsed, dict) else {}
        decision = decide(payload)
    except Exception:  # noqa: BLE001 - fail open on any problem
        decision = {}
    _trace(payload, decision)
    print(json.dumps(decision))
    return 0


if __name__ == "__main__":
    sys.exit(main())
