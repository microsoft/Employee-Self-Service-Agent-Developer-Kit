# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Deterministic controller for the six-phase Workday connect lifecycle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from workday_connect_model import (
    CONTROLLER_CONTRACT_VERSION,
    WorkdayConnectModelError,
    plan_hash,
)
from workday_connect_store import (
    WorkdayConnectPlanChangedError,
    WorkdayConnectStore,
    WorkdayConnectStoreError,
)


RESULT_MARKER = "WORKDAY_CONNECT_RESULT_JSON:"
ERROR_MARKER = "WORKDAY_CONNECT_ERROR_JSON:"


def _json_object(value: str, label: str) -> dict[str, Any]:
    try:
        document = json.loads(value)
    except json.JSONDecodeError as exc:
        raise WorkdayConnectStoreError(
            f"{label} must be valid JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise WorkdayConnectStoreError(f"{label} must be a JSON object.")
    return document


def _emit(operation: str, result: dict[str, Any]) -> None:
    print(
        RESULT_MARKER
        + json.dumps(
            {
                "contractVersion": CONTROLLER_CONTRACT_VERSION,
                "operation": operation,
                **result,
            },
            sort_keys=True,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage the Workday connect lifecycle."
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Workspace root containing .local state.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("initialize")
    subparsers.add_parser("status")

    merge = subparsers.add_parser("merge-section")
    merge.add_argument(
        "--section",
        required=True,
        choices=["scope", "identifiers", "endpoints", "operators"],
    )
    merge.add_argument("--json", required=True)

    phase_status = subparsers.add_parser("set-phase-status")
    phase_status.add_argument("--phase", required=True)
    phase_status.add_argument("--status", required=True)
    phase_status.add_argument("--blocker-json")

    complete = subparsers.add_parser("complete-action")
    complete.add_argument("--phase", required=True)
    complete.add_argument("--action", required=True)
    complete.add_argument("--evidence-json")

    handoff = subparsers.add_parser("record-handoff")
    handoff.add_argument("--phase", required=True)
    handoff.add_argument("--json", required=True)

    approve = subparsers.add_parser("approve-plan")
    approve.add_argument("--phase", required=True)
    approve.add_argument("--plan-json", required=True)

    verify = subparsers.add_parser("verify-plan")
    verify.add_argument("--phase", required=True)
    verify.add_argument("--plan-json", required=True)
    verify.add_argument("--plan-hash", required=True)

    calculate = subparsers.add_parser("plan-hash")
    calculate.add_argument("--plan-json", required=True)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    store = WorkdayConnectStore(Path(args.root))
    try:
        if args.command == "initialize":
            state = store.initialize()
            _emit("initialize", {"state": state, "status": store.status()})
        elif args.command == "status":
            _emit("status", store.status())
        elif args.command == "merge-section":
            state = store.merge_section(
                args.section,
                _json_object(args.json, "section data"),
            )
            _emit("merge-section", {"state": state})
        elif args.command == "set-phase-status":
            blocker = (
                _json_object(args.blocker_json, "blocker")
                if args.blocker_json
                else None
            )
            state = store.set_phase_status(
                args.phase,
                args.status,
                blocker=blocker,
            )
            _emit("set-phase-status", {"state": state})
        elif args.command == "complete-action":
            evidence = (
                _json_object(args.evidence_json, "evidence")
                if args.evidence_json
                else None
            )
            state = store.complete_action(
                args.phase,
                args.action,
                evidence=evidence,
            )
            _emit("complete-action", {"state": state})
        elif args.command == "record-handoff":
            state = store.record_handoff(
                args.phase,
                _json_object(args.json, "handoff"),
            )
            _emit("record-handoff", {"state": state})
        elif args.command == "approve-plan":
            state, approved_hash = store.approve_plan(
                args.phase,
                _json_object(args.plan_json, "plan"),
            )
            _emit(
                "approve-plan",
                {"state": state, "planHash": approved_hash},
            )
        elif args.command == "verify-plan":
            verified_hash = store.verify_plan(
                args.phase,
                _json_object(args.plan_json, "plan"),
                args.plan_hash,
            )
            _emit("verify-plan", {"planHash": verified_hash, "verified": True})
        elif args.command == "plan-hash":
            _emit(
                "plan-hash",
                {
                    "planHash": plan_hash(
                        _json_object(args.plan_json, "plan")
                    )
                },
            )
        else:
            parser.error(f"Unsupported command: {args.command}")
    except (
        OSError,
        WorkdayConnectModelError,
        WorkdayConnectPlanChangedError,
        WorkdayConnectStoreError,
    ) as exc:
        print(
            ERROR_MARKER
            + json.dumps(
                {
                    "contractVersion": CONTROLLER_CONTRACT_VERSION,
                    "operation": args.command,
                    "error": str(exc),
                    "errorType": type(exc).__name__,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
