# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Mock response builders for Microsoft Graph v1.0.

# ─────────────────────────────────────────────────────────────────
# MOCK_STATUS = "validatable"
#
# Backed by the publicly-fetchable Graph CSDL (no auth required).
# Each builder's response shape is verified against an EntityType in
# the schema; the cited MS Learn operation page provides the example
# response body Microsoft itself maintains.
#
# Schema:  https://graph.microsoft.com/v1.0/$metadata
# Docs:    https://learn.microsoft.com/graph/api/{operation}
# Tier:    validatable (see tests/fixtures/cassettes/INDEX.md
#          "API tier registry")
# ─────────────────────────────────────────────────────────────────

Used by FlightCheck integration tests for any check that reads tenant
identity, users, directory roles, Conditional Access policies, or
service principals via
solutions/ess-maker-skills/scripts/flightcheck/graph_client.py.

References:
- Graph organization: https://learn.microsoft.com/graph/api/organization-list
- Graph users: https://learn.microsoft.com/graph/api/user-list
- Graph directoryRoles: https://learn.microsoft.com/graph/api/directoryrole-list
- Graph CA policies: https://learn.microsoft.com/graph/api/conditionalaccessroot-list-policies
- Production source: solutions/ess-maker-skills/scripts/flightcheck/graph_client.py
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# Validation status — read by tests/conftest.py:require_validated_mock().
MOCK_STATUS = "validatable"
MOCK_SCHEMA_SOURCE = "https://graph.microsoft.com/v1.0/$metadata"

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

MOCK_TENANT_ID = "00000000-0000-0000-0000-000000001111"
MOCK_USER_ID = "00000000-0000-0000-0000-000000002222"


# ────────────────────────────────────────────────────────────────────────
# Payload builders
# ────────────────────────────────────────────────────────────────────────


def organization(
    *,
    tenant_id: str = MOCK_TENANT_ID,
    display_name: str = "Mock Tenant",
) -> dict[str, Any]:
    """Build a single Graph /organization record.

    Cited consumers:
      - flightcheck/graph_client.py:169-172 (get_organization).

    Source (validatable):
      Schema: https://graph.microsoft.com/v1.0/$metadata
              EntityType Name="organization"
      Docs:   https://learn.microsoft.com/graph/api/organization-get
    """
    return {
        "id": tenant_id,
        "deletedDateTime": None,
        "businessPhones": [],
        "city": "Mocktown",
        "country": None,
        "countryLetterCode": "MC",
        "createdDateTime": "2024-07-29T19:23:19Z",
        "defaultUsageLocation": None,
        "displayName": display_name,
        "isMultipleDataLocationsForServicesEnabled": None,
        "marketingNotificationEmails": [],
        "onPremisesLastSyncDateTime": None,
        "onPremisesSyncEnabled": None,
        "partnerTenantType": None,
        "postalCode": "00000",
        "preferredLanguage": "en",
        "securityComplianceNotificationMails": [],
        "securityComplianceNotificationPhones": [],
        "state": "mc",
        "street": "1 Mock Street",
        "technicalNotificationMails": ["mock.user@contoso.com"],
        "tenantType": "AAD",
        "directorySizeQuota": {"used": 4744, "total": 300000},
        "privacyProfile": None,
        "verifiedDomains": [
            {
                "capabilities": "Email,OfficeCommunicationsOnline",
                "isDefault": True,
                "isInitial": True,
                "name": "mocktenant.onmicrosoft.com",
                "type": "Managed",
            }
        ],
    }


