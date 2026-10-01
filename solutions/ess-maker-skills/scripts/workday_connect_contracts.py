# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Exact Entra and Workday administrator contracts for Workday connect."""

from __future__ import annotations

from datetime import datetime, timezone
import ipaddress
import re
from typing import Any, Mapping
from urllib.parse import urlparse

from workday_connect_model import (
    ADMINISTRATOR_PARTIAL_FIELDS,
    ADMINISTRATOR_PHASES,
    PhaseStatus,
    WorkdayConnectModelError,
    load_catalog,
    workday_saml_entity_id,
)


WORKDAY_CONNECTOR_APP_ID = "4e4707ca-5f53-46a6-a819-f7765446e6ff"
GRAPH_DELEGATED_PERMISSIONS = ("openid", "profile", "User.Read")
WORKDAY_AUTHENTICATION_POLICY_OUTCOMES = {
    "existing-active-policy",
    "reviewed-policy-activated",
}
WORKDAY_NETWORK_READINESS_OUTCOMES = {
    "confirmed-hosts-allowed",
    "no-customer-firewall-change-required",
}
WORKDAY_ROLLOUT_TYPES = {
    "entire-workforce",
    "limited-or-test",
}
WORKDAY_DOMAIN_PERMISSION_OUTCOMES = {
    "get-permission-verified",
}
WORKDAY_AUTHORIZATION_OUTCOMES = {
    "verified",
    "task-not-authorized-remediated",
}
WORKDAY_API_CLIENT_OUTCOMES = {
    "existing-client-verified",
    "new-client-registered",
}
WORKDAY_REQUIRED_FUNCTIONAL_AREA_SCOPES = (
    "Core Payroll",
    "Organizations and Roles",
    "Staffing",
    "Time Off and Leave",
)
WORKDAY_AUTHORIZATION_RETEST_OUTCOMES = {
    "verified-after-remediation",
}
ENTRA_PRESERVATION_OUTCOMES = {
    "preserved",
    "remediated",
}
_SECRET_VALUE_MARKERS = (
    "-----begin certificate-----",
    "-----begin private key-----",
    "-----begin rsa private key-----",
    "client_secret=",
    '"client_secret"',
    '"access_token"',
    '"refresh_token"',
)


class WorkdayConnectContractError(WorkdayConnectModelError):
    """Raised when an exact Entra or Workday contract cannot be produced."""


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


def _required_text(
    document: Mapping[str, Any],
    key: str,
    label: str,
) -> str:
    value = str(document.get(key) or "").strip()
    if not value:
        raise WorkdayConnectContractError(f"{label} is required.")
    return value


def _safe_nonsecret_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise WorkdayConnectContractError(f"{label} is required.")
    if len(text) > 2048 or "\x00" in text:
        raise WorkdayConnectContractError(
            f"{label} exceeds the safe evidence limit."
        )
    normalized = text.casefold()
    if any(marker in normalized for marker in _SECRET_VALUE_MARKERS):
        raise WorkdayConnectContractError(
            f"{label} appears to contain secret or certificate material."
        )
    return text


