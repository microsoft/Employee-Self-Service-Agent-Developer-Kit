# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Mock response builders for the Power Platform API (Licensing / Billing Policy).

# ─────────────────────────────────────────────────────────────────
# MOCK_STATUS = "documented"
#
# Backed by Microsoft Learn reference docs (no public OpenAPI / no-auth
# $metadata exists for this surface, so the documented tier applies — see
# tests/fixtures/cassettes/INDEX.md "API tier registry").
#
# Docs (api-version 2024-10-01):
#   List Billing Policies:
#     https://learn.microsoft.com/en-us/rest/api/power-platform/licensing/billing-policy/list-billing-policies
#   List Billing Policy Environments:
#     https://learn.microsoft.com/en-us/rest/api/power-platform/licensing/billing-policy-environment/list-billing-policy-environments
#   Get Currency Allocation By Environment:
#     https://learn.microsoft.com/en-us/rest/api/power-platform/licensing/currency-allocation/get-currency-allocation-by-environment
# ─────────────────────────────────────────────────────────────────

Used by FlightCheck integration tests for PRE-005 (Pay-As-You-Go) via
solutions/ess-maker-skills/scripts/flightcheck/powerplatform_client.py.

Documented contract (verbatim from the MS Learn "Definitions" tables; the
operation pages document the models rather than a separate example body, so
the shapes below are assembled strictly from those field tables — nothing
guessed):

  BillingPolicyResponseModel:
    | id               | string                          |
    | name             | string                          |
    | status           | "Enabled" | "Disabled"          |
    | location         | string                          |
    | billingInstrument| { id, resourceGroup, subscriptionId (uuid) } |
    | createdBy        | Principal { id, type }          |
    | createdOn        | string (date-time)              |
    | lastModifiedBy   | Principal                       |
    | lastModifiedOn   | string (date-time)              |

  BillingPolicyResponseModelResponseWithOdataContinuation:
    | @odata.nextLink  | string                          |
    | value            | BillingPolicyResponseModel[]    |

  BillingPolicyEnvironmentResponseModelV1:
    | billingPolicyId  | string                          |
    | environmentId    | string                          |

  BillingPolicyEnvironmentResponseModelV1ResponseWithOdataContinuation:
    | @odata.nextLink  | string                          |
    | value            | BillingPolicyEnvironmentResponseModelV1[] |

  CurrencyAllocationModelV1:
    | currencyType     | ExternalCurrencyType ("MCSMessages" | "MCSSessions" | ...) |
    | allocated        | int32                           |

  AllocationsByEnvironmentResponseModelV1 (a single object, NOT an OData
  collection):
    | environmentId        | string                      |
    | currencyAllocations  | CurrencyAllocationModelV1[] |
