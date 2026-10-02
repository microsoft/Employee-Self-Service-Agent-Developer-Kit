from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import pytest


SCRIPTS = (
    Path(__file__).resolve().parents[2] / "solutions" / "ess-maker-skills" / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

from workday_connect_contracts import (  # noqa: E402
    WorkdayConnectContractError,
    build_entra_handoff,
    build_workday_admin_packet,
    validate_agent_binding_evidence,
    validate_administrator_partial_evidence,
    validate_employee_evidence,
    validate_employee_failure_evidence,
    validate_entra_verification,
    validate_workday_admin_response,
)
import workday_connect_contracts as contracts  # noqa: E402
from workday_connect_model import (  # noqa: E402
    ADMINISTRATOR_REQUIRED_FIELDS,
    default_state,
)


def _state():
    state = default_state()
    state["scope"].update(
        {
            "entraTenantId": "00000000-0000-0000-0000-000000000000",
            "workdayTenant": "contoso_impl",
            "packageFlavor": "runtime",
        }
    )
    state["identifiers"].update(
        {
            "microsoftEntraIdentifier": (
                "https://sts.windows.net/"
                "00000000-0000-0000-0000-000000000000/"
            ),
            "entraLoginUrl": (
                "https://login.microsoftonline.com/"
                "00000000-0000-0000-0000-000000000000/saml2"
            ),
            "replyUrl": "https://www.workday.com/saml/acs",
        }
    )
    state["phases"]["preflight"]["status"] = "complete"
    return state


def _entra_checks():
    return {
        "samlMode": {
            "outcome": "verified",
            "provenance": "microsoft-graph",
        },
        "signingCertificate": {
            "outcome": "verified",
            "provenance": "microsoft-graph",
        },
        "connectorPreauthorized": {
            "outcome": "verified",
            "provenance": "microsoft-graph",
        },
        "graphDelegatedPermissions": {
            "outcome": "verified",
            "provenance": "microsoft-graph",
        },
        "adminConsent": {
            "outcome": "verified",
            "provenance": "microsoft-graph",
        },
        "userAssignment": {
            "outcome": "verified",
            "provenance": "microsoft-graph",
        },
        "nameId": {
            "outcome": "verified",
            "provenance": "microsoft-graph",
            "observedValue": "user.userPrincipalName",
        },
        "samlSigningOption": {
            "outcome": "confirmed",
            "provenance": "administrator-attestation",
            "observedValue": "Sign SAML response and assertion",
        },
        "existingScopesPreserved": {
            "outcome": "verified",
            "provenance": "microsoft-graph",
            "observedValue": "preserved",
        },
        "authorizedClientsPreserved": {
            "outcome": "verified",
            "provenance": "microsoft-graph",
            "observedValue": "preserved",
        },
        "permissionsPreserved": {
            "outcome": "verified",
            "provenance": "microsoft-graph",
            "observedValue": "preserved",
        },
    }


def _entra_verification(*, reply_urls=None, reply_url=None):
    app_id = "44444444-4444-4444-4444-444444444444"
    return {
        "tenantId": "00000000-0000-0000-0000-000000000000",
        "selectedDirectory": {
            "tenantId": "00000000-0000-0000-0000-000000000000",
            "displayName": "Contoso",
        },
        "application": {
            "displayName": "Workday exact",
            "appId": app_id,
            "objectId": "55555555-5555-5555-5555-555555555555",
            "servicePrincipalId": "66666666-6666-6666-6666-666666666666",
            "identifierUris": [
                "http://www.workday.com/contoso_impl",
                f"api://{app_id}",
            ],
            "replyUrls": (
                reply_urls
                if reply_urls is not None
                else ["https://www.workday.com/saml/acs"]
            ),
        },
        "scopeGuid": "77777777-7777-7777-7777-777777777777",
        "replyUrl": reply_url or "https://www.workday.com/saml/acs",
        "microsoftEntraIdentifier": (
            "https://sts.windows.net/"
            "00000000-0000-0000-0000-000000000000/"
        ),
        "loginUrl": (
            "https://login.microsoftonline.com/"
            "00000000-0000-0000-0000-000000000000/saml2"
        ),
        "certificate": {
            "thumbprint": "AA11",
            "validFrom": "2026-01-01T00:00:00Z",
            "validTo": "2027-01-01T00:00:00Z",
        },
        "checks": _entra_checks(),
    }


def _workday_state():
    state = _state()
    state["identifiers"]["signingCertificate"] = {
        "thumbprint": "AA11",
        "validFrom": "2026-01-01T00:00:00Z",
        "validTo": "2027-01-01T00:00:00Z",
    }
    return state


def _workday_response(**overrides):
    response = {
        "identityProviderOutcome": "verified-entra-issuer",
        "enabledServiceProviderId": "http://www.workday.com/contoso_impl",
        "certificateSelectionOutcome": "entra-signing-certificate-selected",
        "certificateValidityOutcome": "matches-verified-entra-certificate",
        "oauthClientId": "safe-client-id",
        "apiClientOutcome": "existing-client-verified",
        "clientGrantType": "saml-bearer",
        "includeWorkdayOwnedScope": "yes",
        "identityProviderSsoServiceUrl": (
            "https://login.microsoftonline.com/"
            "00000000-0000-0000-0000-000000000000/saml2"
        ),
        "signOnRedirectUrl": "https://www.workday.com/saml/acs",
        "oauthTokenUrl": (
            "https://example.workday.com/ccx/oauth2/contoso_impl/token"
        ),
        "restBaseUrl": "https://example.workday.com/ccx/api",
        "soapBaseUrl": "https://example.workday.com/ccx/service",
        "authenticationPolicyOutcome": "existing-active-policy",
        "networkReadinessOutcome": "confirmed-hosts-allowed",
        "rolloutType": "limited-or-test",
        "employeeSecurityGroup": "ESS Workday Pilot Employees",
        "publicWorkerReportsOutcome": "get-permission-verified",
        "integrationPermissionsGetOutcome": "get-permission-verified",
        "functionalAreaScopes": [
            "Core Payroll",
            "Organizations and Roles",
            "Staffing",
            "Time Off and Leave",
        ],
        "optionalDomains": [],
        "authorizationOutcome": "verified",
    }
    response.update(overrides)
    return response


def test_entra_handoff_selects_only_exact_service_provider_id():
    handoff = build_entra_handoff(
        _state(),
        {
            "directoryDisplayName": "Contoso",
            "applications": [
                {
                    "displayName": "Workday wrong",
                    "appId": "11111111-1111-1111-1111-111111111111",
                    "objectId": "22222222-2222-2222-2222-222222222222",
                    "servicePrincipalId": "33333333-3333-3333-3333-333333333333",
                    "identifierUris": ["http://www.workday.com/contoso_impl_old"],
                },
                {
                    "displayName": "Workday exact",
                    "appId": "44444444-4444-4444-4444-444444444444",
                    "objectId": "55555555-5555-5555-5555-555555555555",
                    "servicePrincipalId": "66666666-6666-6666-6666-666666666666",
                    "identifierUris": ["http://www.workday.com/contoso_impl/"],
                },
            ]
        },
    )

    assert handoff["target"]["displayName"] == "Workday exact"
    assert handoff["identifiers"]["workdaySamlEntityId"] == (
        "http://www.workday.com/contoso_impl"
    )
    assert handoff["identifiers"]["entraAppIdUri"] == (
        "api://44444444-4444-4444-4444-444444444444"
    )
    assert (
        handoff["identifiers"]["workdaySamlEntityId"]
        != (handoff["identifiers"]["entraAppIdUri"])
    )
    assert "planHash" not in handoff


def test_entra_handoff_rejects_missing_exact_discovery():
    with pytest.raises(WorkdayConnectContractError, match="No exact"):
        build_entra_handoff(
            _state(),
            {
                "directoryDisplayName": "Contoso",
                "applications": [],
            },
        )


def test_entra_handoff_can_request_explicit_creation():
    handoff = build_entra_handoff(
        _state(),
        {
            "directoryDisplayName": "Contoso",
            "applications": [],
            "allowCreate": True,
        },
    )

    assert handoff["target"]["mode"] == "create"
    assert handoff["identifiers"]["entraAppIdUri"] is None
    assert handoff["requiresRediscovery"] is True
    assert handoff["scope"]["directoryDisplayName"] == "Contoso"
    assert handoff["engagementQuestion"].startswith("Have you looped in")
    assert handoff["completionQuestion"].startswith("Has the Microsoft Entra")
    assert any("NameID" in item for item in handoff["informationToReturn"])
    capture_by_field = {
        field: instruction
        for instruction in handoff["captureInstructions"]
        for field in instruction["fields"]
    }
    assert (
        ADMINISTRATOR_REQUIRED_FIELDS["entra"] - {"entraChecks"}
        <= capture_by_field.keys()
    )
    assert {
        "entraChecks.samlMode",
        "entraChecks.signingCertificate",
        "entraChecks.connectorPreauthorized",
        "entraChecks.graphDelegatedPermissions",
        "entraChecks.adminConsent",
        "entraChecks.userAssignment",
        "entraChecks.nameId",
        "entraChecks.samlSigningOption",
        "entraChecks.existingScopesPreserved",
        "entraChecks.authorizedClientsPreserved",
        "entraChecks.permissionsPreserved",
    } <= capture_by_field.keys()
    assert set(handoff["responseForm"]["required"]) == (
        ADMINISTRATOR_REQUIRED_FIELDS["entra"]
    )
    assert len(handoff["responseForm"]["required"]) == 9
    assert "completed administrator worksheet" in handoff["responseForm"]["note"]
    assert "Basic SAML Configuration" in capture_by_field[
        "replyUrl"
    ]["portalLocation"]
    assert "Unique User Identifier" in capture_by_field[
        "nameIdSource"
    ]["portalLocation"]
    signing_location = capture_by_field["samlSigningOption"]["portalLocation"]
    assert "SAML Signing Certificate" in signing_location
    assert "Edit pencil -> Signing Option" in signing_location
    assert "Expose an API" in capture_by_field[
        "entraChecks.connectorPreauthorized"
    ]["portalLocation"]
    assert "API permissions" in capture_by_field[
        "entraChecks.graphDelegatedPermissions"
    ]["portalLocation"]


def test_entra_handoff_reuses_matching_tenant_foundation():
    state = _state()
    app_id = "44444444-4444-4444-4444-444444444444"
    state["tenantFoundation"] = {
        "scope": {
            "entraTenantId": state["scope"]["entraTenantId"],
            "workdayTenant": state["scope"]["workdayTenant"],
        },
        "identifiers": {"entraAppId": app_id},
        "endpoints": {},
        "phases": {
            "entra": {
                "completedActions": [],
                "evidence": [],
            },
            "workday-admin": {
                "completedActions": [],
                "evidence": [],
            },
        },
        "capturedAt": "2026-09-26T00:00:00Z",
    }

    handoff = build_entra_handoff(
        state,
        {
            "directoryDisplayName": "Contoso",
            "applications": [
                {
                    "displayName": "Workday exact",
                    "appId": app_id,
                    "objectId": "55555555-5555-5555-5555-555555555555",
                    "servicePrincipalId": ("66666666-6666-6666-6666-666666666666"),
                    "identifierUris": ["http://www.workday.com/contoso_impl"],
                }
            ]
        },
    )

    assert handoff["foundationReuse"]["eligible"] is True
    assert set(handoff["foundationReuse"]) == {"eligible"}
    assert "administrator to review" in handoff["actions"][0]


def test_entra_verification_requires_all_expected_graph_evidence():
    app_id = "44444444-4444-4444-4444-444444444444"
    result = validate_entra_verification(
        _state(),
        {
            "tenantId": "00000000-0000-0000-0000-000000000000",
            "selectedDirectory": {
                "tenantId": "00000000-0000-0000-0000-000000000000",
                "displayName": "Contoso",
            },
            "application": {
                "displayName": "Workday exact",
                "appId": app_id,
                "objectId": "55555555-5555-5555-5555-555555555555",
                "servicePrincipalId": ("66666666-6666-6666-6666-666666666666"),
                "identifierUris": [
                    "http://www.workday.com/contoso_impl",
                    f"api://{app_id}",
                ],
                "replyUrls": [
                    "https://www.workday.com/saml/acs",
                ],
            },
            "scopeGuid": "77777777-7777-7777-7777-777777777777",
            "replyUrl": "https://www.workday.com/saml/acs",
            "microsoftEntraIdentifier": (
                "https://sts.windows.net/"
                "00000000-0000-0000-0000-000000000000/"
            ),
            "loginUrl": (
                "https://login.microsoftonline.com/"
                "00000000-0000-0000-0000-000000000000/saml2"
            ),
            "certificate": {
                "thumbprint": "AA11",
                "validFrom": "2026-01-01T00:00:00Z",
                "validTo": "2027-01-01T00:00:00Z",
            },
            "checks": _entra_checks(),
        },
    )

    assert result["identifiers"]["entraAppId"] == app_id
    assert result["identifiers"]["entraAppIdUri"] == f"api://{app_id}"
    assert result["evidence"]["checks"]["samlSigningOption"] == {
        "outcome": "confirmed",
        "provenance": "administrator-attestation",
        "observedValue": "Sign SAML response and assertion",
    }


def test_entra_verification_accepts_reduced_guided_evidence():
    app_id = "44444444-4444-4444-4444-444444444444"

    result = validate_entra_verification(
        _state(),
        {
            "selectedDirectory": {"displayName": "Contoso"},
            "application": {
                "displayName": "Workday exact",
                "appId": app_id,
            },
            "replyUrl": "https://www.workday.com/saml/acs",
            "certificate": {
                "thumbprint": "AA11",
                "validTo": "2027-01-01T00:00:00Z",
            },
            "checks": _entra_checks(),
        },
    )

    assert result["identifiers"]["entraAppIdUri"] == f"api://{app_id}"
    assert result["identifiers"]["microsoftEntraIdentifier"].startswith(
        "https://sts.windows.net/"
    )
    assert "entraAppObjectId" not in result["identifiers"]
    assert "entraServicePrincipalId" not in result["identifiers"]
    assert "scopeGuid" not in result["identifiers"]
    assert "validFrom" not in result["identifiers"]["signingCertificate"]
    assert "certificateValidFrom" not in result["partialEvidence"]
    assert result["partialEvidence"]["applicationIdentifierUris"] == [
        "http://www.workday.com/contoso_impl",
        f"api://{app_id}",
    ]


def test_entra_verification_binds_reply_url_to_graph_evidence():
    with pytest.raises(
        WorkdayConnectContractError,
        match="not present",
    ):
        validate_entra_verification(
            _state(),
            _entra_verification(
                reply_urls=["https://www.workday.com/other/acs"],
            ),
        )


def test_saml_signing_option_records_the_exact_required_value():
    with pytest.raises(
        WorkdayConnectContractError,
        match="Sign SAML response and assertion",
    ):
        contracts._normalize_entra_check(
            "samlSigningOption",
            {
                "outcome": "confirmed",
                "provenance": "administrator-attestation",
                "observedValue": "Sign SAML assertion only",
            },
        )


def test_entra_verification_rejects_a_different_graph_tenant():
    app_id = "44444444-4444-4444-4444-444444444444"
    with pytest.raises(
        WorkdayConnectContractError,
        match="does not match",
    ):
        validate_entra_verification(
            _state(),
            {
                "tenantId": "99999999-9999-9999-9999-999999999999",
                "application": {
                    "displayName": "Workday exact",
                    "appId": app_id,
                    "objectId": "55555555-5555-5555-5555-555555555555",
                    "servicePrincipalId": ("66666666-6666-6666-6666-666666666666"),
                    "identifierUris": [
                        "http://www.workday.com/contoso_impl",
                        f"api://{app_id}",
                    ],
                },
                "scopeGuid": "77777777-7777-7777-7777-777777777777",
                "certificate": {
                    "thumbprint": "AA11",
                    "validFrom": "2026-01-01T00:00:00Z",
                    "validTo": "2027-01-01T00:00:00Z",
                },
                "checks": _entra_checks(),
            },
        )


def test_entra_verification_rejects_provenance_free_checks():
    app_id = "44444444-4444-4444-4444-444444444444"
    checks = _entra_checks()
    checks["nameId"] = {"outcome": "verified"}

    with pytest.raises(
        WorkdayConnectContractError,
        match="lacks provenance",
    ):
        validate_entra_verification(
            _state(),
            {
                "tenantId": "00000000-0000-0000-0000-000000000000",
                "application": {
                    "displayName": "Workday exact",
                    "appId": app_id,
                    "objectId": "55555555-5555-5555-5555-555555555555",
                    "servicePrincipalId": ("66666666-6666-6666-6666-666666666666"),
                    "identifierUris": [
                        "http://www.workday.com/contoso_impl",
                        f"api://{app_id}",
                    ],
                },
                "scopeGuid": "77777777-7777-7777-7777-777777777777",
                "certificate": {
                    "thumbprint": "AA11",
                    "validFrom": "2026-01-01T00:00:00Z",
                    "validTo": "2027-01-01T00:00:00Z",
                },
                "checks": checks,
            },
        )


def test_entra_verification_rejects_unused_check_fields():
    app_id = "44444444-4444-4444-4444-444444444444"
    checks = _entra_checks()
    checks["nameId"]["details"] = "not part of the evidence contract"

    with pytest.raises(
        WorkdayConnectContractError,
        match="unsupported fields",
    ):
        validate_entra_verification(
            _state(),
            {
                "tenantId": "00000000-0000-0000-0000-000000000000",
                "application": {
                    "displayName": "Workday exact",
                    "appId": app_id,
                    "objectId": "55555555-5555-5555-5555-555555555555",
                    "servicePrincipalId": ("66666666-6666-6666-6666-666666666666"),
                    "identifierUris": [
                        "http://www.workday.com/contoso_impl",
                        f"api://{app_id}",
                    ],
                },
                "scopeGuid": "77777777-7777-7777-7777-777777777777",
                "certificate": {
                    "thumbprint": "AA11",
                    "validFrom": "2026-01-01T00:00:00Z",
                    "validTo": "2027-01-01T00:00:00Z",
                },
                "checks": checks,
            },
        )


def test_entra_verification_accepts_guided_admin_attestation():
    verification = _entra_verification()
    verification["checks"]["adminConsent"] = {
        "outcome": "confirmed",
        "provenance": "administrator-attestation",
    }

    result = validate_entra_verification(_state(), verification)

    assert result["evidence"]["checks"]["adminConsent"] == {
        "outcome": "confirmed",
        "provenance": "administrator-attestation",
    }


def test_workday_packet_uses_service_provider_id_not_app_id_uri():
    state = _state()
    state["identifiers"].update(
        {
            "workdaySamlEntityId": "http://www.workday.com/contoso_impl",
            "entraAppIdUri": ("api://44444444-4444-4444-4444-444444444444"),
            "signingCertificate": {
                "thumbprint": "AA11",
                "validTo": "2027-01-01T00:00:00Z",
            },
        }
    )
    packet = build_workday_admin_packet(state)

    assert packet["referenceValues"]["serviceProviderId"] == (
        "http://www.workday.com/contoso_impl"
    )
    assert packet["referenceValues"]["entraApplicationIdUri"].startswith("api://")
    assert packet["referenceValues"]["expectedIdentityProviderIssuer"] == (
        "https://sts.windows.net/00000000-0000-0000-0000-000000000000/"
    )
    assert "certificateValidFrom" not in packet["referenceValues"]
    assert packet["referenceValues"]["certificateValidTo"] == "2027-01-01"
    provider_question = packet["identityProviderQuestion"]
    assert "sign-in provider" in provider_question["question"]
    assert any("Microsoft Entra ID" in option for option in provider_question["options"])
    assert any("Okta" in option for option in provider_question["options"])
    assert any("Ping Identity" in option for option in provider_question["options"])
    assert "Another sign-in provider" in provider_question["options"]
    assert "No enabled SAML row" in provider_question["options"]
    assert "I'm not sure" in provider_question["options"]
    certificate_question = packet["certificateSelectionQuestion"]
    assert "Which certificate is selected" in certificate_question["question"]
    assert (
        "The new certificate created from the Entra Base64 file"
        in certificate_question["options"]
    )
    assert (
        "A different existing Workday certificate"
        in certificate_question["options"]
    )
    assert "No certificate is selected" in certificate_question["options"]
    assert "I'm not sure" in certificate_question["options"]
    identifier_question = packet["issuerConfirmationQuestion"]
    assert "identity-provider SSO service URL" in identifier_question["question"]
    assert "sign-on redirect URL" in identifier_question["question"]
    assert "http://www.workday.com/contoso_impl" in identifier_question["question"]
    assert "Yes, all four values match exactly" in identifier_question["options"]
    assert "expiration date matches exactly" in (
        packet["certificateValidityQuestion"]["options"][0]
    )
    assert "customerTaskList" not in packet
    assert packet["actions"][0].startswith(
        "Identify which sign-in provider the enabled Workday SAML row"
    )
    assert any("REST and SOAP hosts" in action for action in packet["actions"])
    assert "certificateName" not in packet["responseForm"]["required"]
    assert "client secrets" in packet["responseForm"]["note"]
    assert packet["engagementQuestion"].startswith("Have you looped in")
    assert packet["completionQuestion"].startswith("Has the Workday")
    assert any(
        "OAuth client ID" in item for item in packet["informationToReturn"]
    )


def test_workday_packet_rejects_identifier_aliasing():
    state = _state()
    state["identifiers"].update(
        {
            "workdaySamlEntityId": "http://www.workday.com/contoso_impl",
            "entraAppIdUri": "http://www.workday.com/contoso_impl",
            "signingCertificate": {
                "validFrom": "2026-01-01",
                "validTo": "2027-01-01",
            },
        }
    )

    with pytest.raises(WorkdayConnectContractError, match="remain distinct"):
        build_workday_admin_packet(state)


def test_workday_packet_rejects_tenant_drift():
    state = _state()
    state["identifiers"].update(
        {
            "workdaySamlEntityId": "http://www.workday.com/other",
            "entraAppIdUri": ("api://44444444-4444-4444-4444-444444444444"),
            "signingCertificate": {
                "validFrom": "2026-01-01",
                "validTo": "2027-01-01",
            },
        }
    )

    with pytest.raises(WorkdayConnectContractError, match="does not match"):
        build_workday_admin_packet(deepcopy(state))


def test_workday_admin_response_validates_exact_endpoints():
    state = _state()
    state["identifiers"]["signingCertificate"] = {
        "thumbprint": "AA11",
        "validFrom": "2026-01-01T00:00:00Z",
        "validTo": "2027-01-01T00:00:00Z",
    }
    result = validate_workday_admin_response(
        state,
        {
            "identityProviderOutcome": "verified-entra-issuer",
            "enabledServiceProviderId": ("http://www.workday.com/contoso_impl"),
            "certificateSelectionOutcome": "entra-signing-certificate-selected",
            "certificateValidityOutcome": (
                "matches-verified-entra-certificate"
            ),
            "oauthClientId": "safe-client-id",
            "apiClientOutcome": "existing-client-verified",
            "clientGrantType": "saml-bearer",
            "includeWorkdayOwnedScope": "yes",
            "identityProviderSsoServiceUrl": (
                "https://login.microsoftonline.com/"
                "00000000-0000-0000-0000-000000000000/saml2"
            ),
            "signOnRedirectUrl": "https://www.workday.com/saml/acs",
            "oauthTokenUrl": (
                "https://example.workday.com/ccx/oauth2/contoso_impl/token"
            ),
            "restBaseUrl": "https://example.workday.com/ccx/api",
            "soapBaseUrl": "https://example.workday.com/ccx/service",
            "authenticationPolicyOutcome": "existing-active-policy",
            "networkReadinessOutcome": "confirmed-hosts-allowed",
            "rolloutType": "limited-or-test",
            "employeeSecurityGroup": "ESS Workday Pilot Employees",
            "publicWorkerReportsOutcome": "get-permission-verified",
            "integrationPermissionsGetOutcome": "get-permission-verified",
            "functionalAreaScopes": [
                "Core Payroll",
                "Organizations and Roles",
                "Staffing",
                "Time Off and Leave",
            ],
            "optionalDomains": [],
            "authorizationOutcome": "verified",
        },
    )

    assert result["endpoints"]["restBaseUrl"].endswith("/ccx/api")
    assert result["evidence"]["activeIdentityProviderIssuer"] == (
        "https://sts.windows.net/00000000-0000-0000-0000-000000000000/"
    )
    assert "certificateName" not in result["evidence"]
    assert result["evidence"]["networkReadinessOutcome"] == ("confirmed-hosts-allowed")
    assert result["evidence"]["rolloutType"] == "limited-or-test"
    assert result["evidence"]["employeeSecurityGroup"] == (
        "ESS Workday Pilot Employees"
    )


def test_workday_admin_response_enforces_limited_rollout_group():
    with pytest.raises(
        WorkdayConnectContractError,
        match="cannot use All Employees",
    ):
        validate_workday_admin_response(
            _workday_state(),
            _workday_response(employeeSecurityGroup="All Employees"),
        )


def test_workday_admin_response_requires_exact_functional_area_scopes():
    with pytest.raises(
        WorkdayConnectContractError,
        match="must contain exactly",
    ):
        validate_workday_admin_response(
            _workday_state(),
            _workday_response(
                functionalAreaScopes=["Staffing", "Personal Data"],
            ),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("clientGrantType", "authorization-code", "saml-bearer"),
        ("includeWorkdayOwnedScope", "no", "must be yes"),
        (
            "identityProviderSsoServiceUrl",
            "https://login.microsoftonline.com/other/saml2",
            "does not match",
        ),
        (
            "signOnRedirectUrl",
            "https://www.workday.com/other/acs",
            "does not match",
        ),
    ],
)
def test_workday_admin_response_enforces_api_client_and_saml_mapping(
    field,
    value,
    message,
):
    with pytest.raises(WorkdayConnectContractError, match=message):
        validate_workday_admin_response(
            _workday_state(),
            _workday_response(**{field: value}),
        )


