# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Pure state transformations shared by Workday Connect persistence paths."""

from __future__ import annotations

import copy
from typing import Any, Mapping

from workday_connect_model import (
    ADMINISTRATOR_PARTIAL_FIELDS,
    PHASE_DEFINITIONS,
    TENANT_FOUNDATION_REQUIRED_ENDPOINT_KEYS,
    TENANT_FOUNDATION_REQUIRED_IDENTIFIER_KEYS,
    PhaseStatus,
    default_administrator_state,
    utc_now,
)


_FOUNDATION_SCOPE_KEYS = ("entraTenantId", "workdayTenant")
_FOUNDATION_ENTRA_IDENTIFIER_KEYS = (
    "entraAppId",
    "entraAppObjectId",
    "entraServicePrincipalId",
    "entraAppIdUri",
    "microsoftEntraIdentifier",
    "entraLoginUrl",
    "replyUrl",
    "workdaySamlEntityId",
    "scopeGuid",
    "signingCertificate",
)
_LEGACY_WORKDAY_AUTHORIZATION_FIELDS = frozenset(
    {
        "authorizationOutcome",
        "authorizationRemediationDomain",
        "authorizationRemediationScenario",
        "authorizationRetestOutcome",
    }
)


def discard_legacy_workday_admin_authorization(
    state: dict[str, Any],
) -> None:
    """Remove obsolete Phase 3 authorization fields from persisted snapshots."""

    def clean_phase(phase: Any) -> None:
        if not isinstance(phase, dict):
            return
        administrator = phase.get("administrator")
        if isinstance(administrator, dict):
            partial = administrator.get("partialEvidence")
            if isinstance(partial, dict):
                for field in _LEGACY_WORKDAY_AUTHORIZATION_FIELDS:
                    partial.pop(field, None)
            invalid = administrator.get("invalidFields")
            if isinstance(invalid, list):
                administrator["invalidFields"] = [
                    field
                    for field in invalid
                    if field not in _LEGACY_WORKDAY_AUTHORIZATION_FIELDS
                ]
        evidence = phase.get("evidence")
        if isinstance(evidence, list):
            for record in evidence:
                if not isinstance(record, dict):
                    continue
                for field in _LEGACY_WORKDAY_AUTHORIZATION_FIELDS:
                    record.pop(field, None)

    phases = state.get("phases")
    if isinstance(phases, dict):
        clean_phase(phases.get("workday-admin"))
    foundation = state.get("tenantFoundation")
    if isinstance(foundation, dict):
        foundation_phases = foundation.get("phases")
        if isinstance(foundation_phases, dict):
            clean_phase(foundation_phases.get("workday-admin"))
    targets = state.get("targets")
    if isinstance(targets, dict):
        for target in targets.values():
            if not isinstance(target, dict):
                continue
            target_phases = target.get("phases")
            if isinstance(target_phases, dict):
                clean_phase(target_phases.get("workday-admin"))


def reset_phase(phase: dict[str, Any]) -> None:
    administrator = default_administrator_state() if "administrator" in phase else None
    phase.update(
        {
            "status": PhaseStatus.PENDING.value,
            "completedActions": [],
            "approvedPlanHash": None,
            "approvedPlan": None,
            "evidence": [],
            "validationProfiles": {},
            "blocker": None,
            "updatedAt": utc_now(),
        }
    )
    if administrator is not None:
        phase["administrator"] = administrator


def tenant_foundation_from_state(
    state: Mapping[str, Any],
) -> dict[str, Any] | None:
    phases = state.get("phases") or {}
    entra = phases.get("entra") or {}
    workday = phases.get("workday-admin") or {}
    if (
        entra.get("status") != PhaseStatus.COMPLETE.value
        or workday.get("status") != PhaseStatus.COMPLETE.value
    ):
        return None
    scope = state.get("scope") or {}
    if any(not str(scope.get(key) or "").strip() for key in _FOUNDATION_SCOPE_KEYS):
        return None
    identifiers = state.get("identifiers") or {}
    endpoints = state.get("endpoints") or {}
    if any(
        identifiers.get(key) is None or identifiers.get(key) == ""
        for key in TENANT_FOUNDATION_REQUIRED_IDENTIFIER_KEYS
    ):
        return None
    if any(
        not str(endpoints.get(key) or "").strip()
        for key in TENANT_FOUNDATION_REQUIRED_ENDPOINT_KEYS
    ):
        return None
    return {
        "scope": {key: copy.deepcopy(scope[key]) for key in _FOUNDATION_SCOPE_KEYS},
        "identifiers": copy.deepcopy(dict(identifiers)),
        "endpoints": copy.deepcopy(dict(endpoints)),
        "phases": {
            phase_id: {
                "completedActions": copy.deepcopy(phases[phase_id]["completedActions"]),
                "evidence": copy.deepcopy(phases[phase_id]["evidence"]),
                "administrator": copy.deepcopy(phases[phase_id].get("administrator")),
            }
            for phase_id in ("entra", "workday-admin")
        },
        "capturedAt": utc_now(),
    }


