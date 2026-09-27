# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Exact Entra and Workday administrator contracts for Workday connect."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urlparse

from workday_connect_model import (
    PhaseStatus,
    WorkdayConnectModelError,
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
        "objectId": _required_text(candidate, "objectId", "Entra app object ID"),
        "servicePrincipalId": _required_text(
            candidate,
            "servicePrincipalId",
            "Entra service principal ID",
        ),
        "identifierUris": [
            str(value).strip() for value in identifier_uris if str(value).strip()
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
    unexpected = sorted(set(value) - {"outcome", "provenance"})
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
    return {
        "outcome": outcome,
        "provenance": provenance,
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
        key: _required_text(
            certificate,
            key,
            f"Entra signing certificate {key}",
        )
        for key in ("thumbprint", "validFrom", "validTo")
    }
    return {
        "identifiers": {
            "entraAppId": application["appId"],
            "entraAppObjectId": application["objectId"],
            "entraServicePrincipalId": application["servicePrincipalId"],
            "entraAppIdUri": expected_app_uri,
            "workdaySamlEntityId": expected_entity_id,
            "scopeGuid": scope_guid,
            "signingCertificate": safe_certificate,
        },
        "evidence": {
            "tenantId": observed_tenant_id,
            "applicationDisplayName": application["displayName"],
            "checks": normalized_checks,
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
        "actions": [
            "Identify which sign-in provider the enabled Workday SAML row "
            "uses before changing it",
            "Create a Workday X.509 Public Key from the active Entra SAML "
            "signing certificate, select it on the Microsoft Entra SAML row, "
            "and compare its validity dates",
            f"Set the Workday Service Provider ID to {entity_id}",
            "Enable OAuth 2.0 Clients and SAML in Tenant Setup - Security",
            "Register the signed-in employee API client with Client Grant "
            "Type SAML Bearer, the required functional areas, and Include "
            "Workday Owned Scope",
            "Verify an active authentication policy allows SAML for the "
            "intended employee population",
            "Confirm the returned Workday REST and SOAP hosts are reachable "
            "or approved by the organization network policy",
        ],
        "responseForm": {
            "required": [
                "activeIdentityProviderIssuer",
                "enabledServiceProviderId",
                "certificateName",
                "certificateValidFrom",
                "certificateValidTo",
                "oauthClientId",
                "oauthTokenUrl",
                "restBaseUrl",
                "soapBaseUrl",
                "authenticationPolicyOutcome",
                "networkReadinessOutcome",
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
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise WorkdayConnectContractError(f"{label} must be an HTTPS URL.")
    return text


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
    allowed = {
        "activeIdentityProviderIssuer",
        "enabledServiceProviderId",
        "certificateName",
        "certificateValidFrom",
        "certificateValidTo",
        "oauthClientId",
        "oauthTokenUrl",
        "restBaseUrl",
        "soapBaseUrl",
        "authenticationPolicyOutcome",
        "networkReadinessOutcome",
    }
    unexpected = sorted(set(response) - allowed)
    if unexpected:
        raise WorkdayConnectContractError(
            "Workday administrator response contains unsupported fields: "
            + ", ".join(unexpected)
        )
    scope = state.get("scope") or {}
    tenant = _required_text(scope, "workdayTenant", "Workday tenant")
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
        f"/ccx/service/{tenant}",
        "Workday SOAP base URL",
    )
    required = {
        "activeIdentityProviderIssuer",
        "certificateName",
        "certificateValidFrom",
        "certificateValidTo",
        "oauthClientId",
        "authenticationPolicyOutcome",
        "networkReadinessOutcome",
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
    signing_certificate = (state.get("identifiers") or {}).get("signingCertificate")
    if not isinstance(signing_certificate, Mapping):
        raise WorkdayConnectContractError(
            "Verified Entra signing certificate metadata is required before "
            "recording Workday administrator evidence."
        )
    workday_valid_from = _date_only(
        values["certificateValidFrom"],
        "Workday certificate Valid From",
    )
    workday_valid_to = _date_only(
        values["certificateValidTo"],
        "Workday certificate Valid To",
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
    if workday_valid_from != entra_valid_from or workday_valid_to != entra_valid_to:
        raise WorkdayConnectContractError(
            "The Workday X.509 certificate validity dates do not match the "
            "verified Entra signing certificate."
        )
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
            "activeIdentityProviderIssuer": values["activeIdentityProviderIssuer"],
            "serviceProviderId": expected_entity_id,
            "certificateName": values["certificateName"],
            "certificateValidFrom": workday_valid_from,
            "certificateValidTo": workday_valid_to,
            "authenticationPolicyOutcome": values["authenticationPolicyOutcome"],
            "networkReadinessOutcome": values["networkReadinessOutcome"],
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
        or diagnostics != []
    ):
        raise WorkdayConnectContractError(
            "Every mapped Workday topic must be active, verified, and free "
            "of blocking diagnostics."
        )
    return {
        "environmentId": observed_environment,
        "botId": observed_bot,
        "makerUsername": observed_maker,
        "checkpoints": {
            checkpoint: "Passed" for checkpoint in sorted(required_checkpoints)
        },
        "workdayTopics": {
            "expected": expected_count,
            "verified": verified_count,
            "active": active_count,
            "blockingDiagnostics": [],
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
    return result
