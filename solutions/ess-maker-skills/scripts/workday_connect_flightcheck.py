# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Lifecycle adapter for independently runnable Workday DA FlightChecks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any, Mapping

from workday_connect_model import PHASE_REQUIRED_ACTIONS
from workday_connect_readiness_policy import (
    CHECKPOINT_PHASES,
    PHASE_ORDER as _PHASE_ORDER,
    PHASE_REQUIRED_PROFILES,
    PROFILE_POLICIES,
    checkpoint_phase,
    manual_evidence_for,
)


RESULT_SCHEMA = "flightcheck.result.v2"
INVOCATION_SOURCE = "connect"
DEFAULT_TIMEOUT_SECONDS = 300
_CHECKPOINT_PHASES = CHECKPOINT_PHASES

__all__ = [
    "PHASE_REQUIRED_PROFILES",
    "PROFILE_POLICIES",
    "WorkdayConnectFlightCheckError",
    "effective_validation_state",
    "evaluate_contract",
    "run_profile",
    "validation_input_fingerprint",
]


class WorkdayConnectFlightCheckError(ValueError):
    """Raised when a lifecycle FlightCheck profile cannot be accepted."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str,
        remediation_ids: tuple[str, ...] = (),
        phase_id: str | None = None,
        customer_remediation: str = "",
        input_fingerprint: str = "",
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.remediation_ids = remediation_ids
        self.phase_id = phase_id
        self.customer_remediation = customer_remediation
        self.input_fingerprint = input_fingerprint


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalized(value: Any) -> str:
    return _text(value).rstrip("/").casefold()


def _checkpoint_phase(checkpoint_id: str, fallback: str) -> str:
    return checkpoint_phase(checkpoint_id, fallback)


def _customer_remediation(phase_id: str, error_type: str) -> str:
    if error_type in {
        "flightcheck-timeout",
        "flightcheck-transport-error",
        "flightcheck-execution-error",
    }:
        return (
            "Retry readiness validation. If the problem continues, verify "
            "the recorded account can access the selected environment and "
            "review the service health for the failing phase."
        )
    guidance = {
        "preflight": (
            "Review the selected environment, agent, package installation, "
            "and capacity, then rerun Preflight."
        ),
        "entra": (
            "Have the Microsoft Entra administrator review the Workday "
            "application, consent, assignment, NameID, and signing settings, "
            "then rerun the Entra verification."
        ),
        "workday-admin": (
            "Have the Workday administrator review the API client, tenant "
            "security, authentication policy, and network readiness, then "
            "resubmit the administrator evidence."
        ),
        "connections": (
            "Review both recorded Power Platform connections and their "
            "owners, then rerun connection verification."
        ),
        "runtime": (
            "Review the runtime flows, connection references, authorization, "
            "topic wiring, and selected-agent attachment, then rerun Runtime."
        ),
        "employee-validation": (
            "Retry the signed-in employee validation using the recorded "
            "target and reviewed runtime flows."
        ),
    }
    return guidance[phase_id]


def validation_input_fingerprint(
    state: Mapping[str, Any],
    profile_name: str,
) -> str:
    """Return a stable hash of lifecycle inputs that affect profile acceptance."""
    phases = state.get("phases") or {}
    phase_inputs = {}
    for phase_id in _PHASE_ORDER:
        phase = phases.get(phase_id) or {}
        status = phase.get("status")
        policy = PROFILE_POLICIES.get(profile_name)
        if (
            policy is not None
            and phase_id == policy.phase_id
            and PHASE_REQUIRED_ACTIONS[phase_id]
            <= set(phase.get("completedActions") or [])
            and phase.get("blocker") is None
        ):
            status = "complete"
        phase_inputs[phase_id] = {
            "status": status,
            "completedActions": list(phase.get("completedActions") or []),
            "approvedPlanHash": phase.get("approvedPlanHash"),
            "approvedPlan": phase.get("approvedPlan"),
            "evidence": list(phase.get("evidence") or []),
            "administrator": phase.get("administrator"),
            "employeeTestAttempt": phase.get("employeeTestAttempt"),
        }
    operators = state.get("operators") or {}
    payload = {
        "profile": profile_name,
        "scope": state.get("scope") or {},
        "identifiers": state.get("identifiers") or {},
        "endpoints": state.get("endpoints") or {},
        "powerPlatformMaker": operators.get("powerPlatformMaker") or {},
        "tenantFoundation": state.get("tenantFoundation"),
        "phases": phase_inputs,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def effective_validation_state(
    root: Path,
    state: Mapping[str, Any],
) -> dict[str, Any]:
    """Add the foundation validation realm without mutating lifecycle state."""
    effective_state = dict(state)
    effective_scope = dict(state.get("scope") or {})
    foundation_path = root.resolve() / ".local" / "config.json"
    foundation: Mapping[str, Any] = {}
    foundation_error = False
    if foundation_path.exists():
        try:
            loaded = json.loads(foundation_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, Mapping):
                foundation_error = True
            else:
                foundation = loaded
        except (OSError, json.JSONDecodeError):
            foundation_error = True
    realm = _text(
        effective_scope.get("validationRealm")
        or foundation.get("realm")
        or ("invalid-foundation-config" if foundation_error else "")
        or "dev"
    ).casefold()
    effective_scope["validationRealm"] = realm
    effective_scope["validationRealmSourceValid"] = not foundation_error
    effective_state["scope"] = effective_scope
    return effective_state


def _agent_context(state: Mapping[str, Any]) -> dict[str, str]:
    scope = state.get("scope") or {}
    agent = scope.get("agent") or {}
    if not isinstance(agent, Mapping):
        agent = {}
    return {
        "realm": _text(scope.get("validationRealm")) or "dev",
        "environmentId": _text(scope.get("environmentId")),
        "environmentUrl": _text(scope.get("dataverseUrl")),
        "tenantId": _text(scope.get("entraTenantId")),
        "agentSlug": _text(agent.get("slug")),
        "agentSchemaName": _text(agent.get("schemaName")),
        "agentId": _text(agent.get("botId")),
    }


def _config_projection(state: Mapping[str, Any]) -> dict[str, Any]:
    scope = dict(state.get("scope") or {})
    identifiers = dict(state.get("identifiers") or {})
    endpoints = dict(state.get("endpoints") or {})
    operators = state.get("operators") or {}
    maker = operators.get("powerPlatformMaker") or {}
    agent = scope.get("agent") or {}
    projection: dict[str, Any] = {
        **scope,
        **identifiers,
        **endpoints,
        "realm": scope.get("validationRealm") or "dev",
        "tenantId": scope.get("entraTenantId"),
        "dataverseEndpoint": scope.get("dataverseUrl"),
        "makerUsername": maker.get("username"),
        "activeAgent": agent.get("slug") if isinstance(agent, Mapping) else None,
        "agents": [dict(agent)] if isinstance(agent, Mapping) and agent else [],
        "agent": dict(agent) if isinstance(agent, Mapping) else {},
    }
    return {
        key: value
        for key, value in projection.items()
        if value not in (None, "", [], {})
    }


def _runtime_arguments(state: Mapping[str, Any]) -> list[str]:
    phase = (state.get("phases") or {}).get("employee-validation") or {}
    attempt = phase.get("employeeTestAttempt") or {}
    arguments: list[str] = []
    attempt_id = _text(attempt.get("attemptId"))
    start = _text(attempt.get("startedAt"))
    end = _text(attempt.get("completedAt"))
    if attempt_id:
        arguments.extend(("--runtime-evidence-attempt-id", attempt_id))
    if start:
        arguments.extend(("--runtime-evidence-start", start))
    if end:
        arguments.extend(("--runtime-evidence-end", end))
    for flow_id in attempt.get("expectedFlowIds") or []:
        if _text(flow_id):
            arguments.extend(("--runtime-evidence-flow-id", _text(flow_id)))
    return arguments


def _command(
    root: Path,
    state: Mapping[str, Any],
    profile_name: str,
    output_dir: Path,
    config_path: Path,
    *,
    migration_baseline: bool,
) -> list[str]:
    context = _agent_context(state)
    maker = (
        ((state.get("operators") or {}).get("powerPlatformMaker") or {}).get(
            "username"
        )
    )
    command = [
        sys.executable,
        str(Path(__file__).with_name("flightcheck") / "cli.py"),
        "--output",
        str(output_dir),
        "--connect-config",
        str(config_path),
        "--profile",
        profile_name,
        "--invocation-source",
        INVOCATION_SOURCE,
        "--no-open",
        "--validation-realm",
        context["realm"],
        "--ring",
        _text((state.get("scope") or {}).get("ring")) or "prod",
    ]
    for option, field in (
        ("--environment-url", "environmentUrl"),
        ("--environment-id", "environmentId"),
        ("--tenant-id", "tenantId"),
        ("--agent-slug", "agentSlug"),
        ("--agent-schema-name", "agentSchemaName"),
    ):
        if context[field]:
            command.extend((option, context[field]))
    if _text(maker):
        command.extend(("--preferred-username", _text(maker)))
    if profile_name in {"workday-da:post-runtime", "workday-da:final"}:
        command.extend(_runtime_arguments(state))
        if migration_baseline:
            command.append("--runtime-evidence-migration-baseline")
    return command


def _validate_contract_shape(
    contract: Any,
    profile_name: str,
) -> dict[str, Any]:
    if not isinstance(contract, dict):
        raise WorkdayConnectFlightCheckError(
            "FlightCheck did not return a structured result contract.",
            error_type="malformed-flightcheck-contract",
        )
    schema = contract.get("schemaVersion")
    if schema != RESULT_SCHEMA:
        match = (
            re.fullmatch(r"flightcheck\.result\.v(\d+)", schema)
            if isinstance(schema, str)
            else None
        )
        if match is None:
            error_type = "malformed-flightcheck-contract"
        elif int(match.group(1)) < 2:
            error_type = "stale-flightcheck-contract"
        else:
            error_type = "unsupported-flightcheck-contract"
        raise WorkdayConnectFlightCheckError(
            f"FlightCheck returned unsupported schema {schema!r}.",
            error_type=error_type,
        )
    if contract.get("profile") != profile_name:
        raise WorkdayConnectFlightCheckError(
            "FlightCheck returned a result for a different profile.",
            error_type="malformed-flightcheck-contract",
        )
    for field, expected_type in (
        ("profileCheckpoints", list),
        ("profileFamilies", dict),
        ("emittedCheckpoints", list),
        ("requestedValidationContext", dict),
        ("validationContext", dict),
        ("clientAvailability", dict),
        ("executionErrors", list),
        ("counts", dict),
        ("results", list),
    ):
        if not isinstance(contract.get(field), expected_type):
            raise WorkdayConnectFlightCheckError(
                f"FlightCheck contract field '{field}' is invalid.",
                error_type="malformed-flightcheck-contract",
            )
    if contract.get("overall") not in {
        "READY",
        "READY_WITH_WARNINGS",
        "NOT_READY",
    }:
        raise WorkdayConnectFlightCheckError(
            "FlightCheck contract overall status is invalid.",
            error_type="malformed-flightcheck-contract",
        )
    return contract


def _validate_profile_membership(
    contract: Mapping[str, Any],
    profile_name: str,
) -> None:
    policy = PROFILE_POLICIES[profile_name]
    if tuple(contract["profileCheckpoints"]) != policy.checkpoints:
        raise WorkdayConnectFlightCheckError(
            "Readiness coverage does not match the lifecycle policy.",
            error_type="flightcheck-profile-drift",
        )
    observed_families: dict[str, int] = {}
    for family, details in contract["profileFamilies"].items():
        if not isinstance(family, str) or not isinstance(details, Mapping):
            raise WorkdayConnectFlightCheckError(
                "Readiness family requirements are malformed.",
                error_type="malformed-flightcheck-contract",
            )
        minimum = details.get("minimum")
        if (
            not isinstance(minimum, int)
            or isinstance(minimum, bool)
            or minimum < 1
        ):
            raise WorkdayConnectFlightCheckError(
                "Readiness family requirements are malformed.",
                error_type="malformed-flightcheck-contract",
            )
        observed_families[family] = minimum
    if observed_families != dict(policy.families):
        raise WorkdayConnectFlightCheckError(
            "Readiness family requirements have changed.",
            error_type="flightcheck-profile-drift",
        )


def _validate_target(
    contract: Mapping[str, Any],
    state: Mapping[str, Any],
) -> None:
    expected = _agent_context(state)
    for context_name in ("requestedValidationContext", "validationContext"):
        observed = contract[context_name]
        for field, expected_value in expected.items():
            if not expected_value:
                continue
            observed_value = observed.get(field)
            if (
                context_name == "requestedValidationContext"
                and field == "agentId"
                and not _text(observed_value)
            ):
                continue
            if _normalized(observed_value) != _normalized(expected_value):
                raise WorkdayConnectFlightCheckError(
                    f"FlightCheck {context_name}.{field} does not match the "
                    "selected lifecycle target.",
                    error_type="flightcheck-target-mismatch",
                    phase_id="preflight",
                )


def _validate_clients(
    contract: Mapping[str, Any],
    profile_name: str,
) -> tuple[str, ...]:
    policy = PROFILE_POLICIES[profile_name]
    expected = set(policy.clients)
    observed = set(contract["clientAvailability"])
    if observed != expected:
        raise WorkdayConnectFlightCheckError(
            "Readiness client requirements do not match the lifecycle policy.",
            error_type="flightcheck-profile-drift",
        )
    failed = []
    for client in policy.clients:
        details = contract["clientAvailability"][client]
        if (
            not isinstance(details, Mapping)
            or details.get("required") is not True
            or not isinstance(details.get("available"), bool)
            or not isinstance(
                details.get("authenticatedAccountVerified"),
                bool,
            )
        ):
            raise WorkdayConnectFlightCheckError(
                "Readiness client requirements are malformed.",
                error_type="malformed-flightcheck-contract",
            )
        if not details.get("available") or not details.get(
            "authenticatedAccountVerified"
        ):
            failed.append(client)
    if failed:
        return tuple(sorted(failed))
    return ()


def _has_action(
    state: Mapping[str, Any],
    phase_id: str,
    action: str,
) -> bool:
    phase = (state.get("phases") or {}).get(phase_id) or {}
    completed = set(phase.get("completedActions") or [])
    evidence_actions = {
        _text(record.get("action"))
        for record in phase.get("evidence") or []
        if isinstance(record, Mapping)
    }
    return action in completed and action in evidence_actions


def _manual_accepted(
    state: Mapping[str, Any],
    checkpoint_id: str,
) -> bool:
    requirements = manual_evidence_for(checkpoint_id)
    return bool(requirements) and all(
        _has_action(state, phase_id, action)
        for phase_id, action in requirements
    )


def _validate_results(
    contract: Mapping[str, Any],
    state: Mapping[str, Any],
    profile_name: str,
) -> tuple[dict[str, str], tuple[dict[str, str], ...], tuple[str, ...]]:
    policy = PROFILE_POLICIES[profile_name]
    rows: dict[str, Mapping[str, Any]] = {}
    for row in contract["results"]:
        if not isinstance(row, Mapping) or not _text(row.get("checkpointId")):
            raise WorkdayConnectFlightCheckError(
                "FlightCheck returned an invalid result row.",
                error_type="malformed-flightcheck-contract",
            )
        checkpoint_id = _text(row["checkpointId"])
        if checkpoint_id in rows:
            raise WorkdayConnectFlightCheckError(
                "FlightCheck returned duplicate readiness result rows.",
                error_type="malformed-flightcheck-contract",
            )
        rows[checkpoint_id] = row

    emitted_values = [
        _text(value) for value in contract["emittedCheckpoints"]
    ]
    if len(emitted_values) != len(set(emitted_values)):
        raise WorkdayConnectFlightCheckError(
            "FlightCheck returned duplicate emitted checkpoints.",
            error_type="malformed-flightcheck-contract",
        )
    emitted = set(emitted_values)
    missing = []
    family_members: dict[str, list[str]] = {}
    for checkpoint_id in policy.checkpoints:
        if checkpoint_id in policy.families:
            minimum = policy.families[checkpoint_id]
            members = sorted(
                value
                for value in emitted
                if value.startswith(checkpoint_id + "-")
            )
            family_members[checkpoint_id] = members
            if len(members) < minimum or any(
                member not in rows for member in members
            ):
                missing.append(checkpoint_id)
        elif checkpoint_id not in rows or checkpoint_id not in emitted:
            missing.append(checkpoint_id)
    if missing:
        owning_phase = min(
            (
                _checkpoint_phase(checkpoint_id, policy.phase_id)
                for checkpoint_id in missing
            ),
            key=_PHASE_ORDER.index,
        )
        raise WorkdayConnectFlightCheckError(
            "Required readiness evidence is incomplete.",
            error_type="flightcheck-missing-checkpoints",
            phase_id=owning_phase,
            customer_remediation=_customer_remediation(
                owning_phase,
                "flightcheck-missing-checkpoints",
            ),
        )
    if emitted != set(rows):
        raise WorkdayConnectFlightCheckError(
            "Readiness result rows do not match emitted checkpoints.",
            error_type="malformed-flightcheck-contract",
        )

    checkpoint_statuses: dict[str, str] = {}
    suppressions: list[dict[str, str]] = []
    remediation_ids: set[str] = set()
    rejected: list[str] = []
    evaluated_ids = [
        checkpoint_id
        for checkpoint_id in policy.checkpoints
        if checkpoint_id not in policy.families
    ]
    for members in family_members.values():
        evaluated_ids.extend(members)
    for checkpoint_id in evaluated_ids:
        row = rows[checkpoint_id]
        status = _text(row.get("status"))
        checkpoint_statuses[checkpoint_id] = status
        remediation_id = _text(row.get("remediationId"))
        if status == "Passed":
            continue
        if status == "Manual" and _manual_accepted(state, checkpoint_id):
            suppressions.append(
                {
                    "checkpointId": checkpoint_id,
                    "reason": "validated-controller-evidence",
                }
            )
            continue
        rejected.append(f"{checkpoint_id}={status or 'Unknown'}")
        if remediation_id:
            remediation_ids.add(remediation_id)

    for checkpoint_id, row in rows.items():
        if checkpoint_id in evaluated_ids:
            continue
        if _text(row.get("status")) in {"Failed", "Blocked", "Error"}:
            rejected.append(checkpoint_id)
            remediation_id = _text(row.get("remediationId"))
            if remediation_id:
                remediation_ids.add(remediation_id)

    if contract["overall"] == "NOT_READY" and not rejected:
        rejected.append("profile-overall")

    if rejected:
        owning_phase = min(
            (
                _checkpoint_phase(
                    value.split("=", maxsplit=1)[0],
                    policy.phase_id,
                )
                for value in rejected
            ),
            key=_PHASE_ORDER.index,
        )
        raise WorkdayConnectFlightCheckError(
            "Workday readiness checks need remediation: "
            + ", ".join(rejected),
            error_type="flightcheck-profile-not-ready",
            remediation_ids=tuple(sorted(remediation_ids)),
            phase_id=owning_phase,
            customer_remediation=(
                "Readiness checks needing attention: "
                + ", ".join(rejected)
                + ". "
                + _customer_remediation(
                    owning_phase,
                    "flightcheck-profile-not-ready",
                )
            ),
        )
    return (
        checkpoint_statuses,
        tuple(suppressions),
        tuple(sorted(remediation_ids)),
    )


def evaluate_contract(
    contract: Any,
    state: Mapping[str, Any],
    profile_name: str,
    *,
    source_profile: str | None = None,
    migration_baseline: bool = False,
) -> dict[str, Any]:
    """Validate a FlightCheck contract and return a bounded persisted summary."""
    if profile_name not in PROFILE_POLICIES:
        raise WorkdayConnectFlightCheckError(
            f"Unsupported lifecycle FlightCheck profile: {profile_name}.",
            error_type="unsupported-flightcheck-profile",
        )
    parsed = _validate_contract_shape(contract, profile_name)
    _validate_profile_membership(parsed, profile_name)
    _validate_target(parsed, state)
    failed_clients = _validate_clients(parsed, profile_name)
    if parsed["executionErrors"]:
        execution_phases = [
            _checkpoint_phase(
                _text(row.get("checkpointId")),
                PROFILE_POLICIES[profile_name].phase_id,
            )
            for row in parsed["executionErrors"]
            if isinstance(row, Mapping)
        ]
        raise WorkdayConnectFlightCheckError(
            "FlightCheck reported execution errors.",
            error_type="flightcheck-execution-error",
            phase_id=(
                min(execution_phases, key=_PHASE_ORDER.index)
                if execution_phases
                else PROFILE_POLICIES[profile_name].phase_id
            ),
        )
    checkpoint_statuses, suppressions, remediation_ids = _validate_results(
        parsed,
        state,
        profile_name,
    )
    if failed_clients:
        policy = PROFILE_POLICIES[profile_name]
        client_phases = {
            "graph": "entra",
            "connectivity": "runtime",
        }
        owning_phase = min(
            (
                client_phases.get(client, policy.phase_id)
                for client in failed_clients
            ),
            key=_PHASE_ORDER.index,
        )
        raise WorkdayConnectFlightCheckError(
            "Required authenticated readiness clients are unavailable: "
            + ", ".join(failed_clients),
            error_type="flightcheck-client-unavailable",
            phase_id=owning_phase,
            customer_remediation=_customer_remediation(
                owning_phase,
                "flightcheck-client-unavailable",
            ),
        )
    context = parsed["validationContext"]
    input_fingerprint = validation_input_fingerprint(state, profile_name)
    return {
        "profile": profile_name,
        "sourceProfile": source_profile or profile_name,
        "schemaVersion": RESULT_SCHEMA,
        "overall": "READY",
        "target": {
            field: _text(context.get(field))
            for field in (
                "realm",
                "environmentId",
                "environmentUrl",
                "tenantId",
                "agentSlug",
                "agentSchemaName",
                "agentId",
            )
        },
        "checkpointStatuses": checkpoint_statuses,
        "acceptedSuppressions": list(suppressions),
        "remediationIds": list(remediation_ids),
        "accepted": True,
        "migrationBaseline": migration_baseline,
        "inputFingerprint": input_fingerprint,
    }


def run_profile(
    root: Path,
    state: Mapping[str, Any],
    profile_name: str,
    *,
    source_profile: str | None = None,
    migration_baseline: bool = False,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run one independent profile and return its bounded lifecycle summary."""
    root = root.resolve()
    effective_state = effective_validation_state(root, state)
    policy = PROFILE_POLICIES.get(profile_name)
    phase_id = policy.phase_id if policy else "preflight"
    input_fingerprint = validation_input_fingerprint(
        effective_state,
        profile_name,
    )
    realm = _text(
        (effective_state.get("scope") or {}).get("validationRealm")
    )
    realm_source_valid = (
        (effective_state.get("scope") or {}).get(
            "validationRealmSourceValid"
        )
        is True
    )
    if realm not in {"dev", "test", "prod"}:
        message = (
            "The local foundation configuration could not be read."
            if not realm_source_valid
            else f"Unsupported Workday validation realm: {realm!r}."
        )
        raise WorkdayConnectFlightCheckError(
            message,
            error_type="flightcheck-target-mismatch",
            phase_id="preflight",
            customer_remediation=(
                "Correct the selected environment realm and rerun Preflight."
            ),
            input_fingerprint=input_fingerprint,
        )
    maker = (
        (effective_state.get("operators") or {}).get(
            "powerPlatformMaker"
        )
        or {}
    )
    if not _text(maker.get("username")):
        raise WorkdayConnectFlightCheckError(
            "The recorded Power Platform maker account is required before "
            "readiness validation.",
            error_type="flightcheck-maker-account-required",
            phase_id="preflight",
            customer_remediation=(
                "Rerun Preflight and select the exact Power Platform maker "
                "account for this environment."
            ),
            input_fingerprint=input_fingerprint,
        )
    with tempfile.TemporaryDirectory(prefix="workday-connect-flightcheck-") as raw:
        output_dir = Path(raw)
        config_path = output_dir / "connect-config.json"
        config_path.write_text(
            json.dumps(_config_projection(effective_state), indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            completed = subprocess.run(
                _command(
                    root,
                    effective_state,
                    profile_name,
                    output_dir,
                    config_path,
                    migration_baseline=migration_baseline,
                ),
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise WorkdayConnectFlightCheckError(
                "Workday readiness validation timed out.",
                error_type="flightcheck-timeout",
                phase_id=phase_id,
                customer_remediation=_customer_remediation(
                    phase_id,
                    "flightcheck-timeout",
                ),
                input_fingerprint=input_fingerprint,
            ) from exc
        result_path = output_dir / "results.json"
        if not result_path.is_file():
            raise WorkdayConnectFlightCheckError(
                "Workday readiness validation did not produce a result "
                f"contract (exit code {completed.returncode}).",
                error_type="flightcheck-transport-error",
                phase_id=phase_id,
                customer_remediation=_customer_remediation(
                    phase_id,
                    "flightcheck-transport-error",
                ),
                input_fingerprint=input_fingerprint,
            )
        try:
            document = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkdayConnectFlightCheckError(
                "FlightCheck produced an unreadable result document.",
                error_type="malformed-flightcheck-contract",
                phase_id=phase_id,
                customer_remediation=_customer_remediation(
                    phase_id,
                    "malformed-flightcheck-contract",
                ),
                input_fingerprint=input_fingerprint,
            ) from exc
        contract = document.get("contract") if isinstance(document, dict) else None
        try:
            summary = evaluate_contract(
                contract,
                effective_state,
                profile_name,
                source_profile=source_profile,
                migration_baseline=migration_baseline,
            )
        except WorkdayConnectFlightCheckError as exc:
            exc.phase_id = exc.phase_id or phase_id
            exc.customer_remediation = (
                exc.customer_remediation
                or _customer_remediation(exc.phase_id, exc.error_type)
            )
            exc.input_fingerprint = input_fingerprint
            raise
        if completed.returncode != 0:
            raise WorkdayConnectFlightCheckError(
                "Workday readiness validation ended unexpectedly after "
                "producing a ready result.",
                error_type="flightcheck-transport-error",
                phase_id=phase_id,
                customer_remediation=_customer_remediation(
                    phase_id,
                    "flightcheck-transport-error",
                ),
                input_fingerprint=input_fingerprint,
            )
        return summary
