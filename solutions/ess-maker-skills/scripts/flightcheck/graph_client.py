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
    # Read-only access to Microsoft Graph external connectors (the Graph
    # Connector knowledge sources customers attach to ESS). Used by
    # EXT-002 — Graph Connector KB readiness. Per
    # https://learn.microsoft.com/graph/api/externalconnectors-external-list-connections
    # the list operation requires either ExternalConnection.Read.All or
    # ExternalConnection.ReadWrite.OwnedBy / ExternalConnection.ReadWrite.All.
    # We ask for the read-only one because FlightCheck never mutates state.
    "https://graph.microsoft.com/ExternalConnection.Read.All",
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

    def get_all(
        self,
        path: str,
        params: dict | None = None,
        *,
        raise_on_permission_error: bool = False,
    ) -> list:
        """GET with @odata.nextLink pagination. Returns all items.

        Default behavior on HTTP 401/403 is to return whatever items
        were already collected (partial results) — most FlightCheck
        callers prefer "show what we can see, silently degrade." When
        the caller needs to distinguish "no items exist" from
        "permission denied" (e.g. AUTH-005, where a denied
        appRoleAssignedTo lookup must NOT false-alarm as a Sev-2
        "0 users assigned" finding), pass
        ``raise_on_permission_error=True`` to convert 401/403 into a
        ``PermissionError`` instead.
        """
        items: list = []
        url = f"{GRAPH_BASE}{path}"
        while url:
            resp = _SESSION.get(url, headers=self.headers, params=params, timeout=30)
            if resp.status_code in (401, 403):
                if raise_on_permission_error:
                    raise PermissionError(
                        f"Graph returned HTTP {resp.status_code} on {path}."
                    )
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

    def get_service_principals(
        self,
        filter_expr: str = "",
        *,
        raise_on_permission_error: bool = False,
    ) -> list:
        """List service principals (enterprise apps) with optional filter.

        Default behavior swallows 401/403 into an empty list (matches
        ``get_all()``'s default). Pass ``raise_on_permission_error=True``
        to convert 401/403 into a ``PermissionError`` instead — needed
        when the caller has to distinguish "no SAML apps exist" from
        "missing Application.Read.All consent" (e.g. AUTH-006,
        WD-CONN-010). Mirrors the kwarg on ``get_app_role_assignments``.
        """
        params = {}
        if filter_expr:
            params["$filter"] = filter_expr
        return self.get_all(
            "/servicePrincipals",
            params=params,
            raise_on_permission_error=raise_on_permission_error,
        )

    # ----- Entra Enterprise App user/group assignment (AUTH-005) -----

    def get_app_role_assignments(self, sp_id: str) -> list:
        """List principals (users, groups, service principals) assigned to
        the resource service principal identified by ``sp_id``.

        Returns the collection from
        ``GET /servicePrincipals/{id}/appRoleAssignedTo`` — each item is an
        appRoleAssignment with ``principalId``, ``principalType``
        (``User`` | ``Group`` | ``ServicePrincipal``), ``principalDisplayName``,
        and ``appRoleId``.

        Raises ``PermissionError`` on HTTP 401/403 so callers can
        distinguish "permission denied" from "no assignments exist."
        Without this, ``get_all()``'s default silent-on-401/403 behavior
        would make a denied appRoleAssignedTo lookup look identical to
        a legitimately empty list — letting a Workday SP with a scoped
        Conditional Access policy or a permission-restricted directory
        role false-alarm as "no users/groups assigned" (a Sev-2-shaped
        finding) when the real cause is the kit's own token lacking
        access. AUTH-005 explicitly catches PermissionError and routes
        to WARNING with a permission-remediation message; AUTH-006
        uses the same defensive pattern via a ``graph.get()`` probe.

        Docs: https://learn.microsoft.com/graph/api/serviceprincipal-list-approleassignedto
        """
        path = f"/servicePrincipals/{sp_id}/appRoleAssignedTo"
        try:
            return self.get_all(path, raise_on_permission_error=True)
        except PermissionError as e:
            # Re-raise with a more actionable message (the bare get_all
            # error only mentions the path and status code).
            raise PermissionError(
                f"{e} Requires Application.Read.All or Directory.Read.All."
            ) from e

    def get_application_templates(self, filter_expr: str = "") -> list:
        """List Entra application gallery templates.

        ``GET /v1.0/applicationTemplates`` returns the tenant-independent
        catalog of gallery apps (Workday, ServiceNow, Salesforce, ...).
        Each template has a stable ``id`` (set once when Microsoft
        registered the template) and a list of ``categories``
        (``"Single sign-on"``, ``"User Provisioning"``, ...). When an
        operator provisions an app from the Entra gallery, the
        resulting ``servicePrincipal.applicationTemplateId`` points
        back at this id — so matching SPs by ``applicationTemplateId``
        is the rename-proof way to discover gallery apps.

        No special permission is required (this endpoint exposes
        tenant-independent gallery metadata). On HTTP 401/403 we raise
        ``PermissionError`` rather than silently returning [] so the
        caller can distinguish "Microsoft shipped no matching template"
        (empty list, file an issue) from "we couldn't read the
        catalog" (consent/token problem, fix the token).

        Docs: https://learn.microsoft.com/graph/api/applicationtemplate-list
        """
        params = {}
        if filter_expr:
            params["$filter"] = filter_expr
        return self.get_all(
            "/applicationTemplates",
            params=params,
            raise_on_permission_error=True,
        )

    # ----- Microsoft Graph external connectors (Graph Connectors) -----
    #
    # Used by EXT-002 (Graph Connector KB readiness). The customer-facing
    # "Graph Connector" surface in M365 Admin Center is exposed via the
    # Microsoft Graph external connectors API:
    # https://learn.microsoft.com/graph/api/resources/externalconnectors-externalconnection
    #
    # We never mutate state — the calls below are read-only.

    def get_external_connections(self) -> list:
        """List all Microsoft Graph external connections in the tenant.

        GET /v1.0/external/connections — paginated.
        See https://learn.microsoft.com/graph/api/externalconnectors-external-list-connections.
        """
        return self.get_all("/external/connections")

    def get_external_connection(self, connection_id: str) -> dict:
        """Get a single external connection by its admin-assigned id.

        GET /v1.0/external/connections/{id}.
        See https://learn.microsoft.com/graph/api/externalconnectors-externalconnection-get.

        Returns the parsed JSON body, or a `{"_error": ..., "_status": 404}`
        dict if the connection does not exist (the kit's standard
        "missing resource" sentinel — see ``GraphClient.get`` which
        already converts 401/403 to the same shape).
        """
        url = f"{GRAPH_BASE}/external/connections/{connection_id}"
        resp = _SESSION.get(url, headers=self.headers, timeout=30)
        if resp.status_code == 404:
            return {"_error": "not_found", "_status": 404}
        if resp.status_code in (401, 403):
            return {"_error": "insufficient_permissions", "_status": resp.status_code}
        resp.raise_for_status()
        return resp.json()

    def get_connection_operations(self, connection_id: str) -> list:
        """List crawl operations for a Graph external connection.

        GET /v1.0/external/connections/{id}/operations — paginated.
        See https://learn.microsoft.com/graph/api/externalconnectors-externalconnection-list-operations.

        Each operation has a ``status`` field
        (``unspecified`` | ``inprogress`` | ``completed`` | ``failed``)
        and an optional ``error`` field. EXT-002 inspects the most recent
        operation to detect silent crawl failures.
        """
        return self.get_all(f"/external/connections/{connection_id}/operations")

    def get_claims_mapping_policies(self, service_principal_id: str) -> list:
        """List claimsMappingPolicy objects assigned to a service principal.

        Used by AUTH-006 to read the SAML token-issuance overrides Entra
        applies for a federated enterprise app (e.g., the customer's
        Workday SAML app). An empty list means no policy is assigned
        and the application uses Entra's default claim set
        (NameID = user.userPrincipalName).

        Source (validatable):
          Schema:  https://graph.microsoft.com/v1.0/$metadata
                   EntityType Name="claimsMappingPolicy"
          Docs:    https://learn.microsoft.com/graph/api/serviceprincipal-list-claimsmappingpolicies?view=graph-rest-1.0

        Requires Policy.Read.All (already requested by this client).
        """
        return self.get_all(
            f"/servicePrincipals/{service_principal_id}/claimsMappingPolicies"
        )
