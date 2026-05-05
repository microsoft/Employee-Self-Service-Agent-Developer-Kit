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


# Microsoft public client ID for Power Platform CLI / Dataverse delegated access.
# Source: https://learn.microsoft.com/power-platform/admin/programmability-authentication-v2
# Scope: user_impersonation only (delegated, no admin consent).
CLIENT_ID = "51f81489-12ee-4a9e-aaae-a2591f45987d"

# Kit-internal state directory (token cache, component maps, config).
# Renamed from "my/" -> ".local/" in PR #2 to separate kit-internal state
# from user-edited files (which live under "workspace/").
LOCAL_STATE_DIR = ".local"

HEADERS_BASE = {
    "Accept": "application/json",
    "OData-MaxVersion": "4.0",
    "OData-Version": "4.0",
    "Prefer": "odata.include-annotations=*",
}


class AuthExpiredError(RuntimeError):
    """Raised when a Dataverse call returns 401. Callers can catch this and
    re-authenticate without losing in-flight push state."""


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
    while url:
        page += 1
        resp = _SESSION.get(url, headers=headers, timeout=120, verify=True)
        if resp.status_code == 401:
            raise AuthExpiredError("Dataverse returned 401 (token expired or invalid)")
        resp.raise_for_status()
        data = resp.json()
        records = data.get("value", [])
        all_records.extend(records)
        url = data.get("@odata.nextLink")
        if page == 1:
            print(f"  Page {page}: {len(records)} records", end="")
        elif records:
            print(f" → Page {page}: {len(records)}", end="")

    print(f" → Total: {len(all_records)}")
    return all_records


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
    resp = _SESSION.patch(url, headers=headers, json=data, timeout=60, verify=True)
    if resp.status_code == 401:
        raise AuthExpiredError("Dataverse returned 401 (token expired or invalid)")
    resp.raise_for_status()
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
    resp = _SESSION.post(url, headers=headers, json=data, timeout=60, verify=True)
    if resp.status_code == 401:
        raise AuthExpiredError("Dataverse returned 401 (token expired or invalid)")
    resp.raise_for_status()
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
    resp = _SESSION.delete(url, headers=headers, timeout=60, verify=True)
    if resp.status_code == 401:
        raise AuthExpiredError("Dataverse returned 401 (token expired or invalid)")
    resp.raise_for_status()
    return True


def load_config():
    """Load .local/config.json. Returns the parsed dict or exits on error."""
    config_path = os.path.join(LOCAL_STATE_DIR, "config.json")
    if not os.path.exists(config_path):
        print(f"ERROR: {config_path} not found. Run /setup first.")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)