def test_workday_admin_response_requires_bounded_authorization_retest():
    response = _workday_response(
        authorizationOutcome="task-not-authorized-remediated",
    )
    with pytest.raises(
        WorkdayConnectContractError,
        match="authorizationRemediationDomain",
    ):
        validate_workday_admin_response(_workday_state(), response)

    result = validate_workday_admin_response(
        _workday_state(),
        {
            **response,
            "authorizationRemediationDomain": (
                "Worker Data: Public Worker Reports"
            ),
            "authorizationRemediationScenario": (
                "Signed-in employee profile read"
            ),
            "authorizationRetestOutcome": "verified-after-remediation",
        },
    )

    assert result["evidence"]["authorizationRetestOutcome"] == (
        "verified-after-remediation"
    )


def test_partial_workday_evidence_keeps_valid_siblings() -> None:
    result = validate_administrator_partial_evidence(
        _state(),
        "workday-admin",
        {
            "oauthClientId": "safe-client-id",
            "oauthTokenUrl": "https://example.workday.com/wrong",
            "rolloutType": "limited-or-test",
        },
    )

    assert result["validFields"] == {
        "oauthClientId": "safe-client-id",
        "rolloutType": "limited-or-test",
    }
    assert set(result["fieldErrors"]) == {"oauthTokenUrl"}


