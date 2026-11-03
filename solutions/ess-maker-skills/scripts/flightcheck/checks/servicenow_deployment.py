# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Shared exact-target deployment checkpoint for ServiceNow DA realms."""

from __future__ import annotations

import copy
from typing import Any

import connect_servicenow_da as snow
from flightcheck.runner import CheckResult, Priority, Role, Status


CHECKPOINT_ID = "SN-DA-DEPLOYMENT-001"
_CATEGORY = "ServiceNow DA deployment"
_TARGET_FIELDS = (
    "agentId",
    "environmentId",
    "tenantId",
    "dataverseUrl",
    "almFamilyId",
    "schemaName",
    "commitSha",
)


def _result(
    status: str,
    result: str,
    remediation: str,
    *,
    evidence: dict[str, Any],
) -> CheckResult:
    return CheckResult(
        checkpoint_id=CHECKPOINT_ID,
        category=_CATEGORY,
        priority=Priority.HIGH.value,
        status=status,
        description="Exact ServiceNow target deployment confirmation",
        result=result,
        remediation=remediation,
        evidence=evidence,
        roles=[
            Role.ESS_MAKER.value,
            Role.POWER_PLATFORM_ADMIN.value,
        ],
    )


def _target_context(runner) -> dict[str, Any]:
    direct = getattr(runner, "servicenow_target_context", None)
    if isinstance(direct, dict):
        return copy.deepcopy(direct)
    config = getattr(runner, "config", None)
    config = config if isinstance(config, dict) else {}
    value = config.get("servicenowTargetContext")
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _source_context(runner, target: dict[str, Any]) -> dict[str, Any]:
    direct = getattr(runner, "servicenow_source_context", None)
    if isinstance(direct, dict):
        return direct
    slug = str(
        target.get("sourceAgentSlug")
        or getattr(runner, "agent_slug", "")
        or ""
    ).strip()
    if not slug:
        raise snow.ServiceNowConnectError(
            "Deployment confirmation requires the exact source agent slug."
        )
    return snow.load_context(agent_slug=slug)


def _outcome_from_error(
    exc: snow.ServiceNowConnectError,
) -> tuple[str, str]:
    details = exc.details if isinstance(exc.details, dict) else {}
    status_code = details.get("statusCode") or details.get("httpStatus")
    recovery = details.get("recoveryHandoff")
    recovery = recovery if isinstance(recovery, dict) else {}
    category = str(recovery.get("category") or "")
    if status_code in {401, 403} or category == "Read permission":
        return "permission", Status.BLOCKED.value
    if status_code == 429 or category == "Read throttled":
        return "throttled", Status.BLOCKED.value
    if details.get("targetAbsenceProven") is True:
        return "missing", Status.NOT_CONFIGURED.value
    if details.get("matchCount", 0) > 1:
        return "ambiguous", Status.FAILED.value
    if (
        "mismatch" in category.casefold()
        or "conflict" in str(exc).casefold()
        or any(
            key in details
            for key in (
                "configuredTargetAgentId",
                "siblingTargetAgentId",
                "expectedSchemaName",
                "observedSchemaName",
            )
        )
    ):
        return "conflict", Status.FAILED.value
    if category == "Read or network error":
        return "network", Status.ERROR.value
    return "unknown", Status.ERROR.value


def _expected_mismatches(
    expected: dict[str, Any],
    observed: dict[str, Any],
) -> dict[str, dict[str, str]]:
    mismatches: dict[str, dict[str, str]] = {}
    for field in _TARGET_FIELDS:
        expected_value = str(expected.get(field) or "").strip()
        if not expected_value:
            continue
        observed_value = str(observed.get(field) or "").strip()
        if expected_value.casefold() != observed_value.casefold():
            mismatches[field] = {
                "expected": expected_value,
                "observed": observed_value,
            }
    return mismatches


def deployment_result_for_resolved_target(
    *,
    profile: str,
    realm: str,
    resolved: dict[str, Any],
    expected: dict[str, Any] | None = None,
) -> CheckResult:
    observed = {
        field: resolved.get(field)
        for field in _TARGET_FIELDS
    }
    observed["realm"] = realm
    observed["profile"] = profile
    mismatches = _expected_mismatches(expected or {}, observed)
    evidence = {
        "outcome": "conflict" if mismatches else "found",
        "profile": profile,
        "realm": realm,
        "target": copy.deepcopy(observed),
        "mismatches": mismatches,
        "remoteMutationCount": 0,
    }
    if mismatches:
        return _result(
            Status.FAILED.value,
            "Read-only discovery found a conflicting target deployment.",
            (
                "Have the ALM owner correct the exact target association; "
                "do not borrow another realm, environment, agent, family, "
                "schema, or commit."
            ),
            evidence=evidence,
        )
    return _result(
        Status.PASSED.value,
        (
            f"Read-only discovery proved the exact {realm.title()} "
            f"{profile.upper()} target deployment, agent, environment, "
            "tenant, Dataverse URL, ALM family, schema, and deployed commit."
        ),
        "",
        evidence=evidence,
    )


def run_servicenow_deployment_checks(runner) -> list[CheckResult]:
    target_context = _target_context(runner)
    profile = str(target_context.get("profile") or "").strip().casefold()
    realm = str(target_context.get("realm") or "").strip().casefold()
    evidence = {
        "outcome": "unknown",
        "profile": profile,
        "realm": realm,
        "remoteMutationCount": 0,
    }
    if profile not in {"hrsd", "itsm"} or realm not in {"test", "prod"}:
        return [
            _result(
                Status.ERROR.value,
                "The target profile/realm context is missing or invalid.",
                (
                    "Provide profile hrsd/itsm and realm test/prod in "
                    "servicenowTargetContext, then retry this read-only check."
                ),
                evidence=evidence,
            )
        ]
    try:
        context = _source_context(runner, target_context)
        with snow.product_profile_context(profile):
            resolved = snow._resolve_target_realm(context, realm=realm)
    except snow.ServiceNowConnectError as exc:
        outcome, status = _outcome_from_error(exc)
        details = copy.deepcopy(exc.details)
        evidence.update(
            {
                "outcome": outcome,
                "details": details if isinstance(details, dict) else {},
            }
        )
        return [
            _result(
                status,
                str(exc),
                (
                    "Use the returned typed recovery evidence to restore exact "
                    "read access or correct the target deployment. This check "
                    "never runs promotion."
                ),
                evidence=evidence,
            )
        ]
    except Exception as exc:  # noqa: BLE001 - typed unknown result
        evidence["errorType"] = type(exc).__name__
        return [
            _result(
                Status.ERROR.value,
                f"Target deployment proof is unknown: {type(exc).__name__}: {exc}",
                "Restore the read-only target discovery path and retry.",
                evidence=evidence,
            )
        ]

    client = resolved.pop("client", None)
    check = deployment_result_for_resolved_target(
        profile=profile,
        realm=realm,
        resolved=resolved,
        expected=(
            target_context.get("expected")
            if isinstance(target_context.get("expected"), dict)
            else {}
        ),
    )
    if check.status != Status.PASSED.value:
        return [check]
    runner._servicenow_resolved_target = {
        **copy.deepcopy(resolved),
        "client": client,
    }
    return [check]
