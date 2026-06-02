# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit — Power Platform Admin REST API Client

Provides authenticated access to Power Platform Admin (BAP) APIs and
PowerApps APIs for FlightCheck checks (environments, flows, connections, DLP).

Authentication uses the same MSAL cache as auth.py / graph_client.py.
"""

import os
import sys
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


CLIENT_ID = "51f81489-12ee-4a9e-aaae-a2591f45987d"

BAP_BASE = "https://api.bap.microsoft.com"
POWERAPPS_BASE = "https://api.powerapps.com"
# Power Automate (Flow) admin endpoints live on a separate host from
# PowerApps. `api.powerapps.com/.../scopes/admin/.../v2/flows` returns
# 404 (the path simply does not exist on that host); the equivalent
# admin endpoint that DOES exist is on `api.flow.microsoft.com`. It
# also requires its own audience token (service.flow.microsoft.com),
# not the powerapps.com token used for the BAP / connection endpoints.
# Probed 2026-05 — see tests/captures/probe_flows_endpoint.py for the
# data.
FLOW_BASE = "https://api.flow.microsoft.com"

# The BAP / PowerApps APIs use this resource scope.
PP_SCOPE = "https://service.powerapps.com//.default"
# Power Automate (Flow) admin API uses its own audience.
FLOW_SCOPE = "https://service.flow.microsoft.com//.default"

# Module-level requests Session with bounded retry-with-backoff for 429/5xx.
# Mirrors the auth.py pattern - BAP and PowerApps APIs throttle aggressively
# enough that a single transient 503 mid-FlightCheck would otherwise blow up
# the whole readiness report. Read-only verbs only; FlightCheck never mutates
# tenant state through these clients.
_RETRY = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "HEAD", "OPTIONS"]),
    respect_retry_after_header=True,
)
_SESSION = requests.Session()
_SESSION.mount("https://", HTTPAdapter(max_retries=_RETRY))


class PPAdminClient:
    """Power Platform Admin API client for environment and flow queries."""

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self._token: str | None = None

    def authenticate(self) -> str:
        """Acquire Power Platform access tokens.

        Acquires BOTH the PowerApps audience token (used for BAP / BAP
        admin / PowerApps connections / DLP) and the Flow audience
        token (used for the Power Automate admin flow-listing
        endpoint at api.flow.microsoft.com). The two endpoints live
        on different hosts and require different audience tokens —
        acquiring only the PowerApps token leaves the flow endpoints
        returning AuthenticationFailed.

        Returns the PowerApps token for backwards compatibility.
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

        def acquire(scope: str, label: str) -> str:
            result = None
            if accounts:
                result = app.acquire_token_silent([scope], account=accounts[0])
            if not result or "access_token" not in result:
                print(f"Opening browser for Power Platform sign-in ({label})...")
                result = app.acquire_token_interactive(
                    [scope], prompt="select_account"
                )
            if "access_token" not in result:
                # Don't echo error_description - it can include tenant IDs and
                # internal flow details (CWE-209). Mirrors the auth.py pattern.
                error = result.get("error", "unknown_error")
                raise RuntimeError(f"Power Platform auth failed for {label} ({error}).")
            return result["access_token"]

        pp_token = acquire(PP_SCOPE, "PowerApps/BAP")
        flow_token = acquire(FLOW_SCOPE, "Power Automate (Flow)")

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

        self._token = pp_token
        self._flow_token = flow_token
        return self._token

    @property
    def headers(self) -> dict:
        if not self._token:
            raise RuntimeError("Call authenticate() first")
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }

    @property
    def flow_headers(self) -> dict:
        """Headers for calls against api.flow.microsoft.com.

        Power Automate admin endpoints require the
        service.flow.microsoft.com audience token, not the powerapps
        audience used by `.headers`. Returns the same shape so callers
        can swap in transparently.
        """
        if not getattr(self, "_flow_token", None):
            raise RuntimeError("Call authenticate() first")
        return {
            "Authorization": f"Bearer {self._flow_token}",
            "Accept": "application/json",
        }

    def _get(self, base: str, path: str, params: dict | None = None, *, use_flow_token: bool = False) -> dict:
        url = f"{base}{path}"
        h = self.flow_headers if use_flow_token else self.headers
        resp = _SESSION.get(url, headers=h, params=params, timeout=60)
        if resp.status_code in (401, 403):
            return {"_error": "insufficient_permissions", "_status": resp.status_code}
        resp.raise_for_status()
        return resp.json()

    def _get_all(self, base: str, path: str, params: dict | None = None, *, use_flow_token: bool = False) -> list:
        """Paginate through results."""
        items: list = []
        url = f"{base}{path}"
        h = self.flow_headers if use_flow_token else self.headers
        while url:
            resp = _SESSION.get(url, headers=h, params=params, timeout=60)
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

    def find_environment_id_by_dataverse_url(self, env_url: str) -> str | None:
        """Find the BAP environment "name" (the BAP env id) whose
        `linkedEnvironmentMetadata.instanceUrl` matches `env_url`.

        The BAP env id is NOT the same as the Dataverse OrganizationId.
        Every BAP admin endpoint (`/scopes/admin/environments/{env_id}/...`)
        expects the BAP id. Passing the Dataverse OrganizationId here
        returns 404 (BAP masks the "no such env" path as 404, not 400),
        which is what was breaking EXT-001 / ENV-001 and the entire
        Workday block (no flows discovered ⇒ deep checks skipped).

        Matches by hostname comparison so trailing slash / casing
        differences between config and BAP don't cause a miss.
        """
        target_host = (urlparse(env_url.rstrip("/")).hostname or "").lower()
        if not target_host:
            return None
        envs = self.get_environments()
        if isinstance(envs, dict) and "_error" in envs:
            return None
        for env in envs:
            instance_url = (
                env.get("properties", {})
                .get("linkedEnvironmentMetadata", {})
                .get("instanceUrl", "")
            )
            instance_host = (urlparse(instance_url).hostname or "").lower()
            if instance_host == target_host:
                return env.get("name")
        return None

    # ----- Flow APIs -----
    # Power Automate's admin flow endpoints live on api.flow.microsoft.com
    # and require the service.flow.microsoft.com audience token. The
    # historical path on api.powerapps.com (also used by earlier kit
    # versions) returns 404 — it just doesn't exist there.

    def get_flows(self, env_id: str) -> list:
        """List all flows in an environment (admin scope)."""
        return self._get_all(
            FLOW_BASE,
            f"/providers/Microsoft.ProcessSimple/scopes/admin/environments/{env_id}/v2/flows",
            params={"api-version": "2016-11-01"},
            use_flow_token=True,
        )

    def get_flow(self, env_id: str, flow_id: str) -> dict:
        """Get a specific flow."""
        return self._get(
            FLOW_BASE,
            f"/providers/Microsoft.ProcessSimple/scopes/admin/environments/{env_id}/flows/{flow_id}",
            params={"api-version": "2016-11-01"},
            use_flow_token=True,
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


def derive_environment_id(
    env_url: str,
    dataverse_token: str,
    pp_admin: "PPAdminClient | None" = None,
) -> str | None:
    """Derive the Power Platform (BAP) Environment ID from a Dataverse URL.

    The BAP env id is the value used by every
    `…/scopes/admin/environments/{env_id}/…` URL in this client. It is
    NOT the same as the Dataverse `OrganizationId` returned by `WhoAmI()`
    — they coincide only by accident. Earlier versions of this function
    returned the OrganizationId directly, which caused every BAP admin
    call to 404 (BAP masks "no such env" as 404, not 400) for tenants
    where the two ids diverged.

    Preferred path (when `pp_admin` is supplied and authenticated):
      list BAP admin environments and match `linkedEnvironmentMetadata.instanceUrl`
      against `env_url`. The matching env's `name` is the BAP env id.

    Fallback path (legacy / no BAP token yet):
      WhoAmI returns the Dataverse `OrganizationId`. This is wrong as a
      BAP env id but is retained so callers without a BAP client still
      get *something* (some checks tolerate the wrong id; everything
      hitting admin endpoints does not). Callers SHOULD pass
      `pp_admin` to get the correct id.
    """
    if pp_admin is not None:
        bap_id = pp_admin.find_environment_id_by_dataverse_url(env_url)
        if bap_id:
            return bap_id
        # Fall through to the legacy WhoAmI behavior so the caller still
        # sees a (possibly wrong) value and a "could not resolve via BAP"
        # diagnostic — easier to debug than a silent None.

    # HARD GATE: refuse to attach the Dataverse bearer to a non-HTTPS URL.
    # env_url is config-supplied so a misconfigured or hostile value could
    # otherwise exfiltrate the token over cleartext. Mirrors the
    # _validate_https_url gate in auth.py.
    if not env_url.lower().startswith("https://"):
        raise ValueError(
            f"env_url must use https:// (got: {env_url!r}). Refusing to send "
            "the Dataverse bearer token over an unencrypted channel."
        )
    headers = {
        "Authorization": f"Bearer {dataverse_token}",
        "Accept": "application/json",
    }
    resp = _SESSION.get(
        f"{env_url}/api/data/v9.2/WhoAmI()",
        headers=headers,
        timeout=15,
    )
    if resp.status_code != 200:
        return None
    org_id = resp.json().get("OrganizationId")
    if not org_id:
        return None

    # Dataverse OrganizationId, lowercase, braces stripped. This is the
    # LEGACY fallback only; it is NOT the BAP env id in general. See
    # docstring above and prefer the pp_admin-backed path.
    return org_id.lower().strip("{}")
