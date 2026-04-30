# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Copilot Kit — Power Platform Admin REST API Client

Provides authenticated access to Power Platform Admin (BAP) APIs and
PowerApps APIs for FlightCheck checks (environments, flows, connections, DLP).

Authentication uses the same MSAL cache as auth.py / graph_client.py.
"""

import json
import os
import re
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


CLIENT_ID = "51f81489-12ee-4a9e-aaae-a2591f45987d"

BAP_BASE = "https://api.bap.microsoft.com"
POWERAPPS_BASE = "https://api.powerapps.com"

# The BAP / PowerApps APIs use this resource scope.
PP_SCOPE = "https://service.powerapps.com//.default"


class PPAdminClient:
    """Power Platform Admin API client for environment and flow queries."""

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self._token: str | None = None

    def authenticate(self) -> str:
        """Acquire a Power Platform access token."""
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        cache = msal.SerializableTokenCache()
        cache_path = os.path.join("my", ".token_cache.bin")

        if os.path.exists(cache_path):
            with open(cache_path, "r") as f:
                cache.deserialize(f.read())

        app = msal.PublicClientApplication(
            CLIENT_ID, authority=authority, token_cache=cache
        )

        accounts = app.get_accounts()
        result = None
        if accounts:
            result = app.acquire_token_silent([PP_SCOPE], account=accounts[0])

        if not result or "access_token" not in result:
            print("Opening browser for Power Platform sign-in...")
            result = app.acquire_token_interactive(
                [PP_SCOPE], prompt="select_account"
            )

        if "access_token" not in result:
            error = result.get("error_description", result.get("error", "Unknown"))
            raise RuntimeError(f"Power Platform auth failed: {error}")

        if cache.has_state_changed:
            os.makedirs("my", exist_ok=True)
            with open(cache_path, "w") as f:
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

    def _get(self, base: str, path: str, params: dict | None = None) -> dict:
        url = f"{base}{path}"
        resp = requests.get(url, headers=self.headers, params=params, timeout=60)
        if resp.status_code in (401, 403):
            return {"_error": "insufficient_permissions", "_status": resp.status_code}
        resp.raise_for_status()
        return resp.json()

    def _get_all(self, base: str, path: str, params: dict | None = None) -> list:
        """Paginate through results."""
        items: list = []
        url = f"{base}{path}"
        while url:
            resp = requests.get(url, headers=self.headers, params=params, timeout=60)
            if resp.status_code in (401, 403):
                return items
            resp.raise_for_status()
            data = resp.json()
            items.extend(data.get("value", []))
            url = data.get("nextLink") or data.get("@odata.nextLink")
            params = None
        return items

    # ----- Environment APIs -----

    def get_environment(self, env_id: str) -> dict:
        """Get a specific Power Platform environment."""
        return self._get(
            BAP_BASE,
            f"/providers/Microsoft.BusinessAppPlatform/scopes/admin/environments/{env_id}",
            params={"api-version": "2021-04-01"},
        )

    def get_environments(self) -> list:
        """List all environments the user has admin access to."""
        return self._get_all(
            BAP_BASE,
            "/providers/Microsoft.BusinessAppPlatform/scopes/admin/environments",
            params={"api-version": "2021-04-01"},
        )

    # ----- Flow APIs -----

    def get_flows(self, env_id: str) -> list:
        """List all flows in an environment (admin scope)."""
        return self._get_all(
            POWERAPPS_BASE,
            f"/providers/Microsoft.ProcessSimple/scopes/admin/environments/{env_id}/v2/flows",
            params={"api-version": "2016-11-01"},
        )

    def get_flow(self, env_id: str, flow_id: str) -> dict:
        """Get a specific flow."""
        return self._get(
            POWERAPPS_BASE,
            f"/providers/Microsoft.ProcessSimple/scopes/admin/environments/{env_id}/flows/{flow_id}",
            params={"api-version": "2016-11-01"},
        )

    # ----- Connection APIs -----

    def get_connections(self, env_id: str) -> list:
        """List all connections in an environment (admin scope)."""
        return self._get_all(
            POWERAPPS_BASE,
            f"/providers/Microsoft.PowerApps/scopes/admin/environments/{env_id}/connections",
            params={"api-version": "2016-11-01"},
        )

    # ----- DLP Policy APIs -----

    def get_dlp_policies(self) -> list:
        """List all DLP policies."""
        return self._get_all(
            BAP_BASE,
            "/providers/Microsoft.BusinessAppPlatform/scopes/admin/apiPolicies",
            params={"api-version": "2021-04-01"},
        )

    def get_dlp_policies_for_env(self, env_id: str) -> list:
        """List DLP policies applied to a specific environment."""
        all_policies = self.get_dlp_policies()
        # Filter to policies that include this environment
        relevant = []
        for p in all_policies:
            env_list = (
                p.get("properties", {})
                .get("environmentFilter", {})
                .get("environments", [])
            )
            env_ids = [e.get("name", "") for e in env_list]
            # If no env filter, policy applies to all
            if not env_ids or env_id in env_ids:
                relevant.append(p)
        return relevant


def derive_environment_id(env_url: str, dataverse_token: str) -> str | None:
    """Derive the Power Platform Environment ID from a Dataverse URL.

    Calls the Dataverse WhoAmI endpoint, then uses the OrganizationId
    to query the BAP API for the matching environment.
    """
    headers = {
        "Authorization": f"Bearer {dataverse_token}",
        "Accept": "application/json",
    }
    resp = requests.get(
        f"{env_url}/api/data/v9.2/WhoAmI()",
        headers=headers,
        timeout=15,
    )
    if resp.status_code != 200:
        return None
    org_id = resp.json().get("OrganizationId")
    if not org_id:
        return None

    # The environment ID in BAP is the same as the OrganizationId
    # (lowercase GUID without braces)
    return org_id.lower().strip("{}")
