# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Exact Entra and Workday administrator contracts for Workday connect."""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlparse

from workday_connect_model import (
    PhaseStatus,
    WorkdayConnectModelError,
    workday_saml_entity_id,
)


WORKDAY_CONNECTOR_APP_ID = "4e4707ca-5f53-46a6-a819-f7765446e6ff"
GRAPH_DELEGATED_PERMISSIONS = ("openid", "profile", "User.Read")


class WorkdayConnectContractError(WorkdayConnectModelError):
    """Raised when an exact Entra or Workday contract cannot be produced."""


def _required_text(
    document: Mapping[str, Any],
    key: str,
    label: str,
) -> str:
    value = str(document.get(key) or "").strip()
    if not value:
        raise WorkdayConnectContractError(f"{label} is required.")
    return value


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
    return {
        "displayName": _required_text(
            candidate, "displayName", "Entra app display name"
        ),
        "appId": _required_text(candidate, "appId", "Entra app ID"),
        "objectId": _required_text(
            candidate, "objectId", "Entra app object ID"
        ),
        "servicePrincipalId": _required_text(
            candidate,
            "servicePrincipalId",
            "Entra service principal ID",
        ),
        "identifierUris": [
            str(value).strip()
            for value in identifier_uris
            if str(value).strip()
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
        raise WorkdayConnectContractError(
            "Entra discovery must contain a JSON object."
        )
    scope = state.get("scope") or {}
    tenant = _required_text(scope, "workdayTenant", "Workday tenant")
    entity_id = workday_saml_entity_id(tenant)
    entra_tenant_id = _required_text(
        scope, "entraTenantId", "Microsoft Entra tenant ID"
    )
    candidates = [
        _candidate(value) for value in (discovery.get("applications") or [])
    ]
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
        "actions": [
            (
                "Reuse the exact Workday SAML application"
                if app
                else "Instantiate the Workday gallery application"
            ),
            "Configure SAML mode, the signing certificate, and the exact "
            f"Service Provider ID {entity_id}",
            "Expose the user_impersonation scope at the Entra application ID "
            "URI and pre-authorize the Workday connector",
            "Add openid, profile, and User.Read delegated permissions",
            "Grant administrator consent and verify the final configuration",
        ],
    }


def validate_entra_verification(
    state: Mapping[str, Any],
    verification: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate safe Graph reread evidence after the administrator handoff."""
    if not isinstance(verification, Mapping):
        raise WorkdayConnectContractError(
            "Entra verification must contain a JSON object."
        )
    application = _candidate(verification.get("application"))
    scope = state.get("scope") or {}
    tenant = _required_text(scope, "workdayTenant", "Workday tenant")
    expected_entity_id = workday_saml_entity_id(tenant)
    expected_app_uri = f"api://{application['appId']}"
    observed_uris = {
        _normalized_uri(value) for value in application["identifierUris"]
    }
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
    required_checks = {
        "samlMode",
        "signingCertificate",
        "connectorPreauthorized",
        "graphDelegatedPermissions",
        "adminConsent",
        "userAssignmentAndNameId",
    }
    checks = verification.get("checks")
    if not isinstance(checks, Mapping):
        raise WorkdayConnectContractError(
            "Entra verification checks must contain an object."
        )
    failed_checks = sorted(
        check for check in required_checks if checks.get(check) is not True
    )
    if failed_checks:
        raise WorkdayConnectContractError(
            "Entra verification is incomplete: " + ", ".join(failed_checks)
        )
    scope_guid = _required_text(
        verification,
        "scopeGuid",
        "Entra user_impersonation scope ID",
    )
    certificate = verification.get("certificate")
    if certificate is not None and not isinstance(certificate, Mapping):
        raise WorkdayConnectContractError(
            "Entra certificate metadata must contain an object."
        )
    safe_certificate = {
        key: certificate[key]
        for key in ("thumbprint", "validFrom", "validTo")
        if isinstance(certificate, Mapping) and certificate.get(key)
    }
    return {
        "identifiers": {
            "entraAppId": application["appId"],
            "entraAppObjectId": application["objectId"],
            "entraServicePrincipalId": application["servicePrincipalId"],
            "entraAppIdUri": expected_app_uri,
            "workdaySamlEntityId": expected_entity_id,
            "scopeGuid": scope_guid,
            "signingCertificate": safe_certificate or None,
        },
        "evidence": {
            "applicationDisplayName": application["displayName"],
            "checks": {key: True for key in sorted(required_checks)},
        },
    }


def build_workday_admin_packet(
    state: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one compact handoff packet for the Workday administrator."""
    scope = state.get("scope") or {}
    identifiers = state.get("identifiers") or {}
    endpoints = state.get("endpoints") or {}
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
            "oauthTokenUrl": endpoints.get("oauthTokenUrl"),
        },
        "actions": [
            "Confirm the existing enabled SAML identity-provider row belongs "
            "to this tenant before changing it",
            "Upload the active Entra SAML signing certificate",
            f"Set the Workday Service Provider ID to {entity_id}",
            "Enable OAuth 2.0 Clients and SAML in Tenant Setup - Security",
            "Register the signed-in employee API client with the required "
            "functional areas and Include Workday Owned Scope",
            "Verify an active authentication policy allows SAML for the "
            "intended employee population",
        ],
        "responseForm": {
            "required": [
                "enabledServiceProviderId",
                "certificateValidFrom",
                "certificateValidTo",
                "oauthClientId",
                "oauthTokenUrl",
                "restBaseUrl",
                "soapBaseUrl",
                "authenticationPolicyOutcome",
            ],
            "note": (
                "Return configuration evidence only. Do not paste passwords, "
                "client secrets, tokens, cookies, or certificate private keys."
            ),
        },
    }
    return packet


