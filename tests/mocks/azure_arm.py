# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
Mock response builders for Azure Resource Manager — Subscriptions Get.

# ─────────────────────────────────────────────────────────────────
# MOCK_STATUS = "documented"
#
# Backed by the Microsoft Learn "Subscriptions - Get" reference, which
# publishes a verbatim 200 example response and the SubscriptionState
# enum. No no-auth machine-readable schema endpoint exists for ARM in the
# kit's approved sources, so the documented tier applies — see
# tests/fixtures/cassettes/INDEX.md "API tier registry".
#
# Docs (api-version 2022-12-01):
#   https://learn.microsoft.com/en-us/rest/api/resources/subscriptions/get?view=rest-resources-2022-12-01
# ─────────────────────────────────────────────────────────────────

Used by FlightCheck integration tests for PRE-005 (Pay-As-You-Go) via
solutions/ess-maker-skills/scripts/flightcheck/azure_arm_client.py.

Verbatim documented 200 example response (copied from the MS Learn page,
"GetASingleSubscription" sample response):

  {
    "authorizationSource": "Bypassed",
    "displayName": "Example Subscription",
    "id": "/subscriptions/291bba3f-e0a5-47bc-a099-3bdcb2a50a05",
    "managedByTenants": [
      { "tenantId": "8f70baf1-1f6e-46a2-a1ff-238dac1ebfb7" }
    ],
    "state": "Enabled",
    "subscriptionId": "291bba3f-e0a5-47bc-a099-3bdcb2a50a05",
    "subscriptionPolicies": {
      "locationPlacementId": "Internal_2014-09-01",
      "quotaId": "Internal_2014-09-01",
      "spendingLimit": "Off"
    },
    "tags": { "tagKey1": "tagValue1", "tagKey2": "tagValue2" },
    "tenantId": "31c75423-32d6-4322-88b7-c478bdde4858"
  }

SubscriptionState enum (documented): Enabled, Warned, PastDue, Disabled, Deleted.
The PRE-005 check reads the top-level ``state`` field (NOT nested under
``properties``).

Budgets (spending guardrails, PRE-005 AC3) come from a separate documented
operation, Azure Consumption "Budgets - List":
  https://learn.microsoft.com/en-us/rest/api/consumption/budgets/list?view=rest-consumption-2024-08-01

  GET https://management.azure.com/subscriptions/{id}/providers/Microsoft.Consumption/budgets?api-version=2024-08-01

Verbatim documented 200 example item (from the "BudgetsList" sample response):

  {
    "value": [
      {
        "name": "PSBudget",
        "type": "Microsoft.Consumption/budgets",
        "eTag": "\"1d34d012214157f\"",
        "id": "subscriptions/{id}/providers/Microsoft.Consumption/budgets/PSBudget",
        "properties": {
          "category": "Cost",
          "amount": 100.65,
          "timeGrain": "Monthly",
          "timePeriod": { "startDate": "2017-10-01T00:00:00Z", "endDate": "2018-10-31T00:00:00Z" },
          "currentSpend": { "amount": 80.89, "unit": "USD" },
          "notifications": { ... }
        }
      }
    ]
  }

PRE-005 only consumes the presence of at least one cost budget in ``value``.
"""

from __future__ import annotations

from typing import Any

# Validation status — read by tests/conftest.py:require_validated_mock().
MOCK_STATUS = "documented"

ARM_BASE = "https://management.azure.com"

MOCK_SUBSCRIPTION_ID = "291bba3f-e0a5-47bc-a099-3bdcb2a50a05"
MOCK_TENANT_ID = "31c75423-32d6-4322-88b7-c478bdde4858"


def subscription(
    *,
    subscription_id: str = MOCK_SUBSCRIPTION_ID,
    state: str = "Enabled",
    display_name: str = "Example Subscription",
) -> dict[str, Any]:
    """Build a ``Subscription`` record matching the documented example.

    ``state`` accepts any documented SubscriptionState value: Enabled,
    Warned, PastDue, Disabled, Deleted.
    """
    return {
        "authorizationSource": "Bypassed",
        "displayName": display_name,
        "id": f"/subscriptions/{subscription_id}",
        "managedByTenants": [{"tenantId": "8f70baf1-1f6e-46a2-a1ff-238dac1ebfb7"}],
        "state": state,
        "subscriptionId": subscription_id,
        "subscriptionPolicies": {
            "locationPlacementId": "Internal_2014-09-01",
            "quotaId": "Internal_2014-09-01",
            "spendingLimit": "Off",
        },
        "tags": {"tagKey1": "tagValue1", "tagKey2": "tagValue2"},
        "tenantId": MOCK_TENANT_ID,
    }


def get_subscription(
    *,
    subscription_id: str = MOCK_SUBSCRIPTION_ID,
    state: str = "Enabled",
    status: int = 200,
) -> dict[str, Any]:
    """responses.add(**...) kwargs for GET /subscriptions/{id}.

    Pass ``status=403`` (or 401) to model a permission-denied response;
    the client maps those to a ``{"_error": ...}`` sentinel.
    """
    url = f"{ARM_BASE}/subscriptions/{subscription_id}"
    if status in (401, 403):
        return {
            "method": "GET",
            "url": url,
            "json": {"error": {"code": "AuthorizationFailed",
                               "message": "The client does not have authorization."}},
            "status": status,
        }
    return {
        "method": "GET",
        "url": url,
        "json": subscription(subscription_id=subscription_id, state=state),
        "status": 200,
    }


def budget(
    *,
    name: str = "PSBudget",
    subscription_id: str = MOCK_SUBSCRIPTION_ID,
    amount: float = 100.65,
    category: str = "Cost",
) -> dict[str, Any]:
    """Build a single ``Budget`` record matching the documented example."""
    return {
        "name": name,
        "type": "Microsoft.Consumption/budgets",
        "eTag": '"1d34d012214157f"',
        "id": f"subscriptions/{subscription_id}/providers/Microsoft.Consumption/budgets/{name}",
        "properties": {
            "category": category,
            "amount": amount,
            "timeGrain": "Monthly",
            "timePeriod": {
                "startDate": "2017-10-01T00:00:00Z",
                "endDate": "2018-10-31T00:00:00Z",
            },
            "currentSpend": {"amount": 80.89, "unit": "USD"},
        },
    }


def list_budgets(
    *,
    subscription_id: str = MOCK_SUBSCRIPTION_ID,
    budgets: list[dict] | None = None,
    status: int = 200,
) -> dict[str, Any]:
    """responses.add(**...) kwargs for
    GET /subscriptions/{id}/providers/Microsoft.Consumption/budgets.

    Pass ``status=403`` (or 401) to model a permission-denied response; the
    client maps those to a ``{"_error": ...}`` sentinel (PRE-005 then treats
    the spending guardrail as could-not-determine and WARNs).
    """
    url = (
        f"{ARM_BASE}/subscriptions/{subscription_id}"
        "/providers/Microsoft.Consumption/budgets"
    )
    if status in (401, 403):
        return {
            "method": "GET",
            "url": url,
            "json": {"error": {"code": "AuthorizationFailed",
                               "message": "The client does not have authorization."}},
            "status": status,
        }
    return {
        "method": "GET",
        "url": url,
        "json": {"value": budgets if budgets is not None else []},
        "status": 200,
    }