def test_partial_administrator_evidence_rejects_secret_material() -> None:
    result = validate_administrator_partial_evidence(
        _state(),
        "entra",
        {
            "certificateThumbprint": (
                "-----BEGIN PRIVATE KEY-----\nnot-safe"
            ),
        },
    )

    assert result["validFields"] == {}
    assert "secret or certificate material" in (
        result["fieldErrors"]["certificateThumbprint"]
    )


def test_workday_admin_response_rejects_certificate_date_drift():
    state = _state()
    state["identifiers"]["signingCertificate"] = {
        "thumbprint": "AA11",
        "validFrom": "2026-01-01T00:00:00Z",
        "validTo": "2027-01-01T00:00:00Z",
    }

    with pytest.raises(
        WorkdayConnectContractError,
        match="conflicts",
    ):
        validate_workday_admin_response(
            state,
            {
                "identityProviderOutcome": "verified-entra-issuer",
                "enabledServiceProviderId": ("http://www.workday.com/contoso_impl"),
                "certificateSelectionOutcome": (
                    "entra-signing-certificate-selected"
                ),
                "certificateValidityOutcome": (
                    "matches-verified-entra-certificate"
                ),
                "certificateValidFrom": "2026-01-01",
                "certificateValidTo": "2028-01-01",
                "oauthClientId": "safe-client-id",
                "apiClientOutcome": "existing-client-verified",
                "clientGrantType": "saml-bearer",
                "includeWorkdayOwnedScope": "yes",
                "identityProviderSsoServiceUrl": (
                    "https://login.microsoftonline.com/"
                    "00000000-0000-0000-0000-000000000000/saml2"
                ),
                "signOnRedirectUrl": "https://www.workday.com/saml/acs",
                "oauthTokenUrl": (
                    "https://example.workday.com/ccx/oauth2/contoso_impl/token"
                ),
                "restBaseUrl": "https://example.workday.com/ccx/api",
                "soapBaseUrl": "https://example.workday.com/ccx/service",
                "authenticationPolicyOutcome": "existing-active-policy",
                "networkReadinessOutcome": "confirmed-hosts-allowed",
            },
        )