def _normalized_foundation_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().casefold()
    if isinstance(value, Mapping):
        return {
            str(key): _normalized_foundation_value(item)
            for key, item in sorted(value.items())
        }
    if isinstance(value, list):
        return [_normalized_foundation_value(item) for item in value]
    return value


def _certificate_identity(value: Any) -> tuple[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    thumbprint = str(value.get("thumbprint") or "").replace(" ", "").strip().casefold()
    valid_to = str(value.get("validTo") or "").strip()[:10]
    if not thumbprint or not valid_to:
        return None
    return thumbprint, valid_to


def foundation_matches_current_entra(
    state: Mapping[str, Any],
    foundation: Mapping[str, Any],
) -> bool:
    scope = state.get("scope") or {}
    foundation_scope = foundation.get("scope") or {}
    for key in _FOUNDATION_SCOPE_KEYS:
        if _normalized_foundation_value(scope.get(key)) != (
            _normalized_foundation_value(foundation_scope.get(key))
        ):
            return False
    identifiers = state.get("identifiers") or {}
    foundation_identifiers = foundation.get("identifiers") or {}
    for key in _FOUNDATION_ENTRA_IDENTIFIER_KEYS:
        if key == "signingCertificate":
            if _certificate_identity(identifiers.get(key)) != (
                _certificate_identity(foundation_identifiers.get(key))
            ):
                return False
            continue
        if _normalized_foundation_value(identifiers.get(key)) != (
            _normalized_foundation_value(foundation_identifiers.get(key))
        ):
            return False
    return True


def legacy_administrator_partial_evidence(
    state: Mapping[str, Any],
    phase_id: str,
) -> dict[str, Any]:
    identifiers = state.get("identifiers") or {}
    endpoints = state.get("endpoints") or {}
    phases = state.get("phases") or {}
    phase = phases.get(phase_id) or {}
    evidence_by_action = {
        str(record.get("action") or ""): record
        for record in (phase.get("evidence") or [])
        if isinstance(record, Mapping)
    }
    if phase_id == "entra":
        administrator_evidence = (
            evidence_by_action.get("administrator-configuration-verified") or {}
        )
        checks = administrator_evidence.get("checks") or {}
        certificate = identifiers.get("signingCertificate") or {}
        candidates = {
            "applicationId": identifiers.get("entraAppId"),
            "replyUrl": identifiers.get("replyUrl"),
            "microsoftEntraIdentifier": identifiers.get("microsoftEntraIdentifier"),
            "loginUrl": identifiers.get("entraLoginUrl"),
            "nameIdSource": (
                (checks.get("nameId") or {}).get("observedValue")
                if isinstance(checks, Mapping)
                else None
            ),
            "samlSigningOption": (
                (checks.get("samlSigningOption") or {}).get("observedValue")
                if isinstance(checks, Mapping)
                else None
            ),
            "certificateThumbprint": (
                certificate.get("thumbprint")
                if isinstance(certificate, Mapping)
                else None
            ),
            "certificateValidFrom": (
                certificate.get("validFrom")
                if isinstance(certificate, Mapping)
                else None
            ),
            "certificateValidTo": (
                certificate.get("validTo") if isinstance(certificate, Mapping) else None
            ),
        }
    else:
        administrator_evidence = (
            evidence_by_action.get("administrator-response-validated") or {}
        )
        candidates = {
            "identityProviderOutcome": administrator_evidence.get(
                "identityProviderOutcome"
            ),
            "enabledServiceProviderId": identifiers.get("workdaySamlEntityId"),
            "certificateSelectionOutcome": administrator_evidence.get(
                "certificateSelectionOutcome"
            ),
            "certificateValidityOutcome": administrator_evidence.get(
                "certificateValidityOutcome"
            ),
            "oauthClientId": identifiers.get("oauthClientId"),
            "oauthTokenUrl": endpoints.get("oauthTokenUrl"),
            "restBaseUrl": endpoints.get("restBaseUrl"),
            "soapBaseUrl": endpoints.get("soapBaseUrl"),
            "authenticationPolicyOutcome": administrator_evidence.get(
                "authenticationPolicyOutcome"
            ),
            "networkReadinessOutcome": administrator_evidence.get(
                "networkReadinessOutcome"
            ),
        }
    return {
        key: copy.deepcopy(value)
        for key, value in candidates.items()
        if value not in (None, "", [], {})
        and key in ADMINISTRATOR_PARTIAL_FIELDS[phase_id]
    }


def invalidate_from_phase(
    state: dict[str, Any],
    phase_id: str,
) -> None:
    invalidate = False
    for definition in PHASE_DEFINITIONS:
        if definition.identifier.value == phase_id:
            invalidate = True
        if invalidate:
            reset_phase(state["phases"][definition.identifier.value])


def invalidate_after_phase(
    state: dict[str, Any],
    phase_id: str,
) -> None:
    matched = False
    for definition in PHASE_DEFINITIONS:
        if matched:
            reset_phase(state["phases"][definition.identifier.value])
        if definition.identifier.value == phase_id:
            matched = True
