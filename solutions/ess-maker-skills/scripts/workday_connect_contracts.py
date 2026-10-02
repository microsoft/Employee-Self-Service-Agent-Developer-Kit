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
    ADMINISTRATOR_REQUIRED_FIELDS,
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
ENTRA_WORKSHEET_LABELS = (
    "Directory name",
    "Enterprise application",
    "Application ID",
    "Selected Reply URL",
    "NameID source",
    "SAML signing",
    "Certificate thumbprint (active certificate row)",
    "Certificate expiration date (active certificate row)",
    "SAML configuration",
    "Signing certificate",
    "Authorized connector",
    "Permissions and consent",
    "Employee assignment",
    "Existing configuration",
)
WORKDAY_ADMIN_WORKSHEET_LABELS = (
    "SAML row settings",
    "Certificate",
    "Certificate expiration",
    "OAuth client ID",
    "API client",
    "Client grant type",
    "Workday owned scope",
    "OAuth token URL",
    "REST base URL",
    "SOAP base URL",
    "Authentication policy",
    "Network readiness",
    "Rollout",
    "Public worker reports",
    "Integration permissions",
    "Functional-area scopes",
    "Optional domains",
    "Additional domain mappings",
    "Authorization",
    "Remediated domain",
    "Remediation scenario",
    "Authorization retest",
)
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