def _reject_secret_like_value(value: Any, label: str) -> None:
    if isinstance(value, str):
        normalized = value.casefold()
        if len(value) > 2048 or "\x00" in value or any(
            marker in normalized for marker in _SECRET_VALUE_MARKERS
        ):
            raise WorkdayConnectContractError(
                f"{label} appears to contain secret or certificate material."
            )
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_secret_like_value(item, f"{label}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secret_like_value(item, f"{label}[{index}]")


def _certificate_thumbprint(value: Any, label: str) -> str:
    normalized = re.sub(r"[\s:]", "", str(value or ""))
    if not re.fullmatch(r"[0-9A-Fa-f]{4,128}", normalized):
        raise WorkdayConnectContractError(
            f"{label} must contain hexadecimal thumbprint characters only."
        )
    return normalized.upper()


def _normalized_uri(value: Any) -> str:
    return str(value or "").strip().rstrip("/").casefold()


def _candidate(candidate: Any) -> dict[str, Any]:
    if not isinstance(candidate, Mapping):
        raise WorkdayConnectContractError(
            "Every discovered Entra application must be an object."
        )
    identifier_uris = candidate.get("identifierUris") or []
    if not isinstance(identifier_uris, list):
        raise WorkdayConnectContractError(
            "Discovered Entra identifierUris must be an array."
        )
    reply_urls = candidate.get("replyUrls") or []
    if not isinstance(reply_urls, list):
        raise WorkdayConnectContractError(
            "Discovered Entra replyUrls must be an array."
        )
    return {
        "displayName": _required_text(
            candidate, "displayName", "Entra app display name"
        ),
        "appId": _required_text(candidate, "appId", "Entra app ID"),
        "objectId": _required_text(candidate, "objectId", "Entra app object ID"),
        "servicePrincipalId": _required_text(
            candidate,
            "servicePrincipalId",
            "Entra service principal ID",
        ),
        "identifierUris": [
            str(value).strip() for value in identifier_uris if str(value).strip()
        ],
        "replyUrls": [
            _absolute_https_url(value, "Discovered Entra Reply URL")
            for value in reply_urls
            if str(value or "").strip()
        ],
    }


def _require_preflight(state: Mapping[str, Any]) -> None:
    phases = state.get("phases")
    if not isinstance(phases, Mapping):
        raise WorkdayConnectContractError(
            "Initialize Workday connect before building an Entra plan."
        )
    preflight = phases.get("preflight")
    if (
        not isinstance(preflight, Mapping)
        or preflight.get("status") != PhaseStatus.COMPLETE.value
    ):
        raise WorkdayConnectContractError(
            "Complete Workday preflight before planning Entra changes."
        )


def build_entra_handoff(
    state: Mapping[str, Any],
    discovery: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one exact Entra administrator handoff after discovery."""
    _require_preflight(state)
    if not isinstance(discovery, Mapping):
        raise WorkdayConnectContractError("Entra discovery must contain a JSON object.")
    scope = state.get("scope") or {}
    tenant = _required_text(scope, "workdayTenant", "Workday tenant")
    entity_id = workday_saml_entity_id(tenant)
    entra_tenant_id = _required_text(
        scope, "entraTenantId", "Microsoft Entra tenant ID"
    )
    candidates = [_candidate(value) for value in (discovery.get("applications") or [])]
    matches = [
        value
        for value in candidates
        if _normalized_uri(entity_id)
        in {_normalized_uri(uri) for uri in value["identifierUris"]}
    ]
    if len(matches) > 1:
        raise WorkdayConnectContractError(
            "More than one Entra application has the exact Workday SAML "
            "Service Provider ID. Resolve the duplicate before continuing."
        )
    allow_create = discovery.get("allowCreate") is True
    if not matches and not allow_create:
        raise WorkdayConnectContractError(
            "No exact Entra application was found and application creation "
            "was not authorized for planning."
        )

    app = matches[0] if matches else None
    target = (
        {
            "mode": "reuse",
            **app,
        }
        if app
        else {
            "mode": "create",
            "displayName": str(
                discovery.get("newDisplayName") or "Workday (ESS Copilot)"
            ).strip(),
            "galleryTemplate": "Workday",
        }
    )
    app_id_uri = f"api://{app['appId']}" if app else None
    foundation = state.get("tenantFoundation")
    foundation_scope = (
        foundation.get("scope") if isinstance(foundation, Mapping) else {}
    )
    foundation_identifiers = (
        foundation.get("identifiers") if isinstance(foundation, Mapping) else {}
    )
    reusable = bool(
        app
        and isinstance(foundation_scope, Mapping)
        and isinstance(foundation_identifiers, Mapping)
        and str(foundation_scope.get("entraTenantId") or "").casefold()
        == entra_tenant_id.casefold()
        and str(foundation_scope.get("workdayTenant") or "").casefold()
        == tenant.casefold()
        and str(foundation_identifiers.get("entraAppId") or "").casefold()
        == app["appId"].casefold()
    )
    if app is None:
        actions = [
            "Instantiate the Workday gallery application in the selected "
            "Microsoft Entra tenant",
            "Rerun exact application discovery after Entra assigns the "
            "application and service-principal identifiers",
        ]
    elif reusable:
        actions = [
            "Reread the exact Workday application and service principal "
            "through Microsoft Graph",
            "Reuse the stored tenant configuration when every required "
            "setting still verifies; involve an administrator only for "
            "missing or changed settings",
        ]
    else:
        actions = [
            "Reuse the exact Workday SAML application",
            "Configure SAML mode, the signing certificate, and the exact "
            f"Service Provider ID {entity_id}",
            "Expose the user_impersonation scope at the Entra application ID "
            "URI and pre-authorize the Workday connector",
            "Add openid, profile, and User.Read delegated permissions",
            "Grant administrator consent",
            "Configure enterprise-application user assignment",
            "Map NameID to the attribute that equals the Workday User Name",
            "Set the SAML signing option to Sign SAML response and assertion",
        ]
    return {
        "phase": "entra",
        "scope": {
            "entraTenantId": entra_tenant_id,
            "workdayTenant": tenant,
            "workdaySamlEntityId": entity_id,
        },
        "target": target,
        "identifiers": {
            "workdaySamlEntityId": entity_id,
            "entraAppIdUri": app_id_uri,
        },
        "permissions": {
            "connectorAppId": WORKDAY_CONNECTOR_APP_ID,
            "graphDelegated": list(GRAPH_DELEGATED_PERMISSIONS),
            "scope": "user_impersonation",
        },
        "foundationReuse": {
            "eligible": reusable,
        },
        "requiresRediscovery": app is None,
        "actions": actions,
    }


_ENTRA_CHECKS = {
    "samlMode",
    "signingCertificate",
    "connectorPreauthorized",
    "graphDelegatedPermissions",
    "adminConsent",
    "userAssignment",
    "nameId",
    "samlSigningOption",
    "existingScopesPreserved",
    "authorizedClientsPreserved",
    "permissionsPreserved",
}
_GRAPH_ONLY_ENTRA_CHECKS = _ENTRA_CHECKS - {
    "nameId",
    "samlSigningOption",
}


def _normalize_entra_check(name: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise WorkdayConnectContractError(
            f"Entra verification check '{name}' must contain evidence."
        )
    allowed = {"outcome", "provenance"}
    if name in {
        "nameId",
        "samlSigningOption",
        "existingScopesPreserved",
        "authorizedClientsPreserved",
        "permissionsPreserved",
    }:
        allowed.add("observedValue")
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise WorkdayConnectContractError(
            f"Entra verification check '{name}' contains unsupported fields: "
            + ", ".join(unexpected)
        )
    outcome = str(value.get("outcome") or "").strip().casefold()
    if outcome not in {"verified", "confirmed"}:
        raise WorkdayConnectContractError(
            f"Entra verification check '{name}' is incomplete."
        )
    provenance = str(value.get("provenance") or "").strip()
    if not provenance:
        raise WorkdayConnectContractError(
            f"Entra verification check '{name}' lacks provenance."
        )
    normalized_provenance = provenance.casefold()
    if name in _GRAPH_ONLY_ENTRA_CHECKS and normalized_provenance != "microsoft-graph":
        raise WorkdayConnectContractError(
            f"Entra verification check '{name}' must be proven by Microsoft Graph."
        )
    if name in _GRAPH_ONLY_ENTRA_CHECKS and outcome != "verified":
        raise WorkdayConnectContractError(
            f"Entra verification check '{name}' must have outcome 'verified'."
        )
    if (
        name == "samlSigningOption"
        and normalized_provenance != "administrator-attestation"
    ):
        raise WorkdayConnectContractError(
            "Entra verification check 'samlSigningOption' must be confirmed "
            "by administrator attestation."
        )
    if name == "samlSigningOption" and outcome != "confirmed":
        raise WorkdayConnectContractError(
            "Entra verification check 'samlSigningOption' must have outcome "
            "'confirmed'."
        )
    if name == "nameId" and normalized_provenance not in {
        "microsoft-graph",
        "administrator-attestation",
    }:
        raise WorkdayConnectContractError(
            "Entra verification check 'nameId' must be proven by Microsoft "
            "Graph or administrator attestation."
        )
    if name == "nameId":
        expected_outcome = (
            "verified" if normalized_provenance == "microsoft-graph" else "confirmed"
        )
        if outcome != expected_outcome:
            raise WorkdayConnectContractError(
                "Entra verification check 'nameId' has an outcome that does "
                "not match its provenance."
            )
    result = {
        "outcome": outcome,
        "provenance": provenance,
    }
    if name in {
        "nameId",
        "samlSigningOption",
        "existingScopesPreserved",
        "authorizedClientsPreserved",
        "permissionsPreserved",
    }:
        observed_value = _required_text(
            value,
            "observedValue",
            f"Entra verification check '{name}' observed value",
        )
        if (
            name == "samlSigningOption"
            and observed_value.casefold()
            != "sign saml response and assertion".casefold()
        ):
            raise WorkdayConnectContractError(
                "Entra verification check 'samlSigningOption' must record "
                "'Sign SAML response and assertion'."
            )
        if (
            name
            in {
                "existingScopesPreserved",
                "authorizedClientsPreserved",
                "permissionsPreserved",
            }
            and observed_value not in ENTRA_PRESERVATION_OUTCOMES
        ):
            raise WorkdayConnectContractError(
                f"Entra verification check '{name}' must record preserved "
                "or remediated."
            )
        result["observedValue"] = observed_value
    return result


def validate_entra_verification(
    state: Mapping[str, Any],
    verification: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate safe Graph reread evidence after the administrator handoff."""
    if not isinstance(verification, Mapping):
        raise WorkdayConnectContractError(
            "Entra verification must contain a JSON object."
        )
    _reject_secret_like_value(verification, "Entra verification")
    allowed = {
        "tenantId",
        "selectedDirectory",
        "application",
        "scopeGuid",
        "replyUrl",
        "microsoftEntraIdentifier",
        "loginUrl",
        "certificate",
        "checks",
    }
    unexpected = sorted(set(verification) - allowed)
    if unexpected:
        raise WorkdayConnectContractError(
            "Entra verification contains unsupported fields: "
            + ", ".join(unexpected)
        )
    application = _candidate(verification.get("application"))
    scope = state.get("scope") or {}
    expected_tenant_id = _required_text(
        scope,
        "entraTenantId",
        "Microsoft Entra tenant ID",
    )
    observed_tenant_id = _required_text(
        verification,
        "tenantId",
        "Verified Microsoft Entra tenant ID",
    )
    if observed_tenant_id.casefold() != expected_tenant_id.casefold():
        raise WorkdayConnectContractError(
            "The verified Microsoft Entra tenant does not match the tenant "
            "recorded during Workday preflight."
        )
    tenant = _required_text(scope, "workdayTenant", "Workday tenant")
    expected_entity_id = workday_saml_entity_id(tenant)
    expected_app_uri = f"api://{application['appId']}"
    expected_entra_identifier = (
        f"https://sts.windows.net/{expected_tenant_id}/"
    )
    expected_login_url = (
        f"https://login.microsoftonline.com/{expected_tenant_id}/saml2"
    )
    observed_uris = {_normalized_uri(value) for value in application["identifierUris"]}
    missing_uris = [
        value
        for value in (expected_entity_id, expected_app_uri)
        if _normalized_uri(value) not in observed_uris
    ]
    if missing_uris:
        raise WorkdayConnectContractError(
            "The verified Entra application is missing required identifier "
            "URIs: " + ", ".join(missing_uris)
        )
    checks = verification.get("checks")
    if not isinstance(checks, Mapping):
        raise WorkdayConnectContractError(
            "Entra verification checks must contain an object."
        )
    supplied_checks = dict(checks)
    unexpected_checks = sorted(supplied_checks.keys() - _ENTRA_CHECKS)
    if unexpected_checks:
        raise WorkdayConnectContractError(
            "Entra verification contains unsupported checks: "
            + ", ".join(unexpected_checks)
        )
    missing_checks = sorted(_ENTRA_CHECKS - supplied_checks.keys())
    if missing_checks:
        raise WorkdayConnectContractError(
            "Entra verification is incomplete: " + ", ".join(missing_checks)
        )
    normalized_checks = {
        name: _normalize_entra_check(name, supplied_checks[name])
        for name in sorted(_ENTRA_CHECKS)
    }
    selected_directory = verification.get("selectedDirectory")
    if not isinstance(selected_directory, Mapping):
        raise WorkdayConnectContractError(
            "The selected Microsoft Entra directory must contain an object."
        )
    selected_directory_id = _required_text(
        selected_directory,
        "tenantId",
        "Selected Microsoft Entra directory tenant ID",
    )
    selected_directory_name = _required_text(
        selected_directory,
        "displayName",
        "Selected Microsoft Entra directory display name",
    )
    if selected_directory_id.casefold() != expected_tenant_id.casefold():
        raise WorkdayConnectContractError(
            "The selected Microsoft Entra directory does not match the "
            "preflight tenant."
        )
    observed_entra_identifier = _required_text(
        verification,
        "microsoftEntraIdentifier",
        "Microsoft Entra Identifier",
    )
    if _normalized_uri(observed_entra_identifier) != _normalized_uri(
        expected_entra_identifier
    ):
        raise WorkdayConnectContractError(
            "The Microsoft Entra Identifier does not match the selected "
            "directory."
        )
    observed_login_url = _required_text(
        verification,
        "loginUrl",
        "Microsoft Entra Login URL",
    )
    if _normalized_uri(observed_login_url) != _normalized_uri(
        expected_login_url
    ):
        raise WorkdayConnectContractError(
            "The Microsoft Entra Login URL does not match the selected "
            "directory."
        )
    reply_url = _absolute_https_url(
        verification.get("replyUrl"),
        "Microsoft Entra Reply URL",
    )
    if not application["replyUrls"]:
        raise WorkdayConnectContractError(
            "The Graph-authenticated Entra application evidence contains no "
            "Reply URLs."
        )
    if _normalized_uri(reply_url) not in {
        _normalized_uri(value) for value in application["replyUrls"]
    }:
        raise WorkdayConnectContractError(
            "The Microsoft Entra Reply URL is not present in the "
            "Graph-authenticated application/service-principal evidence."
        )
    scope_guid = _required_text(
        verification,
        "scopeGuid",
        "Entra user_impersonation scope ID",
    )
    certificate = verification.get("certificate")
    if not isinstance(certificate, Mapping):
        raise WorkdayConnectContractError(
            "Entra certificate metadata must contain an object."
        )
    safe_certificate = {
        "thumbprint": _certificate_thumbprint(
            certificate.get("thumbprint"),
            "Entra signing certificate thumbprint",
        ),
        "validFrom": _required_text(
            certificate,
            "validFrom",
            "Entra signing certificate validFrom",
        ),
        "validTo": _required_text(
            certificate,
            "validTo",
            "Entra signing certificate validTo",
        ),
    }
    return {
        "identifiers": {
            "entraAppId": application["appId"],
            "entraAppObjectId": application["objectId"],
            "entraServicePrincipalId": application["servicePrincipalId"],
            "entraAppIdUri": expected_app_uri,
            "microsoftEntraIdentifier": expected_entra_identifier,
            "entraLoginUrl": expected_login_url,
            "replyUrl": reply_url,
            "workdaySamlEntityId": expected_entity_id,
            "scopeGuid": scope_guid,
            "signingCertificate": safe_certificate,
        },
        "evidence": {
            "tenantId": observed_tenant_id,
            "selectedDirectory": {
                "tenantId": selected_directory_id,
                "displayName": selected_directory_name,
            },
            "applicationDisplayName": application["displayName"],
            "checks": normalized_checks,
        },
        "partialEvidence": {
            "selectedDirectoryId": selected_directory_id,
            "selectedDirectoryDisplayName": selected_directory_name,
            "applicationId": application["appId"],
            "applicationDisplayName": application["displayName"],
            "applicationObjectId": application["objectId"],
            "servicePrincipalId": application["servicePrincipalId"],
            "applicationIdentifierUris": application["identifierUris"],
            "applicationReplyUrls": application["replyUrls"],
            "scopeGuid": scope_guid,
            "replyUrl": reply_url,
            "microsoftEntraIdentifier": expected_entra_identifier,
            "loginUrl": expected_login_url,
            "entraChecks": normalized_checks,
            "nameIdSource": normalized_checks["nameId"]["observedValue"],
            "samlSigningOption": normalized_checks[
                "samlSigningOption"
            ]["observedValue"],
            "certificateThumbprint": safe_certificate["thumbprint"],
            "certificateValidFrom": safe_certificate["validFrom"],
            "certificateValidTo": safe_certificate["validTo"],
            "scopePreservationOutcome": normalized_checks[
                "existingScopesPreserved"
            ]["observedValue"],
            "authorizedClientPreservationOutcome": normalized_checks[
                "authorizedClientsPreserved"
            ]["observedValue"],
            "permissionPreservationOutcome": normalized_checks[
                "permissionsPreserved"
            ]["observedValue"],
        },
    }


def build_workday_admin_packet(
    state: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one compact handoff packet for the Workday administrator."""
    scope = state.get("scope") or {}
    identifiers = state.get("identifiers") or {}
    tenant = _required_text(scope, "workdayTenant", "Workday tenant")
    expected_entity_id = workday_saml_entity_id(tenant)
    entity_id = _required_text(
        identifiers,
        "workdaySamlEntityId",
        "Workday SAML Service Provider ID",
    )
    if _normalized_uri(entity_id) != _normalized_uri(expected_entity_id):
        raise WorkdayConnectContractError(
            "The Workday SAML Service Provider ID does not match the selected "
            "Workday tenant."
        )
    entra_app_id_uri = _required_text(
        identifiers,
        "entraAppIdUri",
        "Entra application ID URI",
    )
    expected_issuer = _required_text(
        identifiers,
        "microsoftEntraIdentifier",
        "Microsoft Entra Identifier",
    )
    login_url = _required_text(
        identifiers,
        "entraLoginUrl",
        "Microsoft Entra Login URL",
    )
    reply_url = _required_text(
        identifiers,
        "replyUrl",
        "Microsoft Entra Reply URL",
    )
    signing_certificate = identifiers.get("signingCertificate")
    if not isinstance(signing_certificate, Mapping):
        raise WorkdayConnectContractError(
            "Verified Entra signing certificate metadata is required before "
            "building the Workday administrator packet."
        )
    certificate_valid_from = _date_only(
        _required_text(
            signing_certificate,
            "validFrom",
            "Entra signing certificate Valid From",
        ),
        "Entra signing certificate Valid From",
    )
    certificate_valid_to = _date_only(
        _required_text(
            signing_certificate,
            "validTo",
            "Entra signing certificate Valid To",
        ),
        "Entra signing certificate Valid To",
    )
    if _normalized_uri(entity_id) == _normalized_uri(entra_app_id_uri):
        raise WorkdayConnectContractError(
            "The Workday SAML Service Provider ID and Entra application ID URI "
            "must remain distinct."
        )

    packet = {
        "phase": "workday-admin",
        "scope": {
            "workdayTenant": tenant,
            "workdaySamlEntityId": entity_id,
        },
        "referenceValues": {
            "serviceProviderId": entity_id,
            "entraApplicationIdUri": entra_app_id_uri,
            "expectedIdentityProviderIssuer": expected_issuer,
            "loginUrl": login_url,
            "replyUrl": reply_url,
            "certificateValidFrom": certificate_valid_from,
            "certificateValidTo": certificate_valid_to,
        },
        "identityProviderQuestion": {
            "question": (
                "Which sign-in provider does the enabled Workday SAML row "
                "appear to use?"
            ),
            "options": [
                (
                    "Microsoft Entra ID - the Issuer often contains "
                    "login.microsoftonline.com or sts.windows.net"
                ),
                "Okta - the Issuer often contains okta.com",
                (
                    "Ping Identity - the Issuer often contains pingone.com, "
                    "pingidentity.com, or an organization-specific Ping host"
                ),
                "Another sign-in provider",
                "No enabled SAML row",
                "I'm not sure",
            ],
        },
        "certificateSelectionQuestion": {
            "question": (
                "Which certificate is selected on the enabled Microsoft "
                "Entra SAML row in Workday?"
            ),
            "options": [
                "The new certificate created from the Entra Base64 file",
                "A different existing Workday certificate",
                "No certificate is selected",
                "I'm not sure",
            ],
        },
        "issuerConfirmationQuestion": {
            "question": (
                "Does the Issuer in the enabled Microsoft Entra SAML row "
                f"exactly match {expected_issuer}?"
            ),
            "options": [
                "Yes, it matches exactly",
                "No, the displayed Issuer is different",
                "I'm not sure",
            ],
        },
        "certificateValidityQuestion": {
            "question": (
                "Do the selected Workday certificate dates exactly match "
                f"{certificate_valid_from} through {certificate_valid_to}?"
            ),
            "options": [
                "Yes, both dates match exactly",
                "No, one or both dates are different",
                "I'm not sure",
            ],
        },
        "actions": [
            "Identify which sign-in provider the enabled Workday SAML row "
            "uses before changing it",
            "Create a Workday X.509 Public Key from the active Entra SAML "
            "signing certificate, select it on the Microsoft Entra SAML row, "
            "and compare its validity dates",
            f"Set the Workday Service Provider ID to {entity_id}",
            "Enable OAuth 2.0 Clients and SAML in Tenant Setup - Security",
            "Reuse an approved signed-in employee API client when it already "
            "matches the required contract; otherwise register one with "
            "Client Grant Type SAML Bearer, the required functional areas, "
            "and Include Workday Owned Scope set to Yes",
            f"Set the Workday identity-provider SSO service URL to {login_url}",
            f"Set the Workday sign-on redirect URL to {reply_url}",
            "Choose whether the rollout covers the entire workforce or a "
            "limited/test employee security group",
            "Grant Get on Worker Data: Public Worker Reports and "
            "Integration Permissions, keeping domain permissions separate "
            "from OAuth functional-area scopes",
            "Verify an active authentication policy allows SAML for the "
            "intended employee population",
            "Confirm the returned Workday REST and SOAP hosts are reachable "
            "or approved by the organization network policy",
        ],
        "responseForm": {
            "required": [
                "identityProviderOutcome",
                "enabledServiceProviderId",
                "certificateSelectionOutcome",
                "certificateValidityOutcome",
                "oauthClientId",
                "oauthTokenUrl",
                "restBaseUrl",
                "soapBaseUrl",
                "authenticationPolicyOutcome",
                "networkReadinessOutcome",
                "apiClientOutcome",
                "clientGrantType",
                "includeWorkdayOwnedScope",
                "identityProviderSsoServiceUrl",
                "signOnRedirectUrl",
                "rolloutType",
                "employeeSecurityGroup",
                "publicWorkerReportsOutcome",
                "integrationPermissionsGetOutcome",
                "functionalAreaScopes",
                "optionalDomains",
                "authorizationOutcome",
            ],
            "note": (
                "Return configuration evidence only. Do not paste passwords, "
                "client secrets, tokens, cookies, or certificate private keys. "
                "The Workday certificate display name is optional."
            ),
        },
    }
    return packet


def _https_url(value: Any, label: str) -> str:
    text = str(value or "").strip().rstrip("/")
    parsed = urlparse(text)
    try:
        port = parsed.port
    except ValueError as exc:
        raise WorkdayConnectContractError(
            f"{label} must be an HTTPS URL."
        ) from exc
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port not in {None, 443}
    ):
        raise WorkdayConnectContractError(f"{label} must be an HTTPS URL.")
    hostname = parsed.hostname.casefold().rstrip(".")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise WorkdayConnectContractError(
            f"{label} must use a Workday service hostname, not an IP address."
        )
    if not hostname.endswith((".workday.com", ".myworkday.com")):
        raise WorkdayConnectContractError(
            f"{label} must use a Workday-owned service hostname."
        )
    return text


def _absolute_https_url(value: Any, label: str) -> str:
    text = str(value or "").strip().rstrip("/")
    parsed = urlparse(text)
    try:
        port = parsed.port
    except ValueError as exc:
        raise WorkdayConnectContractError(
            f"{label} must be an HTTPS URL."
        ) from exc
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port not in {None, 443}
    ):
        raise WorkdayConnectContractError(f"{label} must be an HTTPS URL.")
    return text


def _safe_string_list(
    value: Any,
    label: str,
    *,
    allow_empty: bool,
) -> list[str]:
    if not isinstance(value, list):
        raise WorkdayConnectContractError(f"{label} must be an array.")
    if any(not isinstance(item, str) for item in value):
        raise WorkdayConnectContractError(
            f"{label} must contain strings."
        )
    normalized = [
        _safe_nonsecret_text(item, f"{label} item")
        for item in value
    ]
    if any(not item for item in normalized):
        raise WorkdayConnectContractError(
            f"{label} must contain non-empty strings."
        )
    if not allow_empty and not normalized:
        raise WorkdayConnectContractError(
            f"{label} must contain at least one value."
        )
    if len(normalized) != len(set(normalized)):
        raise WorkdayConnectContractError(
            f"{label} must not contain duplicates."
        )
    return normalized


def _optional_domains(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise WorkdayConnectContractError(
            "Workday optionalDomains must be an array."
        )
    normalized = []
    seen = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise WorkdayConnectContractError(
                "Every optional Workday domain must identify its supported "
                "scenario."
            )
        unexpected = sorted(set(item) - {"domain", "scenario"})
        if unexpected:
            raise WorkdayConnectContractError(
                "Optional Workday domain contains unsupported fields: "
                + ", ".join(unexpected)
            )
        domain = _safe_nonsecret_text(
            item.get("domain"),
            "Optional Workday domain",
        )
        scenario = _safe_nonsecret_text(
            item.get("scenario"),
            "Optional Workday domain supported scenario",
        )
        key = (domain.casefold(), scenario.casefold())
        if key in seen:
            raise WorkdayConnectContractError(
                "Workday optionalDomains must not contain duplicates."
            )
        seen.add(key)
        normalized.append({"domain": domain, "scenario": scenario})
    return normalized


def validate_administrator_partial_evidence(
    state: Mapping[str, Any],
    phase_id: str,
    fields: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate independent safe fields without discarding sibling values."""
    if phase_id not in ADMINISTRATOR_PHASES:
        raise WorkdayConnectContractError(
            "Administrator partial evidence is supported only for Entra and "
            "Workday administrator phases."
        )
    if not isinstance(fields, Mapping):
        raise WorkdayConnectContractError(
            "Administrator partial evidence fields must contain an object."
        )
    unexpected = sorted(
        set(fields) - ADMINISTRATOR_PARTIAL_FIELDS[phase_id]
    )
    if unexpected:
        raise WorkdayConnectContractError(
            "Administrator partial evidence contains unsupported fields: "
            + ", ".join(unexpected)
        )
    scope = state.get("scope") or {}
    administrator = (
        ((state.get("phases") or {}).get(phase_id) or {}).get(
            "administrator"
        )
        or {}
    )
    available_fields = {
        **dict(administrator.get("partialEvidence") or {}),
        **dict(fields),
    }
    valid_fields: dict[str, Any] = {}
    field_errors: dict[str, str] = {}

    def validate_field(name: str, value: Any) -> Any:
        _reject_secret_like_value(value, name)
        if phase_id == "entra":
            if name == "selectedDirectoryId":
                observed = str(value or "").strip()
                expected = _required_text(
                    scope,
                    "entraTenantId",
                    "Microsoft Entra tenant ID",
                )
                if observed.casefold() != expected.casefold():
                    raise WorkdayConnectContractError(
                        "Selected directory does not match the preflight tenant."
                    )
                return observed
            if name in {
                "applicationId",
                "applicationDisplayName",
                "applicationObjectId",
                "servicePrincipalId",
                "scopeGuid",
                "selectedDirectoryDisplayName",
                "nameIdSource",
                "samlSigningOption",
            }:
                return _safe_nonsecret_text(value, name)
            if name == "applicationIdentifierUris":
                return _safe_string_list(
                    value,
                    "Entra applicationIdentifierUris",
                    allow_empty=False,
                )
            if name == "applicationReplyUrls":
                reply_urls = _safe_string_list(
                    value,
                    "Entra applicationReplyUrls",
                    allow_empty=False,
                )
                return [
                    _absolute_https_url(item, "Entra application Reply URL")
                    for item in reply_urls
                ]
            if name == "entraChecks":
                if not isinstance(value, Mapping):
                    raise WorkdayConnectContractError(
                        "entraChecks must contain an object."
                    )
                unexpected_checks = sorted(set(value) - _ENTRA_CHECKS)
                if unexpected_checks:
                    raise WorkdayConnectContractError(
                        "entraChecks contains unsupported checks: "
                        + ", ".join(unexpected_checks)
                    )
                return {
                    check_name: _normalize_entra_check(
                        check_name,
                        check_value,
                    )
                    for check_name, check_value in value.items()
                }
            if name in {
                "replyUrl",
                "microsoftEntraIdentifier",
                "loginUrl",
            }:
                normalized = _absolute_https_url(value, name)
                tenant_id = _required_text(
                    scope,
                    "entraTenantId",
                    "Microsoft Entra tenant ID",
                )
                expected = {
                    "microsoftEntraIdentifier": (
                        f"https://sts.windows.net/{tenant_id}/"
                    ),
                    "loginUrl": (
                        "https://login.microsoftonline.com/"
                        f"{tenant_id}/saml2"
                    ),
                }.get(name)
                if expected and _normalized_uri(normalized) != _normalized_uri(
                    expected
                ):
                    raise WorkdayConnectContractError(
                        f"{name} does not match the selected directory."
                    )
                if name == "replyUrl":
                    reply_urls = available_fields.get(
                        "applicationReplyUrls"
                    )
                    if isinstance(reply_urls, list) and reply_urls and (
                        _normalized_uri(normalized)
                        not in {
                            _normalized_uri(item)
                            for item in reply_urls
                        }
                    ):
                        raise WorkdayConnectContractError(
                            "replyUrl is not present in the "
                            "Graph-authenticated application evidence."
                        )
                return normalized
            if name in {
                "scopePreservationOutcome",
                "authorizedClientPreservationOutcome",
                "permissionPreservationOutcome",
            }:
                normalized = str(value or "").strip()
                if normalized not in ENTRA_PRESERVATION_OUTCOMES:
                    raise WorkdayConnectContractError(
                        f"{name} must be preserved or remediated."
                    )
                return normalized
            if name in {"certificateValidFrom", "certificateValidTo"}:
                _date_only(str(value or ""), name)
                return str(value).strip()
            if name == "certificateThumbprint":
                return _certificate_thumbprint(
                    value,
                    "certificateThumbprint",
                )
            return _safe_nonsecret_text(value, name)

        tenant = _required_text(scope, "workdayTenant", "Workday tenant")
        if name == "enabledServiceProviderId":
            observed = _required_text({name: value}, name, name)
            expected = workday_saml_entity_id(tenant)
            if _normalized_uri(observed) != _normalized_uri(expected):
                raise WorkdayConnectContractError(
                    "Enabled Service Provider ID does not match the Workday "
                    "tenant."
                )
            return expected
        if name == "oauthTokenUrl":
            normalized = _https_url(value, "Workday OAuth token URL")
            _require_endpoint_path(
                normalized,
                f"/ccx/oauth2/{tenant}/token",
                "Workday OAuth token URL",
            )
            return normalized
        if name == "restBaseUrl":
            normalized = _https_url(value, "Workday REST base URL")
            _require_endpoint_path(
                normalized,
                "/ccx/api",
                "Workday REST base URL",
            )
            return normalized
        if name == "soapBaseUrl":
            normalized = _https_url(value, "Workday SOAP base URL")
            _require_endpoint_path(
                normalized,
                "/ccx/service",
                "Workday SOAP base URL",
            )
            return normalized
        if name == "identityProviderOutcome":
            normalized = str(value or "").strip()
            if normalized != "verified-entra-issuer":
                raise WorkdayConnectContractError(
                    "identityProviderOutcome must verify the Entra issuer."
                )
            return normalized
        if name == "certificateSelectionOutcome":
            normalized = str(value or "").strip()
            if normalized != "entra-signing-certificate-selected":
                raise WorkdayConnectContractError(
                    "certificateSelectionOutcome must verify the Entra "
                    "signing certificate."
                )
            return normalized
        if name == "certificateValidityOutcome":
            normalized = str(value or "").strip()
            if normalized != "matches-verified-entra-certificate":
                raise WorkdayConnectContractError(
                    "certificateValidityOutcome must verify the Entra "
                    "certificate dates."
                )
            return normalized
        if name == "authenticationPolicyOutcome":
            normalized = str(value or "").strip()
            if normalized not in WORKDAY_AUTHENTICATION_POLICY_OUTCOMES:
                raise WorkdayConnectContractError(
                    "authenticationPolicyOutcome is unsupported."
                )
            return normalized
        if name == "networkReadinessOutcome":
            normalized = str(value or "").strip()
            if normalized not in WORKDAY_NETWORK_READINESS_OUTCOMES:
                raise WorkdayConnectContractError(
                    "networkReadinessOutcome is unsupported."
                )
            return normalized
        if name == "apiClientOutcome":
            normalized = str(value or "").strip()
            if normalized not in WORKDAY_API_CLIENT_OUTCOMES:
                raise WorkdayConnectContractError(
                    "apiClientOutcome must verify an approved existing client "
                    "or a newly registered client."
                )
            return normalized
        if name == "clientGrantType":
            normalized = str(value or "").strip().casefold()
            if normalized != "saml-bearer":
                raise WorkdayConnectContractError(
                    "clientGrantType must be saml-bearer."
                )
            return normalized
        if name == "includeWorkdayOwnedScope":
            normalized = str(value or "").strip().casefold()
            if normalized != "yes":
                raise WorkdayConnectContractError(
                    "includeWorkdayOwnedScope must be yes."
                )
            return normalized
        if name in {
            "identityProviderSsoServiceUrl",
            "signOnRedirectUrl",
        }:
            normalized = _absolute_https_url(value, name)
            expected_key = (
                "entraLoginUrl"
                if name == "identityProviderSsoServiceUrl"
                else "replyUrl"
            )
            expected = _required_text(
                state.get("identifiers") or {},
                expected_key,
                expected_key,
            )
            if _normalized_uri(normalized) != _normalized_uri(expected):
                raise WorkdayConnectContractError(
                    f"{name} does not match the verified Entra value."
                )
            return normalized
        if name == "rolloutType":
            normalized = str(value or "").strip()
            if normalized not in WORKDAY_ROLLOUT_TYPES:
                raise WorkdayConnectContractError(
                    "rolloutType is unsupported."
                )
            return normalized
        if name in {
            "publicWorkerReportsOutcome",
            "integrationPermissionsGetOutcome",
        }:
            normalized = str(value or "").strip()
            if normalized not in WORKDAY_DOMAIN_PERMISSION_OUTCOMES:
                raise WorkdayConnectContractError(
                    f"{name} must verify Get permission."
                )
            return normalized
        if name == "authorizationOutcome":
            normalized = str(value or "").strip()
            if normalized not in WORKDAY_AUTHORIZATION_OUTCOMES:
                raise WorkdayConnectContractError(
                    "authorizationOutcome is unsupported."
                )
            return normalized
        if name in {
            "authorizationRemediationDomain",
            "authorizationRemediationScenario",
        }:
            return _safe_nonsecret_text(value, name)
        if name == "authorizationRetestOutcome":
            normalized = str(value or "").strip()
            if normalized not in WORKDAY_AUTHORIZATION_RETEST_OUTCOMES:
                raise WorkdayConnectContractError(
                    "authorizationRetestOutcome must confirm verification "
                    "after remediation."
                )
            return normalized
        if name == "functionalAreaScopes":
            supplied = _safe_string_list(
                value,
                "Workday functionalAreaScopes",
                allow_empty=False,
            )
            expected = {
                item.casefold()
                for item in WORKDAY_REQUIRED_FUNCTIONAL_AREA_SCOPES
            }
            if {item.casefold() for item in supplied} != expected:
                raise WorkdayConnectContractError(
                    "functionalAreaScopes must contain exactly Core Payroll, "
                    "Organizations and Roles, Staffing, and Time Off and "
                    "Leave."
                )
            return list(WORKDAY_REQUIRED_FUNCTIONAL_AREA_SCOPES)
        if name == "optionalDomains":
            return _optional_domains(value)
        return _safe_nonsecret_text(value, name)

    for name, value in fields.items():
        try:
            valid_fields[name] = validate_field(name, value)
        except WorkdayConnectContractError as exc:
            field_errors[name] = str(exc)
    combined = {
        **dict(administrator.get("partialEvidence") or {}),
        **valid_fields,
    }
    if (
        combined.get("rolloutType") == "limited-or-test"
        and str(combined.get("employeeSecurityGroup") or "").strip().casefold()
        in {"all employees", "all workers"}
    ):
        valid_fields.pop("employeeSecurityGroup", None)
        field_errors["employeeSecurityGroup"] = (
            "A limited or test rollout cannot use All Employees."
        )
    return {
        "validFields": valid_fields,
        "fieldErrors": field_errors,
    }


def _require_endpoint_path(
    url: str,
    expected_path: str,
    label: str,
) -> None:
    observed_path = urlparse(url).path.rstrip("/")
    if observed_path.casefold() != expected_path.casefold():
        raise WorkdayConnectContractError(
            f"{label} must end exactly at {expected_path}."
        )


def _date_only(value: str, label: str) -> str:
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date().isoformat()
    except ValueError as exc:
        raise WorkdayConnectContractError(
            f"{label} must be an ISO-8601 date or timestamp."
        ) from exc


def validate_workday_admin_response(
    state: Mapping[str, Any],
    response: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(response, Mapping):
        raise WorkdayConnectContractError(
            "Workday administrator response must contain a JSON object."
        )
    _reject_secret_like_value(
        response,
        "Workday administrator response",
    )
    allowed = {
        "activeIdentityProviderIssuer",
        "identityProviderOutcome",
        "enabledServiceProviderId",
        "certificateName",
        "certificateSelectionOutcome",
        "certificateValidityOutcome",
        "certificateValidFrom",
        "certificateValidTo",
        "oauthClientId",
        "oauthTokenUrl",
        "restBaseUrl",
        "soapBaseUrl",
        "authenticationPolicyOutcome",
        "networkReadinessOutcome",
        "apiClientOutcome",
        "clientGrantType",
        "includeWorkdayOwnedScope",
        "identityProviderSsoServiceUrl",
        "signOnRedirectUrl",
        "rolloutType",
        "employeeSecurityGroup",
        "publicWorkerReportsOutcome",
        "integrationPermissionsGetOutcome",
        "functionalAreaScopes",
        "optionalDomains",
        "authorizationOutcome",
        "authorizationRemediationDomain",
        "authorizationRemediationScenario",
        "authorizationRetestOutcome",
    }
    unexpected = sorted(set(response) - allowed)
    if unexpected:
        raise WorkdayConnectContractError(
            "Workday administrator response contains unsupported fields: "
            + ", ".join(unexpected)
        )
    scope = state.get("scope") or {}
    tenant = _required_text(scope, "workdayTenant", "Workday tenant")
    entra_tenant_id = _required_text(
        scope,
        "entraTenantId",
        "Microsoft Entra tenant ID",
    )
    expected_issuer = f"https://sts.windows.net/{entra_tenant_id}/"
    identity_provider_outcome = str(
        response.get("identityProviderOutcome") or ""
    ).strip()
    supplied_identity_provider_issuer = str(
        response.get("activeIdentityProviderIssuer") or ""
    ).strip()
    if identity_provider_outcome != "verified-entra-issuer":
        raise WorkdayConnectContractError(
            "identityProviderOutcome must confirm that the enabled Workday "
            "Issuer exactly matches the verified Microsoft Entra tenant."
        )
    if supplied_identity_provider_issuer and (
        _normalized_uri(supplied_identity_provider_issuer)
        != _normalized_uri(expected_issuer)
    ):
        raise WorkdayConnectContractError(
            "The supplied Workday Issuer conflicts with the verified "
            "Microsoft Entra issuer confirmation."
        )
    active_identity_provider_issuer = expected_issuer
    expected_entity_id = workday_saml_entity_id(tenant)
    observed_entity_id = _required_text(
        response,
        "enabledServiceProviderId",
        "Enabled Workday Service Provider ID",
    )
    if _normalized_uri(observed_entity_id) != _normalized_uri(expected_entity_id):
        raise WorkdayConnectContractError(
            "The enabled Workday Service Provider ID does not match the "
            "selected Workday tenant."
        )
    oauth_token_url = _https_url(
        response.get("oauthTokenUrl"),
        "Workday OAuth token URL",
    )
    _require_endpoint_path(
        oauth_token_url,
        f"/ccx/oauth2/{tenant}/token",
        "Workday OAuth token URL",
    )
    rest_base_url = _https_url(
        response.get("restBaseUrl"),
        "Workday REST base URL",
    )
    _require_endpoint_path(
        rest_base_url,
        "/ccx/api",
        "Workday REST base URL",
    )
    soap_base_url = _https_url(
        response.get("soapBaseUrl"),
        "Workday SOAP base URL",
    )
    _require_endpoint_path(
        soap_base_url,
        "/ccx/service",
        "Workday SOAP base URL",
    )
    endpoint_hosts = {
        str(urlparse(value).hostname or "").casefold()
        for value in (oauth_token_url, rest_base_url, soap_base_url)
    }
    if len(endpoint_hosts) != 1:
        raise WorkdayConnectContractError(
            "Workday OAuth, REST, and SOAP endpoints must use the same "
            "verified Workday service hostname."
        )
    required = {
        "oauthClientId",
        "authenticationPolicyOutcome",
        "networkReadinessOutcome",
        "apiClientOutcome",
        "clientGrantType",
        "includeWorkdayOwnedScope",
        "identityProviderSsoServiceUrl",
        "signOnRedirectUrl",
    }
    values = {key: _required_text(response, key, key) for key in required}
    if (
        values["authenticationPolicyOutcome"]
        not in WORKDAY_AUTHENTICATION_POLICY_OUTCOMES
    ):
        raise WorkdayConnectContractError(
            "authenticationPolicyOutcome must confirm either an existing "
            "active employee SAML policy or an activated reviewed change."
        )
    if values["networkReadinessOutcome"] not in WORKDAY_NETWORK_READINESS_OUTCOMES:
        raise WorkdayConnectContractError(
            "networkReadinessOutcome must confirm the Workday hosts are "
            "allowed or that no customer firewall change is required."
        )
    if values["apiClientOutcome"] not in WORKDAY_API_CLIENT_OUTCOMES:
        raise WorkdayConnectContractError(
            "apiClientOutcome must confirm an approved existing API client "
            "or a newly registered API client."
        )
    if values["clientGrantType"].casefold() != "saml-bearer":
        raise WorkdayConnectContractError(
            "clientGrantType must be saml-bearer."
        )
    values["clientGrantType"] = "saml-bearer"
    if values["includeWorkdayOwnedScope"].casefold() != "yes":
        raise WorkdayConnectContractError(
            "includeWorkdayOwnedScope must be yes."
        )
    values["includeWorkdayOwnedScope"] = "yes"
    expected_login_url = _required_text(
        state.get("identifiers") or {},
        "entraLoginUrl",
        "Verified Microsoft Entra Login URL",
    )
    expected_reply_url = _required_text(
        state.get("identifiers") or {},
        "replyUrl",
        "Verified Microsoft Entra Reply URL",
    )
    for field, expected in (
        ("identityProviderSsoServiceUrl", expected_login_url),
        ("signOnRedirectUrl", expected_reply_url),
    ):
        observed = _absolute_https_url(response.get(field), field)
        if _normalized_uri(observed) != _normalized_uri(expected):
            raise WorkdayConnectContractError(
                f"{field} does not match the verified Entra value."
            )
        values[field] = observed
    signing_certificate = (state.get("identifiers") or {}).get("signingCertificate")
    if not isinstance(signing_certificate, Mapping):
        raise WorkdayConnectContractError(
            "Verified Entra signing certificate metadata is required before "
            "recording Workday administrator evidence."
        )
    entra_valid_from = _date_only(
        _required_text(
            signing_certificate,
            "validFrom",
            "Entra signing certificate Valid From",
        ),
        "Entra signing certificate Valid From",
    )
    entra_valid_to = _date_only(
        _required_text(
            signing_certificate,
            "validTo",
            "Entra signing certificate Valid To",
        ),
        "Entra signing certificate Valid To",
    )
    certificate_selection_outcome = str(
        response.get("certificateSelectionOutcome") or ""
    ).strip()
    if certificate_selection_outcome != "entra-signing-certificate-selected":
        raise WorkdayConnectContractError(
            "certificateSelectionOutcome must confirm that the Workday row "
            "uses the certificate created from the verified Entra signing "
            "certificate."
        )
    certificate_validity_outcome = str(
        response.get("certificateValidityOutcome") or ""
    ).strip()
    if certificate_validity_outcome != "matches-verified-entra-certificate":
        raise WorkdayConnectContractError(
            "certificateValidityOutcome must confirm that both Workday "
            "certificate dates exactly match the verified Entra certificate."
        )
    workday_valid_from = entra_valid_from
    workday_valid_to = entra_valid_to
    supplied_valid_from = str(
        response.get("certificateValidFrom") or ""
    ).strip()
    supplied_valid_to = str(response.get("certificateValidTo") or "").strip()
    if supplied_valid_from and (
        _date_only(
            supplied_valid_from,
            "Workday certificate Valid From",
        )
        != entra_valid_from
    ):
        raise WorkdayConnectContractError(
            "The supplied Workday certificate Valid From date conflicts "
            "with the verified certificate-date confirmation."
        )
    if supplied_valid_to and (
        _date_only(
            supplied_valid_to,
            "Workday certificate Valid To",
        )
        != entra_valid_to
    ):
        raise WorkdayConnectContractError(
            "The supplied Workday certificate Valid To date conflicts "
            "with the verified certificate-date confirmation."
        )
    least_privilege_required = {
        "rolloutType",
        "employeeSecurityGroup",
        "publicWorkerReportsOutcome",
        "integrationPermissionsGetOutcome",
        "authorizationOutcome",
    }
    values.update(
        {
            key: _required_text(response, key, key)
            for key in least_privilege_required
        }
    )
    if values["rolloutType"] not in WORKDAY_ROLLOUT_TYPES:
        raise WorkdayConnectContractError(
            "rolloutType must be entire-workforce or limited-or-test."
        )
    if (
        values["rolloutType"] == "limited-or-test"
        and values["employeeSecurityGroup"].casefold()
        in {"all employees", "all workers"}
    ):
        raise WorkdayConnectContractError(
            "A limited or test rollout cannot use All Employees."
        )
    if (
        values["publicWorkerReportsOutcome"]
        not in WORKDAY_DOMAIN_PERMISSION_OUTCOMES
    ):
        raise WorkdayConnectContractError(
            "publicWorkerReportsOutcome must confirm Get permission on "
            "Worker Data: Public Worker Reports."
        )
    if (
        values["integrationPermissionsGetOutcome"]
        not in WORKDAY_DOMAIN_PERMISSION_OUTCOMES
    ):
        raise WorkdayConnectContractError(
            "integrationPermissionsGetOutcome must confirm Get permission "
            "under Integration Permissions."
        )
    if values["authorizationOutcome"] not in WORKDAY_AUTHORIZATION_OUTCOMES:
        raise WorkdayConnectContractError(
            "authorizationOutcome must confirm verification or bounded "
            "Task not authorized remediation."
        )
    supplied_functional_area_scopes = _safe_string_list(
        response.get("functionalAreaScopes"),
        "Workday functionalAreaScopes",
        allow_empty=False,
    )
    expected_functional_area_scopes = {
        value.casefold()
        for value in WORKDAY_REQUIRED_FUNCTIONAL_AREA_SCOPES
    }
    if {
        value.casefold() for value in supplied_functional_area_scopes
    } != expected_functional_area_scopes:
        raise WorkdayConnectContractError(
            "functionalAreaScopes must contain exactly Core Payroll, "
            "Organizations and Roles, Staffing, and Time Off and Leave."
        )
    functional_area_scopes = list(
        WORKDAY_REQUIRED_FUNCTIONAL_AREA_SCOPES
    )
    optional_domains = _optional_domains(response.get("optionalDomains"))
    remediation_evidence: dict[str, str] = {}
    if values["authorizationOutcome"] == "task-not-authorized-remediated":
        remediation_evidence = {
            "authorizationRemediationDomain": _safe_nonsecret_text(
                response.get("authorizationRemediationDomain"),
                "authorizationRemediationDomain",
            ),
            "authorizationRemediationScenario": _safe_nonsecret_text(
                response.get("authorizationRemediationScenario"),
                "authorizationRemediationScenario",
            ),
            "authorizationRetestOutcome": _required_text(
                response,
                "authorizationRetestOutcome",
                "authorizationRetestOutcome",
            ),
        }
        if (
            remediation_evidence["authorizationRetestOutcome"]
            not in WORKDAY_AUTHORIZATION_RETEST_OUTCOMES
        ):
            raise WorkdayConnectContractError(
                "authorizationRetestOutcome must confirm verification after "
                "the bounded authorization remediation."
            )
    certificate_name = str(response.get("certificateName") or "").strip()
    certificate_evidence = {
        "certificateSelectionOutcome": certificate_selection_outcome,
        "certificateValidityOutcome": certificate_validity_outcome,
        "certificateValidFrom": workday_valid_from,
        "certificateValidTo": workday_valid_to,
    }
    if certificate_name:
        certificate_evidence["certificateName"] = certificate_name
    return {
        "identifiers": {
            "workdaySamlEntityId": expected_entity_id,
            "oauthClientId": values["oauthClientId"],
        },
        "endpoints": {
            "oauthTokenUrl": oauth_token_url,
            "restBaseUrl": rest_base_url,
            "soapBaseUrl": soap_base_url,
        },
        "evidence": {
            "activeIdentityProviderIssuer": active_identity_provider_issuer,
            "identityProviderOutcome": identity_provider_outcome,
            "serviceProviderId": expected_entity_id,
            **certificate_evidence,
            "authenticationPolicyOutcome": values["authenticationPolicyOutcome"],
            "networkReadinessOutcome": values["networkReadinessOutcome"],
            "apiClientOutcome": values["apiClientOutcome"],
            "clientGrantType": values["clientGrantType"],
            "includeWorkdayOwnedScope": values[
                "includeWorkdayOwnedScope"
            ],
            "identityProviderSsoServiceUrl": values[
                "identityProviderSsoServiceUrl"
            ],
            "signOnRedirectUrl": values["signOnRedirectUrl"],
            "rolloutType": values["rolloutType"],
            "employeeSecurityGroup": values["employeeSecurityGroup"],
            "publicWorkerReportsOutcome": values[
                "publicWorkerReportsOutcome"
            ],
            "integrationPermissionsGetOutcome": values[
                "integrationPermissionsGetOutcome"
            ],
            "functionalAreaScopes": functional_area_scopes,
            "optionalDomains": optional_domains,
            "authorizationOutcome": values["authorizationOutcome"],
            **remediation_evidence,
        },
        "partialEvidence": {
            "identityProviderOutcome": identity_provider_outcome,
            "enabledServiceProviderId": expected_entity_id,
            "certificateSelectionOutcome": certificate_selection_outcome,
            "certificateValidityOutcome": certificate_validity_outcome,
            "oauthClientId": values["oauthClientId"],
            "oauthTokenUrl": oauth_token_url,
            "restBaseUrl": rest_base_url,
            "soapBaseUrl": soap_base_url,
            "authenticationPolicyOutcome": values[
                "authenticationPolicyOutcome"
            ],
            "networkReadinessOutcome": values["networkReadinessOutcome"],
            "apiClientOutcome": values["apiClientOutcome"],
            "clientGrantType": values["clientGrantType"],
            "includeWorkdayOwnedScope": values[
                "includeWorkdayOwnedScope"
            ],
            "identityProviderSsoServiceUrl": values[
                "identityProviderSsoServiceUrl"
            ],
            "signOnRedirectUrl": values["signOnRedirectUrl"],
            "rolloutType": values["rolloutType"],
            "employeeSecurityGroup": values["employeeSecurityGroup"],
            "publicWorkerReportsOutcome": values[
                "publicWorkerReportsOutcome"
            ],
            "integrationPermissionsGetOutcome": values[
                "integrationPermissionsGetOutcome"
            ],
            "functionalAreaScopes": functional_area_scopes,
            "optionalDomains": optional_domains,
            "authorizationOutcome": values["authorizationOutcome"],
            **remediation_evidence,
        },
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
        "checkpoints",
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
    expected_environment = _required_text(
        scope,
        "environmentId",
        "Workday environment ID",
    )
    expected_bot = _required_text(agent, "botId", "Workday agent bot ID")
    observed_environment = _required_text(
        evidence,
        "environmentId",
        "Verified environment ID",
    )
    observed_bot = _required_text(
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
    expected_maker = _required_text(
        (state.get("operators") or {}).get("powerPlatformMaker") or {},
        "username",
        "Recorded Power Platform maker",
    )
    observed_maker = _required_text(
        evidence,
        "makerUsername",
        "Verified Power Platform maker",
    )
    if observed_maker.casefold() != expected_maker.casefold():
        raise WorkdayConnectContractError(
            "Agent binding verification used a different Power Platform maker."
        )
    checkpoints = evidence.get("checkpoints")
    if not isinstance(checkpoints, Mapping):
        raise WorkdayConnectContractError(
            "Agent binding evidence must contain checkpoint results."
        )
    required_checkpoints = {"WD-REST-002", "WD-CONN-013"}
    failed_checkpoints = sorted(
        checkpoint
        for checkpoint in required_checkpoints
        if checkpoints.get(checkpoint) != "Passed"
    )
    if failed_checkpoints:
        raise WorkdayConnectContractError(
            "Agent binding verification did not pass: " + ", ".join(failed_checkpoints)
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
    attachment_bot = _required_text(
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
    package_flavor = _required_text(
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
        or any(not isinstance(name, str) or not name for name in supplied_flow_names)
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
        "checkpoints": {
            checkpoint: "Passed" for checkpoint in sorted(required_checkpoints)
        },
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
    result = {key: _required_text(evidence, key, key) for key in allowed}
    if result["outcome"].casefold() not in {"passed", "verified"}:
        raise WorkdayConnectContractError(
            "Employee validation outcome must be passed or verified."
        )
    category = result["testUserCategory"].casefold()
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
        _required_text(evidence, "timestamp", "timestamp"),
        "Employee validation failure timestamp",
    )
    supplied_remediation_id = str(evidence.get("remediationId") or "").strip()
    if supplied_remediation_id:
        remediation_id = supplied_remediation_id.upper()
    else:
        legacy_category = _required_text(
            evidence,
            "failureCategory",
            "failureCategory",
        )
        _required_text(evidence, "remediation", "remediation")
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