def _https_url(value: Any, label: str) -> str:
    text = str(value or "").strip().rstrip("/")
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc:
        raise WorkdayConnectContractError(f"{label} must be an HTTPS URL.")
    return text


def validate_workday_admin_response(
    state: Mapping[str, Any],
    response: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(response, Mapping):
        raise WorkdayConnectContractError(
            "Workday administrator response must contain a JSON object."
        )
    scope = state.get("scope") or {}
    tenant = _required_text(scope, "workdayTenant", "Workday tenant")
    expected_entity_id = workday_saml_entity_id(tenant)
    observed_entity_id = _required_text(
        response,
        "enabledServiceProviderId",
        "Enabled Workday Service Provider ID",
    )
    if _normalized_uri(observed_entity_id) != _normalized_uri(
        expected_entity_id
    ):
        raise WorkdayConnectContractError(
            "The enabled Workday Service Provider ID does not match the "
            "selected Workday tenant."
        )
    oauth_token_url = _https_url(
        response.get("oauthTokenUrl"),
        "Workday OAuth token URL",
    )
    rest_base_url = _https_url(
        response.get("restBaseUrl"),
        "Workday REST base URL",
    )
    if not rest_base_url.casefold().endswith("/ccx/api"):
        raise WorkdayConnectContractError(
            "Workday REST base URL must end exactly at /ccx/api."
        )
    soap_base_url = _https_url(
        response.get("soapBaseUrl"),
        "Workday SOAP base URL",
    )
    required = {
        "certificateValidFrom",
        "certificateValidTo",
        "oauthClientId",
        "authenticationPolicyOutcome",
    }
    values = {
        key: _required_text(response, key, key)
        for key in required
    }
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
            "serviceProviderId": expected_entity_id,
            "certificateValidFrom": values["certificateValidFrom"],
            "certificateValidTo": values["certificateValidTo"],
            "authenticationPolicyOutcome": values[
                "authenticationPolicyOutcome"
            ],
        },
    }


def validate_connections_evidence(
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        raise WorkdayConnectContractError(
            "Connection evidence must contain a JSON object."
        )
    required_true = (
        "workdayConnectionConnected",
        "dataverseConnectionConnected",
        "parameterSharingPassed",
        "flowAttachmentConfirmed",
    )
    missing = sorted(
        key for key in required_true if evidence.get(key) is not True
    )
    if missing:
        raise WorkdayConnectContractError(
            "Connection evidence is incomplete: " + ", ".join(missing)
        )
    return {key: True for key in required_true}


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
    result = {
        key: _required_text(evidence, key, key)
        for key in allowed
    }
    if result["outcome"].casefold() not in {"passed", "verified"}:
        raise WorkdayConnectContractError(
            "Employee validation outcome must be passed or verified."
        )
    return result
