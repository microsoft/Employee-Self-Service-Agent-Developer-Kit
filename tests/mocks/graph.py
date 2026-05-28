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


def external_connection(
    *,
    connection_id: str = MOCK_EXTERNAL_CONNECTION_ID,
    name: str = MOCK_EXTERNAL_CONNECTION_NAME,
    state: str = "ready",
    description: str = "Mock connector used by FlightCheck tests.",
) -> dict[str, Any]:
    """Build a single Graph /external/connections record.

    Cited consumers:
      - flightcheck/checks/graph_connector_kb.py — EXT-002.

    Source (validatable):
      Schema: https://graph.microsoft.com/v1.0/$metadata
              EntityType Name="externalConnection" — fields used:
                id          (Edm.String, key, admin-assigned)
                name        (Edm.String)
                state       (Enum connectionState:
                             draft | ready | obsolete | limitExceeded |
                             unknownFutureValue)
                description (Edm.String)
      Docs:   https://learn.microsoft.com/graph/api/externalconnectors-externalconnection-get
    """
    return {
        "id": connection_id,
        "name": name,
        "description": description,
        "state": state,
    }


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
