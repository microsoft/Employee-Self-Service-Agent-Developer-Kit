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


def _policy_env_scope(policy: dict) -> tuple[str | None, list[str]]:
    """Return ``(filter_type, env_ids)`` for a DLP policy's environment scope.

    The apiPolicies endpoint expresses environment scope in one of two
    shapes; this reads both:

    * Legacy: ``properties.environmentFilter.environments[].name`` (with an
      optional ``filterType``; historically an include list).
    * Modern: ``properties.definition.constraints.<key>`` where
      ``type == "EnvironmentFilter"`` and
      ``parameters.{filterType, environments[].name}``.

    ``filter_type`` is ``"include"`` | ``"exclude"`` | ``None``. When no
    environment filter is present ``env_ids`` is empty and the policy
    applies to ALL environments.
    """
    if not isinstance(policy, dict):
        return None, []
    props = policy.get("properties", {})
    if not isinstance(props, dict):
        return None, []

    # Legacy shape: properties.environmentFilter
    legacy = props.get("environmentFilter")
    if isinstance(legacy, dict):
        env_list = legacy.get("environments") or []
        ids = [e.get("name", "") for e in env_list if isinstance(e, dict)]
        if ids:
            ft = str(legacy.get("filterType", "include")).strip().lower()
            return ft, ids

    # Modern shape: properties.definition.constraints.<key> (EnvironmentFilter)
    definition = props.get("definition")
    if isinstance(definition, dict):
        constraints = definition.get("constraints")
        if isinstance(constraints, dict):
            for constraint in constraints.values():
                if not isinstance(constraint, dict):
                    continue
                if constraint.get("type") != "EnvironmentFilter":
                    continue
                params = constraint.get("parameters") or {}
                env_list = params.get("environments") or []
                ids = [e.get("name", "") for e in env_list if isinstance(e, dict)]
                if ids:
                    ft = str(params.get("filterType", "include")).strip().lower()
                    return ft, ids

    return None, []