def test_workday_admin_response_rejects_conflicting_confirmed_defaults():
    state = _state()
    state["identifiers"]["signingCertificate"] = {
        "thumbprint": "AA11",
        "validFrom": "2026-01-01T00:00:00Z",
        "validTo": "2027-01-01T00:00:00Z",
    }
    response = {
        "identityProviderOutcome": "verified-entra-issuer",
        "enabledServiceProviderId": "http://www.workday.com/contoso_impl",
        "certificateSelectionOutcome": "entra-signing-certificate-selected",
        "certificateValidityOutcome": "matches-verified-entra-certificate",
        "oauthClientId": "safe-client-id",
        "apiClientOutcome": "existing-client-verified",
        "clientGrantType": "saml-bearer",
        "includeWorkdayOwnedScope": "yes",
        "identityProviderSsoServiceUrl": (
            "https://login.microsoftonline.com/"
            "00000000-0000-0000-0000-000000000000/saml2"
        ),
        "signOnRedirectUrl": "https://www.workday.com/saml/acs",
        "oauthTokenUrl": (
            "https://example.workday.com/ccx/oauth2/contoso_impl/token"
        ),
        "restBaseUrl": "https://example.workday.com/ccx/api",
        "soapBaseUrl": "https://example.workday.com/ccx/service",
        "authenticationPolicyOutcome": "existing-active-policy",
        "networkReadinessOutcome": "confirmed-hosts-allowed",
    }

    with pytest.raises(WorkdayConnectContractError, match="Issuer conflicts"):
        validate_workday_admin_response(
            state,
            {
                **response,
                "activeIdentityProviderIssuer": "https://sts.windows.net/other/",
            },
        )

    with pytest.raises(WorkdayConnectContractError, match="Valid To date conflicts"):
        validate_workday_admin_response(
            state,
            {
                **response,
                "certificateValidTo": "2028-01-01",
            },
        )


