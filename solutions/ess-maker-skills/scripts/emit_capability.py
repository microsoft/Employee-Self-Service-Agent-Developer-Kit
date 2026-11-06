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
  * Non-blocking for the maker. The command launches a detached worker that
    performs the synchronous emit after the caller has already returned.
  * Consent-aware. The parent checks consent before launching a worker so an
    opted-out maker does not incur a process launch for a no-op.

Usage:
    python scripts/emit_capability.py topic_create
    python scripts/emit_capability.py --list

The capability MUST be one of ``adk_telemetry.ADK_CAPABILITIES`` (the single
canonical value-list). An unknown value is still emitted, but normalized to
``unknown`` by ``adk_telemetry`` so the dashboard dimension stays controlled.
"""

import os
import subprocess
import sys
import threading

# Add scripts/ to path so we can import adk_telemetry, mirroring the
# sibling-import pattern used by discover.py / evaluate_evals.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _parse_connector(args: list[str]) -> tuple[str, list[str]]:
    """Extract ``--connector <value>`` (or ``--connector=<value>``) from args.

    Returns (connector, remaining_args). Missing / malformed flag returns
    ("", args) — the caller passes an empty string through, which
    ``normalize_connector`` maps to "" (not connector-scoped).
    """
    out = []
    connector = ""
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--connector":
            if i + 1 < len(args):
                connector = args[i + 1]
                i += 2
                continue
            i += 1
            continue
        if a.startswith("--connector="):
            connector = a.split("=", 1)[1]
            i += 1
            continue
        out.append(a)
        i += 1
    return connector, out


def main(argv: list[str]) -> int:
    args = argv[1:]

    # Best-effort import: if telemetry can't even load, silently succeed.
    try:
        import adk_telemetry
    except Exception:  # noqa: BLE001 — telemetry must never break a skill
        return 0

    if not args or args[0] in ("-h", "--help"):
        print(
            "Usage: python scripts/emit_capability.py <capability> "
            "[--connector <workday|servicenow|legacy>]\n"
            "Records that a maker used an ADK capability (best-effort, "
            "non-blocking).\n\n"
            "The optional --connector flag attributes Connect + FlightCheck "
            "usage to the specific backend HR system (Workday vs ServiceNow) "
            "so PMs can report adoption / reliability by connector. Pass "
            "'legacy' for older events that predate connector attribution.\n\n"
            "Valid capabilities:\n  "
            + "\n  ".join(adk_telemetry.ADK_CAPABILITIES)
        )
        return 0

    if args[0] in ("--list", "list"):
        for cap in adk_telemetry.ADK_CAPABILITIES:
            print(cap)
        return 0

    # Extract --connector from anywhere in the argv tail so callers can put it
    # before or after the capability positional. Worker mode uses the same
    # parser so the subprocess round-trip preserves the flag.
    connector, rest = _parse_connector(args)

    if rest and rest[0] == "--worker":
        if len(rest) < 2:
            return 0
        try:
            adk_telemetry.emit_capability_use(
                rest[1].strip(), connector=connector, block=True
            )
        except Exception:  # noqa: BLE001 — telemetry must never break a skill
            pass
        return 0

    if not rest:
        return 0
    capability = rest[0].strip()
    if not adk_telemetry.telemetry_enabled():
        return 0

    if adk_telemetry._SYNC:
        try:
            adk_telemetry.emit_capability_use(
                capability, connector=connector, block=True
            )
        except Exception:  # noqa: BLE001 — telemetry must never break a skill
            pass
        return 0

    try:
        kwargs = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            )
        else:
            kwargs["start_new_session"] = True
        worker_argv = [
            sys.executable,
            os.path.abspath(__file__),
            "--worker",
            capability,
        ]
        if connector:
            worker_argv.extend(["--connector", connector])
        worker = subprocess.Popen(worker_argv, **kwargs)
        threading.Thread(
            target=worker.wait,
            name="adk-capability-worker-reaper",
            daemon=True,
        ).start()
    except Exception:  # noqa: BLE001 — telemetry must never break a skill
        pass

    # Always exit 0: a telemetry hiccup must not fail the skill step that ran
    # this command.
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
