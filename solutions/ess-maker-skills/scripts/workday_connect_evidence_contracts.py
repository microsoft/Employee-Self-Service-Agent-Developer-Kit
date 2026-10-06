# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Runtime and employee evidence contracts for Workday Connect."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Mapping

from workday_connect_model import WorkdayConnectModelError, load_catalog


class WorkdayConnectContractError(WorkdayConnectModelError):
    """Raised when a Workday Connect evidence contract is invalid."""


def required_text(
    document: Mapping[str, Any],
    key: str,
    label: str,
) -> str:
    value = str(document.get(key) or "").strip()
    if not value:
        raise WorkdayConnectContractError(f"{label} is required.")
    return value


EMPLOYEE_VALIDATION_REMEDIATIONS: dict[str, dict[str, str]] = {
    "WD-E2E-001": {
        "failureCategory": "employee-authentication",
        "failureSurface": "authentication-prompt",
        "remediation": (
            "Verify the employee assignment and identify which sign-in "
            "surface is prompting again."
        ),
    },
    "WD-E2E-002": {
        "failureCategory": "workday-connection",
        "failureSurface": "workday-connection",
        "remediation": (
            "Verify the selected Workday connection is authenticated and "
            "targets the reviewed Workday resource."
        ),
    },
    "WD-E2E-003": {
        "failureCategory": "runtime-flow",
        "failureSurface": "flow-run",
        "remediation": (
            "Inspect the failed Workday flow run and reverify delegated "
            "authorization before retrying."
        ),
    },
    "WD-E2E-004": {
        "failureCategory": "employee-context",
        "failureSurface": "agent-chat",
        "remediation": (
            "Verify the employee NameID and User Context V2 mapping before "
            "retrying."
        ),
    },
    "WD-E2E-005": {
        "failureCategory": "network",
        "failureSurface": "network-path",
        "remediation": (
            "Verify the required Workday REST and SOAP hosts are reachable "
            "from the configured runtime."
        ),
    },
    "WD-E2E-006": {
        "failureCategory": "workday-access",
        "failureSurface": "workday-response",
        "remediation": (
            "Ask a Workday administrator to verify the test employee's "
            "functional-area and domain access."
        ),
    },
    "WD-E2E-007": {
        "failureCategory": "publish-or-agent",
        "failureSurface": "agent-availability",
        "remediation": (
            "Publish the selected agent and verify the employee is testing "
            "the reviewed agent in the target environment."
        ),
    },
    "WD-E2E-999": {
        "failureCategory": "unknown",
        "failureSurface": "other",
        "remediation": (
            "Capture the failing surface without employee data and route it "
            "to ESS support for classification."
        ),
    },
}

EMPLOYEE_VALIDATION_RESULT_IDS = {
    "Failed - repeated sign-in": "WD-E2E-001",
    "Failed - connector error": "WD-E2E-002",
    "Failed - flow error": "WD-E2E-003",
    "Failed - employee mismatch": "WD-E2E-004",
    "Failed - network error": "WD-E2E-005",
    "Failed - Workday access denied": "WD-E2E-006",
    "Failed - agent not published or unavailable": "WD-E2E-007",
    "Failed - another issue": "WD-E2E-999",
}

EMPLOYEE_VALIDATION_FAILURE_SURFACE_CHOICES = {
    "Agent chat": "agent-chat",
    "Authentication prompt": "authentication-prompt",
    "Workday connection": "workday-connection",
    "Flow run": "flow-run",
    "Network path": "network-path",
    "Workday response": "workday-response",
    "Agent availability": "agent-availability",
    "Other": "other",
}

EMPLOYEE_VALIDATION_FAILURE_SURFACES = frozenset(
    EMPLOYEE_VALIDATION_FAILURE_SURFACE_CHOICES.values()
)

_LEGACY_EMPLOYEE_FAILURE_IDS = {
    "employee-authentication": "WD-E2E-001",
    "repeated-sign-in": "WD-E2E-001",
    "sign-in-loop": "WD-E2E-001",
    "connector-error": "WD-E2E-002",
    "workday-connection": "WD-E2E-002",
    "flow-error": "WD-E2E-003",
    "runtime-flow": "WD-E2E-003",
    "employee-context": "WD-E2E-004",
    "employee-mismatch": "WD-E2E-004",
    "network": "WD-E2E-005",
    "network-error": "WD-E2E-005",
    "workday-access": "WD-E2E-006",
    "workday-access-denied": "WD-E2E-006",
    "agent-not-published": "WD-E2E-007",
    "publish-or-agent": "WD-E2E-007",
    "unknown": "WD-E2E-999",
}


def _normalized_timestamp(value: str, label: str) -> str:
    normalized = value.replace("Z", "+00:00")
    try:
        observed_at = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise WorkdayConnectContractError(
            f"{label} must be ISO-8601."
        ) from exc
    if observed_at.tzinfo is None:
        raise WorkdayConnectContractError(
            f"{label} must include a timezone."
        )
    return observed_at.astimezone(timezone.utc).isoformat().replace(
        "+00:00",
        "Z",
    )