def test_workday_admin_rejects_unused_response_fields():
    state = _state()
    state["identifiers"]["signingCertificate"] = {
        "thumbprint": "AA11",
        "validFrom": "2026-01-01T00:00:00Z",
        "validTo": "2027-01-01T00:00:00Z",
    }

    with pytest.raises(
        WorkdayConnectContractError,
        match="unsupported fields",
    ):
        validate_workday_admin_response(
            state,
            {
                "activeIdentityProviderIssuer": "https://sts.example/",
                "enabledServiceProviderId": ("http://www.workday.com/contoso_impl"),
                "certificateName": "ESS Workday Entra signing certificate",
                "certificateValidFrom": "2026-01-01",
                "certificateValidTo": "2027-01-01",
                "oauthClientId": "safe-client-id",
                "oauthTokenUrl": (
                    "https://example.workday.com/ccx/oauth2/contoso_impl/token"
                ),
                "restBaseUrl": "https://example.workday.com/ccx/api",
                "soapBaseUrl": "https://example.workday.com/ccx/service",
                "authenticationPolicyOutcome": "existing-active-policy",
                "networkReadinessOutcome": "confirmed-hosts-allowed",
                "notes": "not part of the evidence contract",
            },
        )


def test_agent_binding_and_employee_evidence_are_strict():
    state = _state()
    state["scope"].update(
        {
            "environmentId": "environment-id",
            "agent": {"botId": "bot-id"},
        }
    )
    state["operators"]["powerPlatformMaker"] = {"username": "maker@example.com"}
    assert (
        validate_agent_binding_evidence(
            state,
            {
                "environmentId": "environment-id",
                "botId": "bot-id",
                "makerUsername": "maker@example.com",
                "workdayTopics": {
                    "expected": 23,
                    "verified": 23,
                    "active": 23,
                    "blockingDiagnostics": [],
                },
                "flowAttachment": {
                    "outcome": "maker-confirmed",
                    "botId": "bot-id",
                    "flowNames": [
                        "ESS Workday Runtime",
                        "ESS Workday Runtime REST Execution",
                    ],
                    "parameterSharingOutcome": (
                        "enabled-for-exposed-connections"
                    ),
                },
            },
        )["workdayTopics"]["active"]
        == 23
    )

    diagnostic_evidence = validate_agent_binding_evidence(
        state,
        {
            "environmentId": "environment-id",
            "botId": "bot-id",
            "makerUsername": "maker@example.com",
            "workdayTopics": {
                "expected": 23,
                "verified": 23,
                "active": 23,
                "blockingDiagnostics": [{"errorCode": "NotFound"}],
            },
            "flowAttachment": {
                "outcome": "maker-confirmed",
                "botId": "bot-id",
                "flowNames": [
                    "ESS Workday Runtime",
                    "ESS Workday Runtime REST Execution",
                ],
                "parameterSharingOutcome": (
                    "enabled-for-exposed-connections"
                ),
            },
        },
    )
    assert diagnostic_evidence["workdayTopics"]["blockingDiagnostics"] == [
        {"errorCode": "NotFound"}
    ]

    with pytest.raises(WorkdayConnectContractError, match="unsupported fields"):
        validate_employee_evidence(
            {
                "scenarioName": "Read-only scenario",
                "testUserCategory": "standard employee",
                "timestamp": "2026-09-25T00:00:00Z",
                "outcome": "passed",
                "employeeName": "not allowed",
            }
        )


