# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Microsoft Entra administrator contracts for Workday Connect."""

from __future__ import annotations

from typing import Any, Mapping

from workday_connect_contract_common import (
    WorkdayConnectContractError,
    _absolute_https_url,
    _administrator_attestation,
    _certificate_thumbprint,
    _date_only,
    _normalized_uri,
    _parse_labeled_worksheet,
    _reject_secret_like_value,
    _safe_nonsecret_text,
    _worksheet_choice,
    required_text as _required_text,
)
from workday_connect_model import (
    ADMINISTRATOR_REQUIRED_FIELDS,
    PhaseStatus,
    workday_saml_entity_id,
)


WORKDAY_CONNECTOR_APP_ID = "4e4707ca-5f53-46a6-a819-f7765446e6ff"
GRAPH_DELEGATED_PERMISSIONS = ("openid", "profile", "User.Read")
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
ENTRA_WORKSHEET_LABEL_ALIASES = {
    "Directory": "Directory name",
    "Entra directory": "Directory name",
    "Enterprise app": "Enterprise application",
    "Application name": "Enterprise application",
    "App ID": "Application ID",
    "Reply URL": "Selected Reply URL",
    "Name ID source": "NameID source",
    "Certificate thumbprint": (
        "Certificate thumbprint (active certificate row)"
    ),
    "Certificate expiration": (
        "Certificate expiration date (active certificate row)"
    ),
    "Certificate expiration date": (
        "Certificate expiration date (active certificate row)"
    ),
    "Certificate expiry": (
        "Certificate expiration date (active certificate row)"
    ),
    "Certificate expiry date": (
        "Certificate expiration date (active certificate row)"
    ),
}


