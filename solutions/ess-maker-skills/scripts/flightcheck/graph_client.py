# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Microsoft Graph REST API Client

Provides authenticated access to Microsoft Graph for FlightCheck checks
(licenses, roles, Entra ID, conditional access, user sync).

Reuses the same MSAL token cache as auth.py so users don't sign in twice.
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

# Module-level requests Session with bounded retry-with-backoff for 429/5xx.
# Mirrors the auth.py pattern - Graph throttles on /users and /servicePrincipals
# in larger tenants, and one transient 503 mid-FlightCheck would otherwise blow
# up the whole readiness report. Read-only verbs only; FlightCheck never
# mutates tenant state through this client.
_RETRY = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "HEAD", "OPTIONS"]),
    respect_retry_after_header=True,
)
_SESSION = requests.Session()
_SESSION.mount("https://", HTTPAdapter(max_retries=_RETRY))


class GraphClient:
    """Lightweight Microsoft Graph client with MSAL interactive auth."""

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self._token: str | None = None

    def authenticate(self) -> str:
        """Acquire a Graph access token, reusing the shared MSAL cache."""
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        cache = msal.SerializableTokenCache()
        cache_path = os.path.join(".local", ".token_cache.bin")

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
            # Don't echo error_description - it can include tenant IDs and
            # internal flow details (CWE-209). Mirrors the auth.py pattern.
            error = result.get("error", "unknown_error")
            raise RuntimeError(f"Graph authentication failed ({error}).")

        # Persist cache with strict 0o600 permissions on POSIX. The cache
        # holds MSAL refresh tokens; default umask (0o644) would expose them
        # to other users on shared dev VMs.
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
            "ConsistencyLevel": "eventual",
        }

    # ----- Graph query helpers -----

    def get(self, path: str, params: dict | None = None) -> dict:
        """GET a Graph endpoint. Returns parsed JSON."""
        url = f"{GRAPH_BASE}{path}"
        resp = _SESSION.get(url, headers=self.headers, params=params, timeout=30)
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
            resp = _SESSION.get(url, headers=self.headers, params=params, timeout=30)
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