def test_entra_check_outcome_must_match_provenance():
    app_id = "44444444-4444-4444-4444-444444444444"
    checks = _entra_checks()
    checks["nameId"] = {
        "outcome": "confirmed",
        "provenance": "microsoft-graph",
    }

    with pytest.raises(
        WorkdayConnectContractError,
        match="does not match its provenance",
    ):
        validate_entra_verification(
            _state(),
            {
                "tenantId": "00000000-0000-0000-0000-000000000000",
                "application": {
                    "displayName": "Workday exact",
                    "appId": app_id,
                    "objectId": "object-id",
                    "servicePrincipalId": "service-principal-id",
                    "identifierUris": [
                        "http://www.workday.com/contoso_impl",
                        f"api://{app_id}",
                    ],
                },
                "scopeGuid": "scope-guid",
                "certificate": {
                    "thumbprint": "ABC123",
                    "validFrom": "2026-01-01T00:00:00Z",
                    "validTo": "2027-01-01T00:00:00Z",
                },
                "checks": checks,
            },
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "oauthTokenUrl",
            "https://example.workday.com/ccx/oauth2/other/token",
            "OAuth token URL must end exactly",
        ),
        (
            "restBaseUrl",
            "https://example.workday.com/prefix/ccx/api",
            "REST base URL must end exactly",
        ),
        (
            "soapBaseUrl",
            "https://example.workday.com/ccx/service/contoso_impl",
            "SOAP base URL must end exactly",
        ),
    ],
)
def test_workday_admin_rejects_endpoint_path_drift(
    field,
    value,
    message,
):
    state = _state()
    state["identifiers"]["signingCertificate"] = {
        "thumbprint": "ABC123",
        "validFrom": "2026-01-01",
        "validTo": "2027-01-01",
    }
    response = {
        "identityProviderOutcome": "verified-entra-issuer",
        "enabledServiceProviderId": ("http://www.workday.com/contoso_impl"),
        "certificateSelectionOutcome": (
            "entra-signing-certificate-selected"
        ),
        "certificateValidityOutcome": (
            "matches-verified-entra-certificate"
        ),
        "oauthClientId": "safe-client-id",
        "oauthTokenUrl": ("https://example.workday.com/ccx/oauth2/contoso_impl/token"),
        "restBaseUrl": "https://example.workday.com/ccx/api",
        "soapBaseUrl": "https://example.workday.com/ccx/service",
        "authenticationPolicyOutcome": "existing-active-policy",
        "networkReadinessOutcome": "confirmed-hosts-allowed",
    }
    response[field] = value

    with pytest.raises(WorkdayConnectContractError, match=message):
        validate_workday_admin_response(state, response)


