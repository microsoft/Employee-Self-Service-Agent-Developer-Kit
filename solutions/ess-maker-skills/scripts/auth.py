# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
ESS Maker Kit - Shared Dataverse Authentication

Provides MSAL-based interactive browser auth with token caching and
Dataverse REST API helpers. Used by fetch_and_setup.py and push.py.
"""

import json
import os
import re
import sys
import stat
import time
from urllib.parse import quote

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

from http_errors import APIError, raise_api_error  # noqa: E402


# Microsoft public client ID for Power Platform CLI / Dataverse delegated access.
# Source: https://learn.microsoft.com/power-platform/admin/programmability-authentication-v2
# Scope: user_impersonation only (delegated, no admin consent).
CLIENT_ID = "51f81489-12ee-4a9e-aaae-a2591f45987d"

# Kit-internal state directory (token cache, component maps, config).
# Renamed from "my/" -> ".local/" in PR #2 to separate kit-internal state
# from user-edited files (which live under "workspace/").
LOCAL_STATE_DIR = ".local"

# Schema version stamped into .local/config.json by setup.py and gated by
# load_config() below. Bump this when the on-disk schema changes in a way
# old consumers can't tolerate, AND update setup.py to migrate or rewrite
# config.json on the next run.
EXPECTED_CONFIG_VERSION = 1

HEADERS_BASE = {
    "Accept": "application/json",
    "OData-MaxVersion": "4.0",
    "OData-Version": "4.0",
    "Prefer": "odata.include-annotations=*",
}


class AuthExpiredError(APIError):
    """Raised when a Dataverse call returns 401. Callers can catch this and
    re-authenticate without losing in-flight push state.

    Subclasses APIError so generic ``except APIError`` handlers (e.g. in
    discover.py, fetch_and_setup.py) also catch 401s and render the friendly
    "session expired" message. Code that wants to specifically intercept 401
    for re-auth (push.py) keeps using ``except AuthExpiredError``.
    """

    def __init__(self, message=None, response=None):
        # Preserve the legacy positional ``message`` argument for callers and
        # tests that construct AuthExpiredError("...") directly. When a real
        # Response is available, pass it through so URL / method / request_id
        # show up in format_for_terminal() output.
        super().__init__(
            response=response,
            status_code=401,
            operation="access",
            message=message,
        )


# Module-level requests Session with bounded retry-with-backoff for 429/5xx.
# Power Platform throttles aggressively; one transient 503 mid-push otherwise
# leaves the customer in partial state. The session lives for the process so
# connection pools and retry adapters are reused across all Dataverse calls.
#
# IMPORTANT: allowed_methods is restricted to read-only verbs. urllib3 will
# replay any method in this set on 429/5xx, which is unsafe for POST (could
# create duplicate records when the first request landed but the response
# packet was lost) and unsafe for PATCH/DELETE in the response-lost scenario
# (caller can't tell whether the original write succeeded). Mutating verbs
# need throttle handling at the call site with explicit logic - they are NOT
# automatically retried by this Session.
_RETRY = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET", "HEAD", "OPTIONS"]),
    respect_retry_after_header=True,
)
_SESSION = requests.Session()
_SESSION.mount("https://", HTTPAdapter(max_retries=_RETRY))


def _emit_api_call(endpoint, operation, start, *, status=None, error=None):
    """Best-effort ``adk.api.call`` telemetry for a Dataverse call.

    Fail-open: any problem importing or emitting telemetry is swallowed so a
    telemetry issue can never break a Dataverse operation.
    """
    try:
        import adk_telemetry

        latency_ms = int((time.perf_counter() - start) * 1000)
        outcome = "success"
        error_code = ""
        error_category = ""
        if error is not None:
            outcome = "timeout" if "timeout" in type(error).__name__.lower() else "client_error"
            error_code = type(error).__name__
            error_category = "infra"
        elif status is not None and status >= 400:
            outcome = "server_error" if status >= 500 else "client_error"
            error_code = f"HTTP_{status}"
            error_category = "infra"
        adk_telemetry.emit_api_call(
            api_endpoint=f"{operation} {endpoint}",
            outcome=outcome,
            latency_ms=latency_ms,
            error_code=error_code,
            error_category=error_category,
            error_message=str(error) if error else "",
        )
    except Exception:  # noqa: BLE001 — telemetry must never break a Dataverse call
        pass


def _validate_https_url(env_url):
    """Reject http:// URLs - sending tokens over cleartext is unacceptable."""
    if not env_url.lower().startswith("https://"):
        raise ValueError(
            f"env_url must use https:// (got: {env_url!r}). Refusing to send "
            "credentials over an unencrypted channel."
        )


