# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Workday administrator contracts for Workday Connect."""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlparse

from workday_connect_contract_common import (
    WorkdayConnectContractError,
    _absolute_https_url,
    _date_only,
    _https_url,
    _normalized_uri,
    _optional_domains,
    _parse_labeled_worksheet,
    _reject_secret_like_value,
    _require_endpoint_path,
    _safe_nonsecret_text,
    _safe_string_list,
    _worksheet_choice,
    required_text as _required_text,
)
from workday_connect_model import workday_saml_entity_id


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
LEGACY_WORKDAY_AUTHORIZATION_OUTCOMES = {
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
LEGACY_WORKDAY_AUTHORIZATION_RETEST_OUTCOMES = {
    "verified-after-remediation",
}
WORKDAY_ADMIN_WORKSHEET_LABELS = (
    "SAML row settings",
    "Certificate",
    "Certificate expiration",
    "OAuth client ID",
    "API client",
    "OAuth token URL",
    "REST base URL",
    "SOAP base URL",
    "Authentication policy",
    "Network readiness",
    "Rollout",
    "API client access",
    "Required employee access",
    "Additional scenario domains",
)
WORKDAY_ADMIN_WORKSHEET_LABEL_ALIASES = {
    "SAML settings": "SAML row settings",
    "SAML configuration": "SAML row settings",
    "Certificate expiry": "Certificate expiration",
    "Certificate expiry date": "Certificate expiration",
    "Client ID": "OAuth client ID",
    "OAuth application client ID": "OAuth client ID",
    "API client status": "API client",
    "Token URL": "OAuth token URL",
    "REST URL": "REST base URL",
    "SOAP URL": "SOAP base URL",
    "Auth policy": "Authentication policy",
    "Network access": "Network readiness",
    "Employee rollout": "Rollout",
    "Employee population": "Rollout",
    "API access": "API client access",
    "Employee access": "Required employee access",
    "Additional domains": "Additional scenario domains",
    "Domain mappings": "Additional scenario domains",
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
        multiline_labels=frozenset({"Additional scenario domains"}),
        optional_labels=frozenset({"Additional scenario domains"}),
        label_aliases=WORKDAY_ADMIN_WORKSHEET_LABEL_ALIASES,
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
            (
                "The certificate transferred from the completed Entra handoff"
            ): "verified",
            "The new certificate created from the Entra Base64 file": "verified",
        },
    )
    _worksheet_choice(
        values,
        "Certificate expiration",
        {"Yes, the expiration date matches exactly": "verified"},
    )
    _worksheet_choice(
        values,
        "API client access",
        {
            (
                "Yes, SAML Bearer, Workday Owned Scope, and all four "
                "required functional areas are configured"
            ): "verified",
        },
    )
    _worksheet_choice(
        values,
        "Required employee access",
        {
            (
                "Yes, Get permission is verified for Public Worker Reports "
                "and Integration Permissions"
            ): "verified",
        },
    )
    additional_domains = values.get("Additional scenario domains", "").strip()
    optional_domains = (
        []
        if not additional_domains
        or additional_domains.casefold()
        == "no additional scenario domains are required"
        else _optional_domain_mappings(additional_domains)
    )
    identifiers = state.get("identifiers") or {}
    response: dict[str, Any] = {
        "identityProviderOutcome": "verified-entra-issuer",
        "enabledServiceProviderId": _required_text(
            identifiers,
            "workdaySamlEntityId",
            "Verified Workday Service Provider ID",
        ),
        "certificateSelectionOutcome": ("entra-signing-certificate-selected"),
        "certificateValidityOutcome": ("matches-verified-entra-certificate"),
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
        "clientGrantType": "saml-bearer",
        "includeWorkdayOwnedScope": "yes",
        "oauthTokenUrl": values["OAuth token URL"],
        "restBaseUrl": values["REST base URL"],
        "soapBaseUrl": values["SOAP base URL"],
        "authenticationPolicyOutcome": _worksheet_choice(
            values,
            "Authentication policy",
            {
                "An existing active policy allows SAML": ("existing-active-policy"),
                "A reviewed policy was activated": ("reviewed-policy-activated"),
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
            "Required employee access",
            {
                (
                    "Yes, Get permission is verified for Public Worker "
                    "Reports and Integration Permissions"
                ): "get-permission-verified",
            },
        ),
        "integrationPermissionsGetOutcome": _worksheet_choice(
            values,
            "Required employee access",
            {
                (
                    "Yes, Get permission is verified for Public Worker "
                    "Reports and Integration Permissions"
                ): "get-permission-verified",
            },
        ),
        "functionalAreaScopes": list(WORKDAY_REQUIRED_FUNCTIONAL_AREA_SCOPES),
        "optionalDomains": optional_domains,
    }
    return response


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
            "Have you looped in the Workday administrator to complete these tasks?"
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
                "The certificate transferred from the completed Entra handoff",
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
            "Create a Workday X.509 Public Key from the certificate file "
            "already transferred during the completed Entra handoff, select "
            "it on the Microsoft Entra SAML row, and compare its expiration "
            "date",
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
        "captureInstructions": [
            {
                "information": "SAML row settings",
                "fields": [
                    "identityProviderOutcome",
                    "enabledServiceProviderId",
                    "identityProviderSsoServiceUrl",
                    "signOnRedirectUrl",
                ],
                "portalLocation": "Edit Tenant Setup - Security -> SAML Setup",
                "instruction": (
                    "Compare the enabled Microsoft Entra row with the Issuer, "
                    "Service Provider ID, SSO URL, and redirect URL in this handoff."
                ),
                "exampleValue": "Yes, all four values match exactly",
            },
            {
                "information": "Certificate",
                "fields": ["certificateSelectionOutcome"],
                "portalLocation": (
                    "Edit Tenant Setup - Security -> SAML Setup -> enabled "
                    "Microsoft Entra row -> X509 Certificate"
                ),
                "instruction": (
                    "Select the Workday public key created from the certificate "
                    "file transferred during the completed Entra handoff."
                ),
                "exampleValue": (
                    "The certificate transferred from the completed Entra "
                    "handoff"
                ),
            },
            {
                "information": "Certificate expiration",
                "fields": ["certificateValidityOutcome"],
                "portalLocation": (
                    "View the selected Workday X.509 public key details"
                ),
                "instruction": (
                    "Compare its expiration date with the verified Entra date "
                    f"{certificate_valid_to}."
                ),
                "exampleValue": "Yes, the expiration date matches exactly",
            },
            {
                "information": "OAuth client ID",
                "fields": ["oauthClientId"],
                "portalLocation": "View API Client -> Client ID",
                "instruction": "Record the non-secret OAuth client ID.",
                "exampleValue": "safe-client-id",
            },
            {
                "information": "API client",
                "fields": ["apiClientOutcome"],
                "portalLocation": "View API Client or Register API Client",
                "instruction": (
                    "Record whether an approved client was reused or a new "
                    "client was registered."
                ),
                "exampleValue": "An existing approved client was verified",
            },
            {
                "information": "OAuth token URL",
                "fields": ["oauthTokenUrl"],
                "portalLocation": "View API Client -> Token Endpoint",
                "instruction": "Record the complete HTTPS token endpoint.",
                "exampleValue": (
                    "https://wd5.myworkday.com/ccx/oauth2/contoso/token"
                ),
            },
            {
                "information": "REST base URL",
                "fields": ["restBaseUrl"],
                "portalLocation": "Workday REST service endpoint",
                "instruction": "Record the base URL ending at /ccx/api.",
                "exampleValue": "https://wd5.myworkday.com/ccx/api",
            },
            {
                "information": "SOAP base URL",
                "fields": ["soapBaseUrl"],
                "portalLocation": "Workday SOAP service endpoint",
                "instruction": (
                    "Record the base URL ending at /ccx/service without the "
                    "tenant name."
                ),
                "exampleValue": "https://wd5.myworkday.com/ccx/service",
            },
            {
                "information": "Authentication policy",
                "fields": ["authenticationPolicyOutcome"],
                "portalLocation": (
                    "Manage Authentication Policies -> employee environment"
                ),
                "instruction": (
                    "Record whether an existing SAML rule is active or a "
                    "reviewed policy was activated."
                ),
                "exampleValue": "An existing active policy allows SAML",
            },
            {
                "information": "Network readiness",
                "fields": ["networkReadinessOutcome"],
                "portalLocation": "Customer network policy for the REST and SOAP hosts",
                "instruction": (
                    "Record whether both hosts are allowed or no firewall "
                    "change is required."
                ),
                "exampleValue": "Both Workday hosts are allowed",
            },
            {
                "information": "Rollout",
                "fields": ["rolloutType"],
                "portalLocation": "Workday employee security group assignment",
                "instruction": "Record the configured employee population.",
                "exampleValue": (
                    "Limited or test population - the intended Workday "
                    "security group and test employee access are configured"
                ),
            },
            {
                "information": "API client access",
                "fields": [
                    "clientGrantType",
                    "includeWorkdayOwnedScope",
                    "functionalAreaScopes",
                ],
                "portalLocation": "View API Client -> Functional Areas",
                "instruction": (
                    "Confirm SAML Bearer, Include Workday Owned Scope, and "
                    "Core Payroll, Organizations and Roles, Staffing, and "
                    "Time Off and Leave."
                ),
                "exampleValue": (
                    "Yes, SAML Bearer, Workday Owned Scope, and all four "
                    "required functional areas are configured"
                ),
            },
            {
                "information": "Required employee access",
                "fields": [
                    "publicWorkerReportsOutcome",
                    "integrationPermissionsGetOutcome",
                ],
                "portalLocation": "Domain Security Policies for Functional Area",
                "instruction": (
                    "Confirm Get permission on Worker Data: Public Worker "
                    "Reports and Integration Permissions."
                ),
                "exampleValue": (
                    "Yes, Get permission is verified for Public Worker "
                    "Reports and Integration Permissions"
                ),
            },
            {
                "information": "Additional scenario domains",
                "fields": ["optionalDomains"],
                "portalLocation": "Additional domain security policy review",
                "instruction": (
                    "Optional. When custom scenarios require extra domains, "
                    "enter one Domain | supported scenario mapping per line. "
                    "Otherwise omit this row or leave it blank."
                ),
                "exampleValue": "No additional scenario domains are required",
            },
        ],
        "informationToReturn": [
            "Enabled identity provider, exact Issuer, Service Provider ID, "
            "IdP SSO service URL, and sign-on redirect URL",
            "Confirmation that the Entra-derived certificate is selected and "
            "its displayed expiration date matches the completed Entra "
            "handoff",
            "Workday OAuth client ID, token URL, REST base URL, SOAP base URL, "
            "and tenant name",
            "API-client grant type, required functional areas, and Include "
            "Workday Owned Scope outcome",
            "Configured employee rollout population and Integration "
            "Permissions > Get outcome for Worker Data: Public Worker Reports",
            "Any additional domain permission and its supported scenario",
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
            ],
            "collection": {
                "mode": "labeled-worksheet",
                "acceptedFormats": [
                    "five-column-markdown-table",
                    "labeled-worksheet",
                ],
                "labels": list(WORKDAY_ADMIN_WORKSHEET_LABELS),
                "duplicateLabels": "reject",
                "unknownLabels": "reject",
                "validator": "parse_workday_admin_return_worksheet",
            },
            "note": (
                "Return the administrator details in one response. Do not paste "
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


def _validated_workday_endpoints(
    response: Mapping[str, Any],
    tenant: str,
) -> dict[str, str]:
    endpoints = {
        "oauthTokenUrl": _https_url(
            response.get("oauthTokenUrl"),
            "Workday OAuth token URL",
        ),
        "restBaseUrl": _https_url(
            response.get("restBaseUrl"),
            "Workday REST base URL",
        ),
        "soapBaseUrl": _https_url(
            response.get("soapBaseUrl"),
            "Workday SOAP base URL",
        ),
    }
    for key, path_prefix, label in (
        (
            "oauthTokenUrl",
            f"/ccx/oauth2/{tenant}/token",
            "Workday OAuth token URL",
        ),
        ("restBaseUrl", "/ccx/api", "Workday REST base URL"),
        ("soapBaseUrl", "/ccx/service", "Workday SOAP base URL"),
    ):
        _require_endpoint_path(endpoints[key], path_prefix, label)
    endpoint_hosts = {
        str(urlparse(value).hostname or "").casefold() for value in endpoints.values()
    }
    if len(endpoint_hosts) != 1:
        raise WorkdayConnectContractError(
            "Workday OAuth, REST, and SOAP endpoints must use the same "
            "verified Workday service hostname."
        )
    return endpoints


def _validated_workday_certificate_evidence(
    state: Mapping[str, Any],
    response: Mapping[str, Any],
) -> tuple[str, str, dict[str, str]]:
    signing_certificate = (state.get("identifiers") or {}).get("signingCertificate")
    if not isinstance(signing_certificate, Mapping):
        raise WorkdayConnectContractError(
            "Verified Entra signing certificate metadata is required before "
            "recording Workday administrator evidence."
        )
    entra_valid_from_value = str(signing_certificate.get("validFrom") or "").strip()
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
    selection_outcome = str(response.get("certificateSelectionOutcome") or "").strip()
    if selection_outcome != "entra-signing-certificate-selected":
        raise WorkdayConnectContractError(
            "certificateSelectionOutcome must confirm that the Workday row "
            "uses the certificate created from the verified Entra signing "
            "certificate."
        )
    validity_outcome = str(response.get("certificateValidityOutcome") or "").strip()
    if validity_outcome != "matches-verified-entra-certificate":
        raise WorkdayConnectContractError(
            "certificateValidityOutcome must confirm that the Workday "
            "certificate expiration matches the verified Entra certificate."
        )
    supplied_valid_from = str(response.get("certificateValidFrom") or "").strip()
    supplied_valid_to = str(response.get("certificateValidTo") or "").strip()
    if (
        entra_valid_from
        and supplied_valid_from
        and (
            _date_only(
                supplied_valid_from,
                "Workday certificate Valid From",
            )
            != entra_valid_from
        )
    ):
        raise WorkdayConnectContractError(
            "The supplied Workday certificate Valid From date conflicts "
            "with the verified certificate-date confirmation."
        )
    workday_valid_from = entra_valid_from or (
        _date_only(
            supplied_valid_from,
            "Workday certificate Valid From",
        )
        if supplied_valid_from
        else None
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
    evidence = {
        "certificateSelectionOutcome": selection_outcome,
        "certificateValidityOutcome": validity_outcome,
        "certificateValidTo": entra_valid_to,
    }
    if workday_valid_from:
        evidence["certificateValidFrom"] = workday_valid_from
    certificate_name = str(response.get("certificateName") or "").strip()
    if certificate_name:
        evidence["certificateName"] = certificate_name
    return selection_outcome, validity_outcome, evidence


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
    endpoints = _validated_workday_endpoints(response, tenant)
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
        raise WorkdayConnectContractError("clientGrantType must be saml-bearer.")
    values["clientGrantType"] = "saml-bearer"
    if values["includeWorkdayOwnedScope"].casefold() != "yes":
        raise WorkdayConnectContractError("includeWorkdayOwnedScope must be yes.")
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
    (
        certificate_selection_outcome,
        certificate_validity_outcome,
        certificate_evidence,
    ) = _validated_workday_certificate_evidence(state, response)
    least_privilege_required = {
        "rolloutType",
        "publicWorkerReportsOutcome",
        "integrationPermissionsGetOutcome",
    }
    values.update(
        {key: _required_text(response, key, key) for key in least_privilege_required}
    )
    if values["rolloutType"] not in WORKDAY_ROLLOUT_TYPES:
        raise WorkdayConnectContractError(
            "rolloutType must be entire-workforce or limited-or-test."
        )
    employee_security_group = str(response.get("employeeSecurityGroup") or "").strip()
    if values[
        "rolloutType"
    ] == "limited-or-test" and employee_security_group.casefold() in {
        "all employees",
        "all workers",
    }:
        raise WorkdayConnectContractError(
            "A limited or test rollout cannot use All Employees."
        )
    if values["publicWorkerReportsOutcome"] not in WORKDAY_DOMAIN_PERMISSION_OUTCOMES:
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
    supplied_functional_area_scopes = _safe_string_list(
        response.get("functionalAreaScopes"),
        "Workday functionalAreaScopes",
        allow_empty=False,
    )
    expected_functional_area_scopes = {
        value.casefold() for value in WORKDAY_REQUIRED_FUNCTIONAL_AREA_SCOPES
    }
    if {
        value.casefold() for value in supplied_functional_area_scopes
    } != expected_functional_area_scopes:
        raise WorkdayConnectContractError(
            "functionalAreaScopes must contain exactly Core Payroll, "
            "Organizations and Roles, Staffing, and Time Off and Leave."
        )
    functional_area_scopes = list(WORKDAY_REQUIRED_FUNCTIONAL_AREA_SCOPES)
    optional_domains = _optional_domains(
        response.get("optionalDomains")
        if response.get("optionalDomains") is not None
        else []
    )
    legacy_authorization = str(response.get("authorizationOutcome") or "").strip()
    legacy_remediation_fields = {
        "authorizationRemediationDomain": str(
            response.get("authorizationRemediationDomain") or ""
        ).strip(),
        "authorizationRemediationScenario": str(
            response.get("authorizationRemediationScenario") or ""
        ).strip(),
        "authorizationRetestOutcome": str(
            response.get("authorizationRetestOutcome") or ""
        ).strip(),
    }
    if legacy_authorization:
        if legacy_authorization not in LEGACY_WORKDAY_AUTHORIZATION_OUTCOMES:
            raise WorkdayConnectContractError(
                "Legacy authorizationOutcome is unsupported."
            )
    elif any(legacy_remediation_fields.values()):
        raise WorkdayConnectContractError(
            "Legacy authorization remediation fields require "
            "authorizationOutcome."
        )
    if legacy_authorization == "task-not-authorized-remediated":
        _safe_nonsecret_text(
            legacy_remediation_fields["authorizationRemediationDomain"],
            "authorizationRemediationDomain",
        )
        _safe_nonsecret_text(
            legacy_remediation_fields["authorizationRemediationScenario"],
            "authorizationRemediationScenario",
        )
        if (
            legacy_remediation_fields["authorizationRetestOutcome"]
            not in LEGACY_WORKDAY_AUTHORIZATION_RETEST_OUTCOMES
        ):
            raise WorkdayConnectContractError(
                "Legacy authorizationRetestOutcome must confirm verification "
                "after remediation."
            )
    elif any(legacy_remediation_fields.values()):
        raise WorkdayConnectContractError(
            "Legacy authorization remediation fields must be omitted when "
            "authorizationOutcome is verified."
        )
    result = {
        "identifiers": {
            "workdaySamlEntityId": expected_entity_id,
            "oauthClientId": values["oauthClientId"],
        },
        "endpoints": endpoints,
        "evidence": {
            "activeIdentityProviderIssuer": active_identity_provider_issuer,
            "identityProviderOutcome": identity_provider_outcome,
            "serviceProviderId": expected_entity_id,
            **certificate_evidence,
            "authenticationPolicyOutcome": values["authenticationPolicyOutcome"],
            "networkReadinessOutcome": values["networkReadinessOutcome"],
            "apiClientOutcome": values["apiClientOutcome"],
            "clientGrantType": values["clientGrantType"],
            "includeWorkdayOwnedScope": values["includeWorkdayOwnedScope"],
            "identityProviderSsoServiceUrl": values["identityProviderSsoServiceUrl"],
            "signOnRedirectUrl": values["signOnRedirectUrl"],
            "rolloutType": values["rolloutType"],
            "publicWorkerReportsOutcome": values["publicWorkerReportsOutcome"],
            "integrationPermissionsGetOutcome": values[
                "integrationPermissionsGetOutcome"
            ],
            "functionalAreaScopes": functional_area_scopes,
            "optionalDomains": optional_domains,
        },
        "partialEvidence": {
            "identityProviderOutcome": identity_provider_outcome,
            "enabledServiceProviderId": expected_entity_id,
            "certificateSelectionOutcome": certificate_selection_outcome,
            "certificateValidityOutcome": certificate_validity_outcome,
            "oauthClientId": values["oauthClientId"],
            **endpoints,
            "authenticationPolicyOutcome": values["authenticationPolicyOutcome"],
            "networkReadinessOutcome": values["networkReadinessOutcome"],
            "apiClientOutcome": values["apiClientOutcome"],
            "clientGrantType": values["clientGrantType"],
            "includeWorkdayOwnedScope": values["includeWorkdayOwnedScope"],
            "identityProviderSsoServiceUrl": values["identityProviderSsoServiceUrl"],
            "signOnRedirectUrl": values["signOnRedirectUrl"],
            "rolloutType": values["rolloutType"],
            "publicWorkerReportsOutcome": values["publicWorkerReportsOutcome"],
            "integrationPermissionsGetOutcome": values[
                "integrationPermissionsGetOutcome"
            ],
            "functionalAreaScopes": functional_area_scopes,
            "optionalDomains": optional_domains,
        },
    }
    if employee_security_group:
        result["evidence"]["employeeSecurityGroup"] = employee_security_group
        result["partialEvidence"]["employeeSecurityGroup"] = employee_security_group
    return result