def license_detail(
    *,
    sku_id: str = "00000000-0000-0000-0000-0000000000fa",
    sku_part_number: str = "FLOW_PER_USER",
    service_plans: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a single Graph licenseDetails record.

    Consumed by LIC-FLOW-002 via
    flightcheck/graph_client.py:get_user_license_details
    (``GET /users/{id}/licenseDetails``).

    Source (validatable):
      Schema: https://graph.microsoft.com/v1.0/$metadata
              EntityType Name="licenseDetails" (skuId Edm.Guid,
              skuPartNumber Edm.String, servicePlans
              Collection(servicePlanInfo))
      Docs:   https://learn.microsoft.com/graph/api/user-list-licensedetails
    """
    if service_plans is None:
        service_plans = [{
            "servicePlanId": "00000000-0000-0000-0000-0000000000fb",
            "servicePlanName": sku_part_number,
            "provisioningStatus": "Success",
            "appliesTo": "User",
        }]
    return {
        "id": f"{sku_id}_detail",
        "skuId": sku_id,
        "skuPartNumber": sku_part_number,
        "servicePlans": service_plans,
    }


def user(
    *,
    user_id: str = MOCK_USER_ID,
    display_name: str = "Mock User",
    user_principal_name: str = "mock.user@contoso.com",
    job_title: str | None = "Mock Job Title",
) -> dict[str, Any]:
    """Build a single Graph /users record.

    Cited consumers:
      - flightcheck/graph_client.py:186-189 (get_users_sample).

    Source (validatable):
      Schema: https://graph.microsoft.com/v1.0/$metadata
              EntityType Name="user"
      Docs:   https://learn.microsoft.com/graph/api/user-get
    """
    return {
        "businessPhones": [],
        "displayName": display_name,
        "givenName": "Mock",
        "jobTitle": job_title,
        "mail": user_principal_name,
        "mobilePhone": None,
        "officeLocation": None,
        "preferredLanguage": "en-US",
        "surname": "User",
        "userPrincipalName": user_principal_name,
        "id": user_id,
    }


def directory_role(
    *,
    role_id: str = "00000000-0000-0000-0000-000000003001",
    display_name: str = "Mock Directory Role",
    role_template_id: str = "00000000-0000-0000-0000-000000003002",
) -> dict[str, Any]:
    """Build a single Graph /directoryRoles record.

    Cited consumers:
      - flightcheck/graph_client.py:174-180 (get_directory_roles, get_role_members).

    Source (validatable):
      Schema: https://graph.microsoft.com/v1.0/$metadata
              EntityType Name="directoryRole"
      Docs:   https://learn.microsoft.com/graph/api/directoryrole-get
    """
    return {
        "id": role_id,
        "deletedDateTime": None,
        "description": "Mock role description",
        "displayName": display_name,
        "roleTemplateId": role_template_id,
    }


def conditional_access_policy(
    *,
    policy_id: str = "00000000-0000-0000-0000-000000004001",
    display_name: str = "Mock CA Policy",
    state: str = "enabled",
) -> dict[str, Any]:
    """Build a single Graph /identity/conditionalAccess/policies record.

    Cited consumers:
      - flightcheck/graph_client.py:182-184 (get_conditional_access_policies).

    Source (validatable):
      Schema: https://graph.microsoft.com/v1.0/$metadata
              EntityType Name="conditionalAccessPolicy"
      Docs:   https://learn.microsoft.com/graph/api/conditionalaccesspolicy-get
    """
    return {
        "id": policy_id,
        "displayName": display_name,
        "state": state,
        "createdDateTime": "2025-01-01T00:00:00Z",
        "modifiedDateTime": "2025-01-01T00:00:00Z",
        "conditions": {
            "users": {"includeUsers": ["All"], "excludeUsers": []},
            "applications": {"includeApplications": ["All"]},
        },
        "grantControls": {
            "operator": "OR",
            "builtInControls": ["mfa"],
        },
    }


MOCK_WORKDAY_SP_ID = "00000000-0000-0000-0000-000000005001"
MOCK_WORKDAY_APP_ID = "00000000-0000-0000-0000-000000005002"
# The Entra gallery applicationTemplate id for the Workday SSO template.
# Real values are Microsoft-issued; this mock value is stable so tests
# can wire `applicationTemplateId` through the SP and the
# `/applicationTemplates` lookup consistently.
MOCK_WORKDAY_APP_TEMPLATE_ID = "00000000-0000-0000-0000-000000005401"


def service_principal(
    *,
    sp_id: str = MOCK_WORKDAY_SP_ID,
    app_id: str = MOCK_WORKDAY_APP_ID,
    display_name: str = "Workday",
    app_role_assignment_required: bool = True,
    account_enabled: bool = True,
    preferred_sso_mode: str | None = "saml",
    tags: Iterable[str] | None = None,
    login_url: str | None = "https://impl.workday.com/contoso/login-saml.htmld",
    service_principal_names: Iterable[str] | None = None,
    application_template_id: str | None = MOCK_WORKDAY_APP_TEMPLATE_ID,
    key_credentials: Iterable[Mapping[str, Any]] | None = None,
    preferred_token_signing_key_thumbprint: str | None = None,
) -> dict[str, Any]:
    """Build a single Graph /servicePrincipals record.

    Defaults represent a customer's federated Workday enterprise app —
    the shape both AUTH-005 (user-assignment) and AUTH-006 (SAML NameID
    alignment) expect to find. The ``service_principal_names``
    collection includes the SAML entity ID Workday's "SAML Identity
    Providers > Service Provider ID" field references — that's the
    join key AUTH-006 surfaces so the operator can identify which
    Entra app the Workday tenant is actually using.

    ``key_credentials`` and ``preferred_token_signing_key_thumbprint``
    are the certificate-related fields WD-CONN-102 (Workday SAML
    signing certificate health) reads. The defaults keep the existing
    test fixture shape (empty ``keyCredentials``, no preferred
    thumbprint) so this extension is non-breaking for AUTH-005 /
    AUTH-006 callers.

    Cited consumers:
      - flightcheck/graph_client.py (get_service_principals,
        get_workday_saml_service_principals).
      - flightcheck/checks/authentication.py (AUTH-005, AUTH-006).
      - flightcheck/checks/workday.py (WD-CONN-102).
      - flightcheck/checks/workday.py (WD-CONN-010 — single-Entra-tenant
        federation alignment; consumes the same SAML filter as AUTH-006
        plus the servicePrincipalNames entity-ID list).

    Source (validatable):
      Schema: https://graph.microsoft.com/v1.0/$metadata
              EntityType Name="servicePrincipal" — fields used:
                id (Edm.String)
                appId (Edm.String)
                displayName (Edm.String)
                appRoleAssignmentRequired (Edm.Boolean)  [AUTH-005]
                accountEnabled (Edm.Boolean)
                preferredSingleSignOnMode (Edm.String, nullable)  [AUTH-006]
                servicePrincipalNames (Collection(Edm.String))  [AUTH-006]
                tags (Collection(Edm.String))
                loginUrl (Edm.String, nullable)
                applicationTemplateId (Edm.String, nullable)  [AUTH-005]
                keyCredentials (Collection(keyCredential))  [WD-CONN-102]
                preferredTokenSigningKeyThumbprint (Edm.String, nullable)  [WD-CONN-102]
      Docs:   https://learn.microsoft.com/graph/api/serviceprincipal-get
              https://learn.microsoft.com/graph/api/resources/serviceprincipal?view=graph-rest-1.0
              Example response copied verbatim 2026-05.
    """
    if service_principal_names is None:
        # Default mirrors the entity-ID pattern Microsoft documents
        # for the Workday gallery app — see
        # https://learn.microsoft.com/en-us/entra/identity/saas-apps/workday-tutorial
        # step 5 (Reply URL pattern) and step 6 (Service Provider ID).
        service_principal_names = [
            app_id,
            "http://www.workday.com/contoso",
        ]
    record = {
        "id": sp_id,
        "deletedDateTime": None,
        "accountEnabled": account_enabled,
        "addIns": [],
        "alternativeNames": [],
        "appDisplayName": display_name,
        "appId": app_id,
        "appOwnerOrganizationId": MOCK_TENANT_ID,
        "appRoleAssignmentRequired": app_role_assignment_required,
        "appRoles": [],
        "displayName": display_name,
        "info": {
            "termsOfServiceUrl": None,
            "supportUrl": None,
            "privacyStatementUrl": None,
            "marketingUrl": None,
            "logoUrl": None,
        },
        "keyCredentials": (
            list(key_credentials) if key_credentials is not None else []
        ),
        "loginUrl": login_url,
        "logoutUrl": None,
        "oauth2PermissionScopes": [],
        "passwordCredentials": [],
        "preferredSingleSignOnMode": preferred_sso_mode,
        "preferredTokenSigningKeyThumbprint": preferred_token_signing_key_thumbprint,
        "publisherName": None,
        "replyUrls": [],
        "servicePrincipalNames": list(service_principal_names),
        "servicePrincipalType": "Application",
        "signInAudience": "AzureADMyOrg",
        "tags": list(tags) if tags is not None else ["WindowsAzureActiveDirectoryIntegratedApp"],
        "tokenEncryptionKeyId": None,
    }
    # applicationTemplateId is nullable per the CSDL — omit the key
    # entirely (matching Graph's typical response for non-gallery SPs)
    # when the caller explicitly passes None.
    if application_template_id is not None:
        record["applicationTemplateId"] = application_template_id
    return record


def key_credential(
    *,
    key_id: str = "00000000-0000-0000-0000-0000000060c1",
    custom_key_identifier: str | None = None,
    end_date_time: str = "2099-01-01T00:00:00Z",
    start_date_time: str = "2024-01-01T00:00:00Z",
    display_name: str | None = "Workday SAML Signing",
    usage: str = "Sign",
    type_: str = "AsymmetricX509Cert",
    key: str | None = None,
) -> dict[str, Any]:
    """Build a single Graph ``keyCredential`` complex-type record.

    ``customKeyIdentifier`` is the SHA-1 thumbprint of the DER-encoded
    X.509 cert, base64-encoded. WD-CONN-102 decodes this to the
    20-byte SHA-1 digest, then re-encodes it as colon-separated
    uppercase hex (the format Workday's "Edit Tenant Setup -
    Security → SAML Identity Providers" screen displays).

    When ``custom_key_identifier`` is omitted, a deterministic 20-byte
    digest derived from ``key_id`` is used so tests can compute the
    expected colon-hex thumbprint without hard-coding it.

    A Sign+Verify pair (the two halves Graph creates for one logical
    SAML signing cert) shares the same ``customKeyIdentifier`` — the
    test ``test_sign_verify_pair_coalesces`` relies on this contract.

    Cited consumers:
      - flightcheck/checks/workday.py (WD-CONN-102 —
        _check_saml_certificate_health).

    Source (validatable):
      Schema: https://graph.microsoft.com/v1.0/$metadata
              ComplexType Name="keyCredential" — fields used:
                keyId (Edm.Guid)
                customKeyIdentifier (Edm.Binary, nullable) — base64
                  in JSON wire format; WD-CONN-102 decodes to bytes
                endDateTime (Edm.DateTimeOffset, nullable)
                startDateTime (Edm.DateTimeOffset, nullable)
                displayName (Edm.String, nullable)
                usage (Edm.String, nullable) — "Sign" | "Verify" | ...
                type (Edm.String, nullable) —
                  "AsymmetricX509Cert" | "X509CertAndPassword" | ...
                key (Edm.Binary, nullable) — DER bytes, omitted from
                  list responses by Graph
      Docs:   https://learn.microsoft.com/graph/api/resources/keycredential
    """
    if custom_key_identifier is None:
        # Deterministic 20-byte SHA-1 digest derived from key_id so
        # the test can compute the expected display thumbprint
        # without hard-coding it. We use SHA-1 here to match the
        # actual contents of customKeyIdentifier (which IS the SHA-1
        # of the DER-encoded cert per the Graph schema doc).
        import base64
        import hashlib
        digest = hashlib.sha1(key_id.encode("ascii")).digest()
        custom_key_identifier = base64.b64encode(digest).decode("ascii")
    return {
        "customKeyIdentifier": custom_key_identifier,
        "displayName": display_name,
        "endDateTime": end_date_time,
        "key": key,
        "keyId": key_id,
        "startDateTime": start_date_time,
        "type": type_,
        "usage": usage,
    }


def app_role_assignment(
    *,
    assignment_id: str = "00000000-0000-0000-0000-000000005101",
    principal_id: str = "00000000-0000-0000-0000-000000005102",
    principal_display_name: str = "ESS Users",
    principal_type: str = "Group",
    resource_id: str = MOCK_WORKDAY_SP_ID,
    resource_display_name: str = "Workday",
    app_role_id: str = "00000000-0000-0000-0000-000000000000",
) -> dict[str, Any]:
    """Build a single Graph /servicePrincipals/{id}/appRoleAssignedTo record.

    ``principal_type`` is one of ``User``, ``Group``, ``ServicePrincipal``
    per the appRoleAssignment EntityType.

    Cited consumers:
      - flightcheck/graph_client.py (get_app_role_assignments)
      - flightcheck/checks/authentication.py (AUTH-005)

    Source (validatable):
      Schema: https://graph.microsoft.com/v1.0/$metadata
              EntityType Name="appRoleAssignment" — fields used:
                id (Edm.String)
                principalId (Edm.Guid)
                principalDisplayName (Edm.String)
                principalType (Edm.String)
                resourceId (Edm.Guid)
                resourceDisplayName (Edm.String)
                appRoleId (Edm.Guid)
      Docs:   https://learn.microsoft.com/graph/api/serviceprincipal-list-approleassignedto
              Example response copied verbatim 2026-05.
    """
    return {
        "id": assignment_id,
        "deletedDateTime": None,
        "appRoleId": app_role_id,
        "createdDateTime": "2025-01-01T00:00:00Z",
        "principalDisplayName": principal_display_name,
        "principalId": principal_id,
        "principalType": principal_type,
        "resourceDisplayName": resource_display_name,
        "resourceId": resource_id,
    }


def claims_mapping_policy(
    *,
    policy_id: str = "00000000-0000-0000-0000-000000005201",
    display_name: str = "Workday NameID -> employeeId",
    definition: list[str] | None = None,
) -> dict[str, Any]:
    """Build a single Graph claimsMappingPolicy record.

    The `definition` field is a list of JSON-encoded strings (Entra's
    own format — not nested JSON objects). AUTH-006 reads the first
    element to surface the override; if no policy is assigned, the
    application uses Entra's default
    (NameID = user.userPrincipalName).

    Cited consumers:
      - flightcheck/graph_client.py (get_claims_mapping_policies).
      - flightcheck/checks/authentication.py (AUTH-006).

    Source (validatable):
      Schema: https://graph.microsoft.com/v1.0/$metadata
              EntityType Name="claimsMappingPolicy"
              Fields used by AUTH-006:
                id (Edm.String)
                displayName (Edm.String)
                definition (Collection(Edm.String))
      Docs:   https://learn.microsoft.com/graph/api/resources/claimsmappingpolicy?view=graph-rest-1.0
              https://learn.microsoft.com/graph/api/serviceprincipal-list-claimsmappingpolicies?view=graph-rest-1.0
              (verbatim example response cited in the response section)
    """
    if definition is None:
        definition = [
            '{"ClaimsMappingPolicy":{"Version":1,"IncludeBasicClaimSet":"true",'
            '"ClaimsSchema":[{"Source":"user","ID":"employeeid",'
            '"SamlClaimType":'
            '"http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier"}]}}'
        ]
    return {
        "id": policy_id,
        "deletedDateTime": None,
        "displayName": display_name,
        "definition": list(definition),
        "isOrganizationDefault": False,
    }


# ────────────────────────────────────────────────────────────────────────
# Collection wrappers + responses kwargs
# ────────────────────────────────────────────────────────────────────────


def collection(
    records: Iterable[Mapping[str, Any]],
    *,
    next_link: str | None = None,
    odata_context: str = "$metadata#collection",
) -> dict[str, Any]:
    """Wrap a list of records in the OData v4 collection envelope."""
    payload: dict[str, Any] = {
        "@odata.context": f"https://graph.microsoft.com/v1.0/{odata_context}",
        "value": list(records),
    }
    if next_link:
        payload["@odata.nextLink"] = next_link
    return payload


def list_organization(
    *, organizations: Iterable[Mapping[str, Any]] | None = None
) -> dict[str, Any]:
    """Mock GET /v1.0/organization."""
    return {
        "method": "GET",
        "url": f"{GRAPH_BASE}/organization",
        "json": collection(
            organizations if organizations is not None else [organization()],
            odata_context="$metadata#organization",
        ),
        "status": 200,
    }


def list_users(
    *, top: int = 10, users: Iterable[Mapping[str, Any]] | None = None
) -> dict[str, Any]:
    """Mock GET /v1.0/users?$top={top}."""
    return {
        "method": "GET",
        "url": f"{GRAPH_BASE}/users?%24top={top}",
        "json": collection(
            users if users is not None else [user()],
            odata_context="$metadata#users",
        ),
        "status": 200,
    }


def list_directory_roles(
    *, roles: Iterable[Mapping[str, Any]] | None = None
) -> dict[str, Any]:
    """Mock GET /v1.0/directoryRoles."""
    return {
        "method": "GET",
        "url": f"{GRAPH_BASE}/directoryRoles",
        "json": collection(
            roles if roles is not None else [directory_role()],
            odata_context="$metadata#directoryRoles",
        ),
        "status": 200,
    }


def list_conditional_access_policies(
    *, policies: Iterable[Mapping[str, Any]] | None = None
) -> dict[str, Any]:
    """Mock GET /v1.0/identity/conditionalAccess/policies."""
    return {
        "method": "GET",
        "url": f"{GRAPH_BASE}/identity/conditionalAccess/policies",
        "json": collection(
            policies if policies is not None else [conditional_access_policy()],
            odata_context="$metadata#identity/conditionalAccess/policies",
        ),
        "status": 200,
    }


def list_service_principals(
    *,
    service_principals: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Mock GET /v1.0/servicePrincipals (with or without ``$filter``).

    The production check uses a server-side ``$filter`` to narrow on
    ``displayName``; per the cassette-tier rule that ``$filter`` /
    ``$select`` / ``$top`` are server-side narrowing on the same path,
    one mock covers all narrowing variants. Both AUTH-005 and
    AUTH-006 hit this endpoint with different filters and consume
    the same ``servicePrincipal`` shape.
    """
    return {
        "method": "GET",
        "url": f"{GRAPH_BASE}/servicePrincipals",
        "json": collection(
            service_principals
            if service_principals is not None
            else [service_principal()],
            odata_context="$metadata#servicePrincipals",
        ),
        "status": 200,
    }


def list_app_role_assignments(
    *,
    sp_id: str = MOCK_WORKDAY_SP_ID,
    assignments: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Mock GET /v1.0/servicePrincipals/{id}/appRoleAssignedTo."""
    return {
        "method": "GET",
        "url": f"{GRAPH_BASE}/servicePrincipals/{sp_id}/appRoleAssignedTo",
        "json": collection(
            assignments if assignments is not None else [app_role_assignment()],
            odata_context=(
                f"$metadata#servicePrincipals('{sp_id}')/appRoleAssignedTo"
            ),
        ),
        "status": 200,
    }


def application_template(
    *,
    template_id: str = MOCK_WORKDAY_APP_TEMPLATE_ID,
    display_name: str = "Workday",
    categories: Iterable[str] | None = ("Human resources",),
    supported_single_sign_on_modes: Iterable[str] | None = ("saml",),
    publisher: str = "Workday",
    description: str = "Mock Workday gallery template used by FlightCheck tests.",
) -> dict[str, Any]:
    """Build a single Graph /applicationTemplates record.

    The Entra application gallery catalog is tenant-independent
    metadata Microsoft curates centrally. Each template has a stable
    ``id``, a ``categories`` array (functional bucket — "Human
    resources", "Productivity", ...) and a ``supportedSingleSignOnModes``
    array of federation modes (``saml``, ``oidc``, ``password``,
    ``notSupported``). AUTH-005 filters by ``supportedSingleSignOnModes``
    intersecting {``saml``, ``oidc``} to identify federated-SSO
    templates and discover the Workday Enterprise App via
    ``servicePrincipal.applicationTemplateId``.

    Pass ``supported_single_sign_on_modes=("notSupported",)`` or
    ``("password",)`` to mock a non-federated template (e.g. a
    provisioning-only Workday entry).

    Cited consumers:
      - flightcheck/graph_client.py (get_application_templates).
      - flightcheck/checks/authentication.py (AUTH-005).

    Source (validatable):
      Schema: https://graph.microsoft.com/v1.0/$metadata
              EntityType Name="applicationTemplate" — fields used:
                id (Edm.String, key)
                displayName (Edm.String)
                categories (Collection(Edm.String))
                supportedSingleSignOnModes (Collection(Edm.String))
                publisher (Edm.String, nullable)
                description (Edm.String, nullable)
      Docs:   https://learn.microsoft.com/graph/api/applicationtemplate-list
              https://learn.microsoft.com/graph/api/resources/applicationtemplate
    """
    return {
        "id": template_id,
        "displayName": display_name,
        "categories": list(categories) if categories is not None else [],
        "supportedSingleSignOnModes": (
            list(supported_single_sign_on_modes)
            if supported_single_sign_on_modes is not None
            else []
        ),
        "publisher": publisher,
        "description": description,
    }


def list_application_templates(
    *,
    templates: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Mock GET /v1.0/applicationTemplates (with optional ``$filter``)."""
    return {
        "method": "GET",
        "url": f"{GRAPH_BASE}/applicationTemplates",
        "json": collection(
            templates if templates is not None else [application_template()],
            odata_context="$metadata#applicationTemplates",
        ),
        "status": 200,
    }


def list_claims_mapping_policies_for_sp(
    *,
    sp_id: str = MOCK_WORKDAY_SP_ID,
    policies: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Mock GET /v1.0/servicePrincipals/{id}/claimsMappingPolicies.

    Pass `policies=[]` to mock the no-custom-mapping case (the application
    is using Entra's default NameID claim).
    """
    pol_list = list(policies) if policies is not None else [claims_mapping_policy()]
    return {
        "method": "GET",
        "url": f"{GRAPH_BASE}/servicePrincipals/{sp_id}/claimsMappingPolicies",
        "json": collection(
            pol_list,
            odata_context=f"$metadata#servicePrincipals('{sp_id}')/claimsMappingPolicies",
        ),
        "status": 200,
    }


def insufficient_permissions(
    *, path: str = "/identity/conditionalAccess/policies"
) -> dict[str, Any]:
    """Mock a 403 from Graph — used to test partial-results behavior in
    get_all() (returns empty list on 401/403 rather than raising).

    See flightcheck/graph_client.py:148-161.
    """
    return {
        "method": "GET",
        "url": f"{GRAPH_BASE}{path}",
        "json": {
            "error": {
                "code": "Authorization_RequestDenied",
                "message": "Insufficient privileges to complete the operation.",
            }
        },
        "status": 403,
    }


# ────────────────────────────────────────────────────────────────────────
# Microsoft Graph external connectors (Graph Connectors)
#
# Used by EXT-002 — Graph Connector knowledge source readiness. Backed by
# the public Graph CSDL EntityType definitions for externalConnection +
# connectionOperation:
#
#   https://graph.microsoft.com/v1.0/$metadata
#     EntityType Name="externalConnection" — fields used:
#       id (Edm.String, key)
#       name (Edm.String)
#       state (microsoft.graph.externalConnectors.connectionState
#              enum: draft|ready|obsolete|limitExceeded|unknownFutureValue)
#     EntityType Name="connectionOperation" — fields used:
#       id (Edm.String, key, monotonic)
#       status (microsoft.graph.externalConnectors.connectionOperationStatus
#               enum: unspecified|inprogress|completed|failed|unknownFutureValue)
#       error (microsoft.graph.publicError, optional)
#
# Operation docs cited in each builder.
# ────────────────────────────────────────────────────────────────────────


MOCK_EXTERNAL_CONNECTION_ID = "ServiceNowKB48"
MOCK_EXTERNAL_CONNECTION_NAME = "Mock ServiceNow Knowledge Connector"
# Default connectorId for the builder is a real Microsoft Gallery
# template ID (per learn.microsoft.com/microsoftsearch/connectors-overview),
# so default-mock connections behave like Gallery connections in EXT-002.
# Tests that need to exercise the custom (API-created) provenance branch
# pass connector_id=None explicitly.
MOCK_GALLERY_CONNECTOR_ID = "serviceNowKnowledge"


def external_connection(
    *,
    connection_id: str = MOCK_EXTERNAL_CONNECTION_ID,
    name: str = MOCK_EXTERNAL_CONNECTION_NAME,
    state: str = "ready",
    description: str = "Mock connector used by FlightCheck tests.",
    connector_id: str | None = MOCK_GALLERY_CONNECTOR_ID,
    ingested_items_count: int = 0,
) -> dict[str, Any]:
    """Build a single Graph /external/connections record.

    Cited consumers:
      - flightcheck/checks/graph_connector_kb.py — EXT-002.

    Source (validatable):
      Schema: https://graph.microsoft.com/v1.0/$metadata
              EntityType Name="externalConnection" — fields used:
                id                   (Edm.String, key, admin-assigned)
                name                 (Edm.String)
                state                (Enum connectionState:
                                      draft | ready | obsolete |
                                      limitExceeded | unknownFutureValue)
                description          (Edm.String)
                connectorId          (Edm.String, Nullable=true — populated
                                      only when the connection was created
                                      from a Microsoft Gallery template;
                                      null/empty for custom connections
                                      created directly via POST
                                      /external/connections)
                ingestedItemsCount   (Edm.Int64, Nullable=true — current
                                      item count served by the connection)
      Docs:   https://learn.microsoft.com/graph/api/externalconnectors-externalconnection-get
              https://learn.microsoft.com/microsoftsearch/connectors-overview
    """
    record: dict[str, Any] = {
        "id": connection_id,
        "name": name,
        "description": description,
        "state": state,
        "ingestedItemsCount": ingested_items_count,
    }
    if connector_id is not None:
        record["connectorId"] = connector_id
    return record


def connection_operation(
    *,
    operation_id: str = "00000000-0000-0000-0000-000000005001",
    status: str = "completed",
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a single Graph /external/connections/{id}/operations record.

    Cited consumers:
      - flightcheck/checks/graph_connector_kb.py — EXT-002 latest crawl.

    Source (validatable):
      Schema: https://graph.microsoft.com/v1.0/$metadata
              EntityType Name="connectionOperation" — fields used:
                id     (Edm.String, key)
                status (Enum connectionOperationStatus:
                        unspecified | inprogress | completed | failed |
                        unknownFutureValue)
                error  (microsoft.graph.publicError, optional)
      Docs:   https://learn.microsoft.com/graph/api/externalconnectors-externalconnection-list-operations
    """
    record: dict[str, Any] = {
        "id": operation_id,
        "status": status,
    }
    if error is not None:
        record["error"] = error
    return record


def list_external_connections(
    *, connections: Iterable[Mapping[str, Any]] | None = None
) -> dict[str, Any]:
    """Mock GET /v1.0/external/connections."""
    return {
        "method": "GET",
        "url": f"{GRAPH_BASE}/external/connections",
        "json": collection(
            connections if connections is not None else [external_connection()],
            odata_context="$metadata#external/connections",
        ),
        "status": 200,
    }


def get_external_connection(
    *,
    connection_id: str = MOCK_EXTERNAL_CONNECTION_ID,
    record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Mock GET /v1.0/external/connections/{id}."""
    payload = dict(record) if record is not None else external_connection(
        connection_id=connection_id
    )
    return {
        "method": "GET",
        "url": f"{GRAPH_BASE}/external/connections/{connection_id}",
        "json": payload,
        "status": 200,
    }


def get_external_connection_not_found(
    *, connection_id: str = MOCK_EXTERNAL_CONNECTION_ID
) -> dict[str, Any]:
    """Mock GET /v1.0/external/connections/{id} → 404."""
    return {
        "method": "GET",
        "url": f"{GRAPH_BASE}/external/connections/{connection_id}",
        "json": {
            "error": {
                "code": "ItemNotFound",
                "message": f"External connection '{connection_id}' was not found.",
            }
        },
        "status": 404,
    }


def list_connection_operations(
    *,
    connection_id: str = MOCK_EXTERNAL_CONNECTION_ID,
    operations: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Mock GET /v1.0/external/connections/{id}/operations."""
    return {
        "method": "GET",
        "url": f"{GRAPH_BASE}/external/connections/{connection_id}/operations",
        "json": collection(
            operations if operations is not None else [connection_operation()],
            odata_context=f"$metadata#external/connections('{connection_id}')/operations",
        ),
        "status": 200,
    }


# ────────────────────────────────────────────────────────────────────────
# subscribedSku + directoryRole members (PRE-001/002/003/008/009)
# ────────────────────────────────────────────────────────────────────────


def subscribed_sku(
    *,
    sku_part_number: str = "MICROSOFT_365_COPILOT",
    consumed_units: int = 5,
    enabled_units: int = 10,
    sku_id: str = "00000000-0000-0000-0000-0000000040a1",
) -> dict[str, Any]:
    """Build a single Graph /subscribedSkus record.

    Cited consumers:
      - flightcheck/checks/prerequisites.py (PRE-001/002/003 — license SKUs).
      - flightcheck/graph_client.py:194-196 (get_subscribed_skus).

    Source (validatable):
      Schema: https://graph.microsoft.com/v1.0/$metadata
              EntityType Name="subscribedSku" — fields used:
                skuPartNumber (Edm.String)
                consumedUnits (Edm.Int32)
                prepaidUnits (ComplexType licenseUnitsDetail; enabled Edm.Int32)
      Docs: https://learn.microsoft.com/graph/api/subscribedsku-list
    """
    return {
        "skuId": sku_id,
        "skuPartNumber": sku_part_number,
        "consumedUnits": consumed_units,
        "prepaidUnits": {"enabled": enabled_units, "suspended": 0, "warning": 0},
    }


def list_subscribed_skus(
    *, skus: Iterable[Mapping[str, Any]] | None = None
) -> dict[str, Any]:
    """Mock GET /v1.0/subscribedSkus."""
    return {
        "method": "GET",
        "url": f"{GRAPH_BASE}/subscribedSkus",
        "json": collection(
            skus if skus is not None else [subscribed_sku()],
            odata_context="$metadata#subscribedSkus",
        ),
        "status": 200,
    }


def list_role_members(
    *, role_id: str, members: Iterable[Mapping[str, Any]] | None = None
) -> dict[str, Any]:
    """Mock GET /v1.0/directoryRoles/{role_id}/members."""
    return {
        "method": "GET",
        "url": f"{GRAPH_BASE}/directoryRoles/{role_id}/members",
        "json": collection(
            members if members is not None else [user()],
            odata_context="$metadata#directoryObjects",
        ),
        "status": 200,
    }