def test_workday_admin_rejects_legacy_identity_provider_evidence():
    state = _state()
    state["identifiers"]["signingCertificate"] = {
        "thumbprint": "ABC123",
        "validFrom": "2026-01-01",
        "validTo": "2027-01-01",
    }

    with pytest.raises(
        WorkdayConnectContractError,
        match="identityProviderOutcome",
    ):
        validate_workday_admin_response(
            state,
            {
                "activeIdentityProviderIssuer": "https://wrong.example/",
                "enabledServiceProviderId": (
                    "http://www.workday.com/contoso_impl"
                ),
                "certificateName": "Unrelated certificate",
                "certificateValidFrom": "2026-01-01",
                "certificateValidTo": "2027-01-01",
                "oauthClientId": "safe-client-id",
                "oauthTokenUrl": (
                    "https://example.workday.com/ccx/oauth2/"
                    "contoso_impl/token"
                ),
                "restBaseUrl": "https://example.workday.com/ccx/api",
                "soapBaseUrl": (
                    "https://example.workday.com/ccx/service"
                ),
                "authenticationPolicyOutcome": "existing-active-policy",
                "networkReadinessOutcome": "confirmed-hosts-allowed",
            },
        )


def test_workday_admin_rejects_non_workday_or_mixed_endpoint_hosts():
    state = _state()
    state["identifiers"]["signingCertificate"] = {
        "thumbprint": "ABC123",
        "validFrom": "2026-01-01",
        "validTo": "2027-01-01",
    }
    response = {
        "identityProviderOutcome": "verified-entra-issuer",
        "enabledServiceProviderId": "http://www.workday.com/contoso_impl",
        "certificateSelectionOutcome": "entra-signing-certificate-selected",
        "certificateValidityOutcome": "matches-verified-entra-certificate",
        "oauthClientId": "safe-client-id",
        "oauthTokenUrl": (
            "https://attacker.example/ccx/oauth2/contoso_impl/token"
        ),
        "restBaseUrl": "https://example.workday.com/ccx/api",
        "soapBaseUrl": "https://example.workday.com/ccx/service",
        "authenticationPolicyOutcome": "existing-active-policy",
        "networkReadinessOutcome": "confirmed-hosts-allowed",
    }

    with pytest.raises(WorkdayConnectContractError, match="Workday-owned"):
        validate_workday_admin_response(state, response)

    response["oauthTokenUrl"] = (
        "https://other.workday.com/ccx/oauth2/contoso_impl/token"
    )
    with pytest.raises(WorkdayConnectContractError, match="same verified"):
        validate_workday_admin_response(state, response)

    response["oauthTokenUrl"] = (
        "https://example.workday.com:notaport/ccx/oauth2/"
        "contoso_impl/token"
    )
    with pytest.raises(WorkdayConnectContractError, match="HTTPS URL"):
        validate_workday_admin_response(state, response)


