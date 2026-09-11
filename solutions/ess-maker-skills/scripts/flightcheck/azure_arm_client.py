# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Azure Resource Manager (ARM) Client

Provides authenticated read access to Azure Resource Manager tenant and
subscription surfaces. Foundation setup uses tenant listing for a friendly
organization picker; FlightCheck PRE-005 reads subscription health.

This is a separate Entra token from the Power Platform one: the ARM
audience is ``https://management.azure.com``. Authentication reuses the
shared MSAL token cache (``.local/.token_cache.bin``).

API contract tier: ``documented`` — see the "API tier registry" in
``tests/fixtures/cassettes/INDEX.md``. Response shape verified against
the MS Learn Subscriptions - Get reference (api-version 2022-12-01).
"""

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

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

ARM_BASE = "https://management.azure.com"
ARM_SCOPE = "https://management.azure.com/.default"

# Subscriptions - Get is stable at this version (MS Learn).
API_VERSION = "2022-12-01"
# Consumption Budgets - List (spending guardrails for PRE-005 AC3).
BUDGETS_API_VERSION = "2024-08-01"

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


class AzureArmClient:
    """Azure Resource Manager client for tenant and subscription queries."""

    def __init__(
        self,
        tenant_id: str,
        *,
        cache_path: str | os.PathLike[str] | None = None,
    ):
        self.tenant_id = tenant_id
        self.cache_path = Path(
            cache_path or os.path.join(".local", ".token_cache.bin")
        )
        self._token: str | None = None

    def authenticate(self, *, force_account_selection: bool = False) -> str:
        """Acquire an Azure Resource Manager access token.

        Uses the shared MSAL cache so the operator's existing sign-in is
        reused silently when possible, falling back to interactive. This
        is a distinct audience (management.azure.com) from the Power
        Platform token, so it may prompt a separate consent.
        """
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        cache = msal.SerializableTokenCache()
        if self.cache_path.exists():
            with self.cache_path.open("r", encoding="utf-8") as f:
                cache.deserialize(f.read())

        app = msal.PublicClientApplication(
            CLIENT_ID, authority=authority, token_cache=cache
        )

        result = None
        accounts = app.get_accounts()
        if accounts and not force_account_selection:
            result = app.acquire_token_silent([ARM_SCOPE], account=accounts[0])
        if not result or "access_token" not in result:
            print("Opening browser for Azure (ARM) sign-in...")
            result = app.acquire_token_interactive(
                [ARM_SCOPE], prompt="select_account"
            )
        if "access_token" not in result:
            # Don't echo error_description - it can include tenant IDs and
            # internal flow details (CWE-209). Mirrors the auth.py pattern.
            error = result.get("error", "unknown_error")
            raise RuntimeError(f"Azure ARM auth failed ({error}).")

        if cache.has_state_changed:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.cache_path.parent, 0o700)
            except OSError:
                pass  # Windows ignores chmod for directories
            flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY
            fd = os.open(self.cache_path, flags, 0o600)
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

    def list_tenants(self) -> list[dict]:
        """List organizations available to the authenticated account."""
        url = f"{ARM_BASE}/tenants"
        params = {"api-version": API_VERSION}
        tenants: list[dict] = []
        for _page in range(20):
            resp = _SESSION.get(
                url,
                headers=self.headers,
                params=params,
                timeout=60,
            )
            if resp.status_code in (401, 403):
                raise RuntimeError(
                    "Azure organization discovery is not authorized."
                )
            resp.raise_for_status()
            try:
                body = resp.json()
            except ValueError as exc:
                raise RuntimeError(
                    "Azure organization discovery returned invalid JSON."
                ) from exc
            values = body.get("value") if isinstance(body, dict) else None
            if not isinstance(values, list) or not all(
                isinstance(item, dict) for item in values
            ):
                raise RuntimeError(
                    "Azure organization discovery returned an invalid shape."
                )
            tenants.extend(values)
            next_link = body.get("nextLink")
            if not next_link:
                return tenants
            parsed = urlparse(str(next_link))
            if (
                parsed.scheme != "https"
                or parsed.hostname != "management.azure.com"
                or parsed.username
                or parsed.password
                or parsed.port not in (None, 443)
                or parsed.path != "/tenants"
            ):
                raise RuntimeError(
                    "Azure organization discovery returned an unsafe "
                    "continuation URL."
                )
            url = str(next_link)
            params = None
        raise RuntimeError(
            "Azure organization discovery returned too many pages."
        )

    def get_subscription(self, subscription_id: str) -> dict:
        """Get details about a subscription, including its ``state``.

        MS Learn (documented tier):
        https://learn.microsoft.com/en-us/rest/api/resources/subscriptions/get?view=rest-resources-2022-12-01

        GET https://management.azure.com/subscriptions/{subscriptionId}?api-version=2022-12-01

        The health signal is the top-level ``state`` field (NOT nested
        under ``properties``). ``SubscriptionState`` values: ``Enabled``,
        ``Warned``, ``PastDue``, ``Disabled``, ``Deleted``.

        Returns the subscription dict, or a ``{"_error": ...}`` sentinel
        on 401/403 so callers can surface "health unverifiable" instead of
        failing the check outright.
        """
        url = f"{ARM_BASE}/subscriptions/{subscription_id}"
        resp = _SESSION.get(
            url, headers=self.headers,
            params={"api-version": API_VERSION}, timeout=60,
        )
        if resp.status_code in (401, 403):
            return {"_error": "insufficient_permissions", "_status": resp.status_code}
        resp.raise_for_status()
        return resp.json()

    def list_budgets(self, subscription_id: str) -> list | dict:
        """List Azure Consumption budgets defined on a subscription.

        MS Learn (documented tier):
        https://learn.microsoft.com/en-us/rest/api/consumption/budgets/list?view=rest-consumption-2024-08-01

        GET https://management.azure.com/subscriptions/{subscriptionId}/providers/Microsoft.Consumption/budgets?api-version=2024-08-01

        Each item is a ``Budget`` with ``properties.category`` ("Cost" |
        "Usage"). PRE-005 treats the presence of at least one cost budget as
        the "spending guardrail" signal for a Pay-As-You-Go subscription.

        Returns the list (``[]`` when none), or a ``{"_error": ...}`` sentinel
        on 401/403. Listing budgets needs Cost Management Reader, a broader
        grant than the subscription GET, so a permission failure here is
        common and is treated by the caller as "guardrails unknown" (never a
        false WARN), not as "no guardrails".
        """
        items: list = []
        url = (
            f"{ARM_BASE}/subscriptions/{subscription_id}"
            "/providers/Microsoft.Consumption/budgets"
        )
        params: dict | None = {"api-version": BUDGETS_API_VERSION}
        while url:
            resp = _SESSION.get(url, headers=self.headers, params=params, timeout=60)
            if resp.status_code in (401, 403):
                return {"_error": "insufficient_permissions", "_status": resp.status_code}
            resp.raise_for_status()
            data = resp.json()
            items.extend(data.get("value", []))
            url = data.get("nextLink") or data.get("@odata.nextLink")
            params = None
        return items