"""

from __future__ import annotations

from typing import Any, Iterable

# Validation status — read by tests/conftest.py:require_validated_mock().
MOCK_STATUS = "documented"

PP_API_BASE = "https://api.powerplatform.com"

MOCK_ENV_ID = "Default-00000000-0000-0000-0000-000000001111"
MOCK_POLICY_ID = "00000000-0000-0000-0000-00000000b111"
MOCK_SUBSCRIPTION_ID = "291bba3f-e0a5-47bc-a099-3bdcb2a50a05"
MOCK_RESOURCE_GROUP = "rg-ess-payg"


def _principal(principal_id: str = "00000000-0000-0000-0000-0000000000aa") -> dict[str, Any]:
    return {"id": principal_id, "type": "User"}


def billing_policy(
    *,
    policy_id: str = MOCK_POLICY_ID,
    name: str = "ESS PayG Billing",
    status: str = "Enabled",
    subscription_id: str | None = MOCK_SUBSCRIPTION_ID,
    resource_group: str = MOCK_RESOURCE_GROUP,
    location: str = "unitedstates",
) -> dict[str, Any]:
    """Build a single ``BillingPolicyResponseModel`` record.

    Pass ``subscription_id=None`` to model a policy with no bound Azure
    subscription (empty ``billingInstrument.subscriptionId``).
    """
    return {
        "id": policy_id,
        "name": name,
        "status": status,
        "location": location,
        "billingInstrument": {
            "id": f"/billingInstruments/{policy_id}",
            "resourceGroup": resource_group,
            "subscriptionId": subscription_id or "",
        },
        "createdBy": _principal(),
        "createdOn": "2024-01-15T12:00:00Z",
        "lastModifiedBy": _principal(),
        "lastModifiedOn": "2024-01-15T12:00:00Z",
    }


def billing_policy_environment(
    *,
    policy_id: str = MOCK_POLICY_ID,
    environment_id: str = MOCK_ENV_ID,
) -> dict[str, Any]:
    """Build a single ``BillingPolicyEnvironmentResponseModelV1`` record."""
    return {"billingPolicyId": policy_id, "environmentId": environment_id}


def collection(items: Iterable[dict], *, next_link: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"value": list(items)}
    if next_link:
        payload["@odata.nextLink"] = next_link
    return payload


def list_billing_policies(
    *,
    policies: Iterable[dict] | None = None,
    status: int = 200,
) -> dict[str, Any]:
    """responses.add(**...) kwargs for GET /licensing/billingPolicies.

    Pass ``status=403`` (or 401) to model a permission-denied response.
    """
    if status in (401, 403):
        return {
            "method": "GET",
            "url": f"{PP_API_BASE}/licensing/billingPolicies",
            "json": {"error": {"code": "AuthorizationFailed"}},
            "status": status,
        }
    return {
        "method": "GET",
        "url": f"{PP_API_BASE}/licensing/billingPolicies",
        "json": collection(policies if policies is not None else []),
        "status": 200,
    }


def list_policy_environments(
    *,
    policy_id: str = MOCK_POLICY_ID,
    environments: Iterable[dict] | None = None,
    status: int = 200,
) -> dict[str, Any]:
    """responses.add(**...) kwargs for
    GET /licensing/billingPolicies/{policy_id}/environments.

    Pass ``status=404`` to model "no environments linked" (the client maps
    404 to an empty list); ``status=403``/``401`` for permission denied.
    """
    url = f"{PP_API_BASE}/licensing/billingPolicies/{policy_id}/environments"
    if status in (401, 403):
        return {
            "method": "GET",
            "url": url,
            "json": {"error": {"code": "AuthorizationFailed"}},
            "status": status,
        }
    if status == 404:
        return {
            "method": "GET",
            "url": url,
            "json": {"error": {"code": "BillingPolicyEnvironmentNotFound"}},
            "status": 404,
        }
    return {
        "method": "GET",
        "url": url,
        "json": collection(environments if environments is not None else []),
        "status": 200,
    }


def currency_allocation(*, currency_type: str = "MCSMessages", allocated: int = 0) -> dict[str, Any]:
    """Build a single ``CurrencyAllocationModelV1`` record.

    ``currency_type`` follows the ``ExternalCurrencyType`` enum; Copilot Studio
    message capacity is ``MCSMessages``.
    """
    return {"currencyType": currency_type, "allocated": allocated}


def get_currency_allocations(
    *,
    environment_id: str = MOCK_ENV_ID,
    allocations: Iterable[dict] | None = None,
    status: int = 200,
) -> dict[str, Any]:
    """responses.add(**...) kwargs for
    GET /licensing/environments/{environment_id}/allocations.

    The success body is a single ``AllocationsByEnvironmentResponseModelV1``
    (not an OData collection). Pass ``status=404`` to model "environment has no
    allocations" (the client maps 404 to an empty list); ``status=403``/``401``
    for permission denied.
    """
    url = f"{PP_API_BASE}/licensing/environments/{environment_id}/allocations"
    if status in (401, 403):
        return {
            "method": "GET",
            "url": url,
            "json": {"error": {"code": "AuthorizationFailed"}},
            "status": status,
        }
    if status == 404:
        return {
            "method": "GET",
            "url": url,
            "json": {"error": {"code": "EnvironmentAllocationsNotFound"}},
            "status": 404,
        }
    return {
        "method": "GET",
        "url": url,
        "json": {
            "environmentId": environment_id,
            "currencyAllocations": list(allocations) if allocations is not None else [],
        },
        "status": 200,
    }