def test_employee_evidence_rejects_maker_and_invalid_timestamp():
    with pytest.raises(WorkdayConnectContractError, match="non-maker"):
        validate_employee_evidence(
            {
                "scenarioName": "Read-only scenario",
                "testUserCategory": "Environment Maker",
                "timestamp": "2026-09-25T00:00:00Z",
                "outcome": "passed",
            }
        )


def test_employee_failure_evidence_derives_safe_canonical_fields():
    for remediation_id, contract in (
        contracts.EMPLOYEE_VALIDATION_REMEDIATIONS.items()
    ):
        evidence = {
            "remediationId": remediation_id.lower(),
            "timestamp": "2026-09-25T00:00:00+00:00",
        }
        if remediation_id == "WD-E2E-999":
            evidence["failureSurface"] = "agent-chat"
        assert validate_employee_failure_evidence(
            evidence
        ) == {
            "remediationId": remediation_id,
            "failureCategory": contract["failureCategory"],
            "failureSurface": (
                "agent-chat"
                if remediation_id == "WD-E2E-999"
                else contract["failureSurface"]
            ),
            "timestamp": "2026-09-25T00:00:00Z",
            "remediation": contract["remediation"],
        }


def test_employee_failure_evidence_migrates_legacy_files():
    assert validate_employee_failure_evidence(
        {
            "failureCategory": "workday-access-denied",
            "timestamp": "2026-09-25T00:00:00Z",
            "remediation": "Customer-specific wording is discarded.",
        }
    ) == {
        "remediationId": "WD-E2E-006",
        "failureCategory": "workday-access",
        "failureSurface": "workday-response",
        "timestamp": "2026-09-25T00:00:00Z",
        "remediation": (
            contracts.EMPLOYEE_VALIDATION_REMEDIATIONS[
                "WD-E2E-006"
            ]["remediation"]
        ),
    }
    assert validate_employee_failure_evidence(
        {
            "failureCategory": "previous-custom-category",
            "timestamp": "2026-09-25T00:00:00Z",
            "remediation": "Visit https://customer.example/employee.",
        }
    ) == {
        "remediationId": "WD-E2E-999",
        "failureCategory": "unknown",
        "failureSurface": "other",
        "timestamp": "2026-09-25T00:00:00Z",
        "remediation": (
            contracts.EMPLOYEE_VALIDATION_REMEDIATIONS[
                "WD-E2E-999"
            ]["remediation"]
        ),
    }


def test_employee_failure_evidence_ignores_redundant_caller_text():
    assert validate_employee_failure_evidence(
        {
            "remediationId": "WD-E2E-006",
            "failureCategory": "network",
            "timestamp": "2026-09-25T00:00:00Z",
            "remediation": "Visit https://customer.example/employee.",
        }
    ) == {
        "remediationId": "WD-E2E-006",
        "failureCategory": "workday-access",
        "failureSurface": "workday-response",
        "timestamp": "2026-09-25T00:00:00Z",
        "remediation": (
            contracts.EMPLOYEE_VALIDATION_REMEDIATIONS[
                "WD-E2E-006"
            ]["remediation"]
        ),
    }


def test_employee_failure_evidence_rejects_unsafe_fields():
    with pytest.raises(WorkdayConnectContractError, match="unsupported fields"):
        validate_employee_failure_evidence(
            {
                "remediationId": "WD-E2E-006",
                "timestamp": "2026-09-25T00:00:00Z",
                "accessToken": "must-not-be-recorded",
            }
        )

    with pytest.raises(WorkdayConnectContractError, match="must be one of"):
        validate_employee_failure_evidence(
            {
                "remediationId": "WD-E2E-123",
                "timestamp": "2026-09-25T00:00:00Z",
            }
        )

    with pytest.raises(
        WorkdayConnectContractError,
        match="accepted only for WD-E2E-999",
    ):
        validate_employee_failure_evidence(
            {
                "remediationId": "WD-E2E-006",
                "failureSurface": "workday-response",
                "timestamp": "2026-09-25T00:00:00Z",
            }
        )

    with pytest.raises(
        WorkdayConnectContractError,
        match="failureSurface must be one of",
    ):
        validate_employee_failure_evidence(
            {
                "remediationId": "WD-E2E-999",
                "failureSurface": "https://customer.example/employee",
                "timestamp": "2026-09-25T00:00:00Z",
            }
        )

    with pytest.raises(WorkdayConnectContractError, match="is required"):
        validate_employee_failure_evidence(
            {
                "remediationId": "WD-E2E-999",
                "timestamp": "2026-09-25T00:00:00Z",
            }
        )

    with pytest.raises(WorkdayConnectContractError, match="ISO-8601"):
        validate_employee_evidence(
            {
                "scenarioName": "Read-only scenario",
                "testUserCategory": "non-maker employee",
                "timestamp": "not-a-time",
                "outcome": "passed",
            }
        )