def parse_entra_return_worksheet(
    _state: Mapping[str, Any],
    worksheet: str,
) -> dict[str, Any]:
    values = _parse_labeled_worksheet(
        worksheet,
        labels=ENTRA_WORKSHEET_LABELS,
        label="Microsoft Entra administrator return worksheet",
        label_aliases=ENTRA_WORKSHEET_LABEL_ALIASES,
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
            "Sign SAML response and assertion": ("Sign SAML response and assertion"),
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
        raise WorkdayConnectContractError("Permissions and consent are incomplete.")
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
            "validTo": _date_only(
                _safe_nonsecret_text(
                    values[
                        "Certificate expiration date (active certificate row)"
                    ],
                    "Certificate expiration date",
                ),
                "Certificate expiration date",
            ),
        },
        "checks": checks,
    }


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
    discovery: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an Entra administrator handoff with optional live discovery."""
    _require_preflight(state)
    if discovery is not None and not isinstance(discovery, Mapping):
        raise WorkdayConnectContractError("Entra discovery must contain a JSON object.")
    scope = state.get("scope") or {}
    tenant = _required_text(scope, "workdayTenant", "Workday tenant")
    entity_id = workday_saml_entity_id(tenant)
    entra_tenant_id = _required_text(
        scope, "entraTenantId", "Microsoft Entra tenant ID"
    )
    guided = discovery is None
    discovery_document = discovery or {}
    directory_display_name = (
        None
        if guided
        else _required_text(
            discovery_document,
            "directoryDisplayName",
            "selected Microsoft Entra directory display name",
        )
    )
    candidates = [
        _candidate(value) for value in (discovery_document.get("applications") or [])
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
    allow_create = discovery_document.get("allowCreate") is True
    if not guided and not matches and not allow_create:
        raise WorkdayConnectContractError(
            "No exact Entra application was found and application creation "
            "was not authorized for planning."
        )

    app = matches[0] if matches else None
    if guided:
        target = {
            "mode": "administrator-selection",
            "selectionRule": (
                "Match the expected Workday Service Provider ID and the same "
                "Application ID across the enterprise application and app "
                "registration; never select by display name alone."
            ),
        }
    elif app:
        target = {
            "mode": "reuse",
            **app,
        }
    else:
        target = {
            "mode": "create",
            "displayName": str(
                discovery_document.get("newDisplayName") or "Workday (ESS Copilot)"
            ).strip(),
            "galleryTemplate": "Workday",
        }
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
    if guided:
        actions = [
            "Identify the existing Workday SSO application by the expected "
            "Service Provider ID and matching Application ID",
            "Reuse the existing Workday enterprise application when SSO is "
            "already established; otherwise follow the Microsoft Learn "
            "Workday SSO tutorial to add Workday from the application gallery",
            "Configure and verify every setting in the administrator guide, "
            "download the active Base64 signing certificate and transfer it "
            "through the approved customer channel for the Workday phase, "
            "then return the completed table",
        ]
    elif app is None:
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
            "workdayTenant": tenant,
            "workdaySamlEntityId": entity_id,
            **(
                {"directoryDisplayName": directory_display_name}
                if directory_display_name
                else {}
            ),
        },
        "administratorRole": (
            "Application Administrator or Cloud Application Administrator"
        ),
        "engagementQuestion": (
            "Have you looped in the Microsoft Entra administrator to "
            "complete these tasks?"
        ),
        "completionQuestion": (
            "Has the Microsoft Entra administrator completed the tasks in this handoff?"
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
        "requiresRediscovery": not guided and app is None,
        "actions": actions,
        "captureInstructions": [
            {
                "information": "Directory name",
                "fields": ["selectedDirectoryDisplayName"],
                "portalLocation": (
                    "Microsoft Entra admin center -> Microsoft Entra ID -> Overview"
                ),
                "instruction": (
                    "Record the exact display name of the deployment directory."
                ),
                "exampleValue": "Contoso",
            },
            {
                "information": "Enterprise application",
                "fields": ["applicationDisplayName"],
                "portalLocation": (
                    "Microsoft Entra ID -> Enterprise applications -> the "
                    "exact Workday application -> Overview"
                ),
                "instruction": "Record the exact application display name.",
                "exampleValue": "Workday",
            },
            {
                "information": "Application ID",
                "fields": ["applicationId"],
                "portalLocation": (
                    "Microsoft Entra ID -> Enterprise applications -> the "
                    "exact Workday application -> Overview"
                ),
                "instruction": (
                    "Record the Application ID. Do not record either Object ID."
                ),
                "exampleValue": "11111111-1111-1111-1111-111111111111",
            },
            {
                "information": "Selected Reply URL",
                "fields": ["replyUrl"],
                "portalLocation": (
                    "Enterprise applications -> the exact Workday "
                    "application -> Single sign-on -> SAML -> Basic SAML "
                    "Configuration"
                ),
                "instruction": (
                    "Record the Reply URL intended for this Workday tenant."
                ),
                "exampleValue": "https://wd5.myworkday.com/contoso/login-saml2.htmld",
            },
            {
                "information": "NameID source",
                "fields": ["nameIdSource", "entraChecks.nameId"],
                "portalLocation": (
                    "Enterprise applications -> the exact Workday "
                    "application -> Single sign-on -> SAML -> Attributes & "
                    "Claims -> Unique User Identifier (Name ID)"
                ),
                "instruction": "Record the exact source attribute.",
                "exampleValue": "user.userPrincipalName",
            },
            {
                "information": "SAML signing",
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
                    "Record the exact value shown in the Signing Option field."
                ),
                "exampleValue": "Sign SAML response and assertion",
            },
            {
                "information": "Certificate thumbprint (active certificate row)",
                "fields": ["certificateThumbprint"],
                "portalLocation": (
                    "Enterprise applications -> the exact Workday "
                    "application -> Single sign-on -> SAML -> SAML Signing "
                    "Certificate -> active certificate row"
                ),
                "instruction": "Record the active certificate thumbprint.",
                "exampleValue": "A1B2C3D4E5F6",
            },
            {
                "information": "Certificate expiration date (active certificate row)",
                "fields": ["certificateValidTo"],
                "portalLocation": (
                    "Enterprise applications -> the exact Workday "
                    "application -> Single sign-on -> SAML -> SAML Signing "
                    "Certificate -> active certificate row"
                ),
                "instruction": "Record the Expiration date exactly as displayed.",
                "exampleValue": "2027-01-01",
            },
            {
                "information": "SAML configuration",
                "fields": ["entraChecks.samlMode"],
                "portalLocation": (
                    "Enterprise applications -> the exact Workday "
                    "application -> Single sign-on -> SAML"
                ),
                "instruction": (
                    "Confirm the Identifier, Reply URL, Login URL, NameID, and "
                    "signing option match this handoff."
                ),
                "exampleValue": "Yes, confirmed",
            },
            {
                "information": "Signing certificate",
                "fields": ["entraChecks.signingCertificate"],
                "portalLocation": (
                    "Enterprise applications -> the exact Workday "
                    "application -> Single sign-on -> SAML -> SAML Signing "
                    "Certificate"
                ),
                "instruction": (
                    "Confirm the active Base64 certificate was downloaded and "
                    "transferred through the approved customer channel to the "
                    "person completing the Workday handoff. Do not return the "
                    "certificate in chat."
                ),
                "exampleValue": "Yes, confirmed",
            },
            {
                "information": "Authorized connector",
                "fields": ["entraChecks.connectorPreauthorized"],
                "portalLocation": (
                    "App registrations -> the exact Workday registration -> "
                    "Expose an API"
                ),
                "instruction": (
                    "Confirm the api:// Application ID URI, user_impersonation "
                    "scope, and connector "
                    f"{WORKDAY_CONNECTOR_APP_ID} is authorized for that scope, "
                    "without copying the scope GUID."
                ),
                "exampleValue": "Yes, confirmed",
            },
            {
                "information": "Permissions and consent",
                "fields": [
                    "entraChecks.graphDelegatedPermissions",
                    "entraChecks.adminConsent",
                ],
                "portalLocation": (
                    "App registrations -> the exact Workday registration -> "
                    "API permissions"
                ),
                "instruction": (
                    "Confirm openid, profile, and User.Read are present and "
                    "administrator consent is granted."
                ),
                "exampleValue": "Yes, permissions and consent are confirmed",
            },
            {
                "information": "Employee assignment",
                "fields": ["entraChecks.userAssignment"],
                "portalLocation": (
                    "Enterprise applications -> the exact Workday "
                    "application -> Properties and Users and groups"
                ),
                "instruction": (
                    "Confirm the intended ESS employee group has access, or "
                    "that assignment is not required."
                ),
                "exampleValue": (
                    "Yes, access is confirmed or assignment is not required"
                ),
            },
            {
                "information": "Existing configuration",
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
                    "Confirm unrelated scopes, authorized clients, and "
                    "permissions were preserved."
                ),
                "exampleValue": "Preserved without changes",
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
                "acceptedFormats": [
                    "five-column-markdown-table",
                    "labeled-worksheet",
                ],
                "labels": list(ENTRA_WORKSHEET_LABELS),
                "duplicateLabels": "reject",
                "unknownLabels": "reject",
                "validator": "parse_entra_return_worksheet",
            },
            "note": (
                "Collect the administrator values in one response. Do "
                "not accept blank required values or ask for passwords, client "
                "secrets, tokens, cookies, certificate contents, or private "
                "keys. After submission, show the capture location and a "
                "mini-template containing only values that are missing, "
                "invalid, or inconsistent."
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
            "verified" if normalized_provenance == "microsoft-graph" else "confirmed"
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
            "Entra verification contains unsupported fields: " + ", ".join(unexpected)
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
            str(value).strip() for value in identifier_uris if str(value).strip()
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
    observed_tenant_id = str(verification.get("tenantId") or expected_tenant_id).strip()
    if observed_tenant_id.casefold() != expected_tenant_id.casefold():
        raise WorkdayConnectContractError(
            "The reported Microsoft Entra tenant does not match the tenant "
            "recorded during Workday preflight."
        )
    tenant = _required_text(scope, "workdayTenant", "Workday tenant")
    expected_entity_id = workday_saml_entity_id(tenant)
    expected_app_uri = f"api://{application['appId']}"
    expected_entra_identifier = f"https://sts.windows.net/{expected_tenant_id}/"
    expected_login_url = f"https://login.microsoftonline.com/{expected_tenant_id}/saml2"
    if application["identifierUris"]:
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
        verification.get("microsoftEntraIdentifier") or expected_entra_identifier
    ).strip()
    if _normalized_uri(observed_entra_identifier) != _normalized_uri(
        expected_entra_identifier
    ):
        raise WorkdayConnectContractError(
            "The Microsoft Entra Identifier does not match the selected directory."
        )
    observed_login_url = str(verification.get("loginUrl") or expected_login_url).strip()
    if _normalized_uri(observed_login_url) != _normalized_uri(expected_login_url):
        raise WorkdayConnectContractError(
            "The Microsoft Entra Login URL does not match the selected directory."
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
        "validTo": _date_only(
            _required_text(
                certificate,
                "validTo",
                "Entra signing certificate validTo",
            ),
            "Entra signing certificate expiration date",
        ),
    }
    if certificate_valid_from:
        safe_certificate["validFrom"] = _date_only(
            certificate_valid_from,
            "Entra signing certificate start date",
        )
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
        identifiers["entraServicePrincipalId"] = application["servicePrincipalId"]
    if scope_guid:
        identifiers["scopeGuid"] = scope_guid
    partial_evidence = {
        "selectedDirectoryId": selected_directory_id,
        "selectedDirectoryDisplayName": selected_directory_name,
        "applicationId": application["appId"],
        "applicationDisplayName": application["displayName"],
        "applicationIdentifierUris": (
            application["identifierUris"] or [expected_entity_id, expected_app_uri]
        ),
        "applicationReplyUrls": application["replyUrls"] or [reply_url],
        "replyUrl": reply_url,
        "microsoftEntraIdentifier": expected_entra_identifier,
        "loginUrl": expected_login_url,
        "entraChecks": normalized_checks,
        "nameIdSource": normalized_checks["nameId"]["observedValue"],
        "samlSigningOption": normalized_checks["samlSigningOption"]["observedValue"],
        "certificateThumbprint": safe_certificate["thumbprint"],
        "certificateValidTo": safe_certificate["validTo"],
        "scopePreservationOutcome": normalized_checks["existingScopesPreserved"][
            "observedValue"
        ],
        "authorizedClientPreservationOutcome": normalized_checks[
            "authorizedClientsPreserved"
        ]["observedValue"],
        "permissionPreservationOutcome": normalized_checks["permissionsPreserved"][
            "observedValue"
        ],
    }
    if certificate_valid_from:
        partial_evidence["certificateValidFrom"] = certificate_valid_from
    if application["objectId"]:
        partial_evidence["applicationObjectId"] = application["objectId"]
    if application["servicePrincipalId"]:
        partial_evidence["servicePrincipalId"] = application["servicePrincipalId"]
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