def validate_employee_evidence(
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        raise WorkdayConnectContractError(
            "Employee validation evidence must contain a JSON object."
        )
    allowed = {"scenarioName", "testUserCategory", "timestamp", "outcome"}
    unexpected = sorted(set(evidence) - allowed)
    if unexpected:
        raise WorkdayConnectContractError(
            "Employee validation evidence contains unsupported fields: "
            + ", ".join(unexpected)
        )
    required = {"testUserCategory", "timestamp", "outcome"}
    result = {key: required_text(evidence, key, key) for key in required}
    scenario_name = str(evidence.get("scenarioName") or "").strip()
    if scenario_name:
        result["scenarioName"] = scenario_name
    if result["outcome"].casefold() not in {"passed", "verified"}:
        raise WorkdayConnectContractError(
            "Employee validation outcome must be passed or verified."
        )
    category = result["testUserCategory"].casefold()
    if category == "maker":
        return result
    explicitly_non_maker = (
        "non-maker" in category or "non maker" in category
    )
    if (
        "employee" not in category
        or "admin" in category
        or ("maker" in category and not explicitly_non_maker)
    ):
        raise WorkdayConnectContractError(
            "Employee validation must use a signed-in non-maker employee."
        )
    result["timestamp"] = _normalized_timestamp(
        result["timestamp"],
        "Employee validation timestamp",
    )
    return result


def validate_employee_failure_evidence(
    evidence: Mapping[str, Any],
) -> dict[str, str]:
    if not isinstance(evidence, Mapping):
        raise WorkdayConnectContractError(
            "Employee validation failure must contain a JSON object."
        )
    allowed = {
        "remediationId",
        "failureCategory",
        "failureSurface",
        "timestamp",
        "remediation",
    }
    unexpected = sorted(set(evidence) - allowed)
    if unexpected:
        raise WorkdayConnectContractError(
            "Employee validation failure contains unsupported fields: "
            + ", ".join(unexpected)
        )
    timestamp = _normalized_timestamp(
        required_text(evidence, "timestamp", "timestamp"),
        "Employee validation failure timestamp",
    )
    supplied_remediation_id = str(evidence.get("remediationId") or "").strip()
    if supplied_remediation_id:
        remediation_id = supplied_remediation_id.upper()
    else:
        legacy_category = required_text(
            evidence,
            "failureCategory",
            "failureCategory",
        )
        required_text(evidence, "remediation", "remediation")
        normalized_category = re.sub(
            r"[^a-z0-9]+",
            "-",
            legacy_category.casefold(),
        ).strip("-")
        remediation_id = _LEGACY_EMPLOYEE_FAILURE_IDS.get(
            normalized_category,
            "WD-E2E-999",
        )
    contract = EMPLOYEE_VALIDATION_REMEDIATIONS.get(remediation_id)
    if contract is None:
        raise WorkdayConnectContractError(
            "Employee validation remediationId must be one of: "
            + ", ".join(EMPLOYEE_VALIDATION_REMEDIATIONS)
            + "."
        )
    failure_surface = contract["failureSurface"]
    supplied_surface = str(evidence.get("failureSurface") or "").strip()
    if supplied_surface:
        if remediation_id != "WD-E2E-999":
            raise WorkdayConnectContractError(
                "Employee validation failureSurface is accepted only for "
                "WD-E2E-999."
            )
        if supplied_surface not in EMPLOYEE_VALIDATION_FAILURE_SURFACES:
            raise WorkdayConnectContractError(
                "Employee validation failureSurface must be one of: "
                + ", ".join(sorted(EMPLOYEE_VALIDATION_FAILURE_SURFACES))
                + "."
            )
        failure_surface = supplied_surface
    elif supplied_remediation_id and remediation_id == "WD-E2E-999":
        raise WorkdayConnectContractError(
            "Employee validation failureSurface is required for WD-E2E-999."
        )
    return {
        "remediationId": remediation_id,
        "failureCategory": contract["failureCategory"],
        "failureSurface": failure_surface,
        "timestamp": timestamp,
        "remediation": contract["remediation"],
    }


def validate_agent_binding_evidence(
    state: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        raise WorkdayConnectContractError(
            "Agent binding evidence must contain a JSON object."
        )
    allowed = {
        "environmentId",
        "botId",
        "makerUsername",
        "flowAttachment",
        "workdayTopics",
    }
    unexpected = sorted(set(evidence) - allowed)
    if unexpected:
        raise WorkdayConnectContractError(
            "Agent binding evidence contains unsupported fields: "
            + ", ".join(unexpected)
        )
    scope = state.get("scope") or {}
    agent = scope.get("agent") or {}
    expected_environment = required_text(
        scope,
        "environmentId",
        "Workday environment ID",
    )
    expected_bot = required_text(agent, "botId", "Workday agent bot ID")
    observed_environment = required_text(
        evidence,
        "environmentId",
        "Verified environment ID",
    )
    observed_bot = required_text(
        evidence,
        "botId",
        "Verified agent bot ID",
    )
    if observed_environment.casefold() != expected_environment.casefold():
        raise WorkdayConnectContractError(
            "Agent binding verification targeted a different environment."
        )
    if observed_bot.casefold() != expected_bot.casefold():
        raise WorkdayConnectContractError(
            "Agent binding verification targeted a different agent."
        )
    expected_maker = required_text(
        (state.get("operators") or {}).get("powerPlatformMaker") or {},
        "username",
        "Recorded Power Platform maker",
    )
    observed_maker = required_text(
        evidence,
        "makerUsername",
        "Verified Power Platform maker",
    )
    if observed_maker.casefold() != expected_maker.casefold():
        raise WorkdayConnectContractError(
            "Agent binding verification used a different Power Platform maker."
        )
    flow_attachment = evidence.get("flowAttachment")
    if not isinstance(flow_attachment, Mapping):
        raise WorkdayConnectContractError(
            "Agent binding evidence must contain the maker-confirmed Workday "
            "flow attachment."
        )
    attachment_allowed = {
        "outcome",
        "botId",
        "flowNames",
        "parameterSharingOutcome",
    }
    attachment_unexpected = sorted(
        set(flow_attachment) - attachment_allowed
    )
    if attachment_unexpected:
        raise WorkdayConnectContractError(
            "Workday flow attachment evidence contains unsupported fields: "
            + ", ".join(attachment_unexpected)
        )
    if flow_attachment.get("outcome") != "maker-confirmed":
        raise WorkdayConnectContractError(
            "Workday flow attachment must be explicitly confirmed by the maker."
        )
    attachment_bot = required_text(
        flow_attachment,
        "botId",
        "Workday flow attachment agent bot ID",
    )
    if attachment_bot.casefold() != expected_bot.casefold():
        raise WorkdayConnectContractError(
            "Workday flow attachment confirmation targeted a different agent."
        )
    if (
        flow_attachment.get("parameterSharingOutcome")
        != "enabled-for-exposed-connections"
    ):
        raise WorkdayConnectContractError(
            "Workday flow attachment must confirm parameter sharing for every "
            "connection exposed by the agent."
        )
    package_flavor = required_text(
        scope,
        "packageFlavor",
        "Workday package flavor",
    )
    package = (load_catalog().get("packages") or {}).get(package_flavor)
    if not isinstance(package, Mapping):
        raise WorkdayConnectContractError(
            f"Unsupported Workday package flavor: {package_flavor}."
        )
    expected_flow_names = {
        str(name)
        for name in package.get("agentConnectionFlowNames") or []
    }
    if not expected_flow_names:
        raise WorkdayConnectContractError(
            "The selected Workday package does not define agent-facing flows."
        )
    supplied_flow_names = flow_attachment.get("flowNames")
    if (
        not isinstance(supplied_flow_names, list)
        or any(
            not isinstance(name, str) or not name
            for name in supplied_flow_names
        )
        or len(supplied_flow_names) != len(expected_flow_names)
        or set(supplied_flow_names) != expected_flow_names
    ):
        raise WorkdayConnectContractError(
            "Workday flow attachment confirmation must name exactly the "
            "reviewed agent-facing Workday flows."
        )
    topics = evidence.get("workdayTopics")
    if not isinstance(topics, Mapping):
        raise WorkdayConnectContractError(
            "Agent binding evidence must contain Workday topic verification."
        )
    expected_count = topics.get("expected")
    verified_count = topics.get("verified")
    active_count = topics.get("active")
    diagnostics = topics.get("blockingDiagnostics")
    if (
        not isinstance(expected_count, int)
        or isinstance(expected_count, bool)
        or expected_count <= 0
        or not isinstance(verified_count, int)
        or isinstance(verified_count, bool)
        or not isinstance(active_count, int)
        or isinstance(active_count, bool)
        or verified_count != expected_count
        or active_count != expected_count
        or not isinstance(diagnostics, list)
        or any(not isinstance(diagnostic, Mapping) for diagnostic in diagnostics)
    ):
        raise WorkdayConnectContractError(
            "Every mapped Workday topic must be active and verified, and "
            "reported topic diagnostics must be structured."
        )
    return {
        "environmentId": observed_environment,
        "botId": observed_bot,
        "makerUsername": observed_maker,
        "flowAttachment": {
            "outcome": "maker-confirmed",
            "botId": attachment_bot,
            "flowNames": sorted(expected_flow_names),
            "parameterSharingOutcome": "enabled-for-exposed-connections",
        },
        "workdayTopics": {
            "expected": expected_count,
            "verified": verified_count,
            "active": active_count,
            "blockingDiagnostics": [
                dict(diagnostic) for diagnostic in diagnostics
            ],
        },
    }