def _policy_applies_to_env(policy: dict, env_id: str) -> bool:
    """Whether a DLP policy is effective on ``env_id``.

    An unscoped policy (no environment filter) applies to all
    environments. An ``include`` filter applies only to the listed
    environments; an ``exclude`` filter applies to every environment
    EXCEPT the listed ones.
    """
    filter_type, env_ids = _policy_env_scope(policy)
    if not env_ids:
        return True  # tenant-wide
    if filter_type == "exclude":
        return env_id not in env_ids
    return env_id in env_ids  # include (default)


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

    def authenticate_silent(self) -> bool:
        """Acquire a PowerApps/BAP token from cache WITHOUT prompting.

        Unlike :meth:`authenticate`, this never opens a browser: it only
        tries ``acquire_token_silent`` against the shared MSAL cache
        (``.local/.token_cache.bin``). Intended for best-effort background
        lookups (e.g. resolving an environment SKU during telemetry) that
        must never block or interrupt the user. Returns True if a token was
        obtained (``self._token`` set), False otherwise. Only the PowerApps
        audience is acquired — callers needing flow endpoints must use the
        interactive :meth:`authenticate`.
        """
        try:
            authority = f"https://login.microsoftonline.com/{self.tenant_id}"
            cache = msal.SerializableTokenCache()
            cache_path = os.path.join(".local", ".token_cache.bin")
            if not os.path.exists(cache_path):
                return False
            with open(cache_path, "r") as f:
                cache.deserialize(f.read())
            app = msal.PublicClientApplication(
                CLIENT_ID, authority=authority, token_cache=cache
            )
            accounts = app.get_accounts()
            if not accounts:
                return False
            result = app.acquire_token_silent([PP_SCOPE], account=accounts[0])
            if not result or "access_token" not in result:
                return False
            self._token = result["access_token"]
            return True
        except Exception:  # noqa: BLE001 — best-effort, never raise to caller
            return False

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

    def _get_all(self, base: str, path: str, params: dict | None = None, *, use_flow_token: bool = False) -> list | dict:
        """Paginate through results.

        On 401/403 returns a structured ``{"_error": ...}`` dict (matching
        ``_get``) so callers surface the permission failure instead of
        mistaking a swallowed auth error for an empty collection. Every
        consumer of the list-returning methods (get_connections,
        get_flows, get_environments, get_dlp_policies) already guards
        with ``isinstance(result, dict) and "_error" in result``.
        """
        items: list = []
        url = f"{base}{path}"
        h = self.flow_headers if use_flow_token else self.headers
        while url:
            resp = _SESSION.get(url, headers=h, params=params, timeout=60)
            if resp.status_code in (401, 403):
                return {"_error": "insufficient_permissions", "_status": resp.status_code}
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
        linked Dataverse instance matches `env_url`.

        The BAP env id is NOT the same as the Dataverse OrganizationId.
        Every BAP admin endpoint (`/scopes/admin/environments/{env_id}/...`)
        expects the BAP id. Passing the Dataverse OrganizationId here
        returns 404 (BAP masks the "no such env" path as 404, not 400),
        which is what was breaking EXT-001 / ENV-001 and the entire
        Workday block (no flows discovered ⇒ deep checks skipped).

        Matches by hostname against BOTH `linkedEnvironmentMetadata.instanceUrl`
        and `linkedEnvironmentMetadata.instanceApiUrl`. BAP advertises the
        web hostname (e.g. ``org<hash>.crm12.dynamics.com``) on one field and
        the Web API hostname (``org<hash>.api.crm12.dynamics.com``) on the
        other; the config's `dataverseEndpoint` is typically the API form,
        so checking only `instanceUrl` silently misses every match on a
        tenant whose config uses the `.api.` hostname.
        """
        target_host = (urlparse(env_url.rstrip("/")).hostname or "").lower()
        if not target_host:
            return None
        envs = self.get_environments()
        if isinstance(envs, dict) and "_error" in envs:
            return None
        for env in envs:
            linked = env.get("properties", {}).get("linkedEnvironmentMetadata", {})
            for url_field in ("instanceUrl", "instanceApiUrl"):
                candidate = linked.get(url_field, "")
                if not candidate:
                    continue
                candidate_host = (urlparse(candidate).hostname or "").lower()
                if candidate_host == target_host:
                    return env.get("name")
        return None

    def get_environment_sku_by_dataverse_url(self, env_url: str) -> str | None:
        """Return the ``environmentSku`` of the BAP environment whose linked
        Dataverse instance matches ``env_url`` (host match against both
        ``instanceUrl`` and ``instanceApiUrl``), or ``None`` if not found.

        Mirrors :meth:`find_environment_id_by_dataverse_url` but returns the
        SKU (e.g. Production/Default/Sandbox/Trial/Developer) rather than the
        BAP env id — used to classify deploy telemetry into sandbox vs
        production.
        """
        target_host = (urlparse(env_url.rstrip("/")).hostname or "").lower()
        if not target_host:
            return None
        envs = self.get_environments()
        if isinstance(envs, dict) and "_error" in envs:
            return None
        for env in envs:
            props = env.get("properties", {})
            linked = props.get("linkedEnvironmentMetadata", {})
            for url_field in ("instanceUrl", "instanceApiUrl"):
                candidate = linked.get(url_field, "")
                if not candidate:
                    continue
                candidate_host = (urlparse(candidate).hostname or "").lower()
                if candidate_host == target_host:
                    return props.get("environmentSku") or props.get("environmentType")
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

    def get_flow_runs(self, env_id: str, flow_id: str) -> list | dict:
        """List recent runs (run history) for a cloud flow.

        Uses the Power Automate *runtime* runs endpoint (maker/owner scope) —
        run history is NOT exposed on the ``/scopes/admin`` governance surface,
        so this path omits ``scopes/admin``. Same host + audience as
        ``get_flows`` (``api.flow.microsoft.com`` / ``service.flow.microsoft.com``
        token).

        Returns the first page of runs (newest first). We deliberately do NOT
        paginate the whole history — a health check only needs recent runs.
        On 401/403 returns the structured ``{"_error": ...}`` dict (matching
        ``_get``) so callers surface a permission failure instead of mistaking
        it for "no runs".

        Each run record carries (see WD-RUN-001 + the cassette for the shape):
          - ``properties.status``        — "Succeeded" / "Failed" / "Cancelled" / "Running"
          - ``properties.response.name`` — the flow's success-vs-failure Response action
        """
        resp = self._get(
            FLOW_BASE,
            f"/providers/Microsoft.ProcessSimple/environments/{env_id}/flows/{flow_id}/runs",
            params={"api-version": "2016-11-01"},
            use_flow_token=True,
        )
        if isinstance(resp, dict) and "_error" in resp:
            return resp
        return resp.get("value", [])

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

    def get_dlp_policies_for_env(self, env_id: str) -> list | dict:
        """List DLP policies applied to a specific environment."""
        all_policies = self.get_dlp_policies()
        # Surface a permission failure rather than treating it as "no
        # DLP policies" — the caller (ENV-008) renders this as a SKIP
        # ("requires Power Platform Administrator") instead of a false
        # "environment is unrestricted" verdict.
        if isinstance(all_policies, dict) and "_error" in all_policies:
            return all_policies
        # Filter to policies effective on this environment.
        relevant = []
        for p in all_policies:
            if _policy_applies_to_env(p, env_id):
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
      list BAP admin environments and match against
      `linkedEnvironmentMetadata.instanceUrl` / `instanceApiUrl`. The
      matching env's `name` is the BAP env id.

      If the BAP lookup MISSES (no env matches the hostname, e.g. the
      user lacks admin access on that env), this function returns None
      and lets the caller surface a clear "couldn't resolve via BAP"
      message. We deliberately do NOT fall back to the WhoAmI /
      OrganizationId path here: that value silently corrupts both BAP
      admin calls (404s) and any deep links that embed the env id (the
      deep link points at a non-existent env). A clean None lets
      downstream callers (e.g., the Copilot Studio deep-link builder)
      degrade gracefully to the homepage rather than fabricate a wrong
      target.

    Legacy fallback path (only when `pp_admin` is None):
      WhoAmI returns the Dataverse `OrganizationId`. This is wrong as a
      BAP env id but is retained so callers without a BAP client still
      get *something* for non-BAP checks. New callers SHOULD pass
      `pp_admin` to get the correct id and surface a missed lookup
      explicitly.
    """
    if pp_admin is not None:
        # When BAP is reachable, trust the BAP answer (or its absence).
        # A None here means "could not resolve via BAP" — callers should
        # surface this rather than papering over with WhoAmI/OrganizationId,
        # which corrupts both BAP admin calls and any URL that embeds env id.
        return pp_admin.find_environment_id_by_dataverse_url(env_url)

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
