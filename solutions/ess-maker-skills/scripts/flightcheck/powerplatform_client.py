# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Power Platform API (Licensing / Billing Policy) Client

Provides authenticated read access to the Power Platform API billing-policy
surface for FlightCheck PRE-005 (Pay-As-You-Go binding detection).

This is a DIFFERENT host and audience from the BAP admin client in
``pp_admin_client.py``:

  - BAP (pp_admin_client.py): ``https://api.bap.microsoft.com`` /
    ``https://service.powerapps.com//.default``
  - This client:             ``https://api.powerplatform.com`` /
    ``https://api.powerplatform.com/.default``

Authentication reuses the same MSAL token cache as auth.py /
graph_client.py / pp_admin_client.py (``.local/.token_cache.bin``).

API contract tier: ``documented`` — see the "API tier registry" in
``tests/fixtures/cassettes/INDEX.md``. Response shapes verified against
the MS Learn references cited on each method.
"""

import os
import sys

try:
    import msal
except ImportError:
    print("ERROR: 'msal' package not found. Run: pip install msal")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package not found. Run: pip install requests")
    sys.exit(1)

try:
    from urllib3.util.retry import Retry
    from requests.adapters import HTTPAdapter
except ImportError:
    print("ERROR: 'urllib3' / 'requests' not found. Run: pip install requests")
    sys.exit(1)


# Shared first-party public client used across the kit's MSAL flows.
CLIENT_ID = "51f81489-12ee-4a9e-aaae-a2591f45987d"

PP_API_BASE = "https://api.powerplatform.com"
# The Power Platform API uses its own audience, distinct from the BAP /
# PowerApps (service.powerapps.com) audience the pp_admin client uses.
PP_API_SCOPE = "https://api.powerplatform.com/.default"

# Billing-policy endpoints are stable at this version (MS Learn).
API_VERSION = "2024-10-01"

# Module-level session with bounded retry-with-backoff for 429/5xx, mirroring
# pp_admin_client.py. Read-only verbs only; FlightCheck never mutates state.
_RETRY = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "HEAD", "OPTIONS"]),
    respect_retry_after_header=True,
)
_SESSION = requests.Session()
_SESSION.mount("https://", HTTPAdapter(max_retries=_RETRY))


class PowerPlatformClient:
    """Power Platform API client for billing-policy / PayG queries."""

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self._token: str | None = None

    def authenticate(self) -> str:
        """Acquire a Power Platform API access token.

        Uses the shared MSAL cache so the operator's existing sign-in is
        reused silently when possible, falling back to interactive.
        """
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        cache = msal.SerializableTokenCache()
        cache_path = os.path.join(".local", ".token_cache.bin")

        if os.path.exists(cache_path):
            with open(cache_path, "r") as f:
                cache.deserialize(f.read())

        app = msal.PublicClientApplication(
            CLIENT_ID, authority=authority, token_cache=cache
        )

        accounts = app.get_accounts()
        result = None
        if accounts:
            result = app.acquire_token_silent([PP_API_SCOPE], account=accounts[0])
        if not result or "access_token" not in result:
            print("Opening browser for Power Platform API sign-in...")
            result = app.acquire_token_interactive(
                [PP_API_SCOPE], prompt="select_account"
            )
        if "access_token" not in result:
            # Don't echo error_description - it can include tenant IDs and
            # internal flow details (CWE-209). Mirrors the auth.py pattern.
            error = result.get("error", "unknown_error")
            raise RuntimeError(f"Power Platform API auth failed ({error}).")

        if cache.has_state_changed:
            os.makedirs(".local", exist_ok=True)
            try:
                os.chmod(".local", 0o700)
            except OSError:
                pass  # Windows ignores chmod for directories
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY
            fd = os.open(cache_path, flags, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(cache.serialize())

        self._token = result["access_token"]
        return self._token

    @property
    def headers(self) -> dict:
        if not self._token:
            raise RuntimeError("Call authenticate() first")
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

    def _get_all(self, path: str, params: dict | None = None) -> list | dict:
        """Paginate through a Power Platform API collection.

        Follows the same contract as ``pp_admin_client._get_all``:

        - On 401/403 returns ``{"_error": "insufficient_permissions",
          "_status": <code>}`` so callers surface the permission failure
          instead of mistaking a swallowed auth error for an empty list.
        - On 404 returns ``[]`` — a 404 on a billing-policy sub-collection
          (e.g. ``.../environments``) means "nothing linked", not an error.
          The environments endpoint documents 404 as a valid response.
        - Paginates via ``@odata.nextLink``.
        """
        items: list = []
        url = f"{PP_API_BASE}{path}"
        while url:
            resp = _SESSION.get(url, headers=self.headers, params=params, timeout=60)
            if resp.status_code in (401, 403):
                return {"_error": "insufficient_permissions", "_status": resp.status_code}
            if resp.status_code == 404:
                return items
            resp.raise_for_status()
            data = resp.json()
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink") or data.get("nextLink")
            params = None
        return items

    def list_billing_policies(self) -> list | dict:
        """List all billing policies for the tenant.

        MS Learn (documented tier):
        https://learn.microsoft.com/en-us/rest/api/power-platform/licensing/billing-policy/list-billing-policies

        GET /licensing/billingPolicies?api-version=2024-10-01

        Each item is a ``BillingPolicyResponseModel``:
        ``{id, name, status ("Enabled"|"Disabled"), location,
        billingInstrument: {id, resourceGroup, subscriptionId},
        createdBy, createdOn, lastModifiedBy, lastModifiedOn}``.

        Returns the list, or a ``{"_error": ...}`` sentinel on 401/403.
        """
        return self._get_all(
            "/licensing/billingPolicies",
            params={"api-version": API_VERSION},
        )

    def list_policy_environments(self, billing_policy_id: str) -> list | dict:
        """List environments linked to a billing policy.

        MS Learn (documented tier):
        https://learn.microsoft.com/en-us/rest/api/power-platform/licensing/billing-policy-environment/list-billing-policy-environments

        GET /licensing/billingPolicies/{billingPolicyId}/environments?api-version=2024-10-01

        Each item is a ``BillingPolicyEnvironmentResponseModelV1``:
        ``{billingPolicyId, environmentId}``.

        Returns the list (``[]`` when none / 404), or a ``{"_error": ...}``
        sentinel on 401/403.
        """
        return self._get_all(
            f"/licensing/billingPolicies/{billing_policy_id}/environments",
            params={"api-version": API_VERSION},
        )

    def get_currency_allocations(self, environment_id: str) -> list | dict:
        """Get prepaid currency capacity allocated to a single environment.

        MS Learn (documented tier):
        https://learn.microsoft.com/en-us/rest/api/power-platform/licensing/currency-allocation/get-currency-allocation-by-environment

        GET /licensing/environments/{environmentId}/allocations?api-version=2024-10-01

        The response is a single ``AllocationsByEnvironmentResponseModelV1``
        (not an OData collection):
        ``{environmentId, currencyAllocations: [{currencyType, allocated}]}``.
        ``currencyType`` is an ``ExternalCurrencyType`` enum; Copilot Studio
        message capacity is ``MCSMessages`` (sessions are ``MCSSessions``).
        The Sept 2025 rename to "Copilot Credits" did not change the enum value.

        Returns the ``currencyAllocations`` list (``[]`` when the environment
        has no allocations / 404), or a ``{"_error": ...}`` sentinel on 401/403.
        """
        url = f"{PP_API_BASE}/licensing/environments/{environment_id}/allocations"
        resp = _SESSION.get(
            url, headers=self.headers,
            params={"api-version": API_VERSION}, timeout=60,
        )
        if resp.status_code in (401, 403):
            return {"_error": "insufficient_permissions", "_status": resp.status_code}
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        return data.get("currencyAllocations", []) or []
