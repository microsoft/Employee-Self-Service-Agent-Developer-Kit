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


def service_principal(
    *,
    sp_id: str = MOCK_WORKDAY_SP_ID,
    app_id: str = MOCK_WORKDAY_APP_ID,
    display_name: str = "Workday",
    app_role_assignment_required: bool = True,
    account_enabled: bool = True,
) -> dict[str, Any]:
    """Build a single Graph /servicePrincipals record.

    Cited consumers:
      - flightcheck/graph_client.py (get_service_principals)
      - flightcheck/checks/authentication.py (AUTH-005)

    Source (validatable):
      Schema: https://graph.microsoft.com/v1.0/$metadata
              EntityType Name="servicePrincipal" — fields used:
                id (Edm.String)
                appId (Edm.String)
                displayName (Edm.String)
                appRoleAssignmentRequired (Edm.Boolean)
                accountEnabled (Edm.Boolean)
      Docs:   https://learn.microsoft.com/graph/api/serviceprincipal-get
              Example response copied verbatim 2026-05.
    """
    return {
        "accountEnabled": account_enabled,
        "addIns": [],
        "alternativeNames": [],
        "appDisplayName": display_name,
        "appId": app_id,
        "appOwnerOrganizationId": MOCK_TENANT_ID,
        "appRoleAssignmentRequired": app_role_assignment_required,
        "appRoles": [],
        "displayName": display_name,
        "id": sp_id,
        "info": {
            "termsOfServiceUrl": None,
            "supportUrl": None,
            "privacyStatementUrl": None,
            "marketingUrl": None,
            "logoUrl": None,
        },
        "keyCredentials": [],
        "logoutUrl": None,
        "oauth2PermissionScopes": [],
        "passwordCredentials": [],
        "publisherName": None,
        "replyUrls": [],
        "servicePrincipalNames": [app_id],
        "servicePrincipalType": "Application",
        "signInAudience": "AzureADMyOrg",
        "tags": ["WindowsAzureActiveDirectoryIntegratedApp"],
        "tokenEncryptionKeyId": None,
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
    one mock covers all narrowing variants.
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