def discover_tenant(env_url):
    """Discover the tenant ID from the environment's auth challenge."""
    _validate_https_url(env_url)
    resp = _SESSION.get(
        f"{env_url}/api/data/v9.2/",
        headers={"Accept": "application/json"},
        allow_redirects=False,
        timeout=10,
        verify=True,
    )
    auth_header = resp.headers.get("WWW-Authenticate", "")
    match = re.search(r"login\.microsoftonline\.com/([^/]+)", auth_header)
    if match:
        return match.group(1)
    return "organizations"


def authenticate(env_url):
    """Get a Dataverse access token via MSAL interactive browser auth.

    Uses a token cache so repeat runs within the same session don't re-prompt.
    Discovers the correct tenant from the environment automatically.
    """
    _validate_https_url(env_url)
    tenant = discover_tenant(env_url)
    authority = f"https://login.microsoftonline.com/{tenant}"
    scope = f"{env_url}/user_impersonation"
    cache = msal.SerializableTokenCache()
    cache_path = os.path.join(LOCAL_STATE_DIR, ".token_cache.bin")

    if os.path.exists(cache_path):
        with open(cache_path, "r") as f:
            cache.deserialize(f.read())

    app = msal.PublicClientApplication(
        CLIENT_ID, authority=authority, token_cache=cache
    )

    # Try silent first (cached token from previous run)
    accounts = app.get_accounts()
    result = None
    if accounts:
        result = app.acquire_token_silent([scope], account=accounts[0])

    if not result or "access_token" not in result:
        print(f"Opening browser for sign-in (tenant: {tenant})...")
        print("Please select the account that has access to this environment.")
        result = app.acquire_token_interactive(
            [scope], prompt="select_account"
        )

    if "access_token" not in result:
        # Don't echo error_description - it can include tenant IDs and
        # internal flow details (CWE-209).
        error = result.get("error", "unknown_error")
        print(f"ERROR: Authentication failed ({error}).")
        print("Verify you have access to this environment and try again.")
        sys.exit(1)

    # Persist cache with strict 0o600 permissions on POSIX. The cache holds
    # MSAL refresh tokens; default umask (0o644) would expose them to other
    # users on shared dev VMs.
    if cache.has_state_changed:
        os.makedirs(LOCAL_STATE_DIR, exist_ok=True)
        try:
            os.chmod(LOCAL_STATE_DIR, 0o700)
        except OSError:
            # Windows ignores chmod for directories - that's expected.
            pass
        # Use os.open with explicit mode so the file is created with 0o600
        # rather than written under default umask first and chmodded after.
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(cache_path, flags, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(cache.serialize())
        finally:
            # Re-chmod is a defense-in-depth no-op on POSIX where O_CREAT mode
            # already set 0o600, and a no-op on Windows where chmod is limited.
            try:
                os.chmod(cache_path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass

    # Record the tenant + start a telemetry session. No developer identity is
    # collected; active-install counts dedupe on a random instance_id.
    # Best-effort: never let telemetry affect authentication.
    try:
        import adk_telemetry

        claims = result.get("id_token_claims", {}) or {}
        adk_telemetry.maybe_print_notice()
        adk_telemetry.start_session(
            tenant_id=claims.get("tid", "") or tenant,
            adk_capability="connect",
        )
    except Exception:  # noqa: BLE001 — telemetry must never break auth
        pass

    return result["access_token"]


def query_all(env_url, token, entity_set, select, filter_expr=None):
    """Query a Dataverse table with automatic @odata.nextLink pagination.

    Returns all records across all pages.
    """
    _validate_https_url(env_url)
    headers = {**HEADERS_BASE, "Authorization": f"Bearer {token}"}
    url = f"{env_url}/api/data/v9.2/{entity_set}?$select={quote(select, safe=',')}"
    if filter_expr:
        url += f"&$filter={quote(filter_expr, safe='')}"

    all_records = []
    page = 0
    _start = time.perf_counter()
    while url:
        page += 1
        resp = _SESSION.get(url, headers=headers, timeout=120, verify=True)
        if resp.status_code == 401:
            _emit_api_call(entity_set, "read", _start, status=401)
            raise AuthExpiredError(response=resp)
        raise_api_error(resp, resource_name=entity_set, operation="read")
        data = resp.json()
        records = data.get("value", [])
        all_records.extend(records)
        url = data.get("@odata.nextLink")
        if page == 1:
            print(f"  Page {page}: {len(records)} records", end="")
        elif records:
            print(f" -> Page {page}: {len(records)}", end="")

    print(f" -> Total: {len(all_records)}")
    _emit_api_call(entity_set, "read", _start, status=200)
    return all_records


def retrieve_shared_principals_and_access(env_url, token, bot_id):
    """Return the principals a Dataverse ``bot`` record is shared with.

    Calls the documented Dataverse Web API function
    ``RetrieveSharedPrincipalsAndAccess(Target=bots(<bot_id>))``. Copilot
    Studio "Share" writes to the underlying ``bot`` record's sharing, so
    this is the supported source for "who is this agent shared with"
    (the sharing pane's own data). Returns the parsed JSON, whose
    ``PrincipalAccesses`` is a list of
    ``{"AccessMask", "Principal": {"@odata.type", "ownerid"}}`` — the
    ``@odata.type`` discriminates ``systemuser`` vs ``team`` and
    ``ownerid`` is the principal's id.

    Used by FlightCheck LIC-FLOW-002 (shared-user license verification)
    and by the cassette recorder. The Target is passed as a parameter
    alias holding an @odata.id entity reference — the documented Web API
    invocation pattern for a function taking a crmbaseentity parameter.

    Docs: https://learn.microsoft.com/power-apps/developer/data-platform/webapi/reference/retrievesharedprincipalsandaccess
    """
    _validate_https_url(env_url)
    target = quote(json.dumps({"@odata.id": f"bots({bot_id})"}), safe="")
    url = (
        f"{env_url}/api/data/v9.2/RetrieveSharedPrincipalsAndAccess"
        f"(Target=@t)?@t={target}"
    )
    headers = {**HEADERS_BASE, "Authorization": f"Bearer {token}"}
    resp = _SESSION.get(url, headers=headers, timeout=120, verify=True)
    if resp.status_code == 401:
        raise AuthExpiredError(response=resp)
    resp.raise_for_status()
    return resp.json()


def dataverse_get(env_url, token, path, params=None):
    """GET a Dataverse Web API endpoint that is not a paged table query.

    Use this for function calls (e.g. ``WhoAmI()``) and single-record reads
    (e.g. ``usersettingscollection({systemuserid})``) where ``query_all`` does
    not fit — ``query_all`` always appends ``$select`` and follows
    ``@odata.nextLink``.

    Parameters
    ----------
    env_url : str
        Base environment URL (e.g. ``https://contoso.crm.dynamics.com``).
    token : str
        Dataverse bearer token.
    path : str
        Path relative to ``/api/data/v9.2/`` (no leading slash). Example:
        ``"WhoAmI()"`` or ``"usersettingscollection(11111111-...)``.
    params : dict | None
        Optional querystring parameters (e.g. ``{"$select": "_preferredsolution_value"}``).

    Returns
    -------
    dict
        Parsed JSON response body.

    Raises
    ------
    AuthExpiredError
        If the response is 401.
    requests.HTTPError
        For other non-2xx responses (raised via ``raise_for_status``).
    """
    _validate_https_url(env_url)
    # Catch developer mistakes where the absolute base path is passed in.
    # `.lstrip('/')` below would silently strip a leading slash; without
    # these asserts, `'/api/data/v9.2/WhoAmI()'` becomes a double-prefixed
    # URL and `'api/data/v9.2/WhoAmI()'` becomes a malformed one. The doc
    # says "path relative to /api/data/v9.2/" — enforce it.
    assert not path.startswith("/"), (
        f"dataverse_get path must be relative to /api/data/v9.2/ "
        f"(no leading slash), got: {path!r}"
    )
    assert not path.lower().startswith("api/data/"), (
        f"dataverse_get path must be relative to /api/data/v9.2/ "
        f"(do not include it), got: {path!r}"
    )
    headers = {**HEADERS_BASE, "Authorization": f"Bearer {token}"}
    url = f"{env_url}/api/data/v9.2/{path.lstrip('/')}"
    _start = time.perf_counter()
    resp = _SESSION.get(url, headers=headers, params=params, timeout=60, verify=True)
    _emit_api_call(path.split("(")[0], "read", _start, status=resp.status_code)
    if resp.status_code == 401:
        raise AuthExpiredError(response=resp)
    resp.raise_for_status()
    return resp.json()


def update_record(env_url, token, entity_set, record_id, data):
    """Update a single Dataverse record via PATCH.

    Note: optimistic-concurrency etag support was removed in round-3 review
    (the parameter was plumbed but no call site used it - half-built
    protection is worse than no protection). Re-add when push.py is wired to
    capture and pass the @odata.etag annotation from the original GET.
    """
    _validate_https_url(env_url)
    headers = {
        **HEADERS_BASE,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    url = f"{env_url}/api/data/v9.2/{entity_set}({record_id})"
    _start = time.perf_counter()
    resp = _SESSION.patch(url, headers=headers, json=data, timeout=60, verify=True)
    _emit_api_call(entity_set, "update", _start, status=resp.status_code)
    if resp.status_code == 401:
        raise AuthExpiredError(response=resp)
    raise_api_error(resp, resource_name=entity_set, operation="update")
    return True


def create_record(env_url, token, entity_set, data):
    """Create a new Dataverse record via POST. Returns the new record ID."""
    _validate_https_url(env_url)
    headers = {
        **HEADERS_BASE,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    url = f"{env_url}/api/data/v9.2/{entity_set}"
    _start = time.perf_counter()
    resp = _SESSION.post(url, headers=headers, json=data, timeout=60, verify=True)
    _emit_api_call(entity_set, "create", _start, status=resp.status_code)
    if resp.status_code == 401:
        raise AuthExpiredError(response=resp)
    raise_api_error(resp, resource_name=entity_set, operation="create")
    result = resp.json()
    return result.get("botcomponentid", result.get("id"))


def delete_record(env_url, token, entity_set, record_id):
    """Delete a single Dataverse record."""
    _validate_https_url(env_url)
    headers = {
        **HEADERS_BASE,
        "Authorization": f"Bearer {token}",
    }
    url = f"{env_url}/api/data/v9.2/{entity_set}({record_id})"
    _start = time.perf_counter()
    resp = _SESSION.delete(url, headers=headers, timeout=60, verify=True)
    _emit_api_call(entity_set, "delete", _start, status=resp.status_code)
    if resp.status_code == 401:
        raise AuthExpiredError(response=resp)
    raise_api_error(resp, resource_name=entity_set, operation="delete")
    return True


def load_config():
    """Load .local/config.json. Returns the parsed dict or exits on error.

    Gates on `configVersion`: if the on-disk version doesn't match
    `EXPECTED_CONFIG_VERSION`, exits with a clear instruction to re-run
    setup. This catches the case where a kit upgrade changed the schema
    and a downstream script would otherwise KeyError on a missing field.
    """
    config_path = os.path.join(LOCAL_STATE_DIR, "config.json")
    if not os.path.exists(config_path):
        print(f"ERROR: {config_path} not found. Run /setup first.")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    ver = cfg.get("configVersion", 0)
    if ver != EXPECTED_CONFIG_VERSION:
        print(
            f"ERROR: {config_path} is schema v{ver}, expected "
            f"v{EXPECTED_CONFIG_VERSION}. Run `/setup --refresh` to migrate."
        )
        sys.exit(1)
    return cfg