def _parse_labeled_worksheet(
    worksheet: str,
    *,
    labels: tuple[str, ...],
    label: str,
    multiline_labels: frozenset[str] = frozenset(),
) -> dict[str, str]:
    if not isinstance(worksheet, str) or not worksheet.strip():
        raise WorkdayConnectContractError(f"{label} is required.")
    if len(worksheet) > 16384 or "\x00" in worksheet:
        raise WorkdayConnectContractError(
            f"{label} exceeds the safe evidence limit."
        )
    normalized = worksheet.casefold()
    if any(marker in normalized for marker in _SECRET_VALUE_MARKERS):
        raise WorkdayConnectContractError(
            f"{label} appears to contain secret or certificate material."
        )
    values: dict[str, str] = {}
    current_label: str | None = None
    for line_number, raw_line in enumerate(worksheet.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        matched_label = next(
            (
                candidate
                for candidate in labels
                if line.startswith(candidate + ":")
            ),
            None,
        )
        if matched_label is not None:
            if matched_label in values:
                raise WorkdayConnectContractError(
                    f"{label} contains duplicate label '{matched_label}'."
                )
            values[matched_label] = line[len(matched_label) + 1 :].strip()
            current_label = matched_label
            continue
        if current_label in multiline_labels:
            values[current_label] = "\n".join(
                value
                for value in (values[current_label], line)
                if value
            )
            continue
        raise WorkdayConnectContractError(
            f"{label} line {line_number} does not use a recognized exact label."
        )
    missing = [candidate for candidate in labels if candidate not in values]
    if missing:
        raise WorkdayConnectContractError(
            f"{label} is missing labels: " + ", ".join(missing) + "."
        )
    return values


def _worksheet_choice(
    values: Mapping[str, str],
    label: str,
    choices: Mapping[str, str],
) -> str:
    supplied = str(values.get(label) or "").strip()
    normalized = supplied.casefold()
    normalized_choices = {
        option.casefold(): mapped for option, mapped in choices.items()
    }
    if normalized not in normalized_choices:
        raise WorkdayConnectContractError(
            f"{label} must use one of the worksheet's listed successful "
            "answers."
        )
    return normalized_choices[normalized]


def _administrator_attestation(
    *,
    observed_value: str | None = None,
) -> dict[str, str]:
    result = {
        "outcome": "confirmed",
        "provenance": "administrator-attestation",
    }
    if observed_value is not None:
        result["observedValue"] = observed_value
    return result


def parse_entra_return_worksheet(
    _state: Mapping[str, Any],
    worksheet: str,
) -> dict[str, Any]:
    values = _parse_labeled_worksheet(
        worksheet,
        labels=ENTRA_WORKSHEET_LABELS,
        label="Microsoft Entra administrator return worksheet",
    )
    confirmed = {
        "Yes, confirmed": "confirmed",
    }
    permissions = _worksheet_choice(
        values,
        "Permissions and consent",
        {
            "Yes, permissions and consent are confirmed": "confirmed",
        },
    )
    preservation = _worksheet_choice(
        values,
        "Existing configuration",
        {
            "Preserved without changes": "preserved",
            "Remediated without replacing unrelated configuration": "remediated",
        },
    )
    _worksheet_choice(values, "SAML configuration", confirmed)
    _worksheet_choice(values, "Signing certificate", confirmed)
    _worksheet_choice(values, "Authorized connector", confirmed)
    _worksheet_choice(
        values,
        "Employee assignment",
        {
            "Yes, access is confirmed or assignment is not required": "confirmed",
        },
    )
    name_id = _safe_nonsecret_text(
        values["NameID source"],
        "NameID source",
    )
    saml_signing = _worksheet_choice(
        values,
        "SAML signing",
        {
            "Sign SAML response and assertion": (
                "Sign SAML response and assertion"
            ),
        },
    )
    checks = {
        "samlMode": _administrator_attestation(),
        "signingCertificate": _administrator_attestation(),
        "connectorPreauthorized": _administrator_attestation(),
        "graphDelegatedPermissions": _administrator_attestation(),
        "adminConsent": _administrator_attestation(),
        "userAssignment": _administrator_attestation(),
        "nameId": _administrator_attestation(observed_value=name_id),
        "samlSigningOption": _administrator_attestation(
            observed_value=saml_signing,
        ),
        "existingScopesPreserved": _administrator_attestation(
            observed_value=preservation,
        ),
        "authorizedClientsPreserved": _administrator_attestation(
            observed_value=preservation,
        ),
        "permissionsPreserved": _administrator_attestation(
            observed_value=preservation,
        ),
    }
    if permissions != "confirmed":
        raise WorkdayConnectContractError(
            "Permissions and consent are incomplete."
        )
    return {
        "selectedDirectory": {
            "displayName": _safe_nonsecret_text(
                values["Directory name"],
                "Directory name",
            ),
        },
        "application": {
            "displayName": _safe_nonsecret_text(
                values["Enterprise application"],
                "Enterprise application",
            ),
            "appId": _safe_nonsecret_text(
                values["Application ID"],
                "Application ID",
            ),
        },
        "replyUrl": _safe_nonsecret_text(
            values["Selected Reply URL"],
            "Selected Reply URL",
        ),
        "certificate": {
            "thumbprint": _safe_nonsecret_text(
                values["Certificate thumbprint (active certificate row)"],
                "Certificate thumbprint",
            ),
            "validTo": _safe_nonsecret_text(
                values["Certificate expiration date (active certificate row)"],
                "Certificate expiration date",
            ),
        },
        "checks": checks,
    }


def _optional_domain_mappings(value: str) -> list[dict[str, str]]:
    if not value.strip():
        return []
    result = []
    for line in value.splitlines():
        parts = [part.strip() for part in line.split("|", 1)]
        if len(parts) != 2 or not all(parts):
            raise WorkdayConnectContractError(
                "Additional domain mappings must use 'Domain | supported "
                "scenario', one mapping per line."
            )
        result.append({"domain": parts[0], "scenario": parts[1]})
    return result


def parse_workday_admin_return_worksheet(
    state: Mapping[str, Any],
    worksheet: str,
) -> dict[str, Any]:
    values = _parse_labeled_worksheet(
        worksheet,
        labels=WORKDAY_ADMIN_WORKSHEET_LABELS,
        label="Workday administrator return worksheet",
        multiline_labels=frozenset({"Additional domain mappings"}),
    )
    _worksheet_choice(
        values,
        "SAML row settings",
        {"Yes, all four values match exactly": "verified"},
    )
    _worksheet_choice(
        values,
        "Certificate",
        {
            "The new certificate created from the Entra Base64 file": "verified",
        },
    )
    _worksheet_choice(
        values,
        "Certificate expiration",
        {"Yes, the expiration date matches exactly": "verified"},
    )
    optional_domain_outcome = _worksheet_choice(
        values,
        "Optional domains",
        {
            "No additional domains are required": "none",
            "Yes, additional supported scenarios require domains": "provided",
        },
    )
    optional_domains = _optional_domain_mappings(
        values["Additional domain mappings"]
    )
    if optional_domain_outcome == "none" and optional_domains:
        raise WorkdayConnectContractError(
            "Additional domain mappings must be blank when no additional "
            "domains are required."
        )
    if optional_domain_outcome == "provided" and not optional_domains:
        raise WorkdayConnectContractError(
            "At least one additional domain mapping is required."
        )
    authorization = _worksheet_choice(
        values,
        "Authorization",
        {
            "Verified without an authorization error": "verified",
            "Task not authorized was remediated and retested": (
                "task-not-authorized-remediated"
            ),
        },
    )
    identifiers = state.get("identifiers") or {}
    response: dict[str, Any] = {
        "identityProviderOutcome": "verified-entra-issuer",
        "enabledServiceProviderId": _required_text(
            identifiers,
            "workdaySamlEntityId",
            "Verified Workday Service Provider ID",
        ),
        "certificateSelectionOutcome": (
            "entra-signing-certificate-selected"
        ),
        "certificateValidityOutcome": (
            "matches-verified-entra-certificate"
        ),
        "oauthClientId": _safe_nonsecret_text(
            values["OAuth client ID"],
            "OAuth client ID",
        ),
        "apiClientOutcome": _worksheet_choice(
            values,
            "API client",
            {
                "An existing approved client was verified": (
                    "existing-client-verified"
                ),
                "A new client was registered": "new-client-registered",
            },
        ),
        "clientGrantType": _worksheet_choice(
            values,
            "Client grant type",
            {"SAML Bearer": "saml-bearer"},
        ),
        "includeWorkdayOwnedScope": _worksheet_choice(
            values,
            "Workday owned scope",
            {"Yes": "yes"},
        ),
        "oauthTokenUrl": values["OAuth token URL"],
        "restBaseUrl": values["REST base URL"],
        "soapBaseUrl": values["SOAP base URL"],
        "authenticationPolicyOutcome": _worksheet_choice(
            values,
            "Authentication policy",
            {
                "An existing active policy allows SAML": (
                    "existing-active-policy"
                ),
                "A reviewed policy was activated": (
                    "reviewed-policy-activated"
                ),
            },
        ),
        "networkReadinessOutcome": _worksheet_choice(
            values,
            "Network readiness",
            {
                "Both Workday hosts are allowed": "confirmed-hosts-allowed",
                "No customer-managed firewall change is required": (
                    "no-customer-firewall-change-required"
                ),
            },
        ),
        "identityProviderSsoServiceUrl": _required_text(
            identifiers,
            "entraLoginUrl",
            "Verified Microsoft Entra Login URL",
        ),
        "signOnRedirectUrl": _required_text(
            identifiers,
            "replyUrl",
            "Verified Microsoft Entra Reply URL",
        ),
        "rolloutType": _worksheet_choice(
            values,
            "Rollout",
            {
                "Entire workforce - All Employees access is configured": (
                    "entire-workforce"
                ),
                (
                    "Limited or test population - the intended Workday "
                    "security group and test employee access are configured"
                ): "limited-or-test",
            },
        ),
        "publicWorkerReportsOutcome": _worksheet_choice(
            values,
            "Public worker reports",
            {"Yes, Get permission is verified": "get-permission-verified"},
        ),
        "integrationPermissionsGetOutcome": _worksheet_choice(
            values,
            "Integration permissions",
            {"Yes, Get permission is verified": "get-permission-verified"},
        ),
        "functionalAreaScopes": list(
            WORKDAY_REQUIRED_FUNCTIONAL_AREA_SCOPES
        ),
        "optionalDomains": optional_domains,
        "authorizationOutcome": authorization,
    }
    _worksheet_choice(
        values,
        "Functional-area scopes",
        {
            "Yes, all four required functional areas are present": "verified",
        },
    )
    if authorization == "task-not-authorized-remediated":
        response.update(
            {
                "authorizationRemediationDomain": _safe_nonsecret_text(
                    values["Remediated domain"],
                    "Remediated domain",
                ),
                "authorizationRemediationScenario": _safe_nonsecret_text(
                    values["Remediation scenario"],
                    "Remediation scenario",
                ),
                "authorizationRetestOutcome": _worksheet_choice(
                    values,
                    "Authorization retest",
                    {
                        "Verified after remediation": (
                            "verified-after-remediation"
                        ),
                    },
                ),
            }
        )
    elif any(
        values[label].strip()
        for label in (
            "Remediated domain",
            "Remediation scenario",
            "Authorization retest",
        )
    ):
        raise WorkdayConnectContractError(
            "Authorization remediation fields must be blank when no bounded "
            "remediation was required."
        )
    return response


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
    directory_display_name = _required_text(
        discovery,
        "directoryDisplayName",
        "selected Microsoft Entra directory display name",
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
            "Confirm whether Microsoft Entra SSO for Workday already exists",
            "Reuse the existing Workday enterprise application when SSO is "
            "already established; otherwise follow the Microsoft Learn "
            "Workday SSO tutorial to add Workday from the application gallery",
            "Rerun exact application discovery after Entra assigns the "
            "application and service-principal identifiers",
        ]
    elif reusable:
        actions = [
            "Ask the Microsoft Entra administrator to review the exact "
            "Workday application and service principal",
            "Reuse the stored tenant configuration only after the "
            "administrator confirms every required setting",
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
            "directoryDisplayName": directory_display_name,
            "workdayTenant": tenant,
            "workdaySamlEntityId": entity_id,
        },
        "administratorRole": (
            "Application Administrator or Cloud Application Administrator"
        ),
        "engagementQuestion": (
            "Have you looped in the Microsoft Entra administrator to "
            "complete these tasks?"
        ),
        "completionQuestion": (
            "Has the Microsoft Entra administrator completed the tasks in "
            "this handoff?"
        ),
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
        "captureInstructions": [
            {
                "information": "Selected directory display name",
                "fields": ["selectedDirectoryDisplayName"],
                "portalLocation": (
                    "Microsoft Entra admin center -> Microsoft Entra ID -> "
                    "Overview"
                ),
                "instruction": (
                    "After switching to the deployment directory, record its "
                    "exact display name. The tenant ID is already recorded "
                    "from Preflight and does not need to be re-entered."
                ),
            },
            {
                "information": (
                    "Enterprise application display name and Application ID"
                ),
                "fields": [
                    "applicationDisplayName",
                    "applicationId",
                ],
                "portalLocation": (
                    "Microsoft Entra ID -> Enterprise applications -> the "
                    "exact Workday application -> Overview"
                ),
                "instruction": (
                    "Record the exact display name and Application ID. Object "
                    "IDs are reserved for future role-aware verification and "
                    "do not need to be copied by the maker."
                ),
            },
            {
                "information": (
                    "Selected Reply URL and SAML configuration outcome"
                ),
                "fields": [
                    "replyUrl",
                    "entraChecks.samlMode",
                ],
                "portalLocation": (
                    "Enterprise applications -> the exact Workday "
                    "application -> Single sign-on -> SAML -> Basic SAML "
                    "Configuration"
                ),
                "instruction": (
                    "Confirm the displayed Identifier (Entity ID) matches the "
                    "expected Workday Service Provider ID in this handoff, "
                    "then record only the Reply URL intended for this Workday "
                    "tenant. The Microsoft Entra Identifier and Login URL are "
                    "derived from the selected tenant ID."
                ),
            },
            {
                "information": (
                    "Unique User Identifier (Name ID) source attribute"
                ),
                "fields": [
                    "nameIdSource",
                    "entraChecks.nameId",
                ],
                "portalLocation": (
                    "Enterprise applications -> the exact Workday "
                    "application -> Single sign-on -> SAML -> Attributes & "
                    "Claims -> Unique User Identifier (Name ID)"
                ),
                "instruction": (
                    "Record the exact source attribute, such as user.mail or "
                    "user.userPrincipalName."
                ),
            },
            {
                "information": "SAML signing option",
                "fields": [
                    "samlSigningOption",
                    "entraChecks.samlSigningOption",
                ],
                "portalLocation": (
                    "Enterprise applications -> the exact Workday "
                    "application -> Single sign-on -> SAML -> SAML Signing "
                    "Certificate card -> Edit pencil -> Signing Option"
                ),
                "instruction": (
                    "Open the Edit panel and record the exact value shown in "
                    "the Signing Option field. The expected selection is Sign "
                    "SAML response and assertion."
                ),
            },
            {
                "information": (
                    "Active certificate thumbprint and expiration date, and "
                    "certificate-transfer confirmation"
                ),
                "fields": [
                    "certificateThumbprint",
                    "certificateValidTo",
                    "entraChecks.signingCertificate",
                ],
                "portalLocation": (
                    "Enterprise applications -> the exact Workday "
                    "application -> Single sign-on -> SAML -> SAML Signing "
                    "Certificate -> active certificate row"
                ),
                "instruction": (
                    "Record the active certificate's thumbprint and "
                    "Expiration date exactly as displayed. Confirm separately "
                    "that the Base64 certificate was transferred through the "
                    "approved customer channel; do not return the certificate "
                    "body."
                ),
            },
            {
                "information": (
                    "Application ID URI, user_impersonation scope, and "
                    "connector authorization outcome"
                ),
                "fields": [
                    "entraChecks.connectorPreauthorized",
                ],
                "portalLocation": (
                    "App registrations -> the exact Workday registration -> "
                    "Expose an API"
                ),
                "instruction": (
                    "Confirm the derived api:// Application ID URI and enabled "
                    "user_impersonation scope, then confirm connector "
                    f"{WORKDAY_CONNECTOR_APP_ID} is authorized for that scope, "
                    "without copying the scope GUID."
                ),
            },
            {
                "information": (
                    "Required delegated permissions and admin-consent outcome"
                ),
                "fields": [
                    "entraChecks.graphDelegatedPermissions",
                    "entraChecks.adminConsent",
                ],
                "portalLocation": (
                    "App registrations -> the exact Workday registration -> "
                    "API permissions"
                ),
                "instruction": (
                    "Confirm openid, profile, and User.Read are present, note "
                    "whether admin consent is granted, and return one combined "
                    "permissions-and-consent outcome."
                ),
            },
            {
                "information": (
                    "Assignment-required setting and intended ESS employee "
                    "group assignment outcome"
                ),
                "fields": ["entraChecks.userAssignment"],
                "portalLocation": (
                    "Enterprise applications -> the exact Workday "
                    "application -> Properties and Users and groups"
                ),
                "instruction": (
                    "Record whether assignment is required and whether the "
                    "intended ESS employee group, including the test employee, "
                    "has access."
                ),
            },
            {
                "information": (
                    "Preservation of unrelated scopes, authorized clients, "
                    "and API permissions"
                ),
                "fields": [
                    "entraChecks.existingScopesPreserved",
                    "entraChecks.authorizedClientsPreserved",
                    "entraChecks.permissionsPreserved",
                ],
                "portalLocation": (
                    "App registrations -> the exact Workday registration -> "
                    "Expose an API and API permissions"
                ),
                "instruction": (
                    "Return one combined outcome confirming that unrelated "
                    "configuration was preserved, or that targeted remediation "
                    "was completed without replacing unrelated configuration."
                ),
            },
        ],
        "informationToReturn": [
            "Selected directory display name and exact Workday application "
            "display name and Application ID",
            "Reply URL and confirmation that the displayed Entity ID matches "
            "the expected Workday Service Provider ID",
            "Exact NameID source attribute and SAML signing option",
            "Active certificate thumbprint and expiration date, plus "
            "confirmation that its Base64 certificate was transferred through "
            "an approved customer channel",
            "Connector scope, delegated permissions and consent, employee "
            "assignment, and preservation outcomes",
        ],
        "responseForm": {
            "required": sorted(ADMINISTRATOR_REQUIRED_FIELDS["entra"]),
            "collection": {
                "mode": "labeled-worksheet",
                "labels": list(ENTRA_WORKSHEET_LABELS),
                "duplicateLabels": "reject",
                "unknownLabels": "reject",
                "validator": "parse_entra_return_worksheet",
            },
            "note": (
                "Collect the completed administrator worksheet in one "
                "response and do not accept blank required lines. Do not ask "
                "for passwords, client secrets, tokens, cookies, certificate "
                "contents, or private keys. After submission, show the "
                "capture location and a mini-template containing only values "
                "that are missing, invalid, or inconsistent."
            ),
        },
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
_ROLE_AWARE_GRAPH_ENTRA_CHECKS = _ENTRA_CHECKS - {
    "nameId",
    "samlSigningOption",
}
# Role-aware execution will require these live Entra API checks later.
# For now, Workday Connect accepts a guided Entra administrator attestation.
# _GRAPH_ONLY_ENTRA_CHECKS = _ROLE_AWARE_GRAPH_ENTRA_CHECKS


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
    if name in _ROLE_AWARE_GRAPH_ENTRA_CHECKS:
        if normalized_provenance not in {
            "microsoft-graph",
            "administrator-attestation",
        }:
            raise WorkdayConnectContractError(
                f"Entra verification check '{name}' must be proven by Microsoft "
                "Graph or administrator attestation."
            )
        expected_outcome = (
            "verified"
            if normalized_provenance == "microsoft-graph"
            else "confirmed"
        )
        if outcome != expected_outcome:
            raise WorkdayConnectContractError(
                f"Entra verification check '{name}' has an outcome that does "
                "not match its provenance."
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
    """Validate safe structured evidence after the administrator handoff."""
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
    application_value = verification.get("application")
    if not isinstance(application_value, Mapping):
        raise WorkdayConnectContractError(
            "Entra verification application must contain an object."
        )
    application = {
        "displayName": _required_text(
            application_value,
            "displayName",
            "Entra app display name",
        ),
        "appId": _required_text(
            application_value,
            "appId",
            "Entra app ID",
        ),
        "objectId": str(application_value.get("objectId") or "").strip(),
        "servicePrincipalId": str(
            application_value.get("servicePrincipalId") or ""
        ).strip(),
    }
    identifier_uris = application_value.get("identifierUris")
    if identifier_uris is None:
        application["identifierUris"] = []
    elif isinstance(identifier_uris, list):
        application["identifierUris"] = [
            str(value).strip()
            for value in identifier_uris
            if str(value).strip()
        ]
    else:
        raise WorkdayConnectContractError(
            "Entra application identifierUris must be an array."
        )
    reply_urls = application_value.get("replyUrls")
    if reply_urls is None:
        application["replyUrls"] = []
    elif isinstance(reply_urls, list):
        application["replyUrls"] = [
            _absolute_https_url(value, "Entra application Reply URL")
            for value in reply_urls
            if str(value or "").strip()
        ]
    else:
        raise WorkdayConnectContractError(
            "Entra application replyUrls must be an array."
        )
    scope = state.get("scope") or {}
    expected_tenant_id = _required_text(
        scope,
        "entraTenantId",
        "Microsoft Entra tenant ID",
    )
    observed_tenant_id = str(
        verification.get("tenantId") or expected_tenant_id
    ).strip()
    if observed_tenant_id.casefold() != expected_tenant_id.casefold():
        raise WorkdayConnectContractError(
            "The reported Microsoft Entra tenant does not match the tenant "
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
    if application["identifierUris"]:
        observed_uris = {
            _normalized_uri(value)
            for value in application["identifierUris"]
        }
        missing_uris = [
            value
            for value in (expected_entity_id, expected_app_uri)
            if _normalized_uri(value) not in observed_uris
        ]
        if missing_uris:
            raise WorkdayConnectContractError(
                "The reported Entra application is missing required "
                "identifier URIs: " + ", ".join(missing_uris)
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
    selected_directory_id = str(
        selected_directory.get("tenantId") or expected_tenant_id
    ).strip()
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
    observed_entra_identifier = str(
        verification.get("microsoftEntraIdentifier")
        or expected_entra_identifier
    ).strip()
    if _normalized_uri(observed_entra_identifier) != _normalized_uri(
        expected_entra_identifier
    ):
        raise WorkdayConnectContractError(
            "The Microsoft Entra Identifier does not match the selected "
            "directory."
        )
    observed_login_url = str(
        verification.get("loginUrl") or expected_login_url
    ).strip()
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
    if application["replyUrls"] and _normalized_uri(reply_url) not in {
        _normalized_uri(value) for value in application["replyUrls"]
    }:
        raise WorkdayConnectContractError(
            "The Microsoft Entra Reply URL is not present in the "
            "administrator-provided application/service-principal evidence."
        )
    scope_guid = str(verification.get("scopeGuid") or "").strip()
    certificate = verification.get("certificate")
    if not isinstance(certificate, Mapping):
        raise WorkdayConnectContractError(
            "Entra certificate metadata must contain an object."
        )
    certificate_valid_from = str(certificate.get("validFrom") or "").strip()
    safe_certificate = {
        "thumbprint": _certificate_thumbprint(
            certificate.get("thumbprint"),
            "Entra signing certificate thumbprint",
        ),
        "validTo": _required_text(
            certificate,
            "validTo",
            "Entra signing certificate validTo",
        ),
    }
    if certificate_valid_from:
        safe_certificate["validFrom"] = certificate_valid_from
    identifiers = {
            "entraAppId": application["appId"],
            "entraAppIdUri": expected_app_uri,
            "microsoftEntraIdentifier": expected_entra_identifier,
            "entraLoginUrl": expected_login_url,
            "replyUrl": reply_url,
            "workdaySamlEntityId": expected_entity_id,
            "signingCertificate": safe_certificate,
    }
    if application["objectId"]:
        identifiers["entraAppObjectId"] = application["objectId"]
    if application["servicePrincipalId"]:
        identifiers["entraServicePrincipalId"] = application[
            "servicePrincipalId"
        ]
    if scope_guid:
        identifiers["scopeGuid"] = scope_guid
    partial_evidence = {
        "selectedDirectoryId": selected_directory_id,
        "selectedDirectoryDisplayName": selected_directory_name,
        "applicationId": application["appId"],
        "applicationDisplayName": application["displayName"],
        "applicationIdentifierUris": (
            application["identifierUris"]
            or [expected_entity_id, expected_app_uri]
        ),
        "applicationReplyUrls": application["replyUrls"] or [reply_url],
        "replyUrl": reply_url,
        "microsoftEntraIdentifier": expected_entra_identifier,
        "loginUrl": expected_login_url,
        "entraChecks": normalized_checks,
        "nameIdSource": normalized_checks["nameId"]["observedValue"],
        "samlSigningOption": normalized_checks[
            "samlSigningOption"
        ]["observedValue"],
        "certificateThumbprint": safe_certificate["thumbprint"],
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
    }
    if certificate_valid_from:
        partial_evidence["certificateValidFrom"] = certificate_valid_from
    if application["objectId"]:
        partial_evidence["applicationObjectId"] = application["objectId"]
    if application["servicePrincipalId"]:
        partial_evidence["servicePrincipalId"] = application[
            "servicePrincipalId"
        ]
    if scope_guid:
        partial_evidence["scopeGuid"] = scope_guid
    return {
        "identifiers": identifiers,
        "evidence": {
            "tenantId": observed_tenant_id,
            "selectedDirectory": {
                "tenantId": selected_directory_id,
                "displayName": selected_directory_name,
            },
            "applicationDisplayName": application["displayName"],
            "checks": normalized_checks,
        },
        "partialEvidence": partial_evidence,
    }


def build_workday_admin_packet(
    state: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one shareable handoff packet for the Workday administrator."""
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
    certificate_valid_from_value = str(
        signing_certificate.get("validFrom") or ""
    ).strip()
    certificate_valid_from = (
        _date_only(
            certificate_valid_from_value,
            "Entra signing certificate Valid From",
        )
        if certificate_valid_from_value
        else None
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
        "administratorRole": "Workday Administrator",
        "engagementQuestion": (
            "Have you looped in the Workday administrator to complete these "
            "tasks?"
        ),
        "completionQuestion": (
            "Has the Workday administrator completed every applicable task "
            "in this handoff?"
        ),
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
                "In the enabled Microsoft Entra SAML row, do the Issuer, "
                "Service Provider ID, identity-provider SSO service URL, and "
                "sign-on redirect URL exactly match "
                f"{expected_issuer}, {entity_id}, {login_url}, and "
                f"{reply_url}?"
            ),
            "options": [
                "Yes, all four values match exactly",
                "No, one or more values are different",
                "I'm not sure",
            ],
        },
        "certificateValidityQuestion": {
            "question": (
                "Does the selected Workday certificate expiration date "
                f"exactly match {certificate_valid_to}?"
            ),
            "options": [
                "Yes, the expiration date matches exactly",
                "No, the expiration date is different",
                "I'm not sure",
            ],
        },
        "actions": [
            "Identify which sign-in provider the enabled Workday SAML row "
            "uses before changing it",
            "Create a Workday X.509 Public Key from the active Entra SAML "
            "signing certificate, select it on the Microsoft Entra SAML row, "
            "and compare its expiration date",
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
        "informationToReturn": [
            "Enabled identity provider, exact Issuer, Service Provider ID, "
            "IdP SSO service URL, and sign-on redirect URL",
            "Confirmation that the Entra-derived certificate is selected and "
            "its displayed expiration date matches",
            "Workday OAuth client ID, token URL, REST base URL, SOAP base URL, "
            "and tenant name",
            "API-client grant type, required functional areas, and Include "
            "Workday Owned Scope outcome",
            "Configured employee rollout population and Integration "
            "Permissions > Get outcome for Worker Data: Public Worker Reports",
            "Any optional domain permission, its supported scenario, and the "
            "employee retest outcome",
            "Authentication-policy outcome and network-readiness outcome",
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
                "publicWorkerReportsOutcome",
                "integrationPermissionsGetOutcome",
                "functionalAreaScopes",
                "optionalDomains",
                "authorizationOutcome",
            ],
            "collection": {
                "mode": "labeled-worksheet",
                "labels": list(WORKDAY_ADMIN_WORKSHEET_LABELS),
                "duplicateLabels": "reject",
                "unknownLabels": "reject",
                "validator": "parse_workday_admin_return_worksheet",
            },
            "note": (
                "Return the completed worksheet in one response. Do not paste "
                "passwords, client secrets, tokens, cookies, certificate "
                "contents, or private keys. For missing or invalid values, "
                "show one mini-worksheet with only those fields and their "
                "capture instructions."
            ),
        },
    }
    if certificate_valid_from:
        packet["referenceValues"]["certificateValidFrom"] = certificate_valid_from
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
                            "administrator-provided application evidence."
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
    entra_valid_from_value = str(
        signing_certificate.get("validFrom") or ""
    ).strip()
    entra_valid_from = (
        _date_only(
            entra_valid_from_value,
            "Entra signing certificate Valid From",
        )
        if entra_valid_from_value
        else None
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
            "certificateValidityOutcome must confirm that the Workday "
            "certificate expiration matches the verified Entra certificate."
        )
    workday_valid_to = entra_valid_to
    supplied_valid_from = str(
        response.get("certificateValidFrom") or ""
    ).strip()
    supplied_valid_to = str(response.get("certificateValidTo") or "").strip()
    if entra_valid_from and supplied_valid_from and (
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
    workday_valid_from = (
        entra_valid_from
        or (
            _date_only(
                supplied_valid_from,
                "Workday certificate Valid From",
            )
            if supplied_valid_from
            else None
        )
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
    employee_security_group = str(
        response.get("employeeSecurityGroup") or ""
    ).strip()
    if (
        values["rolloutType"] == "limited-or-test"
        and employee_security_group.casefold()
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
        "certificateValidTo": workday_valid_to,
    }
    if workday_valid_from:
        certificate_evidence["certificateValidFrom"] = workday_valid_from
    if certificate_name:
        certificate_evidence["certificateName"] = certificate_name
    result = {
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
    if employee_security_group:
        result["evidence"]["employeeSecurityGroup"] = employee_security_group
        result["partialEvidence"]["employeeSecurityGroup"] = employee_security_group
    return result


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
