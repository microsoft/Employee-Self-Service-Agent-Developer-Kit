# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - capability telemetry shim.

A tiny, dependency-light CLI wrapper around
``adk_telemetry.emit_capability_use`` so the SKILL.md-driven skills (topic /
workflow authoring, cleanup, troubleshoot, evaluations) can record that a
maker used an ADK capability by running ONE terminal command, without each
skill needing its own bespoke Python entry point.

Why this exists: the session-start and capability-use events were only wired
into the few skills backed by a Python script (auth/connect, discover,
evaluate, push). The biggest maker-facing surfaces — authoring topics and
workflows, scanning for errors, troubleshooting — are driven by SKILL.md
instructions with no script to hook, so they emitted nothing and the
"Capability Usage by Type" dashboard undercounted real work. This shim closes
that gap: a skill adds a single ``python scripts/emit_capability.py <cap>``
step and the capability shows up on the dashboards.

Design rules (match adk_telemetry.py):
  * Fail-open. Telemetry must NEVER break a skill. Any error is swallowed and
    we exit 0 regardless, so a skill step that runs this can't fail the flow.
  * Non-blocking for the maker, but synchronous emit. This is a short-lived
    CLI process, so we pass ``block=True`` (emit on the calling thread);
    otherwise the daemon emit thread would be killed when the interpreter
    exits and the event would be lost.
  * Consent-aware. ``emit_capability_use`` already no-ops when telemetry is
    disabled (``ESS_ADK_TELEMETRY=off`` or opted out via
    ``python scripts/adk_telemetry.py off``), so no extra gating is needed
    here.

Usage:
    python scripts/emit_capability.py topic_create
    python scripts/emit_capability.py --list

The capability MUST be one of ``adk_telemetry.ADK_CAPABILITIES`` (the single
canonical value-list). An unknown value is still emitted, but normalized to
``unknown`` by ``adk_telemetry`` so the dashboard dimension stays controlled.
"""

import os
import sys

# Add scripts/ to path so we can import adk_telemetry, mirroring the
# sibling-import pattern used by discover.py / evaluate_evals.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main(argv: list[str]) -> int:
    args = argv[1:]

    # Best-effort import: if telemetry can't even load, silently succeed.
    try:
        import adk_telemetry
    except Exception:  # noqa: BLE001 — telemetry must never break a skill
        return 0

    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: python scripts/emit_capability.py <capability>\n"
            "Records that a maker used an ADK capability (best-effort, "
            "non-blocking).\n\n"
            "Valid capabilities:\n  "
            + "\n  ".join(adk_telemetry.ADK_CAPABILITIES)
        )
        return 0

    if args[0] in ("--list", "list"):
        for cap in adk_telemetry.ADK_CAPABILITIES:
            print(cap)
        return 0

    capability = args[0].strip()

    try:
        # block=True: short-lived CLI process — emit synchronously so the
        # event isn't dropped when the interpreter exits and kills a daemon
        # thread. This posts on the calling thread and flushes the on-disk
        # buffer, so no explicit flush() is needed (flush() only joins async
        # emit threads, of which block=True creates none). Matches the other
        # inline hooks (backup/restore_template_configs.py, fetch_and_setup.py).
        # emit_capability_use() no-ops when telemetry is disabled.
        adk_telemetry.emit_capability_use(capability, block=True)
    except Exception:  # noqa: BLE001 — telemetry must never break a skill
        pass

    # Always exit 0: a telemetry hiccup must not fail the skill step that ran
    # this command.
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
