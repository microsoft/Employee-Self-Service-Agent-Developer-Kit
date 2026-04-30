# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Copilot Kit — Microsoft Graph REST API Client

Provides authenticated access to Microsoft Graph for FlightCheck checks
(licenses, roles, Entra ID, conditional access, user sync).

Reuses the same MSAL token cache as auth.py so users don't sign in twice.
"""

import json
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


# Well-known Microsoft client IDs.
# Use the Microsoft Graph Command Line Tools app ID, which is a well-known
# first-party app with preauthorized Graph delegated permissions.
GRAPH_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Scopes needed for FlightCheck Graph queries (all read-only).
GRAPH_SCOPES = [
    "https://graph.microsoft.com/Organization.Read.All",
    "https://graph.microsoft.com/Directory.Read.All",
    "https://graph.microsoft.com/User.Read.All",
    "https://graph.microsoft.com/Policy.Read.All",
]


class GraphClient:
    """Lightweight Microsoft Graph client with MSAL interactive auth."""

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self._token: str | None = None

    def authenticate(self) -> str:
        """Acquire a Graph access token, reusing the shared MSAL cache."""
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        cache = msal.SerializableTokenCache()
        cache_path = os.path.join("my", ".token_cache.bin")

        if os.path.exists(cache_path):
            with open(cache_path, "r") as f:
                cache.deserialize(f.read())

        app = msal.PublicClientApplication(
            GRAPH_CLIENT_ID, authority=authority, token_cache=cache
        )

        # Try silent first
        accounts = app.get_accounts()
        result = None
        if accounts:
            result = app.acquire_token_silent(GRAPH_SCOPES, account=accounts[0])

        if not result or "access_token" not in result:
            print("Opening browser for Microsoft Graph sign-in...")
            result = app.acquire_token_interactive(
                GRAPH_SCOPES, prompt="select_account"
            )

        if "access_token" not in result:
            error = result.get("error_description", result.get("error", "Unknown"))
            raise RuntimeError(f"Graph authentication failed: {error}")

        # Persist cache
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
            "ConsistencyLevel": "eventual",
        }

    # ----- Graph query helpers -----

    def get(self, path: str, params: dict | None = None) -> dict:
        """GET a Graph endpoint. Returns parsed JSON."""
        url = f"{GRAPH_BASE}{path}"
        resp = requests.get(url, headers=self.headers, params=params, timeout=30)
        if resp.status_code == 403:
            return {"_error": "insufficient_permissions", "_status": 403}
        if resp.status_code == 401:
            return {"_error": "token_expired", "_status": 401}
        resp.raise_for_status()
        return resp.json()

    def get_all(self, path: str, params: dict | None = None) -> list:
        """GET with @odata.nextLink pagination. Returns all items."""
        items: list = []
        url = f"{GRAPH_BASE}{path}"
        while url:
            resp = requests.get(url, headers=self.headers, params=params, timeout=30)
            if resp.status_code in (401, 403):
                return items  # partial results
            resp.raise_for_status()
            data = resp.json()
            items.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
            params = None  # nextLink is fully qualified
        return items

    # ----- Convenience methods for common FlightCheck queries -----

    def get_subscribed_skus(self) -> list:
        """List all subscribed SKUs (licenses) in the tenant."""
        return self.get_all("/subscribedSkus")

    def get_organization(self) -> dict:
        """Get tenant organization info."""
        orgs = self.get_all("/organization")
        return orgs[0] if orgs else {}

    def get_directory_roles(self) -> list:
        """List activated directory roles."""
        return self.get_all("/directoryRoles")

    def get_role_members(self, role_id: str) -> list:
        """List members of a directory role."""
        return self.get_all(f"/directoryRoles/{role_id}/members")

    def get_conditional_access_policies(self) -> list:
        """List Conditional Access policies."""
        return self.get_all("/identity/conditionalAccess/policies")

    def get_users_sample(self, top: int = 10) -> list:
        """Get a sample of users for sync verification."""
        data = self.get("/users", params={"$top": str(top)})
        return data.get("value", [])

    def get_service_principals(self, filter_expr: str = "") -> list:
        """List service principals (enterprise apps) with optional filter."""
        params = {}
        if filter_expr:
            params["$filter"] = filter_expr
        return self.get_all("/servicePrincipals", params=params)
