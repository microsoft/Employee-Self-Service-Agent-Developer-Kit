# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Read-only execution decisions for the shared Connect lifecycle."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


_SAFE_PROVIDER = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SAFE_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class LifecycleDecisionError(RuntimeError):
    """Raised when contract/state identity cannot be trusted."""


def _load_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise LifecycleDecisionError(f"{label} does not exist.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LifecycleDecisionError(f"{label} is invalid JSON.") from exc
    if not isinstance(value, dict):
        raise LifecycleDecisionError(f"{label} must be a JSON object.")
    return value


def _contract_path(root: Path, provider: str) -> Path:
    return root / "src" / "skills" / "connect" / provider / "contract.json"


def _state_path(root: Path, provider: str, agent_slug: str) -> Path:
    return (
        root
        / ".local"
        / "connect"
        / provider
        / "agents"
        / agent_slug
        / "lifecycle.json"
    )


def _initialization_command(
    contract: dict[str, Any],
    *,
    revision: int,
    agent_slug: str,
) -> str | None:
    command = contract.get("stateInitializationCommand")
    if command is None:
        return None
    if not isinstance(command, str) or not command.strip():
        raise LifecycleDecisionError(
            "Contract stateInitializationCommand must be a non-empty string."
        )
    return command.replace(
        "{contractRevision}",
        str(revision),
    ).replace(
        "{agentSlug}",
        agent_slug,
    )


def decide_next_step(
    root: Path,
    *,
    provider: str,
    agent_slug: str,
    executed_actions: frozenset[str] = frozenset(),
    verified_phases: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    if not _SAFE_PROVIDER.fullmatch(provider):
        raise LifecycleDecisionError("Provider key is invalid.")
    if not _SAFE_SLUG.fullmatch(agent_slug):
        raise LifecycleDecisionError("Agent slug is invalid.")

    contract = _load_object(_contract_path(root, provider), "Provider contract")
    if contract.get("provider") != provider:
        raise LifecycleDecisionError("Contract provider identity does not match.")
    revision = contract.get("contractRevision", 1)
    if not isinstance(revision, int) or isinstance(revision, bool) or revision <= 0:
        raise LifecycleDecisionError("Contract revision must be a positive integer.")

    state_path = _state_path(root, provider, agent_slug)
    if not state_path.exists():
        return {
            "schemaVersion": "connect.lifecycle-next.v1",
            "decision": "plan-required",
            "provider": provider,
            "agentSlug": agent_slug,
            "contractRevision": revision,
            "stateExists": False,
            "planReason": "first-run",
            "stateInitializationRequired": True,
            "stateInitializationCommand": _initialization_command(
                contract,
                revision=revision,
                agent_slug=agent_slug,
            ),
        }

    state = _load_object(state_path, "Lifecycle state")
    if state.get("provider") != provider:
        raise LifecycleDecisionError("Lifecycle provider identity does not match.")
    if state.get("agentSlug") != agent_slug:
        raise LifecycleDecisionError("Lifecycle agent identity does not match.")

    if state.get("attested") is not True or state.get(
        "acceptedContractRevision"
    ) != revision:
        accepted_revision = state.get("acceptedContractRevision")
        revision_reapproval = (
            state.get("attested") is True
            and accepted_revision != revision
        )
        return {
            "schemaVersion": "connect.lifecycle-next.v1",
            "decision": "plan-required",
            "provider": provider,
            "agentSlug": agent_slug,
            "contractRevision": revision,
            "stateExists": True,
            "planReason": (
                "revision-reapproval"
                if revision_reapproval
                else "attestation-required"
            ),
            "stateInitializationRequired": False,
            "stateInitializationCommand": None,
            "acceptedContractRevision": accepted_revision,
        }

    phases = contract.get("phases")
    state_phases = state.get("phases")
    if not isinstance(phases, list) or not phases:
        raise LifecycleDecisionError("Provider contract has no phases.")
    if not isinstance(state_phases, dict):
        raise LifecycleDecisionError("Lifecycle state has no phase map.")

    current: dict[str, Any] | None = None
    current_state: dict[str, Any] | None = None
    mode = "current"
    for phase in phases:
        if not isinstance(phase, dict) or not isinstance(phase.get("id"), str):
            raise LifecycleDecisionError("Provider contract has an invalid phase.")
        phase_id = phase["id"]
        value = state_phases.get(phase_id)
        if not isinstance(value, dict):
            raise LifecycleDecisionError(
                f"Lifecycle state is missing phase {phase_id!r}."
            )
        status = value.get("status")
        if status not in {"pending", "in-progress", "done", "blocked"}:
            raise LifecycleDecisionError(
                f"Lifecycle phase {phase_id!r} has an invalid status."
            )
        if status == "done":
            if phase_id in verified_phases:
                continue
            current = phase
            current_state = value
            mode = "reverify-done"
            break
        if status != "done":
            current = phase
            current_state = value
            break

    if current is None or current_state is None:
        return {
            "schemaVersion": "connect.lifecycle-next.v1",
            "decision": "complete",
            "provider": provider,
            "agentSlug": agent_slug,
            "contractRevision": revision,
            "stateExists": True,
        }

    phase_id = current["id"]
    action_doc = current.get("actionDoc")
    action_execution = current.get("actionExecution", "once")
    if action_execution not in {"once", "every-invocation"}:
        raise LifecycleDecisionError(
            f"Lifecycle phase {phase_id!r} has invalid actionExecution."
        )
    action_already_executed = phase_id in executed_actions
    should_run_action = bool(action_doc) and not action_already_executed and (
        action_execution == "every-invocation"
        or (
            mode == "current"
            and (
                current_state.get("actionApplied") is not True
                or (
                    action_execution == "once"
                    and current.get("resumeActionWhenIncomplete") is True
                )
            )
        )
    )
    decision = "run-action" if should_run_action else "run-checkpoints"
    result = {
        "schemaVersion": "connect.lifecycle-next.v1",
        "decision": decision,
        "provider": provider,
        "agentSlug": agent_slug,
        "contractRevision": revision,
        "stateExists": True,
        "phase": {
            "id": phase_id,
            "mode": mode,
            "status": current_state["status"],
            "checkpoints": list(current.get("checkpoints") or []),
            "actionExecution": action_execution,
            "actionApplied": current_state.get("actionApplied") is True,
            "resumeActionWhenIncomplete": (
                current.get("resumeActionWhenIncomplete") is True
            ),
        },
    }
    if should_run_action:
        if not isinstance(action_doc, str) or not action_doc:
            raise LifecycleDecisionError(
                f"Lifecycle phase {phase_id!r} has an invalid action document."
            )
        result["phase"]["actionDoc"] = action_doc
        result["phase"]["preserveHistoricalActionEvidence"] = (
            current_state.get("actionApplied") is True
        )
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    next_step = subparsers.add_parser(
        "next-step",
        help="Return the next executable lifecycle operation without writing state.",
    )
    next_step.add_argument("--provider", required=True)
    next_step.add_argument("--agent-slug", required=True)
    next_step.add_argument(
        "--executed-action",
        action="append",
        default=[],
        help="Phase action already executed in this invocation.",
    )
    next_step.add_argument(
        "--verified-phase",
        action="append",
        default=[],
        help="Completed phase live-verified in this invocation.",
    )
    next_step.add_argument("--root", type=Path, default=Path.cwd())
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = decide_next_step(
            args.root.resolve(),
            provider=args.provider,
            agent_slug=args.agent_slug,
            executed_actions=frozenset(args.executed_action),
            verified_phases=frozenset(args.verified_phase),
        )
    except (LifecycleDecisionError, OSError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1
    print(
        "DA_LIFECYCLE_NEXT_JSON:"
        + json.dumps(result, ensure_ascii=True, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
