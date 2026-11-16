# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - capability and lifecycle telemetry shim for skill sessions.

Invoke one existing SDK emitter per command. With no --event, record capability
usage. Lifecycle calls require explicit agent identity and completion facts;
the session owns scope, timing, outcome interpretation and recovery. No batch
state, clock, implicit capability count or lifecycle sequence is added here.

Design rules (match adk_telemetry.py):
  * Fail-open. Telemetry must NEVER break a skill. Invalid lifecycle arguments
    are diagnosed without emission; telemetry failures still exit 0. Exit 0
    is not an ingestion acknowledgement. Do not retry unknown delivery.
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

Use --help for lifecycle fields. Outcome strings pass through unchanged;
acceptance by this adapter does not establish an approved outcome mapping.
Supply duration from actual clock observations, not conversation estimates.
Select deploy_target from the environment SKU using the SDK's
classify_deploy_target contract, not the agent's Dev/Prod realm. Error fields
must be approved diagnostic codes/categories, never raw service responses.
"""

import argparse
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


def _parse_emission(args: list[str], connector: str) -> tuple[str, dict[str, str | int | bool]]:
    parser = argparse.ArgumentParser(
        prog="emit_capability.py",
        description="Invoke one existing SDK emitter with explicit observed facts.",
        allow_abbrev=False,
    )
    parser.add_argument("capability")
    parser.add_argument("--event", choices=("build-start", "build-complete", "agent-deploy"))
    parser.add_argument("--agent-id")
    parser.add_argument("--outcome")
    parser.add_argument("--duration-ms", type=int)
    parser.add_argument("--deploy-target", choices=("sandbox", "production"))
    parser.add_argument("--error-code")
    parser.add_argument("--error-category")
    options = parser.parse_args(args)
    completion = (
        options.outcome, options.duration_ms, options.deploy_target,
        options.error_code, options.error_category,
    )
    if options.event is None:
        if options.agent_id is not None or any(value is not None for value in completion):
            parser.error("lifecycle fields require --event")
        return "emit_capability_use", {
            "adk_capability": options.capability.strip(), "connector": connector, "block": True,
        }
    if not options.agent_id or not options.agent_id.strip() or not options.capability.strip():
        parser.error("lifecycle emission requires non-empty --agent-id and capability")
    if connector:
        parser.error("--connector is supported only for capability usage")

    fields: dict[str, str | int | bool] = {
        "agent_id": options.agent_id.strip(),
        "adk_capability": options.capability.strip(),
        "block": True,
    }
    if options.event == "build-start":
        if any(value is not None for value in completion):
            parser.error("build-start does not accept completion fields")
    else:
        if not options.outcome or not options.outcome.strip():
            parser.error("completion requires an explicit --outcome")
        if options.duration_ms is None or options.duration_ms < 0:
            parser.error("completion requires a non-negative --duration-ms")
        fields.update(
            outcome=options.outcome,
            duration_ms=options.duration_ms,
            error_code=options.error_code or "",
            error_category=options.error_category or "",
        )
        if options.event == "agent-deploy":
            if options.deploy_target is None:
                parser.error("agent-deploy requires an explicit --deploy-target")
            fields["deploy_target"] = options.deploy_target
        elif options.deploy_target is not None:
            parser.error("--deploy-target is supported only for agent-deploy")
    return "emit_" + options.event.replace("-", "_"), fields


def main(argv: list[str]) -> int:
    args = argv[1:]

    # Keep telemetry failures separate from the maker's operation.
    try:
        import adk_telemetry
    except Exception as exc:  # noqa: BLE001 - telemetry must never break a skill
        print(f"Telemetry SDK unavailable ({type(exc).__name__}); no event dispatched.", file=sys.stderr)
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
            "Lifecycle: <capability> --event "
            "<build-start|build-complete|agent-deploy> --agent-id <id>\n"
            "Completion additionally requires --outcome <approved-value> "
            "--duration-ms <observed-elapsed-ms> (zero or greater).\n"
            "agent-deploy also requires --deploy-target <sandbox|production> "
            "from the environment SKU, not the agent realm.\n"
            "Completion accepts --error-code <code> --error-category <category>; "
            "do not pass raw errors or customer content.\n"
            "Lifecycle calls do not accept --connector or add a capability count. "
            "The session owns timing, sequencing and approved outcome mappings; "
            "no outcomes or success are inferred. "
            "Exit 0 is not delivery confirmation; do not retry unknown delivery.\n\n"
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

    is_worker = bool(rest and rest[0] == "--worker")
    if is_worker:
        rest = rest[1:]
    if not rest:
        return 0

    try:
        emitter_name, fields = _parse_emission(rest, connector)
    except SystemExit:
        return 0

    try:
        emitter = getattr(adk_telemetry, emitter_name)
        if not is_worker and not adk_telemetry.telemetry_enabled():
            return 0
    except Exception as exc:  # noqa: BLE001 - unavailable consent/SDK must not launch telemetry
        print(f"Telemetry unavailable ({type(exc).__name__}); no worker started.", file=sys.stderr)
        return 0

    if is_worker or adk_telemetry._SYNC:
        try:
            emitter(**fields)
        except Exception as exc:  # noqa: BLE001 - telemetry must never break a skill
            print(f"Telemetry emission failed ({type(exc).__name__}); delivery is unconfirmed.", file=sys.stderr)
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
            *rest,
        ]
        if connector:
            worker_argv.extend(["--connector", connector])
        worker = subprocess.Popen(worker_argv, **kwargs)
        threading.Thread(
            target=worker.wait,
            name="adk-capability-worker-reaper",
            daemon=True,
        ).start()
    except Exception as exc:  # noqa: BLE001 - telemetry must never break a skill
        print(f"Telemetry dispatch failed ({type(exc).__name__}); delivery is unconfirmed.", file=sys.stderr)

    # Always exit 0: a telemetry hiccup must not fail the skill step that ran
    # this command.
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
